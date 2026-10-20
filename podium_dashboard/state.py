"""Read and change `podium.json` without loading it into the agent's context.

Every write is atomic (temp file, then rename) and stamps `updatedAt`. It writes
only this command's changes, onto podium.json as it is at that moment, under the
run's lock: a command that runs for minutes keeps every write other commands
made meanwhile.
The files live in the run dir's `podium/` folder (podium_dir).
Build-all is per milestone, `milestones[].buildAll`: a top-level `buildAll`
(an older run's, or `set . buildAll=…`) is the active milestone's, and every
load and write moves it there.
"""
import contextlib
import copy
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

from podium_dashboard import human
from podium_dashboard.human import (DAYS, HOURS, HUMAN_FILE, availability, day_set, human_hours,  # noqa: F401
                                    human_line, human_state, in_hours, local, me, next_change, write_human)

NOW = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
STAGES = ("STARTED", "RED", "GREEN", "REFACTOR", "FIX", "CONTRACT", "COMMITTED", "FAILED")
ACT_ON = {"confirm", "reverse", "asana", "asana-done"}  # the user's own answers: acted on whenever they arrive
PERSONAL = ("active", "needsYou")


def podium_dir(root):
    """The orchestrator's own folder in the run dir, `<run dir>/podium/`; a run begun before it keeps its files in
    the run dir itself (podium.json at the top) and is read there until they are moved."""
    d = os.path.join(root, "podium")
    legacy = not os.path.exists(os.path.join(d, "podium.json")) and os.path.exists(os.path.join(root, "podium.json"))
    return root if legacy else d


class Podium:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.dir = podium_dir(self.root)
        self.path = os.path.join(self.dir, "podium.json")
        self.repo = os.path.dirname(self.root)
        self.held = None  # events a batch holds back until its one write
        self.fresh = []  # the events this command appended at the current time: a backdated one is history
        self.lock_fd, self.lock_depth = None, 0
        self._me = None
        self.load()

    def read(self):
        """podium.json as it is on disk now; {} before the first write."""
        try:
            with open(self.path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def load(self):
        """Read podium.json afresh into `data`; `base`, the copy as read, is what save() measures this command's
        changes against."""
        self.data = self.read()
        self.base = copy.deepcopy(self.data)
        self.adopt_build_all()

    @contextlib.contextmanager
    def locked(self):
        """The run's lock (flock on the podium dir), held while a command reads and writes podium.json or
        events.jsonl, so two podium commands never write at once. Re-entrant."""
        if not self.lock_depth:
            os.makedirs(self.dir, exist_ok=True)
            self.lock_fd = os.open(self.dir, os.O_RDONLY)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX)
        self.lock_depth += 1
        try:
            yield
        finally:
            self.lock_depth -= 1
            if not self.lock_depth:
                os.close(self.lock_fd)  # releases the lock

    def refresh(self):
        """Catch up with podium.json as other commands left it, keeping this command's changes: after a long step,
        before deciding anything from `data`. Objects taken from `data` before it are stale."""
        with self.locked():
            fresh = self.read()
            self.data, self.base = rebase(self.base, self.data, fresh), copy.deepcopy(fresh)
        self.adopt_build_all()

    def adopt_build_all(self):
        """Build-all is per milestone: a top-level `buildAll` becomes the active milestone's (none: it is dropped)."""
        if "buildAll" in self.data:
            flag, mid = self.data.pop("buildAll"), self.active().get("milestone")
            for m in self.milestones():
                if m.get("id") == mid:
                    m["buildAll"] = flag

    def save(self):
        """Write this command's changes since load onto podium.json as it is now, so a write another command made
        meanwhile stays. Objects taken from `data` before it are stale."""
        with self.locked():
            self.data = rebase(self.base, self.data, self.read())
            self.adopt_build_all()
            self.data["updatedAt"] = NOW()
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, self.path)
            self.base = copy.deepcopy(self.data)

    def event(self, type_, milestone=None, story=None, **fields):
        backdated = bool(fields.get("at"))
        line = {"at": fields.pop("at", None) or NOW(), "type": type_, **fields}
        if milestone:
            line["milestone"] = milestone
        if story:
            line["story"] = story
        if not backdated:
            self.fresh.append(line)
        if self.held is not None:
            self.held.append(line)
            return
        with self.locked(), open(os.path.join(self.dir, "events.jsonl"), "a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def release(self):
        """Append the events a batch held back, in order, in one write."""
        held, self.held = self.held or [], None
        if held:
            with self.locked(), open(os.path.join(self.dir, "events.jsonl"), "a") as f:
                f.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in held)
        return len(held)

    # --- this person's state ------------------------------------------------
    @property
    def me(self):
        if self._me is None:
            self._me = me()
        return self._me

    def synced(self):
        s = self.data.get("sync")
        return isinstance(s, dict) and bool(s.get("enabled"))

    def per_person(self):
        """Whether each person's active, needsYou and assumptions are written to `people.<me>`: in a run that syncs or
        has a `people` block. Any other run keeps them at the top level."""
        return self.synced() or isinstance(self.data.get("people"), dict)

    def person(self):
        """`people.<me>` as it is, {} when absent."""
        people = self.data.get("people")
        found = people.get(self.me) if isinstance(people, dict) else None
        return found if isinstance(found, dict) else {}

    def own(self):
        """The object this person's active, needsYou and assumptions are written to."""
        return person_of(self.data, self.me) if self.per_person() else self.data

    def mine(self, key, default=None):
        """This person's `key`: people.<me>'s, else the top-level one of a run from before `people`."""
        found = self.person()
        return found[key] if key in found else self.data.get(key, default)

    def active(self):
        return self.mine("active") or {}

    def needs_you(self):
        return self.mine("needsYou")

    def assumptions_list(self):
        found = self.mine("assumptions")
        return found if isinstance(found, list) else []

    # --- lookup -------------------------------------------------------------
    def epics(self):
        return self.data.get("epics", [])

    def milestones(self):
        return [m for e in self.epics() for m in e.get("milestones", [])]

    def milestone(self, mid=None):
        mid = mid or self.active().get("milestone")
        m = next((m for m in self.milestones() if m.get("id") == mid), None)
        if not m:
            sys.exit(f"no milestone {mid!r}" if mid else "no active milestone")
        return m

    def story(self, sid, mid=None):
        m = self.milestone(mid)
        s = next((s for s in m.get("stories", []) if s.get("id") == sid), None)
        if not s:
            sys.exit(f"no story {sid!r} in {m['id']}")
        return m, s

    def resolve(self, target):
        """(object, milestone id, story id) for a target."""
        if target == ".":
            return self.data, self.active().get("milestone"), None
        if target == "me":
            return self.own(), self.active().get("milestone"), None
        if target.startswith("epic:"):
            e = next((e for e in self.epics() if e.get("id") == target[5:]), None)
            if not e:
                sys.exit(f"no epic {target[5:]!r}")
            return e, None, None
        if target.startswith("milestone:"):
            m = self.milestone(target[10:] or None)
            return m, m["id"], None
        mid, _, sid = target.rpartition("/")
        m, s = self.story(sid, mid or None)
        return s, m["id"], s["id"]

    def handed_off(self, m):
        """Ids of m's stories the user took to a session of their own (handoffs.json, the Podium's copy button)."""
        try:
            with open(os.path.join(self.dir, "handoffs.json")) as f:
                return {k.split("/", 1)[1] for k in json.load(f) if k.startswith(m["id"] + "/")}
        except (OSError, ValueError):
            return set()

    def ready(self, m):
        done = {s["id"] for s in m.get("stories", []) if s.get("status") == "done"}
        away = self.handed_off(m)
        return [s["id"] for s in m.get("stories", [])
                if s.get("status") == "todo" and s["id"] not in away
                and set(s.get("deps", []) + s.get("overlapAfter", [])) <= done]


def person_of(data, name):
    """`people.<name>` of a podium.json's data, created when absent."""
    people = data.get("people")
    if not isinstance(people, dict):
        people = data["people"] = {}
    if not isinstance(people.get(name), dict):
        people[name] = {}
    return people[name]


def rebase(base, mine, theirs):
    """`theirs`, podium.json as other commands left it, with this command's changes since it read `base` on top:
    values it set, keys it added or removed, list items it changed, added or removed. List items with an `id`
    (epics, milestones, stories) pair up by id, others by position. An object both added merges key by key. Where both
    changed one value, this command's wins."""
    if mine == base:
        return theirs
    if theirs == base:
        return mine
    if isinstance(base, dict) and isinstance(mine, dict) and isinstance(theirs, dict):
        out = dict(theirs)
        for k in list(base) + [k for k in mine if k not in base]:
            if k not in mine:
                out.pop(k, None)
            elif k in base and k in theirs:
                out[k] = rebase(base[k], mine[k], theirs[k])
            elif k in theirs and isinstance(mine[k], dict) and isinstance(theirs[k], dict):
                out[k] = rebase({}, mine[k], theirs[k])
            elif k not in base or mine[k] != base[k]:  # added here, or changed here and removed there
                out[k] = mine[k]
        return out
    if isinstance(base, list) and isinstance(mine, list) and isinstance(theirs, list):
        ids = lambda xs: [x.get("id") if isinstance(x, dict) else None for x in xs]
        if None not in ids(base) + ids(mine) + ids(theirs):
            b, m, t_ids = dict(zip(ids(base), base)), dict(zip(ids(mine), mine)), ids(theirs)
            out = [rebase(b[t["id"]], m[t["id"]], t) if t["id"] in b and t["id"] in m else t
                   for t in theirs if t["id"] in m or t["id"] not in b]
            return out + [x for x in mine if x["id"] not in b and x["id"] not in t_ids]
        if len(mine) >= len(base) <= len(theirs):
            n = len(base)
            return [rebase(*x) for x in zip(base, mine, theirs)] + theirs[n:] + mine[n:]
    return mine


def building(m):
    """Whether milestone m is building its stories; a second one can build beside the active one."""
    return m.get("status") == "working" and m.get("phase") == "build"


# --- values -------------------------------------------------------------------
def parse_value(raw):
    if raw == "now":
        return NOW()
    if raw.startswith("@"):
        with open(raw[1:]) as f:
            return json.load(f)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def assign(obj, item):
    key, eq, raw = item.partition("=")
    if not eq:
        sys.exit(f"expected key=value, got {item!r}")
    op = "+=" if key.endswith("+") else "="
    key = key.rstrip("+")
    *path, last = key.split(".")
    for k in path:
        if isinstance(obj, list):
            obj = obj[int(k)]
            continue
        if obj.get(k) is None:  # absent, or null like an unopened `pr`
            obj[k] = {}
        obj = obj[k]
    if isinstance(obj, list):
        sys.exit(f"{key}: set a field of the item (key.<n>.field=value)")
    value = parse_value(raw)
    if op == "+=":
        cur = obj.get(last)
        if isinstance(cur, list) or cur is None and not isinstance(value, (int, float)):
            obj.setdefault(last, []).append(value)
        else:
            obj[last] = (cur or 0) + value
    else:
        obj[last] = value


def pairs(items):
    out = {}
    for item in items:
        assign(out, item)
    return out


# --- commands -----------------------------------------------------------------
def cmd_status(p, args):
    all_ = "--all" in args
    named = args[args.index("--milestone") + 1] if "--milestone" in args else None
    d = p.data
    act = p.active()
    owned = lambda m: f" · owner {m['owner']}" if m.get("owner") else ""
    print(f"{(d.get('project') or {}).get('title', '?')} · active {act.get('epic', '-')}/{act.get('milestone', '-')}"
          f" · dispatcher {d.get('dispatcher', '-')}")
    print(f"human: {human_line(availability())}")
    if p.needs_you():
        print(f"needsYou: {json.dumps(p.needs_you(), ensure_ascii=False)}")
    open_ = [a for a in p.assumptions_list() if a.get("status") == "open"]
    if open_:
        print(f"assumptions: {len(open_)} open")
    people = {name: x for name, x in (d["people"] if isinstance(d.get("people"), dict) else {}).items() if isinstance(x, dict)}
    if people:
        print("people: " + " · ".join(f"{name} → {(x.get('active') or {}).get('milestone') or '-'}" for name, x in people.items()))
    for e in p.epics():
        ms = e.get("milestones", [])
        counts = {}
        for m in ms:
            counts[m.get("status")] = counts.get(m.get("status"), 0) + 1
        owners = ", ".join(f"{m['id']} {m['owner']}" for m in ms if m.get("owner"))
        print(f"epic {e['id']}: " + ", ".join(f"{n} {s}" for s, n in counts.items()) + (f" · owners {owners}" if owners else ""))
        if all_:
            for m in ms:
                print(f"  {m['id']} {m.get('status')} {m.get('phase', '')} {m.get('title', '')}"
                      f" ({len(m.get('stories', []))} stories){owned(m)}")
    shown = [named] if named else [act.get("milestone")] + [m["id"] for m in p.milestones() if building(m)]
    for mid in dict.fromkeys(x for x in shown if x):
        m = p.milestone(mid)
        print(f"\n{m['id']} {m.get('title', '')} · {m.get('status')} · phase {m.get('phase')} · branch {m.get('branch', '-')}"
              f" · buildAll {'on' if m.get('buildAll') else 'off'}{owned(m)}")
        for name, r in (m.get("repos") or {}).items():
            pr = r.get("pr")
            print(f"  repo {name} {r.get('branch', '-')} → {r.get('base', '-')} · " + (f"PR #{pr.get('number')} {pr.get('state')}" if pr else "no PR"))
        away = p.handed_off(m)
        for s in m.get("stories", []):
            extra = ["handed off" if s["id"] in away and s.get("status") == "todo" else "",
                     f"repos {','.join(s['repos'])}" if s.get("repos") else "",
                     f"deps {','.join(s['deps'])}" if s.get("deps") else "",
                     f"after {','.join(s['overlapAfter'])}" if s.get("overlapAfter") else "",
                     f"att {s['attempts']}" if s.get("attempts") else "",
                     f"failure: {s['failure']}" if s.get("failure") else ""]
            print(f"  {s['id']:<5} {s.get('status', '?'):<8} " + " · ".join(x for x in extra if x))
        print(f"ready: {' '.join(p.ready(m)) or '-'}")


def cmd_get(p, args):
    if len(args) != 1:
        sys.exit("get <target>")
    obj, _, _ = p.resolve(args[0])
    if "stories" in obj:
        obj = {**obj, "stories": f"<{len(obj['stories'])} stories>"}
    if "epics" in obj:
        obj = {**obj, "epics": [e["id"] for e in obj["epics"]]}
    print(json.dumps(obj, ensure_ascii=False))


def cascade_block(m, failed):
    blocked, frontier = [], {failed}
    while frontier:
        nxt = {s["id"] for s in m.get("stories", [])
               if set(s.get("deps", [])) & frontier and s.get("status") in ("todo", "blocked") and s["id"] not in blocked}
        blocked += sorted(nxt)
        frontier = nxt
    for s in m.get("stories", []):
        if s["id"] in blocked:
            s["status"] = "blocked"
    return blocked


def apply_set(p, args):
    """One `set`, in memory, its event appended (or held by a batch); the caller saves."""
    if not args:
        sys.exit("set <target> [key=value ...] [--event TYPE [key=value ...]]")
    target, rest = args[0], args[1:]
    ev = rest.index("--event") if "--event" in rest else len(rest)
    if ev == len(rest) - 1:
        sys.exit("--event needs a TYPE")
    obj, mid, sid = p.resolve(target)
    for item in rest[:ev]:
        assign(p.own() if target == "." and personal(p, item) else obj, item)
    if sid and obj.get("status") == "failed":
        blocked = cascade_block(p.milestone(mid), sid)
        if blocked:
            print(f"blocked: {' '.join(blocked)}")
    if rest[ev:]:
        p.event(rest[ev + 1], mid, sid, **pairs(rest[ev + 2:]))


def personal(p, item):
    """Whether `set .`'s key=value is this person's own in a run that keeps one per person: active and needsYou, and
    assumptions once they have a list of their own."""
    key = item.partition("=")[0].rstrip("+").split(".")[0]
    return p.per_person() and (key in PERSONAL or key == "assumptions" and key in p.person())


def cmd_set(p, args):
    apply_set(p, args)
    p.save()


def cmd_batch(p, args):
    ops = [shlex.split(l) for l in sys.stdin.read().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    ops = [op[1:] if op[0] == "set" else op for op in ops]
    p.held = []
    for op in ops:
        apply_set(p, op)  # an op that fails exits here, before anything is written
    p.save()
    print(f"{len(ops)} sets, {p.release()} events")


def cmd_ready(p, args):
    named = args[args.index("--milestone") + 1] if "--milestone" in args else None
    print(" ".join(p.ready(p.milestone(named))))


def cmd_human(p, _):
    print(human_line(availability()))


def cmd_hours(p, args):
    if args:
        m = re.fullmatch(r"(\S+) (\d\d:\d\d)-(\d\d:\d\d)", " ".join(args))
        if not m:
            sys.exit("hours: <days> <HH:MM>-<HH:MM>, e.g. Mon-Fri 07:00-17:00")
        try:
            day_set(m[1])
        except ValueError:
            sys.exit(f"hours: unknown days {m[1]!r}; use Mon-Fri or Mon,Wed,Fri-Sun")
        write_human(hours={"days": m[1], "from": m[2], "to": m[3]})
    h = human_hours()
    print(f"hours {h['days']} {h['from']}-{h['to']} ({human.HUMAN_FILE})")


def cmd_assume(p, args):
    opt = lambda flag: args[args.index(flag) + 1] if flag in args else None
    story, short = opt("--story"), opt("--short")
    flags = {i for f in ("--story", "--short") if f in args for i in (args.index(f), args.index(f) + 1)}
    rest = [a for i, a in enumerate(args) if i not in flags]
    if len(rest) != 3:
        sys.exit("assume <question> <choice> <why> [--story [<milestone>/]ID] [--short TEXT]")
    question, choice, why = rest
    mid, _, story = (story or "").rpartition("/")  # a story of another milestone than the active one comes as <milestone>/<story>
    mid, story = mid or p.active().get("milestone"), story or None
    a = {"at": NOW(), "milestone": mid, "story": story, "question": question, "choice": choice, "why": why, "short": short, "status": "open"}
    assumed = p.own().setdefault("assumptions", [])
    assumed.append({k: v for k, v in a.items() if v is not None})
    p.event("assumed", mid, story, question=question, choice=choice)
    p.save()
    print(f"assumption {len(assumed) - 1}")


def cmd_assumptions(p, _):
    for i, a in enumerate(p.assumptions_list()):
        if a.get("status") == "open":
            where = "/".join(x for x in (a.get("milestone"), a.get("story")) if x)
            print(f"{i} [{where}] {a['question']} → {a['choice']} ({a['why']})")


def cmd_settle(p, args):
    if len(args) != 2 or args[1] not in ("confirmed", "reversed"):
        sys.exit("settle <n>[,<n>...] <confirmed|reversed>")
    assumed = p.assumptions_list()
    try:
        ids = [int(i) for i in args[0].split(",") if i]
    except ValueError:
        ids = []
    if not ids or any(not 0 <= i < len(assumed) for i in ids):
        sys.exit(f"no assumption {args[0]!r}")
    for i in ids:
        assumed[i]["status"] = args[1]
    one = assumed[ids[0]]
    p.event("settled", one.get("milestone") if len(ids) == 1 else None, status=args[1],
            **({"question": one["question"]} if len(ids) == 1 else {"count": len(ids)}))
    p.save()
    print(f"{len(ids)} {args[1]}")


def cmd_whoami(p, args):
    if len(args) > 1 or args and not re.fullmatch(r"\S+", args[0]):
        sys.exit("whoami [<name>]")
    if args:
        write_human(me=args[0])
    print(me() + (" ($PODIUM_ME)" if os.environ.get("PODIUM_ME") else ""))


# --- ownership ----------------------------------------------------------------
def require_owner(p, milestone_id, force=False):
    """Exit 1 unless this person may change milestone `milestone_id` (None: the active one): it is theirs, or nobody
    owns it in a run that doesn't sync, or no milestone has an owner and the run doesn't sync. A synced run's
    milestone without an owner must be claimed first. `force` skips the check."""
    if force:
        return
    m = p.milestone(milestone_id)
    if not p.synced() and not any(x.get("owner") for x in p.milestones()):
        return
    owner = m.get("owner")
    if owner and owner != p.me:
        sys.exit(f"podium: milestone {m['id']} is owned by {owner}")
    if not owner and p.synced():
        sys.exit(f"podium: milestone {m['id']} has no owner: podium claim {m['id']}")


def cmd_claim(p, args):
    from podium_dashboard import sync
    force, rest = "--force" in args, [a for a in args if a != "--force"]
    if len(rest) != 1:
        sys.exit("claim <milestone> [--force]")
    if p.synced():
        sync.pull(p)
    m = p.milestone(rest[0])
    mid, owner = m["id"], m.get("owner")
    if owner and owner != p.me and not force:
        sys.exit(f"podium: milestone {mid} is owned by {owner}")
    if owner != p.me:
        m["owner"] = p.me
        p.save()
        if p.synced():
            claimed_first(p, mid)
        if owner:
            p.event("handover", mid, **{"from": owner, "to": p.me})
        p.event("owner", mid, owner=p.me)
    print(f"claimed {mid}")


def claimed_first(p, mid):
    """Push this claim; when another one reached the remote first, the sync merge keeps theirs and this exits 1."""
    from podium_dashboard import sync
    out = sync.save(p, f"{mid} claimed by {p.me}")
    if out == "BEHIND":
        sync.pull(p)
        out = sync.save(p, f"{mid} claimed by {p.me}")
    if not out.startswith(("SAVED", "UNCHANGED")) or "(not pushed" in out:
        print(out)
    owner = p.milestone(mid).get("owner")
    if owner != p.me:
        sys.exit(f"podium: milestone {mid} is owned by {owner}")


def cmd_release(p, args):
    from podium_dashboard import sync
    if len(args) != 1:
        sys.exit("release <milestone>")
    if p.synced():
        sync.pull(p)
    m = p.milestone(args[0])
    owner = m.get("owner")
    if owner and owner != p.me:
        sys.exit(f"podium: milestone {m['id']} is owned by {owner}")
    if owner:
        del m["owner"]
        p.event("owner", m["id"], owner=None)
        p.save()
    print(f"released {m['id']}")


def story_target(p, args):
    """(milestone, story, rest of args) from a leading `[<milestone>/]<story>` arg, else PODIUM_MILESTONE and
    PODIUM_STORY, else the cwd's branch `story/<id>`; a bare story id is looked up in the working stories first."""
    target = args[0] if args and args[0] not in STAGES else None
    rest = args[1:] if target else args
    if not target and os.environ.get("PODIUM_STORY"):
        target = "/".join(x for x in (os.environ.get("PODIUM_MILESTONE"), os.environ["PODIUM_STORY"]) if x)
    if not target:
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
        target = branch[len("story/"):] if branch.startswith("story/") else None
    if not target:
        sys.exit("which story? pass [<milestone>/]<story>, or set PODIUM_STORY")
    mid, _, sid = target.rpartition("/")
    if not mid:
        mid = next((m["id"] for m in p.milestones() for s in m.get("stories", [])
                    if s.get("id") == sid and s.get("status") in ("working", "approval")), None)
    m, s = p.story(sid, mid or None)
    return m, s, rest


def cmd_log(p, args):
    m, s, rest = story_target(p, args)
    if not rest or rest[0] not in STAGES:
        sys.exit(f"log [<milestone>/<story>] <STAGE> <note>, STAGE one of {' '.join(STAGES)}")
    note = " ".join(" ".join(rest[1:]).split())  # one line: a newline would start a line of its own
    path = os.path.join(p.dir, "stories", m["id"], f"{s['id']}.progress")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(f"{NOW()} {rest[0]} {note}".rstrip() + "\n")


def cmd_init(p, args):
    flags = ("--name", "--command", "--extension", "--phases")
    opts = dict(zip(args[::2], args[1::2]))
    if len(args) % 2 or set(opts) - set(flags) or not all(opts.get(f) for f in flags[:3]):
        sys.exit("init --name <name> --command </command> --extension <path to .py> [--phases a,b,c]")
    created = not os.path.exists(p.path)
    if created:
        title = os.path.basename(p.repo if os.path.basename(p.root).startswith(".") else p.root)
        p.data = {"project": {"title": title}, "active": {}, "needsYou": None, "assumptions": [], "epics": []}
    orchestrator = {**(p.data.get("orchestrator") or {}),
                    "name": opts["--name"], "command": opts["--command"], "extension": opts["--extension"]}
    if "--phases" in opts:
        orchestrator["phases"] = [x.strip() for x in opts["--phases"].split(",") if x.strip()]
    p.data["orchestrator"] = orchestrator
    p.save()
    print(f"{'created' if created else 'updated'} {p.path}")


# --- the Podium and its requests ----------------------------------------------
def http(url, method="GET", timeout=2):
    """A localhost call's JSON answer, or None."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=timeout) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def podium_url(p):
    """(url, /info) of the Podium serving this run, or (None, None): the URL server.log names last, else the
    first port of the server's range whose /info names this run dir."""
    tried = []
    try:
        with open(os.path.join(p.dir, "server.log")) as f:
            tried += re.findall(r"serving (http://\S+?/)\s", f.read())[-1:]
    except OSError:
        pass
    for url in dict.fromkeys(tried + [f"http://127.0.0.1:{port}/" for port in range(8765, 8785)]):
        info = http(url + "info", timeout=1)
        if info and os.path.realpath(info.get("runDir", "")) == os.path.realpath(p.root):
            return url, info
    return None, None


def watcher_span(p, path):
    """(from, to): the byte range of `path` the watcher's current run has read and printed, or (0, 0)."""
    try:
        with open(os.path.join(p.dir, "watcher.json")) as f:
            w = json.load(f)
    except (OSError, ValueError):
        return 0, 0
    key = next((k for k in w.get("offsets", {}) if os.path.realpath(k) == os.path.realpath(path)), None)
    return (w.get("since", {}).get(key, w["offsets"][key]), w["offsets"][key]) if key else (0, 0)


def requests_seen(p):
    """The byte offset of requests.jsonl that turns have passed on, from the machine-local cursor.json, or None
    before the first. An older run kept it in podium.json's `requestsSeen`: it moves to cursor.json here, and out
    of podium.json with the caller's next save."""
    legacy = p.data.pop("requestsSeen", None)
    try:
        with open(os.path.join(p.dir, "cursor.json")) as f:
            return json.load(f)["requestsSeen"]
    except (OSError, ValueError, KeyError, TypeError):
        if legacy is not None:
            set_requests_seen(p, legacy)
        return legacy


def set_requests_seen(p, offset):
    path = os.path.join(p.dir, "cursor.json")
    with p.locked():
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump({"requestsSeen": offset}, f)
        os.replace(tmp, path)


def queued_requests(p):
    """requests.jsonl lines neither an earlier call nor the watcher passed on, as ACT and LIST lines, the cursor moved
    past them; confirm and reverse lines whose assumptions were settled meanwhile drop out."""
    path = os.path.join(p.dir, "requests.jsonl")
    with p.locked():
        if not os.path.exists(path):
            requests_seen(p)
            set_requests_seen(p, 0)  # whatever the Podium queues from now on is new
            return []
        with open(path, "rb") as f:
            data = f.read()
        start = requests_seen(p)
        since, to = watcher_span(p, path)
        start = since if start is None else start  # a run from before the cursor: earlier sessions listed what came before
        start = 0 if start > len(data) else start
        end = data.rfind(b"\n", start) + 1 or start  # whole lines only: one being written waits for the next call
        set_requests_seen(p, end)
    lines, at = [], start
    open_ = {str(i) for i, a in enumerate(p.assumptions_list()) if a.get("status") == "open"}
    for raw in data[start:end].splitlines(keepends=True):
        at, here = at + len(raw), at
        if since <= here < to:
            continue
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        action, ident = r.get("action"), r.get("story") or ""
        if action in ("confirm", "reverse"):
            ident = ",".join(i for i in str(ident).split(",") if i in open_)
            if not ident:
                continue
        note = f" note={r['note']}" if r.get("note") else ""
        lines.append(f"{'ACT' if action in ACT_ON else 'LIST'} {action} {ident}".rstrip() + note)
    return lines


def cmd_requests(p, _):
    for line in queued_requests(p):
        print(line)
    if p.data != p.base:
        p.save()
