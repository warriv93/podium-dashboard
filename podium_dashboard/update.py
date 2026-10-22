"""`podium self-update`: bring a pip install from git up to its remote's HEAD, at most once per 6 hours per machine."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, distribution

from podium_dashboard import human
from podium_dashboard.files import NOW, git_argv, write_atomic

USAGE = "self-update [--check] [--force]"
THROTTLE = timedelta(hours=6)
LS_REMOTE_TIMEOUT = 20
PIP_TIMEOUT = 300


def stamp_file():
    return os.path.join(os.path.dirname(human.HUMAN_FILE), "update.json")


def direct_url():
    """The installed dist's direct_url.json as a dict, or None when there is no dist or no such file."""
    try:
        text = distribution("podium-dashboard").read_text("direct_url.json")
    except PackageNotFoundError:
        return None
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def last_line(text):
    lines = (text or "").strip().splitlines()
    return lines[-1] if lines else "no output"


class Failed(Exception):
    pass


def output(argv, timeout, what):
    """`argv`'s stdout; raises Failed naming `what` when it cannot run, times out or exits non-zero."""
    try:
        r = run(argv, timeout)
    except subprocess.TimeoutExpired:
        raise Failed(f"{what} timed out after {timeout}s")
    except OSError as e:
        raise Failed(f"{what}: {e}")
    if r.returncode:
        raise Failed(f"{what}: {last_line(r.stderr or r.stdout)}")
    return r.stdout


def stamps():
    """update.json: {"podium": {"at": …}} beside the skills' own "skills:<toplevel>" keys; {} when missing or malformed."""
    try:
        with open(stamp_file()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def checked_recently(now):
    try:
        at = datetime.fromisoformat(stamps()["podium"]["at"])
        return timedelta(0) <= now - at < THROTTLE
    except (KeyError, TypeError, ValueError):
        return False


def write_stamp():
    try:
        os.makedirs(os.path.dirname(stamp_file()), exist_ok=True)
        write_atomic(stamp_file(), json.dumps({**stamps(), "podium": {"at": NOW()}}))
    except OSError:
        pass


def remote_head(url):
    sha = output(git_argv("ls-remote", url, "HEAD"), LS_REMOTE_TIMEOUT, "git ls-remote").partition("\t")[0].strip()
    if not sha:
        raise Failed(f"git ls-remote: {url} has no HEAD")
    return sha


def pip(*args, timeout=PIP_TIMEOUT, what="pip"):
    return output([sys.executable, "-m", "pip", *args], timeout, what)


def pip_major():
    out = pip("--version", what="pip --version")
    try:
        return int(out.split()[1].split(".")[0])
    except (IndexError, ValueError):
        raise Failed(f"pip --version: cannot read {last_line(out)!r}")


def upgrade_old_pip():
    """pip before 22 cannot build this package from git: upgrade it first."""
    if pip_major() < 22:
        pip("install", "--user", "--quiet", "--upgrade", "pip", what="pip upgrade")


def self_update(check=False, force=False, now=None):
    """The lines `podium self-update` prints."""
    info = direct_url()
    if info and (info.get("dir_info") or {}).get("editable"):
        return ["SKIP podium editable"]
    vcs = (info or {}).get("vcs_info") or {}
    if vcs.get("vcs") != "git" or not vcs.get("commit_id") or not info.get("url"):
        return ["SKIP podium not from git"]
    if not force and checked_recently(now or datetime.now(timezone.utc)):
        return ["SKIP podium checked within 6h"]
    old, url = vcs["commit_id"], info["url"]
    try:
        if not check:
            write_stamp()
        new = remote_head(url)
        if new == old:
            return [f"OK podium {old[:7]}"]
        if check:
            return [f"BEHIND podium {old[:7]}→{new[:7]}"]
        upgrade_old_pip()
        pip("install", "--user", "--quiet", "--upgrade", f"git+{url}", what="pip install")
    except Failed as e:
        return [f"WARN podium {e}"]
    return [f"UPDATED podium {old[:7]}→{new[:7]}", "RESTART server"]


def cmd_self_update(p, args):
    if any(a not in ("--check", "--force") for a in args):
        sys.exit(USAGE)
    for line in self_update(check="--check" in args, force="--force" in args):
        print(line)
