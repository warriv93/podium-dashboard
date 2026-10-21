"""The files of a run's `podium/` folder, the one way they are written (whole, through a temp file), and the one way
the tool runs git on folders a pull may have written."""
import glob
import os
from datetime import datetime, timezone

NOW = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
SHARED_FILES = ["podium.json", "events.jsonl", "handoffs.json", "stories/**"]
MACHINE_FILES = ["cursor.json", "requests.jsonl", "watcher.json", "server.log", "synced.json"]
EMPTY_WHEN_MISSING = {"handoffs.json": {}, "events.jsonl": "", "requests.jsonl": ""}


def progress_files(folder):
    return glob.glob(os.path.join(folder, "stories", "*", "*.progress"))


def watched(folder):
    """requests.jsonl first, then every story's progress file."""
    return [os.path.join(folder, "requests.jsonl"), *progress_files(folder)]


def git_argv(*args):
    """The argv of a git command that takes no folder for a bare repository unless --git-dir names it: a pull may have
    written a bare repository's files, with config that runs commands, anywhere in the run dir."""
    return ["git", "-c", "safe.bareRepository=explicit", *args]


def write_atomic(path, content):
    """Replace `path` with `content` (str or bytes) at once: a reader sees the old file or the new one, never part."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb" if isinstance(content, bytes) else "w") as f:
        f.write(content)
    os.replace(tmp, path)
