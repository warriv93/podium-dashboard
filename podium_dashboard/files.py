"""The files of a run's `podium/` folder, and the one way they are written: whole, through a temp file."""
import glob
import os

SHARED_FILES = ["podium.json", "events.jsonl", "handoffs.json", "stories/**"]
MACHINE_FILES = ["cursor.json", "requests.jsonl", "watcher.json", "server.log"]
EMPTY_WHEN_MISSING = {"handoffs.json": {}, "events.jsonl": "", "requests.jsonl": ""}


def progress_files(folder):
    return glob.glob(os.path.join(folder, "stories", "*", "*.progress"))


def watched(folder):
    """requests.jsonl first, then every story's progress file."""
    return [os.path.join(folder, "requests.jsonl"), *progress_files(folder)]


def write_atomic(path, content):
    """Replace `path` with `content` (str or bytes) at once: a reader sees the old file or the new one, never part."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb" if isinstance(content, bytes) else "w") as f:
        f.write(content)
    os.replace(tmp, path)
