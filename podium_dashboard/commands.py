"""The core `podium` verbs, each `cmd_<verb>(p, args)`, and the ownership checks an extension's verbs share."""
import json
import os
import re
import shlex
import subprocess
import sys

from podium_dashboard import human, sync
from podium_dashboard.files import git_argv
from podium_dashboard.human import availability, day_set, human_hours, human_line, me, write_human
from podium_dashboard.state import NOW, STAGES, assign, building, pairs, queued_requests, valid_id

PERSONAL = ("active", "needsYou")


def option(args, flag):
    return args[args.index(flag) + 1] if flag in args else None


def refuse(milestone_id, owner):
    sys.exit(f"podium: milestone {milestone_id} is owned by {owner}")


def cmd_status(p, args):
    all_ = "--all" in args
    named = option(args, "--milestone")
    d = p.data
    act = p.active()
    owned = lambda m: f" · owner {m['owner']}" if m.get("owner") else ""
    print(f"{(d.get('project') or {}).get('title', '?')} · active {act.get('epic', '-')}/{act.get('milestone', '-')}")
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
    named = option(args, "--milestone")
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
    story, short = option(args, "--story"), option(args, "--short")
    flags = {i for f in ("--story", "--short") if f in args for i in (args.index(f), args.index(f) + 1)}
    rest = [a for i, a in enumerate(args) if i not in flags]
    if len(rest) != 3:
        sys.exit("assume <question> <choice> <why> [--story [<milestone>/]ID] [--short TEXT]")
    question, choice, why = rest
    mid, _, story = (story or "").rpartition("/")
    mid, story = mid or p.active().get("milestone"), story or None
    a = {"at": NOW(), "milestone": mid, "story": story, "question": question, "choice": choice, "why": why, "short": short, "status": "open"}
    assumed = p.own().setdefault("assumptions", [])
    assumed.append({k: v for k, v in a.items() if v is not None})
    p.event("assumed", mid, story, question=question, choice=choice)
    p.save()
    print(f"assumption {len(assumed) - 1}")


def cmd_assumptions(p, _):
    for i, a in p.numbered_assumptions():
        if a.get("status") == "open":
            where = "/".join(x for x in (a.get("milestone"), a.get("story")) if x)
            print(f"{i} [{where}] {a['question']} → {a['choice']} ({a['why']})")


def cmd_settle(p, args):
    if len(args) != 2 or args[1] not in ("confirmed", "reversed"):
        sys.exit("settle <n>[,<n>...] <confirmed|reversed>")
    assumed = dict(p.numbered_assumptions())
    ids = [i for i in args[0].split(",") if i]
    if not ids or any(i not in assumed for i in ids):
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


def require_owner(p, milestone_id, force=False, claim=True):
    """Exit 1 unless this person may change milestone `milestone_id` (None: the active one): it is theirs, or nobody
    owns it in a run that doesn't sync, or no milestone has an owner and the run doesn't sync. A synced run's
    milestone without an owner becomes theirs through `claim_milestone` first, or passes unclaimed with `claim`
    False. `force` skips the check."""
    if force:
        return
    m = p.milestone(milestone_id)
    if not p.synced() and not any(x.get("owner") for x in p.milestones()):
        return
    owner = m.get("owner")
    if owner and owner != p.me:
        refuse(m["id"], owner)
    if not owner and p.synced() and claim:
        print(f"claimed {claim_milestone(p, m['id'])}")


def claim_milestone(p, milestone_id, force=False):
    """Make the milestone this person's: pull when the run syncs, exit 1 while someone else owns it (unless `force`,
    a `handover`), set the owner, push, and record an `owner` event. Returns the milestone's id."""
    if p.synced():
        sync.pull(p)
    m = p.milestone(milestone_id)
    mid, owner = m["id"], m.get("owner")
    if owner and owner != p.me and not force:
        refuse(mid, owner)
    if owner != p.me:
        m["owner"] = p.me
        p.save()
        if p.synced():
            claimed_first(p, mid)
        if owner:
            p.event("handover", mid, **{"from": owner, "to": p.me})
        p.event("owner", mid, owner=p.me)
    return mid


def cmd_claim(p, args):
    force, rest = "--force" in args, [a for a in args if a != "--force"]
    if len(rest) != 1:
        sys.exit("claim <milestone> [--force]")
    print(f"claimed {claim_milestone(p, rest[0], force)}")


def claimed_first(p, mid):
    """Push this claim; when another one reached the remote first, the sync merge keeps theirs and this exits 1."""
    out = sync.save(p, f"{mid} claimed by {p.me}")
    if out == "BEHIND":
        sync.pull(p)
        out = sync.save(p, f"{mid} claimed by {p.me}")
    if not out.startswith(("SAVED", "UNCHANGED")) or "(not pushed" in out:
        print(out)
    owner = p.milestone(mid).get("owner")
    if owner != p.me:
        refuse(mid, owner)


def cmd_release(p, args):
    if len(args) != 1:
        sys.exit("release <milestone>")
    if p.synced():
        sync.pull(p)
    m = p.milestone(args[0])
    owner = m.get("owner")
    if owner and owner != p.me:
        refuse(m["id"], owner)
    if owner:
        del m["owner"]
        p.event("owner", m["id"], owner=None)
        p.save()
    print(f"released {m['id']}")


def stages(p):
    extra = (p.data.get("orchestrator") or {}).get("stages")
    return STAGES + tuple(k for k in (extra if isinstance(extra, dict) else {}) if k not in STAGES)


def story_target(p, args):
    """(milestone, story, rest of args) from a leading `[<milestone>/]<story>` arg, else PODIUM_MILESTONE and
    PODIUM_STORY, else the cwd's branch `story/<id>`; a bare story id is looked up in the working stories first."""
    target = args[0] if args and args[0] not in stages(p) else None
    rest = args[1:] if target else args
    if not target and os.environ.get("PODIUM_STORY"):
        target = "/".join(x for x in (os.environ.get("PODIUM_MILESTONE"), os.environ["PODIUM_STORY"]) if x)
    if not target:
        branch = subprocess.run(git_argv("rev-parse", "--abbrev-ref", "HEAD"), capture_output=True, text=True).stdout.strip()
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
    if not rest or rest[0] not in stages(p):
        sys.exit(f"log [<milestone>/<story>] <STAGE> <note>, STAGE one of {' '.join(stages(p))}")
    if not (valid_id(m["id"]) and valid_id(s["id"])):
        sys.exit(f"not a safe id: {m['id']!r}/{s['id']!r}")
    note = " ".join(" ".join(rest[1:]).split())  # one line: a newline would start a line of its own
    path = os.path.join(p.dir, "stories", m["id"], f"{s['id']}.progress")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with p.locked(), open(path, "a") as f:
        f.write(f"{NOW()} {rest[0]} {note}".rstrip() + "\n")


def stored_extension(given, folder):
    """`given` as podium.json keeps it: a `~` or absolute path as typed, a path relative to the cwd rewritten relative
    to `folder`, the one holding podium.json."""
    if given.startswith("~") or os.path.isabs(given):
        return given
    where = os.path.realpath(os.path.dirname(os.path.abspath(given)))
    return os.path.relpath(os.path.join(where, os.path.basename(given)), os.path.realpath(folder))


def cmd_init(p, args):
    flags = ("--name", "--command", "--extension", "--phases")
    opts = dict(zip(args[::2], args[1::2]))
    if len(args) % 2 or set(opts) - set(flags) or not all(opts.get(f) for f in flags[:3]):
        sys.exit("init --name <name> --command </command> --extension <path to .py> [--phases a,b,c]")
    created = not os.path.exists(p.path)
    if created:
        title = os.path.basename(p.repo if os.path.basename(p.root).startswith(".") else p.root)
        p.data = {"project": {"title": title}, "active": {}, "needsYou": None, "assumptions": [], "epics": []}
    orchestrator = {**(p.data.get("orchestrator") or {}), "name": opts["--name"], "command": opts["--command"],
                    "extension": stored_extension(opts["--extension"], p.dir)}
    if "--phases" in opts:
        orchestrator["phases"] = [x.strip() for x in opts["--phases"].split(",") if x.strip()]
    p.data["orchestrator"] = orchestrator
    p.save()
    print(f"{'created' if created else 'updated'} {p.path}")



def cmd_requests(p, _):
    for line in queued_requests(p):
        print(line)
    if p.data != p.base:
        p.save()
