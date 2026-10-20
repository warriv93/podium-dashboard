"""The user's availability: their hours and the Podium's toggle, one file per machine."""
import json
import os
import subprocess
from datetime import datetime, time, timedelta

from podium_dashboard.files import write_atomic

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOURS = {"days": "Mon-Fri", "from": "07:00", "to": "17:00"}
HUMAN_FILE = os.path.expanduser(os.environ.get("PODIUM_HUMAN", "~/.podium/human.json"))


def day_set(spec):
    """'Mon-Fri' or 'Mon,Wed,Fri-Sun' → weekday numbers (Mon = 0)."""
    out = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        i, j = DAYS.index(a), DAYS.index(b or a)
        out |= {d % 7 for d in range(i, j + 1 if j >= i else j + 8)}
    return out


def in_hours(hours, t):
    return t.weekday() in day_set(hours["days"]) and hours["from"] <= t.strftime("%H:%M") < hours["to"]


def next_change(hours, t):
    """The first local time after t at which the hours start or end, or None."""
    now = in_hours(hours, t)
    for d in range(8):
        day = (t + timedelta(days=d)).date()
        for hm in sorted((hours["from"], hours["to"])):
            c = datetime.combine(day, time.fromisoformat(hm))
            if c > t and in_hours(hours, c) != now:
                return c
    return None


def local(iso):
    return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)


def human_state():
    """HUMAN_FILE: {hours, mode, until, at}, the user's hours and the toggle's override while `until` holds."""
    try:
        with open(HUMAN_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def human_hours():
    return {**HOURS, **(human_state().get("hours") or {})}


def me():
    """Who this machine's user is in a shared run: $PODIUM_ME, else `me` in HUMAN_FILE (`podium whoami <name>`), else
    the local part of `git config user.email`, else $USER."""
    named = os.environ.get("PODIUM_ME") or human_state().get("me")
    if named:
        return named
    try:
        email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True).stdout.strip()
    except OSError:
        email = ""
    return email.partition("@")[0] or os.environ.get("USER") or "me"


def write_human(**changes):
    """Change HUMAN_FILE atomically; a None value drops its key."""
    state = {k: v for k, v in {**human_state(), **changes}.items() if v is not None}
    os.makedirs(os.path.dirname(HUMAN_FILE), exist_ok=True)
    write_atomic(HUMAN_FILE, json.dumps(state))


def availability(t=None):
    """{mode, until, source, hours}: mode `available`, `mobile` (reachable in chat on a phone, no
    localhost) or `unavailable`, until a local ISO time or None,
    source `toggle` while the toggle's override holds, else `hours`. Times are naive local."""
    t = t or datetime.now()
    o = human_state()
    hours = human_hours()
    if o.get("mode") in ("available", "mobile", "unavailable") and o.get("until") and local(o["until"]) > t:
        return {"mode": o["mode"], "until": local(o["until"]).isoformat(timespec="minutes"), "source": "toggle", "hours": hours}
    nxt = next_change(hours, t)
    return {"mode": "available" if in_hours(hours, t) else "unavailable",
            "until": nxt and nxt.isoformat(timespec="minutes"), "source": "hours", "hours": hours}


def human_line(a):
    until = datetime.fromisoformat(a["until"]).strftime("%a %H:%M") if a["until"] else "further notice"
    h = a["hours"]
    why = "Podium toggle; " if a["source"] == "toggle" else ""
    return f"{a['mode']} until {until} ({why}hours {h['days']} {h['from']}-{h['to']})"
