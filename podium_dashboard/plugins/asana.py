"""Asana, over its REST API: `podium asana link <url> [<target>]` links the project, an epic or a milestone to an Asana
project or task, and `podium asana refresh` re-reads every link. A linked task is an epic and its subtasks are that
epic's milestones. The run's extension sees each task first, through on_asana_refresh(p, task_json)."""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from podium_dashboard import extension, sync
from podium_dashboard.state import NOW

API = "https://app.asana.com/api/1.0"
KEYCHAIN = "podium-asana"
FIELDS = "name,notes,completed,assignee.name,permalink_url,custom_fields.name,custom_fields.display_value"
TASK_FIELDS = FIELDS + "," + ",".join(f"subtasks.{f}" for f in FIELDS.split(","))
PROJECT_FIELDS = "name,completed,owner.name,permalink_url,custom_fields.name,custom_fields.display_value"


class AsanaError(Exception):
    pass


def asana_token():
    """The personal access token: $ASANA_TOKEN, else the keychain's `podium-asana` item; None without one."""
    if os.environ.get("ASANA_TOKEN"):
        return os.environ["ASANA_TOKEN"]
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN, "-w"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def fetch(path, token, **params):
    """GET an Asana API path: its `data`, a list followed through every page."""
    url, out = f"{API}{path}?{urllib.parse.urlencode(params)}", []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:
            raise AsanaError(f"{e.code} {e.reason}")
        except (OSError, ValueError) as e:
            raise AsanaError(str(e))
        if not isinstance(body.get("data"), list):
            return body.get("data")
        out += body["data"]
        url = (body.get("next_page") or {}).get("uri")
    return out


def parse(url):
    """(kind, gid) of an Asana project or task link, kind `project` or `task`; None for any other link. A project's
    permalink repeats its gid (`/0/<gid>/<gid>`)."""
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.netloc != "app.asana.com":
        return None
    parts = [s for s in u.path.split("/") if s]
    after = lambda word: next((b for a, b in zip(parts, parts[1:]) if a == word and b.isdigit()), None)
    old = parts[1:3] if parts[:1] == ["0"] and len(parts) > 1 and parts[1].isdigit() else []
    if after("task"):
        return "task", after("task")
    if len(old) == 2 and old[1].isdigit() and old[1] != old[0]:
        return "task", old[1]
    gid = after("project") or after("projects") or (old[0] if old and old[0] != "0" else None)
    return ("project", gid) if gid else None


def linked_as(a):
    """(kind, gid) of an object's `asana`: its own kind, else the kind its URL names (a run from before kinds), else
    a task."""
    kind, gid = parse(a.get("url") or "") or ("task", None)
    return a.get("kind") or kind, a.get("gid") or gid


def asana_link(t, kind, old=None):
    """An Asana task or project as podium.json's `asana`, keeping what the run added (`keep`)."""
    return {**(old or {}), "kind": kind, "gid": t["gid"], "url": t.get("permalink_url"),
            "assignee": (t.get("assignee") or {}).get("name"),
            "fields": [{"name": f.get("name"), "value": f["display_value"]} for f in t.get("custom_fields") or []
                       if f.get("display_value") not in (None, "")],
            "completed": bool(t.get("completed")), "syncedAt": NOW()}


def norm(text):
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def links(p):
    return [x for x in [p.data.get("project") or {}] + p.epics() + p.milestones() if x.get("asana")]


def link(p, url, target="."):
    """Link the project (`.`), an epic (`epic:<id>`) or a milestone (`milestone:<id>`) to the Asana project or task the
    URL names, storing its kind; the next refresh reads it. Returns the line to print; the caller saves."""
    found = parse(url)
    if not found:
        sys.exit(f"asana link: not an Asana project or task link: {url}")
    kind, gid = found
    if target == ".":
        obj, mid = p.data.setdefault("project", {}), None
    elif target.startswith(("epic:", "milestone:")):
        obj, mid, _ = p.resolve(target)
    else:
        sys.exit("asana link <url> [. | epic:<id> | milestone:<id>]")
    other = next((x for x in links(p) if x is not obj and linked_as(x["asana"])[1] == gid), None)
    if other:
        sys.exit(f"asana link: {kind} {gid} is already linked to {other.get('id') or 'the project'}")
    old = obj.get("asana") or {}
    obj["asana"] = {**(old if old.get("gid") == gid else {}), "kind": kind, "gid": gid, "url": url}
    line = f"LINKED {target} to Asana {kind} {gid}"
    p.event("asana", mid, text=line)
    return line


def refresh(p, token=None):
    """Re-read every linked project and task: generic fields written into each object's `asana`, a line and an `asana`
    event per change, a linked epic task's new subtasks matched to its milestones (LINKED, NEW, or `ASK <subtask gid>
    "<name>" → <candidates>` for one only the user can place), and `COMPLETED <milestone> …` for a milestone whose
    subtask was completed while it hasn't landed. The extension's on_asana_refresh sees every task before its write:
    `task_json["subtasks"]` holds the subtasks of a task read on its own. [] when nothing links Asana, `ASANA NO_TOKEN`
    without a token. The caller prints the lines and saves."""
    if not links(p):
        return []
    token = token or asana_token()
    if not token:
        return ["ASANA NO_TOKEN"]
    module, why = extension.load(p)
    hook = extension.on_asana_refresh(module)
    lines, seen, events = [f"ASANA-ERROR {why}"] if why else [], set(), len(p.new_events)
    title = lambda t: " ".join(t.get("name", "").split())

    def note(line, milestone=None):
        lines.append(line)
        p.event("asana", milestone, text=line)

    def update(obj, t, label, milestone=None, kind="task"):
        old = dict(obj.get("asana") or {})
        if hook and kind == "task":
            hook(p, t)
        obj["asana"] = asana_link(t, kind, obj.get("asana"))
        seen.add(t["gid"])
        changed = [k for k in ("url", "assignee", "fields", "completed") if old.get(k) != obj["asana"][k]]
        if changed and old.get("syncedAt"):
            note(f"ASANA {label} " + ", ".join(f"{k} {obj['asana'][k]}" if k != "fields" else "fields" for k in changed), milestone)
        return old

    def read(a):
        kind, gid = linked_as(a)
        try:
            if kind == "project":
                t = fetch(f"/projects/{gid}", token, opt_fields=PROJECT_FIELDS)
                return kind, {**t, "assignee": t.get("owner")}
            t = fetch(f"/tasks/{gid}", token, opt_fields=TASK_FIELDS)
            if "subtasks" not in t:
                t["subtasks"] = fetch(f"/tasks/{gid}/subtasks", token, opt_fields=FIELDS, limit=100)
            return kind, t
        except AsanaError as e:
            lines.append(f"ASANA-ERROR {gid}: {e}")
            return kind, None

    def linked(gid):
        return next((m for m in p.milestones() if (m.get("asana") or {}).get("gid") == gid), None)

    def next_id(prefix):
        nums = [int(x[len(prefix):]) for x in (m.get("id", "") for m in p.milestones()) if re.fullmatch(rf"{prefix}\d+", x)]
        return f"{prefix}{max(nums, default=0) + 1}"

    def refresh_milestone(m, t, kind="task"):
        old = update(m, t, m["id"], m["id"], kind)
        if t.get("completed") and not old.get("completed") and m.get("status") not in ("done", "dropped"):
            note(f"COMPLETED {m['id']} in Asana, not landed: the Podium asks Done?", m["id"])

    for e in p.epics():
        if not e.get("asana"):
            continue
        kind, t = read(e["asana"])
        if not t:
            continue
        update(e, t, f"epic {e['id']}", kind=kind)
        for sub in t.get("subtasks") or []:
            m = linked(sub["gid"])
            if m:
                refresh_milestone(m, sub)
                continue
            unlinked = [m for m in e.get("milestones", []) if not (m.get("asana") or {}).get("gid") and m.get("status") != "dropped"]
            named = lambda m: (norm(m.get("title", "")) == norm(title(sub)) or re.search(rf"(?<!\w){re.escape(m['id'])}(?!\w)", sub["name"], re.I)
                               or (re.fullmatch(r"M(\d+)", m["id"]) and re.search(rf"\bmilestone\s+{m['id'][1:]}\b", sub["name"], re.I)))
            obvious = [m for m in unlinked if named(m)]
            if len(obvious) == 1:
                note(f"LINKED {obvious[0]['id']} to subtask \"{title(sub)}\"", obvious[0]["id"])
                refresh_milestone(obvious[0], sub)
            elif unlinked:
                lines.append(f"ASK {sub['gid']} \"{title(sub)}\" → {' '.join(m['id'] for m in obvious or unlinked)} new")
                seen.add(sub["gid"])
            else:
                m = {"id": next_id("M"), "title": title(sub), "summary": (sub.get("notes") or "").strip().split("\n\n")[0][:300],
                     "status": "done" if sub.get("completed") else "draft", "deps": []}
                e.setdefault("milestones", []).append(m)
                update(m, sub, m["id"])
                note(f"NEW {m['id']} {m['status']} \"{m['title']}\" in {e['id']}", m["id"])

    project = p.data.get("project") or {}
    if project.get("asana"):
        kind, t = read(project["asana"])
        if t:
            update(project, t, "project", kind=kind)

    for m in p.milestones():  # a subtask linked outside its epic's task, or under an unlinked epic
        if not m.get("asana") or linked_as(m["asana"])[1] in seen:
            continue
        kind, t = read(m["asana"])
        if t:
            refresh_milestone(m, t, kind)
    return lines or ([] if len(p.new_events) > events else [f"ASANA {len(seen)} tasks read, no changes"])


def cmd_asana(p, args):
    if args[:1] == ["link"] and len(args) in (2, 3):
        print(link(p, *args[1:]))
        p.save()
        return
    if args != ["refresh"]:
        sys.exit("asana link <url> [. | epic:<id> | milestone:<id>] | asana refresh")
    token = asana_token()
    if not token:
        print("NO_TOKEN")
        sys.exit(3)
    lines = refresh(p, token) if links(p) else ["ASANA nothing linked"]
    p.save()
    for line in lines:
        print(line)
    if any(line.startswith("ASANA-ERROR") for line in lines):
        sync.autosave(p)
        sys.exit(1)
