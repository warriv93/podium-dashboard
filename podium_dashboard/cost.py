"""What a run's stories cost in tokens on this machine, for GET /cost.

A story's sessions are the Claude Code sessions whose cwd is one of its `worktrees` (relative to the run dir, `~`-based
or absolute) or a folder inside one, plus the subagent log of its `agent.id` when an Agent-tool subagent built it.
Claude Code keeps a session's log in ~/.claude/projects/<slug>, the slug being the cwd it started in with every
character but an ASCII letter or digit made a dash, so only folders named a worktree's slug, or that slug and a dash
and more, are read. A worktree two stories share (a story id reused in another milestone) gives each message to the
story that started last before it.

Logs are parsed in a background thread, a file again only once its size or mtime changed. A request answers what is
ready and starts a refresh when the last one finished over REFRESH seconds ago; `ready` is false until the first has.
"""
import glob
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from podium_dashboard.state import Podium
from podium_dashboard.tokens import largest, message_usages

REFRESH = 30
AGENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def worktrees(root, story):
    found = story.get("worktrees")
    paths = set()
    for path in (found.values() if isinstance(found, dict) else []):
        if isinstance(path, str) and path.strip():
            full = os.path.normpath(os.path.join(root, os.path.expanduser(path)))
            paths |= {full, os.path.realpath(full)}
    return paths


def agent_id(story):
    agent = story.get("agent")
    if isinstance(agent, dict) and agent.get("backend") == "agent" and isinstance(agent.get("id"), str):
        return agent["id"] if AGENT_ID.match(agent["id"]) else None
    return None


def session_logs(projects, path):
    name = slug(path)
    folders = glob.glob(os.path.join(projects, name)) + glob.glob(os.path.join(projects, name + "-*"))
    return {f for d in folders for f in glob.glob(os.path.join(d, "*.jsonl")) + glob.glob(os.path.join(d, "*", "subagents", "*.jsonl"))}


def subagent_logs(projects):
    return glob.glob(os.path.join(projects, "*", "*", "subagents", "agent-*.jsonl"))


def inside(cwd, path):
    return cwd == path or cwd.startswith(path.rstrip("/") + "/")


def owner(cwd, at, claims):
    """The story a message at `at` in `cwd` belongs to: the deepest worktree holding the cwd, and of the stories
    sharing it the last to start before the message, else the first to start."""
    held = [p for p in claims if inside(cwd, p)]
    if not held:
        return None
    stories = sorted(claims[max(held, key=len)])
    before = [s for s in stories if s[0] <= at]
    return before[-1][1] if before else stories[0][1]


def utc(text):
    """An ISO time as a sortable UTC string, "" when it isn't one."""
    try:
        at = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except (AttributeError, TypeError, ValueError):
        return ""
    return (at.astimezone(timezone.utc) if at.tzinfo else at).isoformat(timespec="milliseconds")


def totals(usage):
    i, creation, read, out = usage
    return {"input": i, "cache": creation + read, "output": out}


def added(a, b):
    return {k: a.get(k, 0) + b[k] for k in b}


class Costs:
    def __init__(self, root, projects=None):
        self.root = root
        self.projects = projects or os.path.expanduser(os.path.join("~", ".claude", "projects"))
        self.parsed = {}
        self.answer = {"ready": False, "milestones": {}}
        self.lock = threading.Lock()
        self.running = False
        self.finished = None

    def get(self):
        with self.lock:
            if not self.running and (self.finished is None or time.monotonic() - self.finished >= REFRESH):
                self.running = True
                threading.Thread(target=self.refresh, daemon=True).start()
            return self.answer

    def refresh(self):
        answer = None
        try:
            answer = self.compute()
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                self.running = False
                self.finished = time.monotonic()
                if answer is not None:
                    self.answer = answer

    def usages(self, path):
        try:
            st = os.stat(path)
            seen = self.parsed.get(path)
            if seen and seen[0] == (st.st_mtime, st.st_size):
                return seen[1]
            found = message_usages(path)
        except OSError:
            return {}
        self.parsed[path] = ((st.st_mtime, st.st_size), found)
        return found

    def compute(self):
        claims, agents, logs = defaultdict(list), {}, set()
        for m in Podium(self.root).milestones():
            for s in m.get("stories") or []:
                if not isinstance(s, dict) or not isinstance(m.get("id"), str) or not isinstance(s.get("id"), str):
                    continue
                story = (m["id"], s["id"])
                started = utc(s.get("startedAt"))
                for path in worktrees(self.root, s):
                    claims[path].append((started, story))
                    logs |= session_logs(self.projects, path)
                if agent_id(s):
                    agents[f"agent-{agent_id(s)}.jsonl"] = story
        by_agent = {f: agents[os.path.basename(f)] for f in subagent_logs(self.projects) if os.path.basename(f) in agents} if agents else {}
        messages = defaultdict(dict)
        for f in logs | set(by_agent):
            for mid, u in self.usages(f).items():
                story = by_agent.get(f) or owner(u["cwd"], utc(u["at"]), claims)
                if story:
                    seen = messages[story].get(mid)
                    messages[story][mid] = largest(seen, u["usage"]) if seen else u["usage"]
        self.parsed = {f: v for f, v in self.parsed.items() if f in logs or f in by_agent}
        milestones = {}
        for (ms, sid), found in messages.items():
            tokens = totals([sum(col) for col in zip(*found.values())])
            entry = milestones.setdefault(ms, {"input": 0, "cache": 0, "output": 0, "stories": {}})
            entry.update(added(entry, tokens))
            entry["stories"][sid] = tokens
        return {"ready": True, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "milestones": milestones}
