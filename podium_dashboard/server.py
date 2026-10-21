"""The Podium server: `podium server [--dir <run dir>] [--port 8765] [--idle 60] [--detach] [--git-every 5]`.

Serves `podium.html` (next to this file) plus the run directory (by default the run `podium` finds from the cwd,
whose `podium/` folder holds the run's files) on 127.0.0.1, and turns the Podium's buttons into lines in
`requests.jsonl`, which the orchestrator watches. The browser only ever sends an action and an id; prompts come from
the run's orchestrator extension.

It answers only requests whose Host is 127.0.0.1:<port> or localhost:<port>, and any but a GET or HEAD only when its
Origin, if any, is that same server: a page elsewhere can't reach it through DNS rebinding or a cross-site form. Only
a POST, a DELETE or a visible tab's poll from its own page counts as use (below); a HEAD or an OPTIONS never does.
GET /repo/<path> serves a file of the run dir's git toplevel, else of the run dir, never one outside it; any other
path a file of the run dir, never a folder, nor one whose real path (past any symlink) is outside it. Everything
it serves but the page itself comes sandboxed (Content-Security-Policy): a synced HTML file runs in an origin of its
own, whose POSTs say `Origin: null` and are refused. The page's own policy lets it load and fetch only from this
server.

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
domain-story, claim, share) and the extension's ACTIONS. POST /share, which takes no id, asks the orchestrator to
share the run with a colleague, or, once it syncs, to print the colleague's steps again. confirm and reverse take an assumption's number as `podium
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
from podium_dashboard.files import EMPTY_WHEN_MISSING, MACHINE_FILES, SHARED_FILES, git_argv, progress_files, write_atomic
from podium_dashboard.human import availability, human_hours, human_state, next_change, set_toggle, write_toggle
from podium_dashboard.plugins import paseo
from podium_dashboard.state import ACT_ON, ID, NOW, Podium, checkout_path, find_run, podium_dir, watcher_running

STORY_ID = ID
SETTLE = {"confirm", "reverse"}
MILESTONE_ACTIONS = {"plan", "build-all", "stop", "claim"}
RUN_ACTIONS = {"share"}
NO_PROMPT = "no orchestrator extension prompt"
PORTS = 20
STARTED = time.time()
PACKAGE = os.path.dirname(os.path.abspath(__file__))
ARGV = []


def stale():
    sources = glob.glob(os.path.join(PACKAGE, "*.py")) + glob.glob(os.path.join(PACKAGE, "plugins", "*.py"))
    return any(os.path.getmtime(f) > STARTED for f in sources if os.path.exists(f))


def restart():
    """Replace this process with a fresh server: same arguments and port, no fork (already detached if it was). It
    starts in the folder holding this package, as `python -m` imports from the cwd first: never a run dir's code."""
    time.sleep(0.3)  # let the reply go out
    os.chdir(os.path.dirname(PACKAGE))
    os.execv(sys.executable, [sys.executable, "-m", "podium_dashboard.server", *ARGV])


ASANA_URL = re.compile(r"^https://app\.asana\.com/[\w/?=&.-]{1,300}$")


def run_dir(given):
    """The run dir: `given`, else $PODIUM_DIR, else the nearest run at or above the cwd; exits when there is none."""
    found = given or os.environ.get("PODIUM_DIR") or find_run(os.getcwd())
    if not found:
        sys.exit("podium: no run dir at or above here: pass --dir <run dir>, or set PODIUM_DIR")
    return os.path.abspath(found)


def load_podium(root):
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
PAGE_PATHS = ("/", "/index.html", "/podium.html")
SANDBOX = "sandbox allow-scripts allow-forms allow-popups"
PAGE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")


def orchestrator_of(data):
    """The run's orchestrator, {name, command}, each None when podium.json names none."""
    found = data.get("orchestrator")
    found = found if isinstance(found, dict) else {}
    return {"name": found.get("name"), "command": found.get("command")}


def repo_dir(root):
    """The folder `/repo/` serves: the git toplevel of the run dir, else the run dir itself."""
    return git(root, "rev-parse", "--show-toplevel") or root


def info(root):
    p = load_podium(root)
    data = p.data if p else {}
    people = data.get("people") if isinstance(data.get("people"), dict) else {}
    module = extension.load(p)[0] if p else None
    return {"runDir": root, "repoDir": repo_dir(root), "watching": watcher_running(podium_dir(root)),
            "orchestrator": {**orchestrator_of(data), "shareSteps": extension.share_steps(module)},
            "me": p.me if p else None,
            "people": {name: {"active": who.get("active")} for name, who in people.items() if isinstance(who, dict)},
            "paseoServer": paseo.server_id(),
            "lastUse": {"ago": round(time.time() - SEEN["at"]), "by": SEEN["by"]}, "stale": stale()}


def handoffs(root):
    """handoffs.json: {"<milestone>/<story>": {at}} for each story the user took to a session of their own."""
    try:
        with open(os.path.join(podium_dir(root), "handoffs.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


RUN_FILES = [f.replace("**", "") for f in SHARED_FILES + MACHINE_FILES]


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


GIT = {"repos": [], "at": None}


def git(repo, *args, timeout=30):
    """A git command's output, or None when it fails or hangs (a fetch never prompts for credentials)."""
    try:
        r = subprocess.run(git_argv("-C", repo, *args), capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def repos_of(root):
    """{name: path} for the run's own repo and the active milestone's `repos`, but a checkout a pull may have written."""
    out, repo = {}, git(root, "rev-parse", "--show-toplevel")
    if repo:
        out[os.path.basename(repo)] = repo
    p, (_, active) = load_podium(root), load_run(root)
    for name, r in ((active or {}).get("repos") or {}).items():
        path = p and (r or {}).get("path") and checkout_path(p, r["path"])
        if path:
            out[name] = path
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
        GIT["at"] = NOW()
        time.sleep(minutes * 60)


SEEN = {"at": time.time(), "by": "start"}


def last_activity(root):
    pd = podium_dir(root)
    paths = [os.path.join(pd, "podium.json"), os.path.join(pd, "events.jsonl")] + progress_files(pd)
    mtimes = [os.path.getmtime(p) for p in paths if os.path.exists(p)]
    return max([SEEN["at"]] + mtimes)


def stop_when_idle(server, root, minutes):
    while True:
        time.sleep(60)
        if time.time() - last_activity(root) > minutes * 60:
            print(f"{datetime.now():%H:%M} idle for {minutes} min, stopping", flush=True)
            server.shutdown()
            return


def contains(base, path):
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
            visible = self.headers.get("X-Podium-Visible") == "1" and self.same_origin()
            if self.command in ("POST", "DELETE") or (self.command == "GET" and visible):
                SEEN.update(at=time.time(), by=f"{self.command} {self.path.split('?')[0]} from {self.headers.get('User-Agent', '?')[:60]}")
                if not self.path.startswith("/human/"):
                    self.at_desk()
            return True

        def trusted(self):
            """The Host names this server (no DNS rebinding), and any request but a GET or HEAD comes from its own
            page."""
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return False
            return self.command in ("GET", "HEAD") or self.same_origin()

        def same_origin(self):
            """No Origin (not a browser), or this server's own; never `null`, a sandboxed file's."""
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            return origin is None or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

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
            page = getattr(self, "path", "").split("?")[0] in PAGE_PATHS
            self.send_header("Content-Security-Policy", PAGE_CSP if page else SANDBOX)
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
            if self.path.split("?")[0] in PAGE_PATHS:
                with open(PAGE, "rb") as f:
                    return self.send(200, "text/html; charset=utf-8", f.read())
            super().do_GET()

        def send_head(self):
            """A file of the run dir, by its real path: never a folder, nor one a symlink leads outside the run dir."""
            full = os.path.realpath(self.translate_path(self.path))
            if not contains(os.path.realpath(root), full) or not os.path.isfile(full):
                self.send_error(404)
                return None
            return super().send_head()

        def repo_file(self, rel):
            """A file of the repo the run dir sits in, read-only: a mock kept outside the run dir."""
            base = os.path.realpath(repo_dir(root))
            full = os.path.realpath(os.path.join(base, urllib.parse.unquote(rel)))
            if not contains(base, full) or not os.path.isfile(full):
                return self.send_error(404)
            with open(full, "rb") as f:
                self.send(200, mimetypes.guess_type(full)[0] or "application/octet-stream", f.read())

        def do_POST(self):
            url = urlparse(self.path)
            first = ([p for p in url.path.split("/") if p] or [""])[0]
            if url.path == "/restart":
                threading.Thread(target=restart, daemon=True).start()
                return self.reply(202, {"restarting": True})
            if not url.path.startswith("/human/") and first not in ACT_ON and not watcher_running(podium_dir(root)):
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
            story = "/".join(parts[1:]) or None
            if action in ("build-all", "stop") and not story:
                story = (load_run(root)[1] or {}).get("id")
            p = load_podium(root)
            if not p or action not in extension.actions(extension.load(p)[0]) or (not story and action not in RUN_ACTIONS):
                return self.reply(404, {"error": "unknown action"})
            if action in RUN_ACTIONS:
                if story:
                    return self.reply(404, {"error": "unknown id"})
            elif action in SETTLE and story == "all":
                answered = self.answered()
                story = ",".join(i for i in self.known_ids(p, action) if i not in answered)
                if not story:
                    return self.reply(404, {"error": f"nothing to {action}"})
            elif not all(STORY_ID.match(x) for x in story.split("/")) or story not in self.known_ids(p, action):
                return self.reply(404, {"error": "unknown id"})
            line = {"action": action, "story": story, "at": NOW()}
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
                taken[key] = {"at": NOW()}
            else:
                taken.pop(key, None)
            write_atomic(path, json.dumps(taken, indent=1))
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
            self.send(200, "text/plain; charset=utf-8", (text if text.endswith("\n") else text + "\n").encode())

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
            if mode not in ("available", "mobile", "unavailable", "auto"):
                return self.reply(404, {"error": "unknown mode"})
            try:
                set_toggle(mode, None if mode == "auto" else until)
            except ValueError as e:
                return self.reply(400, {"error": str(e)})
            self.reply(200, availability())

        def link_asana(self, epic, link):
            """POST /asana[/<epic>]?url=<Asana link>: queue a link for the orchestrator to map
            (an epic id links that epic to a task; none links a project or a task as a new epic)."""
            if not ASANA_URL.match(link):
                return self.reply(400, {"error": "not an Asana link"})
            if epic is not None:
                if not STORY_ID.match(epic) or epic not in self.epic_ids():
                    return self.reply(404, {"error": "unknown epic"})
            self.queue({"action": "asana", "story": epic, "note": link, "at": NOW()})

        def asana_done(self, mid, choice):
            """POST /asana-done/<milestone>?choice=<drop|keep>: the user's answer for a milestone
            completed in Asana but not landed here (skip building it, or keep it)."""
            milestones, _ = load_run(root)
            if choice not in ("drop", "keep") or mid not in {m.get("id") for m in milestones}:
                return self.reply(404, {"error": "unknown milestone or choice"})
            self.queue({"action": "asana-done", "story": mid, "note": choice, "at": NOW()})

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
            if isinstance(body, dict):
                return self.reply(200, body)
            self.send(200, "text/plain", body.encode())

        def reply(self, code, body):
            self.send(code, "application/json", json.dumps(body).encode())

        def send(self, code, content_type, data):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
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
    ARGV[:] = [a for a in argv if a != "--detach"] + ["--dir", root, "--port", str(port)]
    print(f"http://127.0.0.1:{port}/", flush=True)
    if args.detach:
        if os.fork():
            os._exit(0)
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
