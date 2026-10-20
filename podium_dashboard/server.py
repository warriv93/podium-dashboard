"""The Podium server: `podium server [--dir <run dir>] [--port 8765] [--idle 60] [--detach] [--git-every 5]`.

Serves `podium.html` (next to this file) plus the run directory (by default the run `podium` finds from the cwd,
whose `podium/` folder holds the run's files) on 127.0.0.1, and turns the Podium's buttons into lines in
`requests.jsonl`, which the orchestrator watches. The browser only ever sends an action and an id; prompts come from
the run's orchestrator extension.

It answers only requests whose Host is 127.0.0.1:<port> or localhost:<port>, and a POST or DELETE only when its
Origin, if any, is that same server: a page elsewhere can't reach it through DNS rebinding or a cross-site form.
GET /repo/<path> serves a file of the folder the run dir sits in, never one outside it.

A story in a path is `<story>`, of the active milestone, or `<milestone>/<story>`, of any: two milestones can build
at once.

GET /prompt/<plan|assign>/<id> returns the prompt the orchestrator would act on, for the user to run in a session of
their own: the extension's prompt(p, kind, id), with `<id>` a milestone for plan and `<milestone>/<story>` for
assign. A plan prompt the extension doesn't give is `<orchestrator.command> <milestone>`. Without an extension
prompt, assign answers 501.

POST /handoff/<story> hands a ready story to such a session: it records the story in `handoffs.json` (this server is
its only writer), so the orchestrator leaves it alone, and returns the extension's `handoff` prompt (501 without one).
DELETE /handoff/<story> takes it back.

POST /<action>/<id> queues a request: the core's actions (assign, plan, build-all, stop, confirm, reverse,
domain-story, claim) and the extension's ACTIONS. confirm and reverse take an assumption's number as `podium
assumptions` prints it (`<n>`, or `t<n>` for a run's older top-level ones in a run with one state per person) or
`all`, every open one not yet answered. POST /build-all/<milestone> and /stop/<milestone> queue that milestone's
build-all and its stop: each milestone has its own. Bare, from an older page, they name the active milestone.

POST /asana[/<epic>]?url=<Asana link> queues a link of an Asana project or task (or of an epic to its task) as an
`asana` request, like settling an assumption kept for the next orchestrator run, so it needs no watcher.
POST /asana-done/<milestone>?choice=<drop|keep> queues the user's answer for a milestone completed in Asana but not
landed here, the same way.

The buttons that need the orchestrator (all but confirm, reverse and the Asana ones) answer 409 while no watcher is
running (watcher.json older than 30 s): nothing would read the request. GET /info says `watching`.

The availability toggle writes the user's human.json, shared by every Podium on the machine:
POST /human/<available|mobile|unavailable|auto>[?until=HH:MM]. GET /human returns the reading of the user's
availability. A Podium tab in use while the toggle says mobile means the user is at a computer: after 15 minutes of
Mobile, it turns the toggle to available.

It stops itself after --idle minutes (default 60, 0 = never) without activity: a Podium tab in view and used in the
last 10 minutes (its polls carry X-Podium-Visible), a button, or a change to podium.json, events.jsonl or a story's
progress file. --detach binds the port, prints the URL and returns, leaving the server running in the background with
its output in server.log in the podium dir.

GET /info says `stale` once a Python file of this package changed after the server started: it still runs the old
code, while podium.html is read on every load. POST /restart replaces the process with a fresh one on the same port
and arguments, so it picks up the change; the run's state is all on disk.

On start, in a run dir inside a git repo, it lists the run's files in the clone's .git/info/exclude, so they stay out
of git: machine-local state that would otherwise swap with every branch switch.

GET /git says, per repo the run works in (its own, plus the active milestone's `repos`), how far the checkout's branch
and the default branch are behind origin, refreshed by a `git fetch` every --git-every minutes (default 5, 0 =
never): a run that moved on another machine shows in the Podium.
"""
import argparse
import glob
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from podium_dashboard import extension
from podium_dashboard.plugins import paseo
from podium_dashboard.state import Podium, availability, human_hours, human_state, next_change, podium_dir, write_human

# Run files that are normal to lack early on: an empty answer instead of a 404 on every poll.
EMPTY_WHEN_MISSING = {"handoffs.json": {}, "events.jsonl": "", "requests.jsonl": ""}

STORY_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
# The user settling an assumption: an answer, kept until an orchestrator runs, so it needs no watcher.
SETTLE = {"confirm", "reverse"}
# Linking Asana is the user's own request too: queued for the orchestrator, watcher or not.
QUEUED = SETTLE | {"asana", "asana-done"}
MILESTONE_ACTIONS = {"plan", "build-all", "stop", "claim"}
NO_PROMPT = "no orchestrator extension prompt"
PORTS = 20
STARTED = time.time()
PACKAGE = os.path.dirname(os.path.abspath(__file__))
ARGV = []  # the arguments to restart with, set by main()


def stale():
    """Whether this server's code changed on disk after it started."""
    sources = glob.glob(os.path.join(PACKAGE, "*.py")) + glob.glob(os.path.join(PACKAGE, "plugins", "*.py"))
    return any(os.path.getmtime(f) > STARTED for f in sources if os.path.exists(f))


def restart():
    """Replace this process with a fresh server: same arguments and port, no fork (already detached if it was)."""
    time.sleep(0.3)  # let the reply go out
    os.execv(sys.executable, [sys.executable, "-m", "podium_dashboard.server", *ARGV])


ASANA_URL = re.compile(r"^https://app\.asana\.com/[\w/?=&.-]{1,300}$")


def run_dir(given):
    """The run dir: `given`, else $PODIUM_DIR, else the nearest run at or above the cwd; exits when there is none."""
    from podium_dashboard.cli import find_run
    found = given or os.environ.get("PODIUM_DIR") or find_run(os.getcwd())
    if not found:
        sys.exit("podium: no run dir at or above here: pass --dir <run dir>, or set PODIUM_DIR")
    return os.path.abspath(found)


def load_podium(root):
    """The run's Podium, or None while podium.json doesn't parse."""
    try:
        return Podium(root)
    except ValueError:
        return None


def load_run(root):
    """The run's milestones (across every epic) and this person's active milestone."""
    p = load_podium(root)
    if not p:
        return [], None
    milestones, active_id = p.milestones(), p.active().get("milestone")
    return milestones, next((m for m in milestones if m.get("id") == active_id), None)


def find_story(root, ident):
    """(milestone, story) for `<story>` of the active milestone or `<milestone>/<story>`, else (None, None)."""
    milestones, active = load_run(root)
    mid, _, sid = (ident or "").rpartition("/")
    m = next((x for x in milestones if x.get("id") == mid), None) if mid else active
    s = next((x for x in (m or {}).get("stories", []) if x.get("id") == sid), None)
    return (m, s) if s else (None, None)


PAGE = os.path.join(PACKAGE, "podium.html")


def orchestrator_of(data):
    """The run's orchestrator, {name, command}, each None when podium.json names none."""
    found = data.get("orchestrator")
    found = found if isinstance(found, dict) else {}
    return {"name": found.get("name"), "command": found.get("command")}


def info(root):
    p = load_podium(root)
    data = p.data if p else {}
    people = data.get("people") if isinstance(data.get("people"), dict) else {}
    return {"runDir": root, "repoDir": os.path.dirname(root), "watching": watching(root),
            "orchestrator": orchestrator_of(data),
            "me": p.me if p else None,
            "people": {name: {"active": who.get("active")} for name, who in people.items() if isinstance(who, dict)},
            "paseoServer": paseo.server_id(),
            "lastUse": {"ago": round(time.time() - SEEN["at"]), "by": SEEN["by"]}, "stale": stale()}


def watching(root):
    """Whether an orchestrator's watcher is running: its heartbeat in watcher.json is under 30 s old."""
    try:
        with open(os.path.join(podium_dir(root), "watcher.json")) as f:
            return time.time() - json.load(f)["at"] < 30
    except (OSError, ValueError, KeyError, TypeError):
        return False


def handoffs(root):
    """handoffs.json: {"<milestone>/<story>": {at}} for each story the user took to a session of their own."""
    try:
        with open(os.path.join(podium_dir(root), "handoffs.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_toggle(mode, end):
    """The availability override, until `end` (naive local)."""
    write_human(mode=mode, until=end.astimezone().isoformat(timespec="minutes"),
                at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


# The orchestrator's own files: machine-local run state, kept out of git.
RUN_FILES = ["podium.json", "events.jsonl", "requests.jsonl", "human.json", "watcher.json", "handoffs.json", "server.log", "stories/"]


def exclude_run_files(root):
    """List the run's files in the clone's .git/info/exclude (local, nothing to commit), when the run dir is inside a
    git repo. Tracked, they would swap with every branch switch and conflict between machines."""
    repo = git(root, "rev-parse", "--show-toplevel")
    path = repo and git(repo, "rev-parse", "--git-path", "info/exclude")
    if not path:
        return
    path = path if os.path.isabs(path) else os.path.join(repo, path)
    pd = os.path.realpath(podium_dir(root))
    rel = os.path.relpath(pd, os.path.realpath(repo))
    if rel == "." or rel.startswith(".."):
        return
    # a run with its own podium/ folder excludes the folder; an older run lists the files
    want = [f"/{rel}/"] if pd != os.path.realpath(root) else [f"/{rel}/{n}" for n in RUN_FILES]
    try:
        with open(path) as f:
            have = set(f.read().splitlines())
    except OSError:
        have = set()
    missing = [w for w in want if w not in have]
    if missing:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write("\n# orchestrator run state (machine-local; added by the Podium server)\n" + "\n".join(missing) + "\n")


# Each repo's distance from origin, refreshed by watch_git; GET /git serves it.
GIT = {"repos": [], "at": None}


def git(repo, *args, timeout=30):
    """A git command's output, or None when it fails or hangs (a fetch never prompts for credentials)."""
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def repos_of(root):
    """{name: path} for the run's own repo and the active milestone's `repos`."""
    out, repo = {}, git(root, "rev-parse", "--show-toplevel")
    if repo:
        out[os.path.basename(repo)] = repo
    _, active = load_run(root)
    for name, r in ((active or {}).get("repos") or {}).items():
        if (r or {}).get("path"):
            out[name] = os.path.expanduser(r["path"])
    return out


def repo_state(name, path):
    git(path, "fetch", "--quiet", "--no-tags", timeout=60)
    branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    lr = git(path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    ahead, behind = map(int, lr.split()) if lr else (0, 0)
    base = (git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "origin/main").split("/", 1)[-1]
    base_behind = git(path, "rev-list", "--count", f"{base}..origin/{base}") if base != branch else None
    return {"name": name, "branch": branch, "ahead": ahead, "behind": behind, "base": base,
            "baseBehind": int(base_behind) if base_behind else 0}


def watch_git(root, minutes):
    while True:
        GIT["repos"] = [repo_state(n, p) for n, p in repos_of(root).items()]
        GIT["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        time.sleep(minutes * 60)


# The last time someone used the Podium; the idle check reads it.
SEEN = {"at": time.time(), "by": "start"}


def last_activity(root):
    """The latest of the last Podium use and the last change to the run's files."""
    pd = podium_dir(root)
    paths = [os.path.join(pd, "podium.json"), os.path.join(pd, "events.jsonl")] + glob.glob(os.path.join(pd, "stories", "*", "*.progress"))
    mtimes = [os.path.getmtime(p) for p in paths if os.path.exists(p)]
    return max([SEEN["at"]] + mtimes)


def stop_when_idle(server, root, minutes):
    while True:
        time.sleep(60)
        if time.time() - last_activity(root) > minutes * 60:
            print(f"{datetime.now():%H:%M} idle for {minutes} min, stopping", flush=True)
            server.shutdown()
            return


def inside(base, path):
    """Whether `path` is `base` or below it, both already resolved."""
    return os.path.commonpath([base, path]) == base


def make_handler(root):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def parse_request(self):
            ok = super().parse_request()
            if not ok:
                return False
            if not self.trusted():
                self.send_error(403)
                return False
            if self.command != "GET" or self.headers.get("X-Podium-Visible") == "1":
                SEEN.update(at=time.time(), by=f"{self.command} {self.path.split('?')[0]} from {self.headers.get('User-Agent', '?')[:60]}")
                if not self.path.startswith("/human/"):
                    self.at_desk()
            return True

        def trusted(self):
            """The Host names this server (no DNS rebinding), and a POST or DELETE comes from its own page."""
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return False
            origin = self.headers.get("Origin")
            return (self.command not in ("POST", "DELETE") or origin is None
                    or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"))

        def at_desk(self):
            """Someone using a Podium tab is at a computer (the server answers 127.0.0.1 only), so Mobile
            turns to Available, once Mobile has held 15 minutes: setting it from the desk on the way out
            outlasts the tab's last 10 minutes of use."""
            try:
                since = datetime.fromisoformat(human_state().get("at") or "")
            except (ValueError, TypeError):
                return
            if availability()["mode"] != "mobile" or datetime.now(timezone.utc) - since < timedelta(minutes=15):
                return
            now = datetime.now()
            write_toggle("available", next_change(human_hours(), now) or now + timedelta(days=1))

        def log_message(self, *_):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            if self.path == "/info":
                return self.reply(200, info(root))
            if self.path == "/git":
                return self.reply(200, GIT)
            if self.path.startswith("/prompt/"):
                parts = [urllib.parse.unquote(p) for p in self.path.split("?")[0].split("/") if p][1:]
                return self.prompt(parts[0] if parts else None, "/".join(parts[1:]) or None)
            if self.path == "/human":
                return self.reply(200, availability())
            if os.path.basename(self.path.split("?")[0]) in EMPTY_WHEN_MISSING and not os.path.exists(self.translate_path(self.path)):
                return self.empty(EMPTY_WHEN_MISSING[os.path.basename(self.path.split("?")[0])])
            if self.path.startswith("/repo/"):
                return self.repo_file(self.path[len("/repo/"):].split("?")[0])
            if self.path.split("?")[0] in ("/", "/index.html", "/podium.html"):
                with open(PAGE, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

        def repo_file(self, rel):
            """A file of the repo the run dir sits in, read-only: a mock kept outside the run dir."""
            base = os.path.realpath(os.path.dirname(root))
            full = os.path.realpath(os.path.join(base, urllib.parse.unquote(rel)))
            if not inside(base, full) or not os.path.isfile(full):
                return self.send_error(404)
            with open(full, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            url = urlparse(self.path)
            first = ([p for p in url.path.split("/") if p] or [""])[0]
            if url.path == "/restart":
                threading.Thread(target=restart, daemon=True).start()
                return self.reply(202, {"restarting": True})
            if not url.path.startswith("/human/") and first not in QUEUED and not watching(root):
                return self.reply(409, {"error": "no orchestrator is watching"})
            if url.path.startswith("/handoff/"):
                return self.handoff(url.path[len("/handoff/"):], take=True)
            if url.path.startswith("/human/"):
                return self.toggle(url.path[len("/human/"):], parse_qs(url.query).get("until", [None])[0])
            parts = [urllib.parse.unquote(p) for p in url.path.split("/") if p]
            action = parts[0] if parts else ""
            if action == "asana":
                return self.link_asana(parts[1] if len(parts) > 1 else None, parse_qs(url.query).get("url", [""])[0].strip())
            if action == "asana-done":
                return self.asana_done(parts[1] if len(parts) > 1 else "", parse_qs(url.query).get("choice", [""])[0])
            story = "/".join(parts[1:]) or None  # an assigned story can be <milestone>/<story>
            if action in ("build-all", "stop") and not story:  # an older page's button: the active milestone's
                story = (load_run(root)[1] or {}).get("id")
            p = load_podium(root)
            if not p or action not in extension.actions(extension.load(p)[0]) or not story:
                return self.reply(404, {"error": "unknown action"})
            if action in SETTLE and story == "all":  # Confirm all: one request for every open id not yet answered
                answered = self.answered()
                story = ",".join(i for i in self.known_ids(p, action) if i not in answered)
                if not story:
                    return self.reply(404, {"error": f"nothing to {action}"})
            elif not all(STORY_ID.match(x) for x in story.split("/")) or story not in self.known_ids(p, action):
                return self.reply(404, {"error": "unknown id"})
            line = {"action": action, "story": story,
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            note = (parse_qs(url.query).get("note", [""])[0] or "").strip()[:500]
            if action in SETTLE and note:
                line["note"] = note
            self.queue(line)

        def do_DELETE(self):
            if self.path.startswith("/handoff/"):
                return self.handoff(self.path[len("/handoff/"):], take=False)
            self.reply(404, {"error": "unknown action"})

        def handoff(self, ident, take):
            m, story = find_story(root, urllib.parse.unquote(ident))
            if not story or (take and story.get("status") != "todo"):
                return self.reply(404, {"error": "no story to hand off" if take else "unknown id"})
            path, key = os.path.join(podium_dir(root), "handoffs.json"), f"{m['id']}/{story['id']}"
            text = None
            if take:
                text = self.ask("handoff", key)
                if not isinstance(text, str):
                    return
            taken = handoffs(root)
            if take:
                taken[key] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            else:
                taken.pop(key, None)
            with open(path + ".tmp", "w") as f:
                json.dump(taken, f, indent=1)
            os.replace(path + ".tmp", path)
            if not take:
                return self.reply(200, {"released": key})
            self.text(text)

        def ask(self, kind, target, fallback=None):
            """The extension's prompt for `target`, else `fallback`; else None, the error already answered: 501
            without an extension prompt, 404 when it has none for the target, 500 when it fails."""
            p = load_podium(root)
            module, why = extension.load(p) if p else (None, None)
            hook = extension.prompt(module)
            if not hook:
                if fallback is None:
                    self.reply(501, {"error": why or NO_PROMPT})
                return fallback
            try:
                text = hook(p, kind, target)
            except (Exception, SystemExit) as e:
                self.reply(500, {"error": f"{type(e).__name__}: {e}"})
                return None
            if text is None:
                text = fallback
            if text is None:
                self.reply(404, {"error": "unknown id"})
            return text

        def text(self, text):
            data = (text if text.endswith("\n") else text + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def prompt(self, kind, id_):
            if kind == "plan":
                p = load_podium(root)
                if not p or id_ not in {m.get("id") for m in p.milestones()}:
                    return self.reply(404, {"error": "unknown id"})
                command = orchestrator_of(p.data)["command"]
                text = self.ask("plan", id_, f"{command} {id_}" if command else None)
            elif kind == "assign":
                m, story = find_story(root, id_)
                if not story:
                    return self.reply(404, {"error": "unknown id"})
                text = self.ask("assign", f"{m['id']}/{story['id']}")
            else:
                return self.reply(404, {"error": "unknown id"})
            if isinstance(text, str):
                self.text(text)

        def toggle(self, mode, until):
            """Override the hours until `until` (HH:MM, the next one) or the next change of hours; `auto` clears it."""
            if mode == "auto":
                write_human(mode=None, until=None, at=None)
                return self.reply(200, availability())
            if mode not in ("available", "mobile", "unavailable"):
                return self.reply(404, {"error": "unknown mode"})
            now = datetime.now()
            if until:
                if not re.fullmatch(r"\d\d:\d\d", until):
                    return self.reply(400, {"error": "until is HH:MM"})
                end = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
                end += timedelta(days=end <= now)
            else:
                end = next_change(human_hours(), now) or now + timedelta(days=1)
            write_toggle(mode, end)
            self.reply(200, availability())

        def link_asana(self, epic, link):
            """POST /asana[/<epic>]?url=<Asana link>: queue a link for the orchestrator to map
            (an epic id links that epic to a task; none links a project or a task as a new epic)."""
            if not ASANA_URL.match(link):
                return self.reply(400, {"error": "not an Asana link"})
            if epic is not None:
                if not STORY_ID.match(epic) or epic not in self.epic_ids():
                    return self.reply(404, {"error": "unknown epic"})
            self.queue({"action": "asana", "story": epic, "note": link,
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

        def asana_done(self, mid, choice):
            """POST /asana-done/<milestone>?choice=<drop|keep>: the user's answer for a milestone
            completed in Asana but not landed here (skip building it, or keep it)."""
            milestones, _ = load_run(root)
            if choice not in ("drop", "keep") or mid not in {m.get("id") for m in milestones}:
                return self.reply(404, {"error": "unknown milestone or choice"})
            self.queue({"action": "asana-done", "story": mid, "note": choice,
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

        def queue(self, line):
            os.makedirs(podium_dir(root), exist_ok=True)
            with open(os.path.join(podium_dir(root), "requests.jsonl"), "a") as f:
                f.write(json.dumps(line) + "\n")
            self.reply(202, {"queued": line})

        def answered(self):
            """Assumption ids the user already confirmed or reversed in the Podium, waiting for the orchestrator."""
            try:
                with open(os.path.join(podium_dir(root), "requests.jsonl")) as f:
                    lines = [json.loads(l) for l in f if l.strip()]
            except (OSError, ValueError):
                return set()
            return {i for r in lines if isinstance(r, dict) and r.get("action") in SETTLE
                    for i in str(r.get("story") or "").split(",")}

        def epic_ids(self):
            p = load_podium(root)
            return {e.get("id") for e in p.epics()} if p else set()

        def known_ids(self, p, action):
            """plan, build-all, stop and claim → milestone ids; assign → story ids of the active milestone, and
            <milestone>/<story> of every milestone; confirm and reverse → the numbers of the open assumptions, in
            order; domain-story → epic and milestone ids; an extension's action → any of these but the numbers."""
            if action in SETTLE:
                return [i for i, a in p.numbered_assumptions() if isinstance(a, dict) and a.get("status") == "open"]
            milestones = {m.get("id") for m in p.milestones()}
            epics = {e.get("id") for e in p.epics()}
            if action == "domain-story":
                return epics | milestones
            if action in MILESTONE_ACTIONS:
                return milestones
            active = next((m for m in p.milestones() if m.get("id") == p.active().get("milestone")), None)
            stories = ({s.get("id") for s in (active or {}).get("stories", [])}
                       | {f"{m.get('id')}/{s.get('id')}" for m in p.milestones() for s in m.get("stories", [])})
            return stories if action == "assign" else stories | milestones | epics

        def empty(self, body):
            data = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if isinstance(body, dict) else "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def free_port(start):
    for port in range(start, start + PORTS):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    sys.exit(f"no free port in {start}-{start + PORTS - 1}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(prog="podium server")
    ap.add_argument("--dir")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--idle", type=float, default=60, help="minutes without activity before stopping; 0 = never")
    ap.add_argument("--detach", action="store_true", help="print the URL, then keep serving in the background")
    ap.add_argument("--git-every", type=float, default=5, help="minutes between fetches for GET /git; 0 = never")
    args = ap.parse_args(argv)
    root = run_dir(args.dir)
    exclude_run_files(root)
    port = free_port(args.port)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(root))
    ARGV[:] = [a for a in argv if a != "--detach"] + ["--port", str(port)]
    print(f"http://127.0.0.1:{port}/", flush=True)
    if args.detach:
        if os.fork():
            os._exit(0)  # the port is bound; the child serves it
        os.setsid()
        os.makedirs(podium_dir(root), exist_ok=True)
        log = open(os.path.join(podium_dir(root), "server.log"), "a")
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())
        os.dup2(os.open(os.devnull, os.O_RDONLY), sys.stdin.fileno())
        print(f"{datetime.now():%H:%M} serving http://127.0.0.1:{port}/", flush=True)
    if args.git_every > 0:
        threading.Thread(target=watch_git, args=(root, args.git_every), daemon=True).start()
    if args.idle > 0:
        threading.Thread(target=stop_when_idle, args=(server, root, args.idle), daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
