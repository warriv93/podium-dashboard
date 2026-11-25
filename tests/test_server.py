"""Tests for the Podium server, run as `podium server` against a temp run: what /info says, the Host and Origin checks,
/repo/ confined to the run's repo, the sandbox on every file it serves, checkouts read relative to the run dir and
never one a pull could have written, request queuing, prompts from the run's extension, pulls of a synced run, and what the machine's sessions cost."""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import cost, human, ports, server  # noqa: E402

REF = "refs/heads/podium-run/api"

DATA = {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"}, "needsYou": None,
        "assumptions": [{"question": "q0", "choice": "c", "why": "w", "status": "open"},
                        {"question": "q1", "choice": "c", "why": "w", "status": "confirmed"}],
        "orchestrator": {"name": "orch", "command": "/orch"},
        "epics": [{"id": "e", "milestones": [
            {"id": "M1", "status": "working", "phase": "build", "stories": [{"id": "S1", "status": "todo", "deps": []},
                                                                           {"id": "S2", "status": "done", "deps": []}]},
            {"id": "M2", "status": "todo", "phase": "plan", "stories": []}]}]}

EXTENSION = """
ACTIONS = {"ship"}
SHARE_STEPS = ["Clone {remote}", "Run /orch join {ref}"]

def prompt(p, kind, target_id):
    if kind == "plan":
        return None
    return f"{kind} {target_id} for {p.me}"
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = os.path.join(self.tmp, "api")
        self.run_dir = os.path.join(self.repo, ".deep-plan")
        self.pod = os.path.join(self.run_dir, "podium")
        os.makedirs(self.pod)
        self.env = {k: v for k, v in os.environ.items() if k not in ("PODIUM_DIR", "PODIUM_ME")}
        self.env.update({"HOME": self.tmp, "PYTHONPATH": ROOT, "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"),
                         "PODIUM_ME": "ann", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CEILING_DIRECTORIES": self.tmp})
        self.git("init", "-q", self.repo)

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True,
                       env=self.env)

    def at(self, run_dir):
        self.run_dir, self.pod = run_dir, os.path.join(run_dir, "podium")
        os.makedirs(self.pod, exist_ok=True)

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def serve(self, data=DATA, extension=None, git_every=0, lan=False, leased=None):
        data = json.loads(json.dumps(data))
        if extension:
            data["orchestrator"]["extension"] = self.write("ext/orch.py", textwrap.dedent(extension))
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(data, f)
        self.port = leased or free_port()
        proc = subprocess.Popen([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "server",
                                 *([] if leased else ["--port", str(self.port)]), "--idle", "0", "--git-every", str(git_every),
                                 "--version-every", "0", *(["--lan"] if lan else [])],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.tmp)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        self.assertEqual(proc.stdout.readline().strip(), f"http://127.0.0.1:{self.port}/")
        if lan:
            self.lan = proc.stdout.readline().strip()
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.05)
        self.fail("the server never listened")

    def watched(self):
        with open(os.path.join(self.pod, "watcher.json"), "w") as f:
            json.dump({"at": time.time()}, f)

    def response(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request(method, path, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
        r = conn.getresponse()
        return r, r.read().decode()

    def call(self, method, path, headers=None):
        r, body = self.response(method, path, headers)
        return r.status, (json.loads(body) if r.getheader("Content-Type") == "application/json" else body)

    def lease(self, slug, port, run_dir, **more):
        path = os.path.join(self.tmp, "ports.json")
        leases = self.leases()
        leases[slug] = {"port": port, "used": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dir": run_dir, **more}
        with open(path, "w") as f:
            json.dump(leases, f)

    def leases(self):
        try:
            with open(os.path.join(self.tmp, "ports.json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def other_run(self, name="web", data=DATA):
        other = os.path.join(self.tmp, name, ".deep-plan")
        os.makedirs(os.path.join(other, "podium"), exist_ok=True)
        with open(os.path.join(other, "podium", "podium.json"), "w") as f:
            json.dump(data, f)
        return other

    def in_process(self, run_dir, port=None):
        """A Podium for `run_dir` in this process, so a test can stub what it calls; its port."""
        httpd = server.ThreadingHTTPServer(("127.0.0.1", port or free_port()), server.make_handler(run_dir))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd.server_address[1]

    def stubbed(self, started):
        """Patches for an in-process Podium: this test's ports.json, no port range to scan, and a start that serves the
        run in this process on its leased port and records what it was asked to start."""
        def start(slug, run_dir):
            started.append((slug, run_dir))
            return self.in_process(run_dir, self.leases()[slug]["port"])
        return [unittest.mock.patch.object(human, "HUMAN_FILE", self.env["PODIUM_HUMAN"]),
                unittest.mock.patch.object(server, "PORTS", 0), unittest.mock.patch.object(server, "start_run", start)]

    def requests(self):
        try:
            with open(os.path.join(self.pod, "requests.jsonl")) as f:
                return [(r["action"], r["story"]) for r in map(json.loads, f)]
        except FileNotFoundError:
            return []


class Info(Server):
    def test_names_the_run_its_orchestrator_and_each_persons_active_milestone(self):
        self.serve({**DATA, "people": {"ann": {"active": {"milestone": "M1"}}, "bob": {"active": {"milestone": "M2"}}}})
        code, info = self.call("GET", "/info")
        self.assertEqual(code, 200)
        self.assertEqual(set(info), {"runDir", "repoDir", "run", "title", "watching", "orchestrator", "me", "people", "paseoServer",
                                     "lastUse", "stale", "pull"})
        self.assertEqual((info["runDir"], info["repoDir"], info["run"], info["title"]), (self.run_dir, self.repo, "api", "T"))
        self.assertEqual(info["orchestrator"], {"name": "orch", "command": "/orch", "shareSteps": None})
        self.assertEqual(info["me"], "ann")
        self.assertEqual(info["people"], {"ann": {"active": {"milestone": "M1"}}, "bob": {"active": {"milestone": "M2"}}})
        self.assertEqual((info["watching"], info["stale"], info["paseoServer"], info["pull"]), (False, False, None, None))

    def test_each_persons_podium_version_and_how_far_behind_it_is_shows_when_checked(self):
        old, new = "a" * 40, "b" * 40
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump({**DATA, "people": {"ann": {"podium": old}, "bob": {"podium": new}, "cy": {"podium": "<script>"}}}, f)
        self.addCleanup(server.VERSIONS.clear)
        with unittest.mock.patch.object(server.version, "latest", lambda url: new), \
                unittest.mock.patch.object(server.version, "behind", lambda url, c, head: 0 if c == head else 4), \
                unittest.mock.patch.object(server.version, "running", lambda: (new, "u")), \
                unittest.mock.patch.dict(os.environ, {"PODIUM_ME": "ann"}):
            server.check_versions(self.run_dir, (old, "u"))
            people = server.info(self.run_dir)["people"]
        self.assertEqual({k: v.get("podium") for k, v in people.items()},
                         {"ann": {"commit": "aaaaaaa", "behind": 4, "restart": True}, "bob": {"commit": "bbbbbbb", "behind": 0}, "cy": None})

    def test_a_tick_runs_the_extensions_on_tick_and_saves_what_it_changed(self):
        data = json.loads(json.dumps(DATA))
        data["orchestrator"]["extension"] = self.write("ext/orch.py", textwrap.dedent("""
            def on_tick(p):
                p.milestones()[0]["status"] = "done"
                return ["LANDED M1"]
        """))
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(data, f)
        with unittest.mock.patch.dict(os.environ, {"PODIUM_ME": "ann"}):
            self.assertEqual(server.tick(self.run_dir), ["LANDED M1"])
        with open(os.path.join(self.pod, "podium.json")) as f:
            self.assertEqual(json.load(f)["epics"][0]["milestones"][0]["status"], "done")

    def test_a_tick_without_an_on_tick_hook_changes_nothing(self):
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(DATA, f)
        before = os.stat(os.path.join(self.pod, "podium.json")).st_mtime_ns
        self.assertEqual(server.tick(self.run_dir), [])
        self.assertEqual(os.stat(os.path.join(self.pod, "podium.json")).st_mtime_ns, before)

    def test_a_run_without_an_orchestrator_or_people_says_so(self):
        self.serve({k: v for k, v in DATA.items() if k != "orchestrator"})
        info = self.call("GET", "/info")[1]
        self.assertEqual((info["orchestrator"], info["people"]), ({"name": None, "command": None, "shareSteps": None}, {}))

    def test_passes_on_the_extensions_share_steps_with_their_placeholders(self):
        self.serve(extension=EXTENSION)
        self.assertEqual(self.call("GET", "/info")[1]["orchestrator"]["shareSteps"], ["Clone {remote}", "Run /orch join {ref}"])

    def test_share_steps_that_arent_a_list_of_text_are_left_out(self):
        for steps in ('"Run /orch join {ref}"', "[]", '["Run /orch join {ref}", " "]', '["Run /orch join {ref}", 3]', "None"):
            with self.subTest(steps=steps):
                self.serve(extension=f"SHARE_STEPS = {steps}\n")
                self.assertIsNone(self.call("GET", "/info")[1]["orchestrator"]["shareSteps"])


class Open(Server):
    def test_a_synced_run_is_named_by_its_sync_ref_slug(self):
        self.serve({**DATA, "sync": {"enabled": True, "ref": "refs/heads/podium-run/Shared Plan"}})
        self.assertEqual(self.call("GET", "/info")[1]["run"], "shared-plan")

    def test_its_own_run_redirects_to_the_page_keeping_no_path_of_the_link(self):
        self.serve()
        r, _ = self.response("GET", "/open?run=api")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/"))

    def test_a_run_not_open_here_answers_a_page_with_the_command_to_start_it(self):
        self.serve()
        r, body = self.response("GET", "/open?run=other")
        self.assertEqual(r.status, 404)
        self.assertIn("podium server --detach", body)
        self.assertIn("<b>other</b>", body)

    def test_refuses_a_run_that_is_not_a_slug(self):
        self.serve()
        for run in ("", "../x", "A", "a<b>", "a" * 65):
            self.assertEqual(self.response("GET", "/open?run=" + run)[0].status, 400)
        self.assertEqual(self.response("GET", "/open")[0].status, 400)

    def test_another_run_redirects_to_the_port_of_the_server_that_serves_it(self):
        self.serve()
        mine = self.port
        other = os.path.join(self.tmp, "web", ".deep-plan")
        os.makedirs(os.path.join(other, "podium"))
        with open(os.path.join(other, "podium", "podium.json"), "w") as f:
            json.dump(DATA, f)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", free_port()), server.make_handler(other))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.port = httpd.server_address[1]
        with unittest.mock.patch.object(server, "PORT", mine), unittest.mock.patch.object(server, "PORTS", 1), \
                unittest.mock.patch.object(human, "HUMAN_FILE", self.env["PODIUM_HUMAN"]):
            r, _ = self.response("GET", "/open?run=api")
        self.assertEqual((r.status, r.getheader("Location")), (302, f"http://127.0.0.1:{mine}/"))

    def test_a_run_whose_lease_serves_it_redirects_there_without_a_scan(self):
        other = self.other_run()
        with unittest.mock.patch.object(human, "HUMAN_FILE", self.env["PODIUM_HUMAN"]):
            port = self.in_process(other)
        self.lease("web", port, other)
        self.serve()
        r, _ = self.response("GET", "/open?run=web")
        self.assertEqual((r.status, r.getheader("Location")), (302, f"http://127.0.0.1:{port}/"))

    def test_a_stopped_run_with_a_lease_is_started_from_the_leases_dir_and_then_redirected_to(self):
        other, started = self.other_run(), []
        self.lease("web", free_port(), other)
        for patch in self.stubbed(started):
            patch.start()
            self.addCleanup(patch.stop)
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(DATA, f)
        self.port = self.in_process(self.run_dir)
        r, _ = self.response("GET", "/open?run=web")
        self.assertEqual(started, [("web", other)])
        self.assertEqual(r.status, 302)
        self.assertRegex(r.getheader("Location"), r"^http://127\.0\.0\.1:\d+/$")
        self.assertEqual(server.http(r.getheader("Location") + "info")["run"], "web")

    def test_never_starts_a_run_without_a_lease_or_one_whose_dir_is_gone(self):
        started = []
        self.lease("gone", free_port(), os.path.join(self.tmp, "nowhere"))
        for patch in self.stubbed(started):
            patch.start()
            self.addCleanup(patch.stop)
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(DATA, f)
        self.port = self.in_process(self.run_dir)
        for run in ("other", "gone"):
            r, body = self.response("GET", f"/open?run={run}")
            self.assertEqual(r.status, 404)
            self.assertIn("podium server --detach", body)
        self.assertEqual(started, [])


class Leases(Server):
    def test_a_run_takes_its_leased_port_and_a_second_start_of_it_is_refused(self):
        port = free_port()
        self.lease("api", port, self.run_dir)
        self.serve(leased=port)
        self.assertEqual(self.call("GET", "/info")[1]["run"], "api")
        again = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "server", "--idle", "0"],
                               capture_output=True, text=True, env=self.env, cwd=self.tmp, timeout=30)
        self.assertEqual(again.returncode, 1)
        self.assertIn(f"api is already served at http://127.0.0.1:{port}/", again.stderr)
        self.assertEqual(again.stdout, "")

    def test_an_explicit_port_is_recorded_as_the_runs_lease(self):
        self.serve()
        lease = self.leases()["api"]
        self.assertEqual((lease["port"], lease["dir"]), (self.port, self.run_dir))
        self.assertLess(datetime.now(timezone.utc) - datetime.fromisoformat(lease["used"]), timedelta(minutes=1))

    def test_starting_a_run_spawns_a_detached_server_for_its_dir_and_waits_for_it(self):
        other = self.other_run()
        with unittest.mock.patch.object(human, "HUMAN_FILE", self.env["PODIUM_HUMAN"]):
            port = self.in_process(other)
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw.get("cwd")))
            return subprocess.CompletedProcess(argv, 0, f"http://127.0.0.1:{port}/\n", "")
        with unittest.mock.patch.object(server.subprocess, "run", run):
            self.assertEqual(server.start_run("web", other), port)
        self.assertEqual(calls[0], ([sys.executable, "-m", "podium_dashboard.server", "--dir", other, "--detach"], ROOT))

    def test_a_start_that_never_serves_the_run_gives_none(self):
        port = free_port()
        with unittest.mock.patch.object(server.subprocess, "run",
                                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no free port")), \
                unittest.mock.patch.object(server, "START_WAIT", 0.2):
            self.assertIsNone(server.start_run("web", self.run_dir))
        with unittest.mock.patch.object(server.subprocess, "run",
                                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, f"http://127.0.0.1:{port}/\n", "")), \
                unittest.mock.patch.object(server, "START_WAIT", 0.2):
            self.assertIsNone(server.start_run("web", self.run_dir))


class Runs(Server):
    def test_lists_every_lease_with_whether_it_serves_marking_this_run(self):
        other, gone = self.other_run(), self.other_run("ops")
        port = free_port()
        self.lease("web", port, other, pinned=True)
        self.lease("ops", free_port(), gone)
        self.serve()
        runs = self.call("GET", "/runs")[1]["runs"]
        self.assertEqual([r["slug"] for r in runs], ["api", "ops", "web"])
        mine, web = runs[0], runs[2]
        self.assertEqual({k: mine[k] for k in ("port", "live", "current", "title", "pinned")},
                         {"port": self.port, "live": True, "current": True, "title": "T", "pinned": False})
        self.assertEqual({k: web[k] for k in ("port", "live", "current", "title", "pinned")},
                         {"port": port, "live": False, "current": False, "title": None, "pinned": True})
        self.assertTrue(web["used"])

    def test_a_live_run_gives_its_title(self):
        other = self.other_run(data={**DATA, "project": {"title": "Web <b>"}})
        with unittest.mock.patch.object(human, "HUMAN_FILE", self.env["PODIUM_HUMAN"]):
            port = self.in_process(other)
        self.lease("web", port, other)
        self.serve()
        web = next(r for r in self.call("GET", "/runs")[1]["runs"] if r["slug"] == "web")
        self.assertEqual((web["live"], web["title"]), (True, "Web <b>"))

    def test_start_runs_a_stopped_leased_run_and_answers_its_url_with_no_watcher(self):
        other, started = self.other_run(), []
        self.lease("web", free_port(), other)
        for patch in self.stubbed(started):
            patch.start()
            self.addCleanup(patch.stop)
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(DATA, f)
        self.port = self.in_process(self.run_dir)
        code, body = self.call("POST", "/runs/web/start")
        self.assertEqual(code, 200)
        self.assertEqual(started, [("web", other)])
        self.assertRegex(body["url"], r"^http://127\.0\.0\.1:\d+/$")
        self.assertEqual(server.http(body["url"] + "info")["run"], "web")
        self.assertEqual(self.call("POST", "/runs/web/start")[1], body)
        self.assertEqual(len(started), 1)

    def test_start_answers_this_runs_own_url_and_refuses_a_slug_without_a_lease(self):
        started = []
        for patch in self.stubbed(started):
            patch.start()
            self.addCleanup(patch.stop)
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(DATA, f)
        self.port = self.in_process(self.run_dir)
        self.assertEqual(self.call("POST", "/runs/api/start"), (200, {"url": f"http://127.0.0.1:{self.port}/"}))
        self.assertEqual(self.call("POST", "/runs/other/start")[0], 404)
        self.assertEqual(self.call("POST", "/runs/..%2Fx/start")[0], 400)
        self.assertEqual(self.call("POST", "/runs/web")[0], 404)
        self.assertEqual(started, [])

    def test_refuses_a_start_from_another_origin(self):
        self.lease("web", free_port(), self.other_run())
        self.serve()
        self.assertEqual(self.call("POST", "/runs/web/start", {"Origin": "http://evil.example"})[0], 403)


class Hardening(Server):
    def test_refuses_a_host_other_than_its_own(self):
        self.serve()
        self.assertEqual(self.call("GET", "/info", {"Host": f"evil.example:{self.port}"})[0], 403)
        self.assertEqual(self.call("GET", "/info", {"Host": "127.0.0.1:1"})[0], 403)
        self.assertEqual(self.call("GET", "/info", {"Host": f"localhost:{self.port}"})[0], 200)

    def test_refuses_a_post_or_delete_from_another_origin(self):
        self.serve()
        self.watched()
        self.assertEqual(self.call("POST", "/plan/M1", {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("DELETE", "/handoff/S1", {"Origin": "null"})[0], 403)
        self.assertEqual(self.requests(), [])
        self.assertEqual(self.call("POST", "/plan/M1", {"Origin": f"http://localhost:{self.port}"})[0], 202)
        self.assertEqual(self.call("GET", "/info", {"Origin": "http://evil.example"})[0], 200)

    def test_refuses_any_other_method_from_another_origin_and_counts_no_head_or_options_as_use(self):
        moved = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec="seconds")
        human = json.dumps({"mode": "mobile", "until": "2099-01-01T10:00", "at": moved})
        self.write("human.json", human)
        self.serve()
        visible = {"X-Podium-Visible": "1"}
        self.assertEqual(self.call("OPTIONS", "/plan/M1", {"Origin": "http://evil.example", **visible})[0], 403)
        self.assertEqual(self.call("PUT", "/plan/M1", {"Origin": "null", **visible})[0], 403)
        self.response("HEAD", "/podium/podium.json", {"Origin": "http://evil.example", **visible})
        self.response("HEAD", "/podium/podium.json", visible)
        self.response("OPTIONS", "/podium/podium.json", visible)
        self.response("GET", "/podium/podium.json", {"Origin": "http://evil.example", **visible})
        with open(self.env["PODIUM_HUMAN"]) as f:
            self.assertEqual(f.read(), human)
        self.assertEqual(self.call("GET", "/info")[1]["lastUse"]["by"], "start")
        self.response("GET", "/podium/podium.json", visible)
        self.assertEqual(self.call("GET", "/human")[1]["mode"], "available")

    def test_a_restart_never_imports_code_from_the_cwd(self):
        cwd = os.path.join(self.tmp, "pulled")
        marker = os.path.join(self.tmp, "imported")
        self.write("pulled/json.py", f"open({marker!r}, 'w').close()\nraise ImportError('planted')\n")
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(DATA, f)
        self.port = free_port()
        boot = "import sys; sys.path.insert(0, sys.argv[1]); from podium_dashboard import server; server.main(sys.argv[2:])"
        proc = subprocess.Popen([sys.executable, "-I", "-c", boot, ROOT, "--dir", os.path.relpath(self.run_dir, cwd),
                                 "--port", str(self.port), "--idle", "0", "--git-every", "0", "--version-every", "0"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env, cwd=cwd)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertEqual(self.wait_for_info()["runDir"], self.run_dir)
        self.assertEqual(self.call("POST", "/restart")[0], 202)
        time.sleep(0.5)
        info = self.wait_for_info()
        self.assertIsNone(proc.poll())
        self.assertFalse(os.path.exists(marker))
        self.assertEqual((info["runDir"], info["lastUse"]["by"]), (self.run_dir, "start"))

    def wait_for_info(self):
        for _ in range(100):
            try:
                return self.call("GET", "/info")[1]
            except OSError:
                time.sleep(0.05)
        self.fail("the server never answered")

    def test_refuses_a_post_from_a_sandboxed_page(self):
        self.serve()
        self.watched()
        for path in ("/plan/M1", "/confirm/0", "/handoff/S1", "/human/unavailable"):
            self.assertEqual(self.call("POST", path, {"Origin": "null"})[0], 403, path)
        self.assertEqual(self.requests(), [])
        self.assertFalse(os.path.exists(self.env["PODIUM_HUMAN"]))

    def test_sandboxes_everything_it_serves_but_the_page(self):
        self.write("api/mock.html", "<script>fetch('/plan/M1', {method: 'POST'})</script>")
        self.write("api/.deep-plan/podium/stories/M1/S1.html", "<script></script>")
        self.serve()
        for path in ("/podium/stories/M1/S1.html", "/podium/podium.json", "/repo/mock.html", "/podium/stories/",
                     "/podium/gone.html", "/info"):
            r, _ = self.response("GET", path)
            self.assertEqual(r.getheader("Content-Security-Policy"), "sandbox allow-scripts allow-forms allow-popups", path)
        for path in ("/", "/index.html", "/podium.html?x=1"):
            r, _ = self.response("GET", path)
            self.assertEqual(r.status, 200, path)
            self.assertIn("default-src 'self'", r.getheader("Content-Security-Policy"), path)
            self.assertIn("base-uri 'none'", r.getheader("Content-Security-Policy"), path)

    def test_serves_the_season_layer_by_file_name_from_the_package_and_nothing_else(self):
        self.serve()
        for path, kind, has in (("/podium-season/season.js", "text/javascript; charset=utf-8", "seasonOn"),
                                ("/podium-season/lottie_light.min.js", "text/javascript; charset=utf-8", "lottie"),
                                ("/podium-season/reindeer.json", "application/json", None)):
            r, body = self.response("GET", path)
            self.assertEqual((r.status, r.getheader("Content-Type")), (200, kind), path)
            if has:
                self.assertIn(has, body)
            else:
                self.assertIn("layers", json.loads(body))
        for path in ("/podium-season/../server.py", "/podium-season/%2e%2e/server.py", "/podium-season/nope.js",
                     "/podium-season/LICENSES.md", "/podium-season/", "/podium-season/season.js/x"):
            self.assertEqual(self.response("GET", path)[0].status, 404, path)

    def test_serves_files_of_the_repo_and_nothing_above_it(self):
        self.write("api/mock.html", "mock")
        self.write("secret.txt", "secret")
        os.symlink(os.path.join(self.tmp, "secret.txt"), os.path.join(self.repo, "link.txt"))
        self.serve()
        self.assertEqual(self.call("GET", "/repo/mock.html"), (200, "mock"))
        for path in ("/repo/../secret.txt", "/repo/..%2Fsecret.txt", "/repo/%2E%2E/secret.txt", "/repo/link.txt",
                     f"/repo/{self.tmp}/secret.txt", "/repo/", "/repo/.."):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_serves_the_run_dirs_files_and_none_a_symlink_leads_outside_it(self):
        self.write("api/.deep-plan/repos/x/own.txt", "own")
        secret = self.write("secret.txt", "secret")
        os.symlink(secret, os.path.join(self.run_dir, "repos", "x", "leak.txt"))
        os.symlink(self.tmp, os.path.join(self.run_dir, "repos", "x", "up"))
        os.symlink(os.path.join(self.run_dir, "repos", "x", "own.txt"), os.path.join(self.run_dir, "repos", "x", "inside.txt"))
        self.serve()
        self.assertEqual(self.call("GET", "/repos/x/own.txt"), (200, "own"))
        self.assertEqual(self.call("GET", "/repos/x/inside.txt"), (200, "own"))
        self.assertEqual(self.call("GET", "/podium/podium.json")[0], 200)
        for method in ("GET", "HEAD"):
            for path in ("/repos/x/leak.txt", "/repos/x/leak.txt?x=1", "/repos/x/up/secret.txt", "/repos/x/", "/repos/x/up/"):
                self.assertEqual(self.response(method, path)[0].status, 404, (method, path))

    def test_a_folder_serves_its_index_html_and_never_one_a_symlink_leads_outside(self):
        self.write("api/.deep-plan/mock/index.html", "run mock")
        self.write("api/assets/index.html", "repo mock")
        self.write("api/.deep-plan/empty/x.txt", "x")
        self.write("api/.deep-plan/leaky/x.txt", "x")
        os.symlink(self.write("index.html", "secret"), os.path.join(self.run_dir, "leaky", "index.html"))
        self.serve()
        for path, body in (("/mock/", "run mock"), ("/mock/?x=1", "run mock"), ("/repo/assets/", "repo mock")):
            self.assertEqual(self.call("GET", path), (200, body), path)
        self.assertEqual(self.response("GET", "/mock")[0].getheader("Location"), "/mock/")
        self.assertEqual(self.response("GET", "/repo/assets")[0].getheader("Location"), "/repo/assets/")
        for path in ("/empty/", "/leaky/", "/repo/.deep-plan/leaky/", "/repo/.deep-plan/empty/"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_a_run_at_its_repos_root_serves_nothing_beside_the_repo(self):
        self.at(self.repo)
        self.write("api/mock.html", "mock")
        self.write("secret.txt", "secret")
        self.write("web/index.html", "web")
        self.serve()
        self.assertEqual(self.call("GET", "/info")[1]["repoDir"], self.repo)
        self.assertEqual(self.call("GET", "/repo/mock.html"), (200, "mock"))
        for path in ("/repo/secret.txt", "/repo/../secret.txt", "/repo/web/index.html", "/repo/../web/index.html"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_a_run_outside_any_repo_serves_its_own_files_and_nothing_above_them(self):
        self.at(os.path.join(self.tmp, "myrun"))
        self.write("myrun/own.txt", "own")
        self.write("notes.txt", "notes")
        self.serve()
        self.assertEqual(self.call("GET", "/info")[1]["repoDir"], self.run_dir)
        self.assertEqual(self.call("GET", "/repo/own.txt"), (200, "own"))
        for path in ("/repo/notes.txt", "/repo/../notes.txt", "/repo/myrun/own.txt"):
            self.assertEqual(self.call("GET", path)[0], 404, path)


@unittest.skipUnless(server.lan_address(), "no network address")
class Lan(Server):
    def lan_serve(self):
        self.serve(lan=True)
        self.ip = server.lan_address()
        self.assertRegex(self.lan, rf"^lan http://{self.ip}:{self.port}/\?key=[\w-]{{43}}$")
        self.key = self.lan.split("=", 1)[1]
        self.host = {"Host": f"{self.ip}:{self.port}"}
        self.cookie = {**self.host, "Cookie": f"other=1; podium-{self.port}={self.key}"}

    def test_a_lan_host_needs_the_key_and_the_right_one_sets_a_strict_cookie_and_leaves_the_url(self):
        self.lan_serve()
        r, page = self.response("GET", "/", self.host)
        self.assertEqual(r.status, 403)
        self.assertIn("podium server --lan", page)
        self.assertEqual(self.call("GET", f"/?key={self.key}x", self.host)[0], 403)
        self.assertEqual(self.call("GET", "/?key=", self.host)[0], 403)
        r, _ = self.response("GET", f"/?run=api&key={self.key}", self.host)
        self.assertEqual((r.status, r.getheader("Location")), (302, "/?run=api"))
        self.assertEqual(r.getheader("Set-Cookie"), f"podium-{self.port}={self.key}; Path=/; HttpOnly; SameSite=Strict")
        r, _ = self.response("GET", f"/podium/podium.json?key={self.key}", self.host)
        self.assertEqual(r.getheader("Location"), "/podium/podium.json")
        r, _ = self.response("GET", f"//evil.example/?key={self.key}", self.host)
        self.assertEqual(r.getheader("Location"), "/evil.example/")
        self.assertEqual(self.call("POST", f"/confirm/0?key={self.key}", self.host)[0], 403)
        self.assertEqual(self.requests(), [])

    def test_its_cookie_opens_the_page_and_its_buttons_from_the_lan_origin_only(self):
        self.lan_serve()
        self.watched()
        origin = {"Origin": f"http://{self.ip}:{self.port}"}
        self.assertEqual(self.call("GET", "/", self.cookie)[0], 200)
        code, info = self.call("GET", "/info", self.cookie)
        self.assertEqual((code, info["lan"]), (200, f"http://{self.ip}:{self.port}/"))
        self.assertNotIn(self.key, json.dumps(info))
        self.assertEqual(self.call("POST", "/plan/M1", {**self.cookie, **origin})[0], 202)
        self.assertEqual(self.call("POST", "/plan/M1", {**self.host, **origin})[0], 403)
        self.assertEqual(self.call("POST", "/plan/M1", {**self.host, **origin, "Cookie": f"podium-{self.port}=x"})[0], 403)
        self.assertEqual(self.call("POST", "/plan/M1", {**self.host, **origin, "Cookie": f"podium-1={self.key}"})[0], 403)
        self.assertEqual(self.call("POST", "/plan/M1", {**self.cookie, "Origin": "null"})[0], 403)
        self.assertEqual(self.call("POST", "/plan/M1", {**self.cookie, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("POST", "/plan/M1", {**origin, "Cookie": self.cookie["Cookie"]})[0], 403)
        self.assertEqual(self.requests(), [("plan", "M1")])

    def test_loopback_answers_as_without_lan_but_names_the_lan_url_and_any_other_host_is_refused(self):
        self.lan_serve()
        self.watched()
        code, info = self.call("GET", "/info")
        self.assertEqual((code, info["lan"]), (200, f"http://{self.ip}:{self.port}/"))
        self.assertNotIn(self.key, json.dumps(info))
        self.assertEqual(self.call("POST", "/plan/M1", {"Origin": f"http://localhost:{self.port}"})[0], 202)
        for host in (f"evil.example:{self.port}", f"{self.ip}:1"):
            self.assertEqual(self.call("GET", "/info", {"Host": host, "Cookie": self.cookie["Cookie"]})[0], 403, host)
        with socket.socket() as s:
            self.assertEqual(s.connect_ex((self.ip, self.port)), 0)

    def test_a_restart_keeps_the_key(self):
        self.lan_serve()
        self.assertEqual(self.call("POST", "/restart")[0], 202)
        time.sleep(0.5)
        for _ in range(100):
            try:
                self.assertEqual(self.call("GET", "/info", self.cookie)[0], 200)
                return
            except OSError:
                time.sleep(0.05)
        self.fail("the server never answered")

    def test_without_lan_it_listens_on_loopback_only_and_refuses_a_lan_host(self):
        self.serve()
        ip = server.lan_address()
        self.assertNotIn("lan", self.call("GET", "/info")[1])
        self.assertEqual(self.call("GET", "/info", {"Host": f"{ip}:{self.port}"})[0], 403)
        with socket.socket() as s:
            self.assertNotEqual(s.connect_ex((ip, self.port)), 0)


class Checkouts(Server):
    def test_reads_a_checkout_path_relative_to_the_run_dir_whatever_the_servers_cwd(self):
        checkout = os.path.join(self.run_dir, "repos", "events")
        self.git("init", "-q", "-b", "feat", checkout)
        self.git("-C", checkout, "commit", "-q", "--allow-empty", "-m", "first")
        data = json.loads(json.dumps(DATA))
        data["epics"][0]["milestones"][0]["repos"] = {"events": {"path": "repos/events"}}
        self.serve(data, git_every=1)
        for _ in range(100):
            found = self.call("GET", "/git")[1]
            if found["at"]:
                break
            time.sleep(0.1)
        self.assertEqual({r["name"]: r["branch"] for r in found["repos"]}.get("events"), "feat")


class PlantedRepos(Server):
    def plant(self, rel):
        """A bare repository at the run dir's `rel`, as a pull could write it, whose fetch runs a command."""
        path = os.path.join(self.run_dir, rel)
        self.git("init", "-q", "--bare", path)
        self.ran = os.path.join(self.tmp, "ran")
        ssh = self.write("bin/ssh", f"#!/bin/sh\ntouch {self.ran}\n")
        os.chmod(ssh, 0o755)
        self.git("--git-dir", path, "config", "core.sshCommand", ssh)
        self.git("--git-dir", path, "remote", "add", "origin", "ssh://example.invalid/x.git")
        return path

    def test_git_takes_no_folder_it_finds_for_a_bare_repository(self):
        planted = self.plant("podium/stories/x")
        r = subprocess.run([sys.executable, "-c", "import sys; from podium_dashboard import server; "
                            "print(server.git(sys.argv[1], 'fetch'))", planted], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.stdout.strip(), "None", r.stderr)
        self.assertFalse(os.path.exists(self.ran))

    def test_skips_a_checkout_a_pull_could_have_written(self):
        self.plant("podium/stories/x")
        self.git("init", "-q", "-b", "feat", os.path.join(self.run_dir, "repos", "events"))
        data = json.loads(json.dumps(DATA))
        data["epics"][0]["milestones"][0]["repos"] = {"evil": {"path": "podium/stories/x"}, "events": {"path": "repos/events"}}
        self.serve(data, git_every=1)
        for _ in range(100):
            found = self.call("GET", "/git")[1]
            if found["at"]:
                break
            time.sleep(0.1)
        self.assertEqual(sorted(r["name"] for r in found["repos"]), ["api", "events"])
        self.assertFalse(os.path.exists(self.ran))


class Requests(Server):
    def test_a_button_that_needs_the_orchestrator_waits_for_a_watcher_but_an_answer_is_queued(self):
        self.serve()
        self.assertEqual(self.call("POST", "/plan/M1")[0], 409)
        self.assertEqual(self.call("POST", "/claim/M2")[0], 409)
        self.assertEqual(self.call("POST", "/confirm/0")[0], 202)
        self.assertEqual(self.requests(), [("confirm", "0")])

    def test_queues_core_actions_claim_included_and_refuses_unknown_ones(self):
        self.serve()
        self.watched()
        self.assertEqual(self.call("POST", "/claim/M2")[0], 202)
        self.assertEqual(self.call("POST", "/assign/M1/S1")[0], 202)
        self.assertEqual(self.call("POST", "/stop")[0], 202)
        self.assertEqual(self.call("POST", "/claim/M9")[0], 404)
        self.assertEqual(self.call("POST", "/ship/M1")[0], 404)
        self.assertEqual(self.call("POST", "/confirm/1")[0], 404)
        self.assertEqual(self.requests(), [("claim", "M2"), ("assign", "M1/S1"), ("stop", "M1")])

    def test_queues_proceed_for_a_known_milestone_and_refuses_an_unknown_one(self):
        self.serve()
        self.watched()
        self.assertEqual(self.call("POST", "/proceed/M2")[0], 202)
        self.assertEqual(self.call("POST", "/proceed/M9")[0], 404)
        self.assertEqual(self.call("POST", "/proceed/M1/S1")[0], 404)
        self.assertEqual(self.requests(), [("proceed", "M2")])

    def test_queues_share_with_no_id_for_the_watcher_and_the_next_turn(self):
        self.serve()
        self.assertEqual(self.call("POST", "/share")[0], 409)
        self.watched()
        self.assertEqual(self.call("POST", "/share/M1")[0], 404)
        self.assertEqual(self.call("POST", "/share")[0], 202)
        self.assertEqual(self.requests(), [("share", None)])
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "requests"],
                           capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(r.stdout.splitlines(), ["LIST share"])

    def test_numbers_assumptions_as_podium_assumptions_does_in_a_run_with_one_state_per_person(self):
        people = {"ann": {"assumptions": [{"question": "mine", "status": "open"}]}}
        self.serve({**DATA, "people": people})
        self.assertEqual(self.call("POST", "/confirm/t0")[0], 202)
        self.assertEqual(self.call("POST", "/reverse/t1")[0], 404)
        self.assertEqual(self.call("POST", "/reverse/all")[0], 202)
        self.assertEqual(self.call("POST", "/confirm/all")[0], 404)
        self.assertEqual(self.requests(), [("confirm", "t0"), ("reverse", "0")])


class Reviewed(Server):
    def events(self):
        with open(os.path.join(self.pod, "events.jsonl")) as f:
            return [json.loads(line) for line in f]

    def test_records_a_reviewed_event_for_the_owner_with_no_watcher_and_refuses_an_unknown_pr(self):
        data = json.loads(json.dumps(DATA))
        data["epics"][0]["milestones"][1].update(owner="bob", repos={"core": {"pr": {"number": 7, "state": "draft"}}})
        self.serve({**data, "people": {"ann": {}, "bob": {}}})
        self.assertEqual(self.call("POST", "/reviewed/M2?repo=core&number=8")[0], 404)
        self.assertEqual(self.call("POST", "/reviewed/M9?repo=core&number=7")[0], 404)
        self.assertEqual(self.call("POST", "/reviewed/M2?repo=core&number=7")[0], 202)
        e = self.events()[-1]
        self.assertEqual({k: e[k] for k in ("type", "milestone", "repo", "number", "state", "owner", "by")},
                         {"type": "reviewed", "milestone": "M2", "repo": "core", "number": 7, "state": "draft",
                          "owner": "bob", "by": "ann"})
        self.assertEqual(self.requests(), [])


class Priority(Server):
    def podium(self):
        with open(os.path.join(self.pod, "podium.json")) as f:
            return json.load(f)

    def milestone(self, mid):
        return next(m for E in self.podium()["epics"] for m in E["milestones"] if m["id"] == mid)

    def test_sets_a_milestone_must_or_should_have_and_clears_it_with_no_watcher(self):
        self.serve()
        self.assertEqual(self.call("POST", "/priority/M9?level=must")[0], 404)
        self.assertEqual(self.call("POST", "/priority/M2?level=maybe")[0], 400)
        self.assertEqual(self.call("POST", "/priority/M2?level=must"), (200, {"id": "M2", "priority": "must"}))
        self.assertEqual(self.milestone("M2")["priority"], "must")
        self.assertEqual(self.call("POST", "/priority/M2?level=should"), (200, {"id": "M2", "priority": "should"}))
        self.assertEqual(self.milestone("M2")["priority"], "should")
        self.assertEqual(self.call("POST", "/priority/M2?level=nice"), (200, {"id": "M2", "priority": None}))
        self.assertNotIn("priority", self.milestone("M2"))
        self.assertEqual(self.milestone("M1")["stories"][0]["status"], "todo")
        self.assertEqual(self.requests(), [])

    def test_sets_an_epics_priority_under_epic(self):
        self.serve()
        self.assertEqual(self.call("POST", "/priority/epic/e9?level=must")[0], 404)
        self.assertEqual(self.call("POST", "/priority/epic/e?level=should"), (200, {"id": "e", "priority": "should"}))
        self.assertEqual(self.podium()["epics"][0]["priority"], "should")
        self.assertNotIn("priority", self.milestone("M2"))



REPORT = {"draft": "reports/sync.json", "status": "ready", "name": "Sync 2026-11-20"}
COMMENTS = [{"id": "c1", "author": "Maria Ek", "body": "Is pausing enough?"}, {"id": "c2", "author": "Jonna Lund", "body": "Can I try it?"}]


class Report(Server):
    podium = Priority.podium

    def serve_report(self, report=REPORT):
        os.makedirs(os.path.join(self.run_dir, "reports"), exist_ok=True)
        self.serve({**DATA, "project": {"title": "T", "quest": {"report": report, "reportComments": COMMENTS}}})

    def lines(self):
        with open(os.path.join(self.pod, "requests.jsonl")) as f:
            return [json.loads(line) for line in f]

    def put(self, body, path="reports/sync.json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("PUT", f"/report-draft?path={path}", body=data, headers={"Host": f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        return r.status, json.loads(r.read().decode())

    def draft(self, rel="reports/sync.json"):
        with open(os.path.join(self.run_dir, rel)) as f:
            return json.load(f)

    def test_report_queues_with_its_cover_and_no_id_once_a_watcher_runs_and_refuses_a_cover_it_cannot_read(self):
        self.serve_report()
        self.assertEqual(self.call("POST", "/report?cover=since")[0], 409)
        self.watched()
        for cover in ("since", "all", "2026-11-06"):
            self.assertEqual(self.call("POST", f"/report?cover={cover}")[0], 202)
        for bad in ("", "last", "2026-13-45", "2026-11-6", "since%0Anote", "../x"):
            self.assertEqual(self.call("POST", f"/report?cover={bad}")[0], 400, bad)
        self.assertEqual(self.call("POST", "/report/M1?cover=all")[0], 404)
        lines = self.lines()
        self.assertEqual([(r["action"], r["story"], r["cover"]) for r in lines],
                         [("report", None, "since"), ("report", None, "all"), ("report", None, "2026-11-06")])
        self.assertEqual(list(lines[0]), ["action", "story", "cover", "at"])

    def test_publish_and_comments_queue_with_no_id_once_a_watcher_runs_and_the_turn_prints_the_cover(self):
        self.serve_report()
        self.assertEqual(self.call("POST", "/report-publish")[0], 409)
        self.watched()
        for path in ("/report?cover=since", "/report-publish", "/report-comments"):
            self.assertEqual(self.call("POST", path)[0], 202, path)
        self.assertEqual(self.call("POST", "/report-publish/M1")[0], 404)
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "requests"],
                           capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(r.stdout.splitlines(), ["LIST report cover=since", "LIST report-publish", "LIST report-comments"])

    def test_the_draft_is_saved_whole_to_the_reports_draft_path_with_no_watcher(self):
        self.serve_report()
        edited = {"name": "Sync 2026-11-20", "kind": "sync", "tiers": {"must": [{"id": "M1", "head": "Edited", "hidden": True}]},
                  "sections": ["banner", "must"]}
        self.assertEqual(self.put(edited), (200, {"saved": "reports/sync.json"}))
        self.assertEqual(self.draft(), edited)
        self.assertEqual(self.requests(), [])

    def test_the_draft_must_be_a_json_object_under_256_kb(self):
        self.serve_report()
        for body in ([1, 2], "text", None, b"{not json", b"\xff\xfe"):
            self.assertEqual(self.put(body)[0], 400, body)
        self.assertEqual(self.put({"name": "x" * (256 * 1024)})[0], 413)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "reports", "sync.json")))

    def test_the_draft_is_written_only_to_the_json_file_the_report_names_in_the_run_dirs_reports_and_only_while_ready(self):
        self.serve_report()
        self.assertEqual(self.put({"name": "x"}, "reports/other.json")[0], 409)
        self.assertEqual(self.put({"name": "x"}, "podium/podium.json")[0], 409)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "reports", "other.json")))
        for escape in ("../outside.json", "/tmp/abs.json", "reports/../../outside.json", ".", "podium/podium.json", "reports/x.py", "reports"):
            with open(os.path.join(self.pod, "podium.json")) as f:
                data = json.load(f)
            data["project"]["quest"]["report"] = {**REPORT, "draft": escape}
            with open(os.path.join(self.pod, "podium.json"), "w") as f:
                json.dump(data, f)
            self.assertEqual(self.put({"name": "x"}, escape.replace("/", "%2F"))[0], 400, escape)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "outside.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "outside.json")))
        for status in ("drafting", "published"):
            with open(os.path.join(self.pod, "podium.json")) as f:
                data = json.load(f)
            data["project"]["quest"]["report"] = {**REPORT, "status": status}
            with open(os.path.join(self.pod, "podium.json"), "w") as f:
                json.dump(data, f)
            self.assertEqual(self.put({"name": "x"})[0], 409, status)

    def test_a_comment_is_answered_or_handled_in_podium_json_with_no_watcher_and_an_unknown_one_is_404(self):
        self.serve_report()
        self.assertEqual(self.call("POST", "/report-comment/c1?answer=1"), (200, {"id": "c1", "answer": True}))
        self.assertEqual(self.call("POST", "/report-comment/c2?handled=1"), (200, {"id": "c2", "handled": True}))
        comments = self.podium()["project"]["quest"]["reportComments"]
        self.assertEqual([(c.get("answer"), c.get("handled")) for c in comments], [(True, None), (None, True)])
        self.assertEqual(self.call("POST", "/report-comment/c1?answer=0")[0], 200)
        self.assertNotIn("answer", self.podium()["project"]["quest"]["reportComments"][0])
        self.assertEqual(self.call("POST", "/report-comment/c9?answer=1")[0], 404)
        self.assertEqual(self.call("POST", "/report-comment/__proto__?handled=1")[0], 404)
        for bad in ("?answer=2", "?answer=1&handled=1", "", "?seen=1"):
            self.assertEqual(self.call("POST", f"/report-comment/c1{bad}")[0], 400, bad)
        self.assertEqual(self.requests(), [])


class State(Server):
    podium, milestone = Priority.podium, Priority.milestone

    def events(self):
        with open(os.path.join(self.pod, "events.jsonl")) as f:
            return [{k: e[k] for k in ("type", "milestone", "text", "by") if k in e} for e in map(json.loads, f)]

    def run_with(self, **m2):
        data = json.loads(json.dumps(DATA))
        data["epics"][0]["milestones"][1].update(m2)
        self.serve(data)

    def test_puts_off_closes_and_reopens_a_milestone_with_no_watcher(self):
        self.run_with()
        self.assertEqual(self.call("POST", "/status/M9?to=later")[0], 404)
        self.assertEqual(self.call("POST", "/status/M2?to=gone"), (400, {"error": "to is open, later or closed"}))
        self.assertEqual(self.call("POST", "/status/M2?to=later"), (200, {"id": "M2", "status": "later"}))
        self.assertEqual({k: self.milestone("M2").get(k) for k in ("status", "resumeTo")}, {"status": "later", "resumeTo": "todo"})
        self.assertEqual(self.call("POST", "/status/M2?to=closed"), (200, {"id": "M2", "status": "dropped"}))
        self.assertEqual(self.milestone("M2")["resumeTo"], "todo")
        self.assertEqual(self.call("POST", "/status/M2?to=open"), (200, {"id": "M2", "status": "todo"}))
        self.assertNotIn("resumeTo", self.milestone("M2"))
        self.assertEqual([e["text"] for e in self.events()[-3:]], ["M2 put off for later", "M2 closed", "M2 reopened"])
        self.assertEqual(self.requests(), [])

    def test_paused_is_another_word_for_later(self):
        self.run_with(status="draft")
        self.assertEqual(self.call("POST", "/status/M2?to=paused"), (200, {"id": "M2", "status": "later"}))
        self.assertEqual(self.milestone("M2")["resumeTo"], "draft")

    def test_reopening_a_draft_restores_draft(self):
        self.run_with(status="draft")
        self.call("POST", "/status/M2?to=closed")
        self.assertEqual(self.call("POST", "/status/M2?to=open"), (200, {"id": "M2", "status": "draft"}))

    def test_reopening_one_put_off_elsewhere_is_todo_with_stories_and_draft_without(self):
        for stories, status in (([{"id": "S1", "status": "todo"}], "todo"), ([], "draft")):
            with self.subTest(stories=stories):
                self.run_with(status="later", stories=stories)
                self.assertEqual(self.call("POST", "/status/M2?to=open"), (200, {"id": "M2", "status": status}))

    def test_a_parked_milestone_is_later_and_reopens_where_it_left(self):
        self.run_with(status="parked", resumeTo="draft")
        self.assertEqual(self.call("POST", "/status/M2?to=later"), (200, {"id": "M2", "status": "later"}))
        self.assertEqual(self.call("POST", "/status/M2?to=open"), (200, {"id": "M2", "status": "draft"}))

    def test_setting_the_state_it_already_has_writes_no_event(self):
        self.run_with(status="later")
        self.assertEqual(self.call("POST", "/status/M2?to=paused"), (200, {"id": "M2", "status": "later"}))
        self.assertFalse(os.path.exists(os.path.join(self.pod, "events.jsonl")))

    def test_refuses_a_milestone_in_progress_landed_or_moved(self):
        self.run_with()
        self.assertEqual(self.call("POST", "/status/M1?to=later"), (409, {"error": "M1 is in progress: stop it first"}))
        for status, error in (("done", "M2 has landed"), ("moved", "M2 has moved")):
            with self.subTest(status=status):
                self.run_with(status=status)
                self.assertEqual(self.call("POST", "/status/M2?to=closed"), (409, {"error": error}))
                self.assertEqual(self.milestone("M2")["status"], status)


class Owner(Server):
    podium, milestone = Priority.podium, Priority.milestone

    def events(self):
        with open(os.path.join(self.pod, "events.jsonl")) as f:
            return [{k: e[k] for k in ("type", "milestone", "from", "to", "owner", "by") if k in e} for e in map(json.loads, f)]

    def run_with(self, **m2):
        data = json.loads(json.dumps(DATA))
        data["epics"][0]["milestones"][1].update(m2)
        self.serve({**data, "people": {"ann": {}, "bob": {}, "cy": {}}})

    def test_gives_a_milestone_to_a_colleague_and_back_to_nobody_with_no_watcher(self):
        self.run_with(owner="bob")
        self.assertEqual(self.call("POST", "/owner/M9?to=cy")[0], 404)
        self.assertEqual(self.call("POST", "/owner/M2?to=zed"), (400, {"error": "zed is not in this run's people"}))
        self.assertEqual(self.call("POST", "/owner/M2?to=cy"), (200, {"id": "M2", "owner": "cy"}))
        self.assertEqual(self.milestone("M2")["owner"], "cy")
        self.assertEqual(self.call("POST", "/owner/M2?to="), (200, {"id": "M2", "owner": None}))
        self.assertNotIn("owner", self.milestone("M2"))
        self.assertEqual(self.events()[-3:], [{"type": "handover", "milestone": "M2", "from": "bob", "to": "cy", "by": "ann"},
                                              {"type": "owner", "milestone": "M2", "owner": "cy", "by": "ann"},
                                              {"type": "owner", "milestone": "M2", "owner": None, "by": "ann"}])
        self.assertEqual(self.requests(), [])

    def test_giving_an_unowned_milestone_records_only_its_new_owner_and_the_same_owner_changes_nothing(self):
        self.run_with()
        self.assertEqual(self.call("POST", "/owner/M2?to=bob"), (200, {"id": "M2", "owner": "bob"}))
        self.assertEqual(self.call("POST", "/owner/M2?to=bob"), (200, {"id": "M2", "owner": "bob"}))
        self.assertEqual([e for e in self.events() if e.get("milestone") == "M2"], [{"type": "owner", "milestone": "M2", "owner": "bob", "by": "ann"}])

    def test_refuses_while_the_milestones_stories_are_being_built(self):
        self.run_with(owner="bob", stories=[{"id": "S9", "status": "working", "deps": []}])
        self.assertEqual(self.call("POST", "/owner/M2?to=cy"), (409, {"error": "M2 is building: stop it first"}))
        self.assertEqual(self.milestone("M2")["owner"], "bob")


class Gates(Server):
    def history(self, logs, *runs):
        path = os.path.join(self.run_dir, logs, "gates.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for at, gate, ok, sha in runs:
                f.write(json.dumps({"at": at, "gate": gate, "ok": ok, "secs": 3, "sha": sha}) + "\n")

    def test_a_gate_that_fails_and_then_passes_on_the_same_sha_is_flaky(self):
        self.history("contract.logs", ("T1", "test", False, "a1"), ("T2", "lint", True, "a1"), ("T3", "test", True, "a1"),
                     ("T4", "lint", False, "a1"), ("T5", "lint", True, "a2"), ("T6", "test", False, "a2"), ("T7", "test", True, "a2"))
        self.serve()
        self.assertEqual(self.call("GET", "/gates"), (200, {"gates": [
            {"name": "test", "logs": "contract.logs", "flips": 2, "last": "T7", "runs": 4, "fails": 2}]}))

    def test_a_flake_counts_only_within_its_own_logs_folder(self):
        self.history("contract-core.logs/merge-r6", ("T1", "unit", False, "a1"))
        self.history("contract-core.logs/merge-r7", ("T2", "unit", True, "a1"), ("T3", "unit", False, "b1"), ("T4", "unit", True, "b1"))
        self.serve()
        self.assertEqual(self.call("GET", "/gates")[1]["gates"],
                         [{"name": "unit", "logs": "contract-core.logs/merge-r7", "flips": 1, "last": "T4", "runs": 3, "fails": 1}])

    def test_leaves_out_checkouts_dependencies_folders_too_deep_and_runs_without_a_sha(self):
        flip = (("T1", "unit", False, "a1"), ("T2", "unit", True, "a1"))
        for logs in ("worktrees/S1/contract.logs", "repos/api/contract.logs", "x/node_modules/y", "a/b/c/d"):
            self.history(logs, *flip)
        self.history("contract.logs", ("T1", "unit", False, None), ("T2", "unit", True, None))
        self.serve()
        self.assertEqual(self.call("GET", "/gates"), (200, {"gates": []}))

    def test_skips_broken_lines_and_reads_a_history_again_once_it_grows(self):
        self.history("contract.logs", ("T1", "unit", False, "a1"))
        with open(os.path.join(self.run_dir, "contract.logs", "gates.jsonl"), "a") as f:
            f.write('{"gate": "unit", "ok": "yes"}\nnot json\n')
        self.serve()
        self.assertEqual(self.call("GET", "/gates"), (200, {"gates": []}))
        self.history("contract.logs", ("T2", "unit", True, "a1"))
        self.assertEqual([g["flips"] for g in self.call("GET", "/gates")[1]["gates"]], [1])


class Prompts(Server):
    def test_takes_prompts_and_actions_from_the_extension(self):
        self.serve(extension=EXTENSION)
        self.watched()
        self.assertEqual(self.call("GET", "/prompt/assign/S1"), (200, "assign M1/S1 for ann\n"))
        self.assertEqual(self.call("GET", "/prompt/plan/M2"), (200, "/orch M2\n"))
        self.assertEqual(self.call("GET", "/prompt/assign/M1/S9")[0], 404)
        self.assertEqual(self.call("POST", "/handoff/M1%2FS1"), (200, "handoff M1/S1 for ann\n"))
        with open(os.path.join(self.pod, "handoffs.json")) as f:
            self.assertEqual(list(json.load(f)), ["M1/S1"])
        self.assertEqual(self.call("POST", "/ship/M1")[0], 202)
        self.assertEqual(self.call("DELETE", "/handoff/M1%2FS1"), (200, {"released": "M1/S1"}))

    def test_without_an_extension_a_story_prompt_is_not_implemented_and_nothing_is_handed_off(self):
        self.serve()
        self.watched()
        self.assertEqual(self.call("GET", "/prompt/assign/S1"), (501, {"error": "no orchestrator extension prompt"}))
        self.assertEqual(self.call("POST", "/handoff/S1"), (501, {"error": "no orchestrator extension prompt"}))
        self.assertFalse(os.path.exists(os.path.join(self.pod, "handoffs.json")))
        self.assertEqual(self.call("GET", "/prompt/plan/M1"), (200, "/orch M1\n"))
        self.assertEqual(self.call("GET", "/prompt/plan/M9")[0], 404)


class Pulls(Server):
    def setUp(self):
        super().setUp()
        self.env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.bare = os.path.join(self.tmp, "remote.git")
        self.git("init", "-q", "--bare", self.bare)
        self.sync = {"enabled": True, "remote": self.bare, "ref": REF}
        self.skeleton = {"project": {"title": "T"}, "orchestrator": DATA["orchestrator"], "sync": self.sync}

    def colleague_saves(self, data):
        """A colleague's machine saves `data` as the run's shared state."""
        run = os.path.join(self.tmp, "colleague")
        self.write("colleague/podium/podium.json", json.dumps({**data, "sync": self.sync}))
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", run, "sync", "save"],
                           capture_output=True, text=True, env={**self.env, "PODIUM_ME": "bob"}, cwd=self.tmp)
        self.assertRegex(r.stdout, r"^SAVED ", r.stderr)

    def local(self):
        with open(os.path.join(self.pod, "podium.json")) as f:
            return json.load(f)

    def test_a_run_that_doesnt_sync_pulls_nothing(self):
        self.serve()
        self.assertEqual(self.call("POST", "/pull"), (200, {"result": "OFF"}))
        self.assertIsNone(self.call("GET", "/info")[1]["pull"])

    def test_pulls_a_colleagues_changes_with_no_watcher_and_says_when_it_is_up_to_date(self):
        self.colleague_saves(DATA)
        self.serve(self.skeleton)
        code, body = self.call("POST", "/pull")
        self.assertEqual(code, 200)
        self.assertRegex(body["result"], r"^PULLED [0-9a-f]{7}$")
        self.assertEqual(self.local()["epics"], DATA["epics"])
        self.assertEqual(self.local()["sync"], self.sync)
        self.assertEqual(self.call("GET", "/info")[1]["pull"], body)
        self.assertEqual(self.call("POST", "/pull")[1]["result"], "UP-TO-DATE")

    def test_leaves_a_pull_to_a_running_watcher(self):
        self.colleague_saves(DATA)
        self.serve(self.skeleton)
        self.watched()
        self.assertEqual(self.call("POST", "/pull")[1]["result"], "KEPT the watcher is running")
        self.assertNotIn("epics", self.local())

    def test_refuses_a_pull_from_another_origin(self):
        self.serve(self.skeleton)
        self.assertEqual(self.call("POST", "/pull", {"Origin": "http://evil.example"})[0], 403)

    def test_the_auto_pull_records_each_pull_of_a_synced_run_and_skips_one_that_doesnt_sync(self):
        self.colleague_saves(DATA)
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump({k: v for k, v in DATA.items() if k != "epics"}, f)
        with unittest.mock.patch.dict(os.environ, self.env, clear=True), \
                unittest.mock.patch.object(human, "HUMAN_FILE", self.env["PODIUM_HUMAN"]), \
                unittest.mock.patch.dict(server.PULL, {"at": None, "result": None}):
            self.assertIsNone(server.pull_run(self.run_dir))
            self.assertEqual(server.PULL, {"at": None, "result": None})
            with open(os.path.join(self.pod, "podium.json"), "w") as f:
                json.dump(self.skeleton, f)
            self.assertEqual(server.pull_run(self.run_dir), server.PULL)
            self.assertRegex(server.PULL["result"], r"^PULLED ")
            self.assertTrue(server.PULL["at"])
        self.assertEqual(self.local()["epics"], DATA["epics"])


def cost_run(*stories):
    return {**DATA, "epics": [{"id": "e", "milestones": [
        {"id": ms, "status": "done", "stories": [{"id": sid, "status": "done", **more} for m, sid, more in stories if m == ms]}
        for ms in dict.fromkeys(m for m, _, _ in stories)]}]}


class Cost(Server):
    def log(self, folder, name, *messages):
        """A session log in this HOME's ~/.claude/projects/<folder>/<name>, one assistant line per (id, cwd, tokens, at)."""
        lines = [json.dumps({"type": "assistant", "timestamp": at, "cwd": cwd, "sessionId": "s",
                             "message": {"id": mid, "usage": {"input_tokens": n, "cache_creation_input_tokens": 2 * n,
                                                              "cache_read_input_tokens": 3 * n, "output_tokens": 4 * n}}})
                 for mid, cwd, n, at in messages]
        return self.write(os.path.join(".claude", "projects", folder, name), "".join(line + "\n" for line in lines))

    def worktree(self, rel):
        return os.path.join(self.run_dir, rel)

    def cost(self):
        for _ in range(100):
            body = self.call("GET", "/cost")[1]
            if body["ready"]:
                return body["milestones"]
            time.sleep(0.05)
        self.fail("the cost never got ready")

    def tokens(self, n):
        return {"input": n, "cacheWrite": 2 * n, "cacheRead": 3 * n, "output": 4 * n}

    def test_sums_the_sessions_whose_cwd_is_in_a_storys_worktree_each_message_once(self):
        tree = self.worktree("worktrees/S1/core")
        slug = cost.slug(tree)
        at = "2026-10-20T08:00:00.000Z"
        self.log(slug, "a.jsonl", ("m1", tree, 10, at), ("m1", tree, 10, at), ("m2", tree + "/backend", 1, at))
        self.log(slug + "-backend", "b.jsonl", ("m3", tree + "/backend", 100, at))
        self.log(slug, os.path.join("a", "subagents", "agent-x.jsonl"), ("m4", tree, 1000, at))
        self.log(slug, "elsewhere.jsonl", ("m5", "/elsewhere", 7, at))
        self.log(cost.slug(self.worktree("worktrees/S2/core")), "c.jsonl", ("m6", self.worktree("worktrees/S2/core"), 20000, at))
        self.serve(cost_run(("M1", "S1", {"worktrees": {"core": "worktrees/S1/core"}}),
                            ("M1", "S2", {"worktrees": {"core": "worktrees/S2/core"}}),
                            ("M2", "S3", {"worktrees": {}})))
        self.assertEqual(self.cost(), {"M1": {**self.tokens(21111), "stories": {"S1": self.tokens(1111), "S2": self.tokens(20000)}}})

    def test_counts_an_agent_tool_story_from_its_subagent_log_wherever_it_lies(self):
        self.log("-somewhere-else", os.path.join("parent", "subagents", "agent-a1b2.jsonl"), ("m1", "/somewhere/else", 3, "2026-10-20T08:00:00Z"))
        self.serve(cost_run(("M1", "S1", {"agent": {"backend": "agent", "id": "a1b2"}}),
                            ("M1", "S2", {"agent": {"backend": "agent", "id": "*"}})))
        self.assertEqual(self.cost(), {"M1": {**self.tokens(3), "stories": {"S1": self.tokens(3)}}})

    def test_a_worktree_two_stories_share_gives_each_message_to_the_story_that_started_last_before_it(self):
        tree = self.worktree("worktrees/S1/web")
        self.log(cost.slug(tree), "a.jsonl", ("m1", tree, 1, "2026-10-20T07:00:00Z"), ("m2", tree, 10, "2026-10-20T09:00:00Z"),
                 ("m3", tree, 100, "2026-11-01T09:00:00Z"))
        self.serve(cost_run(("M1", "S1", {"worktrees": {"web": "worktrees/S1/web"}, "startedAt": "2026-10-20T08:00:00+00:00"}),
                            ("M9", "S1", {"worktrees": {"web": tree}, "startedAt": "2026-11-01T10:00:00+02:00"})))
        self.assertEqual(self.cost(), {"M1": {**self.tokens(11), "stories": {"S1": self.tokens(11)}},
                                       "M9": {**self.tokens(100), "stories": {"S1": self.tokens(100)}}})

    def test_answers_at_once_while_the_logs_are_read_and_rereads_only_a_changed_log(self):
        tree = self.worktree("worktrees/S1/core")
        path = self.log(cost.slug(tree), "a.jsonl", ("m1", tree, 1, "2026-10-20T08:00:00Z"))
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(cost_run(("M1", "S1", {"worktrees": {"core": "worktrees/S1/core"}})), f)
        release, parsed, real = threading.Event(), [], cost.message_usages

        def slow(p):
            release.wait(5)
            parsed.append(p)
            return real(p)
        costs = cost.Costs(self.run_dir, os.path.join(self.tmp, ".claude", "projects"))
        with unittest.mock.patch.object(cost, "message_usages", slow), unittest.mock.patch.object(cost, "REFRESH", 0):
            self.assertEqual(costs.get(), {"ready": False, "milestones": {}})
            release.set()
            for _ in range(100):
                if costs.get()["ready"] and not costs.running:
                    break
                time.sleep(0.02)
            self.assertEqual(costs.get()["milestones"]["M1"]["output"], 4)
            while costs.running:
                time.sleep(0.02)
            self.assertEqual(parsed, [path])
            with open(path, "a") as f:
                f.write(json.dumps({"type": "assistant", "timestamp": "2026-10-20T09:00:00Z", "cwd": tree,
                                    "message": {"id": "m2", "usage": {"output_tokens": 6}}}) + "\n")
            for _ in range(100):
                if costs.get()["milestones"]["M1"]["output"] == 10:
                    break
                time.sleep(0.02)
            self.assertEqual(costs.get()["milestones"]["M1"]["output"], 10)
            self.assertEqual(parsed, [path, path])


if __name__ == "__main__":
    unittest.main()
