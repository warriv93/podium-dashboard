"""Tests for the `podium` command: run discovery, --version, init, and an orchestrator extension's verbs."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import __version__  # noqa: E402

DATA = {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"},
        "epics": [{"id": "e", "milestones": [{"id": "M1", "status": "working", "phase": "build",
                                               "stories": [{"id": "S1", "status": "todo", "deps": []},
                                                           {"id": "S2", "status": "todo", "deps": ["S1"]}]}]}]}


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = {**os.environ, "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"), "PYTHONPATH": ROOT, "HOME": self.tmp}
        self.env.pop("PODIUM_DIR", None)

    def run_at(self, run_dir, data=DATA):
        os.makedirs(os.path.join(run_dir, "podium"), exist_ok=True)
        with open(os.path.join(run_dir, "podium", "podium.json"), "w") as f:
            json.dump(data, f)
        return run_dir

    def podium(self, *args, cwd=None, env=None, code=0):
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", *args], capture_output=True, text=True,
                           env={**self.env, **(env or {})}, cwd=cwd or self.tmp)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def state(self, run_dir):
        with open(os.path.join(run_dir, "podium", "podium.json")) as f:
            return json.load(f)


class Discovery(Cli):
    def test_finds_a_feature_folder_run_from_a_folder_inside_it(self):
        run = self.run_at(os.path.join(self.tmp, "feature"))
        inner = os.path.join(run, "podium", "stories")
        os.makedirs(inner)
        self.assertEqual(self.podium("ready", cwd=inner).stdout.strip(), "S1")

    def test_finds_a_repos_deep_plan_run_from_a_subfolder_of_the_repo(self):
        repo = os.path.join(self.tmp, "api")
        self.run_at(os.path.join(repo, ".deep-plan"))
        os.makedirs(os.path.join(repo, "src", "lib"))
        self.assertEqual(self.podium("ready", cwd=os.path.join(repo, "src", "lib")).stdout.strip(), "S1")

    def test_podium_dir_names_the_run_and_dir_overrides_it(self):
        run = self.run_at(os.path.join(self.tmp, "named"))
        other = self.run_at(os.path.join(self.tmp, "other"), {**DATA, "active": {"milestone": "M9"}})
        self.assertEqual(self.podium("ready", env={"PODIUM_DIR": run}).stdout.strip(), "S1")
        self.podium("--dir", other, "ready", env={"PODIUM_DIR": run}, code=1)

    def test_asks_for_a_dir_outside_any_run(self):
        r = self.podium("ready", code=2)
        self.assertIn("--dir", r.stderr)

    def test_hours_human_and_version_need_no_run(self):
        self.assertIn("hours Mon-Fri 07:00-17:00", self.podium("hours").stdout)
        self.assertRegex(self.podium("human").stdout, r"^(available|unavailable) until ")
        self.assertEqual(self.podium("--version").stdout.strip(), f"podium {__version__}")

    def test_bare_podium_lists_the_core_commands(self):
        out = self.podium().stdout
        for verb in ("status", "set", "batch", "ready", "assume", "settle", "log", "requests", "init"):
            self.assertIn(f"\n    {verb}", out)

    def test_an_unknown_command_exits_2(self):
        run = self.run_at(os.path.join(self.tmp, "run"))
        self.assertIn("unknown command 'nope'", self.podium("--dir", run, "nope", code=2).stderr)


class Init(Cli):
    def test_creates_the_run_and_then_updates_only_the_orchestrator_block(self):
        run = os.path.join(self.tmp, "feature")
        os.makedirs(run)
        out = self.podium("init", "--name", "my-skill", "--command", "/my-skill", "--extension", "~/ext.py",
                          "--phases", "plan, build,,ship", cwd=run).stdout
        self.assertEqual(out.strip(), f"created {os.path.join(run, 'podium', 'podium.json')}")
        st = self.state(run)
        self.assertEqual(st["orchestrator"], {"name": "my-skill", "command": "/my-skill", "extension": "~/ext.py",
                                              "phases": ["plan", "build", "ship"]})
        self.assertEqual((st["project"]["title"], st["epics"]), ("feature", []))
        self.podium("--dir", run, "set", ".", "orchestrator.stages={\"RED\": \"test\"}", "project.title=Mine", "epics+={\"id\": \"e\"}")
        self.podium("--dir", run, "init", "--name", "other", "--command", "/other", "--extension", "/x.py")
        st = self.state(run)
        self.assertEqual(st["orchestrator"], {"name": "other", "command": "/other", "extension": "/x.py",
                                              "phases": ["plan", "build", "ship"], "stages": {"RED": "test"}})
        self.assertEqual((st["project"]["title"], st["epics"]), ("Mine", [{"id": "e"}]))

    def test_names_a_deep_plan_run_after_its_repo(self):
        run = os.path.join(self.tmp, "api", ".deep-plan")
        self.podium("--dir", run, "init", "--name", "n", "--command", "/n", "--extension", "x.py")
        self.assertEqual(self.state(run)["project"]["title"], "api")

    def test_stores_a_path_typed_relative_to_the_cwd_relative_to_podium_json(self):
        repo = os.path.join(self.tmp, "api")
        os.makedirs(os.path.join(repo, "tools"))
        with open(os.path.join(repo, "tools", "ext.py"), "w") as f:
            f.write("COMMANDS = {'hi': lambda p, args: print('hi')}\n")
        self.podium("--dir", ".deep-plan", "init", "--name", "n", "--command", "/n", "--extension", "tools/ext.py", cwd=repo)
        run = os.path.join(repo, ".deep-plan")
        self.assertEqual(self.state(run)["orchestrator"]["extension"], "../../tools/ext.py")
        self.assertEqual(self.podium("hi", cwd=os.path.join(repo, "tools")).stdout, "hi\n")

    def test_a_run_at_the_repo_root_loads_an_extension_beside_podium(self):
        repo = os.path.join(self.tmp, "api")
        os.makedirs(repo)
        with open(os.path.join(repo, "ext.py"), "w") as f:
            f.write("COMMANDS = {'hi': lambda p, args: print('hi')}\n")
        self.podium("init", "--name", "n", "--command", "/n", "--extension", "./ext.py", cwd=repo)
        self.assertEqual(self.state(repo)["orchestrator"]["extension"], "../ext.py")
        self.assertEqual(self.podium("hi", cwd=repo).stdout, "hi\n")

    def test_refuses_missing_or_unknown_flags(self):
        for args in (("--name", "n", "--command", "/n"), ("--name", "n", "--command", "/n", "--extension"),
                     ("--name", "n", "--command", "/n", "--extension", "x.py", "--colour", "red")):
            self.podium("--dir", self.tmp, "init", *args, code=1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "podium", "podium.json")))


class Extension(Cli):
    def extension(self, text, name="ext.py"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(textwrap.dedent(text))
        return path

    def run_with(self, extension):
        return self.run_at(os.path.join(self.tmp, "run"), {**DATA, "orchestrator": {"name": "my-skill", "command": "/my-skill",
                                                                                     "extension": extension}})

    def test_dispatches_a_verb_the_core_does_not_know_to_the_extension(self):
        self.extension("""
            from podium_dashboard.state import Podium, building


            def hello(p, args):
                \"\"\"Greet the active milestone.\"\"\"
                print("hello", p.milestone()["id"], building(p.milestone()), *args)


            def status(p, args):
                print("shadowed")


            COMMANDS = {"hello": hello, "status": status}
            """)
        run = self.run_with("~/ext.py")
        self.assertEqual(self.podium("--dir", run, "hello", "a", "b").stdout, "hello M1 True a b\n")
        self.assertNotIn("shadowed", self.podium("--dir", run, "status").stdout)
        listed = self.podium(cwd=run).stdout
        self.assertIn(f"MY-SKILL COMMANDS ({self.tmp}/ext.py)\n    hello\n        Greet the active milestone.\n", listed)

    def test_a_relative_extension_path_is_relative_to_podium_json(self):
        self.extension("COMMANDS = {'hi': lambda p, args: print('hi')}\n")
        run = self.run_with("../../ext.py")
        self.assertEqual(self.podium("--dir", run, "hi").stdout, "hi\n")

    def test_an_unloadable_extension_leaves_the_core_working_and_its_verbs_exit_2(self):
        broken = self.extension("COMMANDS = {'hello': \n", name="broken.py")
        run = self.run_with(broken)
        self.assertEqual(self.podium("--dir", run, "ready").stdout.strip(), "S1")
        self.podium("--dir", run, "status")
        r = self.podium("--dir", run, "hello", code=2)
        self.assertTrue(r.stderr.startswith(f"podium: extension {broken} not loadable: SyntaxError"), r.stderr)
        self.assertIn(f"extension {broken} not loadable", self.podium("--dir", run).stdout)

    def test_only_a_py_file_loads(self):
        for name in ("ext.so", "ext.pyc", "ext.txt"):
            run = self.run_with(self.extension("COMMANDS = {'hello': print}\n", name=name))
            r = self.podium("--dir", run, "hello", code=2)
            self.assertEqual(r.stderr.strip(), f"podium: extension {self.tmp}/{name} not loadable: not a .py file")

    def test_the_samples_extension_beside_the_run_loads(self):
        self.assertIn("MINIMAL COMMANDS (", self.podium("--dir", os.path.join(ROOT, "sample")).stdout)

    def test_a_missing_extension_says_so(self):
        run = self.run_with("~/gone.py")
        r = self.podium("--dir", run, "hello", code=2)
        self.assertEqual(r.stderr.strip(), f"podium: extension {self.tmp}/gone.py not loadable: no such file")

    def test_an_extension_that_exits_while_loading_is_unloadable(self):
        run = self.run_with(self.extension("import sys\nsys.exit('no')\n"))
        self.assertIn("not loadable: SystemExit: no", self.podium("--dir", run, "hello", code=2).stderr)


if __name__ == "__main__":
    unittest.main()
