"""The Podium watcher, run by the orchestrator as a background command: `podium watch [--dir <run dir>] [--paseo
/path/to/paseo] [--once]`, by default for the run `podium` finds from the cwd.

Prints one line per event the orchestrator must act on:

    REQUEST <action> [<id>] [note=…]  a Podium button (requests.jsonl); confirm/reverse <n> settle an assumption; asana [<epic>] note=<Asana link> links Asana;
                                    build-all/stop/proceed <milestone> name the milestone they act on, assign [<milestone>/]<story> its story;
                                    share, with no id, asks to share the run with a colleague
    PROGRESS <story> <line>         a story agent's COMMITTED or FAILED line (stories/<milestone>/<story>.progress);
                                    the other stages only feed the Podium, so they stay out of the agent's context
    PERMISSION <story> <tool>       a Paseo agent waits for approval   (--paseo)
    PERMISSION-CLEARED <story>      that approval was answered          (--paseo)
    IDLE <story>                    a working story's Paseo agent went idle (--paseo)
    HUMAN <available|mobile|unavailable>   the user's availability flipped (hours or the Podium toggle)
    SYNCED <sha> <summary>          a pull brought someone else's saves (sync on): the new events' types by who
                                    made them (`ann: status×2, owner`), else the save's commit subject
    REVIEWED <milestone> [<repo>]#<n> by=<who>   with SYNCED: someone looked at the PR of a milestone this person owns
    LAPSE <mode>, nothing building  the last line: nothing needs watching, so it exits

It needs watching while the user is available or a story of any milestone is working. Otherwise
the only events left are Podium buttons, which need the user at this computer.

In a run that syncs it pulls every 60 s, skipping a turn while another podium command holds the run's lock. The
progress lines a pull brings are the other machine's stories: it never prints them, but prints every line logged
here, also one logged while the pull ran. A progress file a save's merge rewrote behind it (a new inode, or shorter
than where it read to) is read whole: it prints the lines it never handled, and only for a story of a milestone the
run has, with no owner or this person.

--once exits after the first events (and the lines that follow within 2 s), so a
background command returns them. It also rewrites watcher.json ({pid, at}, where
it has read up to, `seen`, each progress file's inode and digests of the lines it
handled, and `since`, where this chain of runs started reading) every few
seconds, its heartbeat: the Podium server takes requests only while it is fresh, a
watcher started within 10 minutes of the last one resumes where that one stopped, so
nothing is lost between runs, and `podium requests` skips the requests it printed.
"""
import argparse
import fcntl
import hashlib
import json
import os
import time

from podium_dashboard import sync
from podium_dashboard.files import watched, write_atomic
from podium_dashboard.human import availability
from podium_dashboard.plugins import paseo
from podium_dashboard.server import load_podium, load_run, run_dir
from podium_dashboard.state import podium_dir

SYNC_EVERY = 60


def busy(p):
    """Whether another podium command holds the run's lock."""
    if not os.path.isdir(p.dir):
        return False
    fd = os.open(p.dir, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def lines_of(path):
    try:
        with open(path) as f:
            return f.read().splitlines()
    except OSError:
        return []


def summary(before, after):
    """The types of the events in `after` that `before` lacks, grouped by who made them: `ann: status×2, owner`."""
    seen, groups = set(before), {}
    for raw in after:
        if raw in seen or not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict):
            types = groups.setdefault(e.get("by"), {})
            kind = str(e.get("type") or "?")
            types[kind] = types.get(kind, 0) + 1
    return "; ".join((f"{who}: " if who else "") + ", ".join(t + (f"×{n}" if n > 1 else "") for t, n in types.items())
                     for who, types in groups.items())


def subject(p, sha):
    g, _ = sync.open_git(p)
    try:
        return g.out("log", "-1", "--format=%s", sha).strip() if g else ""
    except sync.SyncError:
        return ""


def digest(line):
    return hashlib.sha1(line.encode(errors="surrogateescape")).hexdigest()[:12]


def handled(path, upto):
    """{ino, lines}: the inode of `path` and the digests of its lines before byte `upto`."""
    with open(path, "rb") as f:
        return {"ino": os.fstat(f.fileno()).st_ino, "lines": {digest(x) for x in f.read(upto).decode(errors="replace").splitlines()}}


def fresh(folder):
    """(offsets, seen) of a watcher starting anew: every watched file read to its end."""
    offsets = {path: os.path.getsize(path) for path in watched(folder) if os.path.exists(path)}
    return offsets, {path: handled(path, at) for path, at in offsets.items() if path.endswith(".progress")}


def built_here(root, path):
    """Whether a progress file's story is of a milestone the run has, with no owner or this person."""
    p = load_podium(root)
    mid = os.path.basename(os.path.dirname(path))
    found = next((m for m in p.milestones() if m.get("id") == mid), None) if p else None
    return found is not None and (not found.get("owner") or found.get("owner") == p.me)


def news(path, offsets, seen, mine):
    """The lines to print for what `path` gained since the watcher read it; `offsets` and, for a progress file,
    `seen` move to its end. A progress file rewritten behind the watcher is read whole, and of the lines it never
    handled prints those of a story `mine(path)` says is built here; so does one that appeared since the watcher
    started, which a save's merge may have brought."""
    known = seen.get(path) if path.endswith(".progress") else None
    st = os.stat(path)
    rewritten = known is not None and (st.st_ino != known["ino"] or st.st_size < offsets.get(path, 0))
    with open(path) as f:
        f.seek(0 if rewritten else offsets.get(path, 0))
        chunk = f.read()
        offsets[path] = f.tell()
    if not path.endswith(".progress"):
        return printed(path, chunk)
    lines = chunk.splitlines()
    done = known["lines"] if known else set()
    unread = [x for x in lines if digest(x) not in done] if rewritten else lines
    seen[path] = {"ino": st.st_ino, "lines": done | {digest(x) for x in lines}}
    found = printed(path, "\n".join(unread))
    return found if not found or known is not None and not rewritten or mine(path) else []


def printed(path, chunk):
    """The lines to print for a chunk of `path`: its requests, or its COMMITTED and FAILED progress lines."""
    found = []
    for line in chunk.splitlines():
        if not line.strip():
            continue
        if path.endswith("requests.jsonl"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            note = f" note={r['note']}" if r.get("note") else ""
            found.append(f"REQUEST {r.get('action')} {r.get('story') or ''}".rstrip() + note)
        elif line.split()[1:2] in (["COMMITTED"], ["FAILED"]):
            found.append(f"PROGRESS {os.path.basename(path)[:-len('.progress')]} {line}")
    return found


def reviewed(p, before, after):
    """REVIEWED lines for the `reviewed` events in `after` that `before` lacks, made by someone else on a PR of a
    milestone this person owns."""
    seen, out = set(before), []
    for raw in after:
        if raw in seen or not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("type") == "reviewed" and e.get("owner") == p.me and e.get("by") != p.me:
            out.append(f"REVIEWED {e.get('milestone')} {e.get('repo') or ''}#{e.get('number')} by={e.get('by')}")
    return out


def pull(p, offsets, seen):
    """The lines to print after a pull: the progress logged here that the watcher had not read when the pull rewrote
    its file, then SYNCED <sha> <summary> when the pull brought someone else's saves. A rewritten file's offset moves
    past the lines the pull brought, the other machine's stories."""
    events = os.path.join(p.dir, "events.jsonl")
    before = lines_of(events)
    out, found = sync.pull(p, from_watcher=True), []
    for path in watched(p.dir)[1:]:
        here, written = p.rewritten.get(os.path.relpath(path, p.root).replace(os.sep, "/"), (None, None))
        if written is not None:
            found += printed(path, (here or b"")[offsets.get(path, 0):].decode(errors="replace"))
            offsets[path] = len(written)
            seen[path] = {"ino": os.stat(path).st_ino,
                          "lines": {digest(x) for x in written.decode(errors="replace").splitlines()}}
    for path in [x for x in offsets if not os.path.exists(x)]:
        del offsets[path]
        seen.pop(path, None)
    if out.startswith("PULLED "):
        sha = out.split()[1]
        after = lines_of(events)
        found.append(f"SYNCED {sha} {summary(before, after) or subject(p, sha)}".rstrip())
        found += reviewed(p, before, after)
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(prog="podium watch")
    ap.add_argument("--dir")
    ap.add_argument("--paseo")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    root = run_dir(args.dir)

    def human():
        return availability()["mode"]

    beat = os.path.join(podium_dir(root), "watcher.json")
    try:
        with open(beat) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = {}
    if time.time() - last.get("at", 0) < 600 and "offsets" in last:
        offsets, mode = dict(last["offsets"]), last.get("mode") or human()
        waiting, idle = set(last.get("waiting", [])), set(last.get("idle", []))
        since = dict(last.get("since") or {})
        seen = {path: {"ino": v["ino"], "lines": set(v["lines"])} for path, v in (last.get("seen") or {}).items()}
        for path in watched(podium_dir(root)):
            if path.endswith(".progress") and path in offsets and path not in seen and os.path.exists(path):
                seen[path] = handled(path, offsets[path])
            offsets.setdefault(path, 0)
    else:
        offsets, seen = fresh(podium_dir(root))
        mode, waiting, idle = human(), set(), set()
        since = dict(offsets)

    def needed():
        return mode == "available" or any(s.get("status") == "working" for m in load_run(root)[0] for s in m.get("stories", []))

    def save():
        os.makedirs(os.path.dirname(beat), exist_ok=True)
        write_atomic(beat, json.dumps({"pid": os.getpid(), "at": time.time(), "offsets": offsets, "mode": mode,
                                       "since": {path: since.get(path, 0) for path in offsets},
                                       "seen": {path: {"ino": v["ino"], "lines": sorted(v["lines"])} for path, v in seen.items()},
                                       "waiting": sorted(waiting), "idle": sorted(idle)}))

    first = None
    def emit(line):
        nonlocal first
        first = first or time.time()
        print(line, flush=True)

    last_paseo = last_human = last_need = last_beat = last_sync = 0.0
    while True:
        if args.once and first and time.time() - first > 2:
            save()
            return
        if time.time() - last_beat > 5:
            last_beat = time.time()
            save()
        if time.time() - last_need > 60:
            last_need = time.time()
            if not needed():
                save()
                emit(f"LAPSE {mode}, nothing building")
                return

        for path in watched(podium_dir(root)):
            if os.path.exists(path):
                for line in news(path, offsets, seen, lambda x: built_here(root, x)):
                    emit(line)

        if time.time() - last_sync > SYNC_EVERY:
            last_sync = time.time()
            p = load_podium(root)
            if p and sync.enabled(p) and not busy(p):
                for line in pull(p, offsets, seen):
                    emit(line)

        if time.time() - last_human > 15:
            last_human = time.time()
            now_mode = human()
            if now_mode != mode:
                emit(f"HUMAN {now_mode}")
            mode = now_mode

        if args.paseo and time.time() - last_paseo > 10:
            last_paseo = time.time()
            stories = [s for m in load_run(root)[0] for s in m.get("stories", [])]  # every milestone: two can build at once
            lines, waiting, idle = paseo.watch(args.paseo, stories, waiting, idle)
            for line in lines:
                emit(line)

        time.sleep(1)


if __name__ == "__main__":
    main()
