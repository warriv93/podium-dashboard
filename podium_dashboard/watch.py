"""The Podium watcher, run by the orchestrator as a background command: `podium watch [--dir <run dir>] [--paseo
/path/to/paseo] [--once]`, by default for the run `podium` finds from the cwd.

Prints one line per event the orchestrator must act on:

    REQUEST <action> [<id>] [note=…]  a Podium button (requests.jsonl); confirm/reverse <n> settle an assumption; asana [<epic>] note=<Asana link> links Asana;
                                    build-all/stop <milestone> name the milestone they act on, assign [<milestone>/]<story> its story
    PROGRESS <story> <line>         a story agent's COMMITTED or FAILED line (stories/<milestone>/<story>.progress);
                                    the other stages only feed the Podium, so they stay out of the agent's context
    PERMISSION <story> <tool>       a Paseo agent waits for approval   (--paseo)
    PERMISSION-CLEARED <story>      that approval was answered          (--paseo)
    IDLE <story>                    a working story's Paseo agent went idle (--paseo)
    HUMAN <available|mobile|unavailable>   the user's availability flipped (hours or the Podium toggle)
    SYNCED <sha> <summary>          a pull brought someone else's saves (sync on): the new events' types by who
                                    made them (`ann: status×2, owner`), else the save's commit subject
    LAPSE <mode>, nothing building  the last line: nothing needs watching, so it exits

It needs watching while the user is available or a story of any milestone is working. Otherwise
the only events left are Podium buttons, which need the user at this computer.

In a run that syncs it pulls every 60 s, skipping a turn while another podium command holds the run's lock. The
progress lines a pull brings are the other machine's stories: it never prints them.

--once exits after the first events (and the lines that follow within 2 s), so a
background command returns them. It also rewrites watcher.json ({pid, at}, where
it has read up to, and `since`, where this chain of runs started reading) every few
seconds, its heartbeat: the Podium server takes requests only while it is fresh, a
watcher started within 10 minutes of the last one resumes where that one stopped, so
nothing is lost between runs, and `podium requests` skips the requests it printed.
"""
import argparse
import fcntl
import glob
import json
import os
import time

from podium_dashboard import sync
from podium_dashboard.plugins import paseo
from podium_dashboard.server import load_podium, load_run, run_dir  # one reader for podium.json, shared with the server
from podium_dashboard.state import availability, podium_dir

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
        os.close(fd)  # releases the lock
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


def pull(p):
    """SYNCED <sha> <summary> when a pull brought someone else's saves, else None."""
    events = os.path.join(p.dir, "events.jsonl")
    before = lines_of(events)
    out = sync.pull(p, from_watcher=True)
    if not out.startswith("PULLED "):
        return None
    sha = out.split()[1]
    return f"SYNCED {sha} {summary(before, lines_of(events)) or subject(p, sha)}".rstrip()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="podium watch")
    ap.add_argument("--dir")
    ap.add_argument("--paseo")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    root = run_dir(args.dir)

    def watched():
        pod = podium_dir(root)
        return [os.path.join(pod, "requests.jsonl"), *glob.glob(os.path.join(pod, "stories", "*", "*.progress"))]

    def human():
        return availability()["mode"]

    beat = os.path.join(podium_dir(root), "watcher.json")
    try:
        with open(beat) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = {}
    if time.time() - last.get("at", 0) < 600 and "offsets" in last:
        # the previous watcher stopped moments ago: carry on from where it read to; files new since then from the top
        offsets, mode = dict(last["offsets"]), last.get("mode") or human()
        waiting, idle = set(last.get("waiting", [])), set(last.get("idle", []))
        since = dict(last.get("since") or {})
        for path in watched():
            offsets.setdefault(path, 0)
    else:
        # start at the end: only new lines are events
        offsets = {path: os.path.getsize(path) for path in watched() if os.path.exists(path)}
        mode, waiting, idle = human(), set(), set()
        since = dict(offsets)

    def needed():
        """The user is available, or a story is being built."""
        return mode == "available" or any(s.get("status") == "working" for m in load_run(root)[0] for s in m.get("stories", []))

    def save():
        os.makedirs(os.path.dirname(beat), exist_ok=True)
        with open(beat + ".tmp", "w") as f:
            json.dump({"pid": os.getpid(), "at": time.time(), "offsets": offsets, "mode": mode,
                       "since": {path: since.get(path, 0) for path in offsets},
                       "waiting": sorted(waiting), "idle": sorted(idle)}, f)
        os.replace(beat + ".tmp", beat)

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

        for path in watched():
            if not os.path.exists(path):
                continue
            with open(path) as f:
                f.seek(offsets.get(path, 0))
                chunk = f.read()
                offsets[path] = f.tell()
            for line in chunk.splitlines():
                if not line.strip():
                    continue
                if path.endswith("requests.jsonl"):
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    note = f" note={r['note']}" if r.get("note") else ""
                    emit(f"REQUEST {r.get('action')} {r.get('story') or ''}".rstrip() + note)
                elif line.split()[1:2] in (["COMMITTED"], ["FAILED"]):
                    emit(f"PROGRESS {os.path.basename(path)[:-len('.progress')]} {line}")

        if time.time() - last_sync > SYNC_EVERY:
            last_sync = time.time()
            p = load_podium(root)
            if p and sync.enabled(p) and not busy(p):
                synced = pull(p)
                if synced:
                    for path in watched()[1:]:
                        offsets[path] = os.path.getsize(path)
                    emit(synced)

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
