"""Paseo, an agent runner: the local daemon's server id, which the Podium's `paseo://` agent deep links need, and the
watcher's view of the stories whose agent runs in Paseo (`agent.backend` "paseo")."""
import json
import os
import subprocess

SERVER_ID = "~/.paseo/server-id"


def server_id():
    """The local Paseo daemon's server id, or None."""
    try:
        with open(os.path.expanduser(SERVER_ID)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def paseo_json(bin_, *args):
    try:
        out = subprocess.run([bin_, *args, "--json"], capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def watch(bin_, stories, waiting, idle):
    """(lines, waiting, idle): PERMISSION <story> <tool> for a story's agent newly waiting for approval,
    PERMISSION-CLEARED <story> once answered, IDLE <story> for a working story's agent gone idle; `waiting` and `idle`
    are the story ids so far, the returned ones the next call's."""
    lines = []
    by_agent = {s["agent"]["id"]: s for s in stories if s.get("agent", {}).get("backend") == "paseo"}
    now_waiting = {}
    for p in paseo_json(bin_, "permit", "ls"):
        s = by_agent.get(p.get("agentId"))
        if s:
            now_waiting[s["id"]] = p.get("name", "tool")
    for sid, tool in now_waiting.items():
        if sid not in waiting:
            lines.append(f"PERMISSION {sid} {tool}")
    for sid in waiting - now_waiting.keys():
        lines.append(f"PERMISSION-CLEARED {sid}")
    working = {s["agent"]["id"]: s["id"] for s in stories if s.get("status") == "working" and s.get("agent", {}).get("backend") == "paseo"}
    now_idle = {working[a["id"]] for a in paseo_json(bin_, "ls", "-g") if a.get("id") in working and a.get("status") == "idle"}
    lines += [f"IDLE {sid}" for sid in now_idle - idle]
    return lines, set(now_waiting), now_idle
