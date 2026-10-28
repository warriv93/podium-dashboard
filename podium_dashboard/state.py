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
import math
import os
import re
import sys
import time
import urllib.request

from podium_dashboard.files import NOW, write_atomic
from podium_dashboard.human import (DAYS, HOURS, HUMAN_FILE, availability, day_set, human_hours,  # noqa: F401
                                    human_line, human_state, in_hours, local, me, next_change, write_human)
from podium_dashboard.merge import rebase

STAGES = ("STARTED", "RED", "GREEN", "REFACTOR", "FIX", "CONTRACT", "COMMITTED", "FAILED")
ACT_ON = {"confirm", "reverse", "asana", "asana-done"}
WATCHER_LIVE = 30
ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def valid_id(x):
    """Whether `x` is an id safe to use as a path component: an epic's, milestone's or story's from podium.json."""
    return isinstance(x, str) and bool(ID.fullmatch(x))


def podium_dir(root):
    """The orchestrator's own folder in the run dir, `<run dir>/podium/`; a run begun before it keeps its files in
    the run dir itself (podium.json at the top) and is read there until they are moved."""
    d = os.path.join(root, "podium")
    legacy = not os.path.exists(os.path.join(d, "podium.json")) and os.path.exists(os.path.join(root, "podium.json"))
    return root if legacy else d


def find_run(d):
    """The nearest run dir at or above d: one holding podium/podium.json, or a repo's .deep-plan run (podium.json
    in .deep-plan/podium/, or at its top in a run from before podium/)."""
    while True:
        for run in (d, os.path.join(d, ".deep-plan")):
            if os.path.isfile(os.path.join(run, "podium", "podium.json")) or (run != d and os.path.isfile(os.path.join(run, "podium.json"))):
                return run
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)


class Podium:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.dir = podium_dir(self.root)
        self.path = os.path.join(self.dir, "podium.json")
        self.repo = os.path.dirname(self.root)
        self.held = None
        self.new_events = []
        self.rewritten = {}
        self.lock_fd, self.lock_depth = None, 0
        self._me = None
        self.load()
        self.opened = self.base

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
                os.close(self.lock_fd)

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
            write_atomic(self.path, json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")
            self.base = copy.deepcopy(self.data)

    def event(self, type_, milestone=None, story=None, **fields):
        backdated = bool(fields.get("at"))
        line = {"at": fields.pop("at", None) or NOW(), "type": type_, **fields}
        if self.per_person():
            line.setdefault("by", self.me)
        if milestone:
            line["milestone"] = milestone
        if story:
            line["story"] = story
        if not backdated:
            self.new_events.append(line)
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
        return [a for _, a in self.numbered_assumptions()]

    def numbered_assumptions(self):
        """[(number, assumption)]: in a per-person run this person's own, numbered `<n>`, then the top-level ones from
        before `people`, numbered `t<n>`; in any other run the top-level ones, numbered `<n>`."""
        top = self.data.get("assumptions")
        top = top if isinstance(top, list) else []
        if not self.per_person():
            return [(str(i), a) for i, a in enumerate(top)]
        own = self.person().get("assumptions")
        own = own if isinstance(own, list) else []
        return [(str(i), a) for i, a in enumerate(own)] + [(f"t{i}", a) for i, a in enumerate(top)]

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


CHECKOUT_DIRS = ("repos", "worktrees")


def checkout_path(p, path):
    """The absolute path of a checkout podium.json names (`~` expands; a relative path is relative to the run dir), or
    None when it resolves inside the run dir anywhere but repos/ or worktrees/, which never sync: elsewhere a pull may
    have written it."""
    full = os.path.normpath(os.path.join(p.root, os.path.expanduser(str(path))))
    real, root = os.path.realpath(full), os.path.realpath(p.root)
    below = lambda base: os.path.commonpath([base, real]) == base
    if below(root) and not any(below(os.path.join(root, d)) for d in CHECKOUT_DIRS):
        return None
    return full


def building(m):
    return m.get("status") == "working" and m.get("phase") == "build"


TEXT_KEY = re.compile(r"(^|_)(sha|id|branch|base|ref|commit|story|milestone)$|[a-z](Sha|Id)$")


def strict_json(raw):
    """`raw` as JSON, refusing what a browser's JSON.parse refuses: NaN, Infinity and numbers too big for a float."""
    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError(text)
        return value

    def refuse(name):
        raise ValueError(name)
    return json.loads(raw, parse_float=finite, parse_constant=refuse)


def parse_value(raw, key=""):
    """A `key=value` argument's value: now, @file, else JSON when it parses strictly, else the text. An id-like key
    (sha, a ...Sha, id, a ...Id, branch, base, ref, commit, story, milestone) keeps its text, so a SHA like 7e59758
    or 7355178 never turns into a number."""
    if raw == "now":
        return NOW()
    if raw.startswith("@"):
        with open(raw[1:]) as f:
            return json.load(f)
    if TEXT_KEY.search(key):
        return raw
    try:
        return strict_json(raw)
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
    value = parse_value(raw, last)
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


def watcher_running(folder):
    """Whether a watcher is running for the run whose podium dir is `folder`: its heartbeat in watcher.json is under
    WATCHER_LIVE seconds old."""
    try:
        with open(os.path.join(folder, "watcher.json")) as f:
            return time.time() - json.load(f)["at"] < WATCHER_LIVE
    except (OSError, ValueError, KeyError, TypeError):
        return False


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
    with p.locked():
        write_atomic(os.path.join(p.dir, "cursor.json"), json.dumps({"requestsSeen": offset}))


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
    open_ = {i for i, a in p.numbered_assumptions() if a.get("status") == "open"}
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
