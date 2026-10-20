"""Tests for the Podium server, run as `podium server` against a temp run: what /info says, the Host and Origin checks,
/repo/ confined to the run's repo, the sandbox on every file it serves, checkouts read relative to the run dir and
never one a pull could have written, request queuing, and prompts from the run's extension."""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
SHARE_HINT = "Install the orch skill from its repo"

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

    def serve(self, data=DATA, extension=None, git_every=0):
        data = json.loads(json.dumps(data))
        if extension:
            data["orchestrator"]["extension"] = self.write("ext/orch.py", textwrap.dedent(extension))
        with open(os.path.join(self.pod, "podium.json"), "w") as f:
            json.dump(data, f)
        self.port = free_port()
        proc = subprocess.Popen([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "server",
                                 "--port", str(self.port), "--idle", "0", "--git-every", str(git_every)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.tmp)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        self.assertEqual(proc.stdout.readline().strip(), f"http://127.0.0.1:{self.port}/")
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
        self.assertEqual(set(info), {"runDir", "repoDir", "watching", "orchestrator", "me", "people", "paseoServer",
                                     "lastUse", "stale"})
        self.assertEqual((info["runDir"], info["repoDir"]), (self.run_dir, self.repo))
        self.assertEqual(info["orchestrator"], {"name": "orch", "command": "/orch", "shareHint": None})
        self.assertEqual(info["me"], "ann")
        self.assertEqual(info["people"], {"ann": {"active": {"milestone": "M1"}}, "bob": {"active": {"milestone": "M2"}}})
        self.assertEqual((info["watching"], info["stale"], info["paseoServer"]), (False, False, None))

    def test_a_run_without_an_orchestrator_or_people_says_so(self):
        self.serve({k: v for k, v in DATA.items() if k != "orchestrator"})
        info = self.call("GET", "/info")[1]
        self.assertEqual((info["orchestrator"], info["people"]), ({"name": None, "command": None, "shareHint": None}, {}))

    def test_passes_on_the_extensions_share_hint(self):
        self.serve(extension=EXTENSION)
        self.assertEqual(self.call("GET", "/info")[1]["orchestrator"]["shareHint"], "Install the orch skill from its repo")


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
                                 "--port", str(self.port), "--idle", "0", "--git-every", "0"],
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


if __name__ == "__main__":
    unittest.main()
