"""The Podium version each person runs: the commit their server started on, kept in `people.<me>.podium`, and how many
commits it lacks against the repo's HEAD, so the page can tell who needs `podium self-update` and a Restart."""
import json
import os
import re
import subprocess
from urllib.request import urlopen

from podium_dashboard.files import git_argv
from podium_dashboard.state import person_of
from podium_dashboard.update import direct_url

GITHUB = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
COMPARED = {}


def git(folder, *args):
    try:
        r = subprocess.run(git_argv("-C", folder, *args), capture_output=True, text=True, timeout=20,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def running():
    """(commit, repo URL) of this install: a git install's recorded commit, else the HEAD of the checkout this code runs
    from (an editable install); else (None, None)."""
    info = direct_url() or {}
    vcs = info.get("vcs_info") or {}
    if vcs.get("vcs") == "git" and vcs.get("commit_id") and info.get("url"):
        return vcs["commit_id"], info["url"]
    folder = os.path.dirname(os.path.abspath(__file__))
    commit, origin = git(folder, "rev-parse", "HEAD"), git(folder, "remote", "get-url", "origin")
    return (commit, re.sub(r"\.git$", "", origin)) if commit and origin else (None, None)


def latest(url):
    out = git(".", "ls-remote", url, "HEAD") if url else None
    return (out or "").partition("\t")[0] or None


def behind(url, commit, head):
    """How many commits `commit` lacks against `head` on GitHub, 0 when they match, None when unknown."""
    if commit == head:
        return 0
    m = GITHUB.match(url or "")
    if not m:
        return None
    key = (commit, head)
    if key not in COMPARED:
        try:
            with urlopen(f"https://api.github.com/repos/{m[1]}/{m[2]}/compare/{commit}...{head}", timeout=10) as r:
                COMPARED[key] = int(json.load(r)["ahead_by"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
    return COMPARED[key]


def record(p, commit):
    """Write the commit this person runs to `people.<me>.podium` in a run with people; saved only when it changed."""
    if not commit or not isinstance(p.data.get("people"), dict):
        return
    person = person_of(p.data, p.me)
    if person.get("podium") != commit:
        person["podium"] = commit
        p.save()
