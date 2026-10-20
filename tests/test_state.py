"""Tests for the run-state commands: set, batch, get, ready, status, human, hours, assume, settle, log, requests,
and the lock and rebase every write goes through.

Each test builds a run in a temp dir: a git repo `api` with a feature worktree, and a feature folder holding
podium/podium.json, and runs `python3 -m podium_dashboard` on it.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import human, state  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class Run(unittest.TestCase):
    """A feature folder `run/` with one milestone M1 on repos `api` and `web`: the main checkout api/ on main and the
    feature worktree run/repos/api on feat/m1. S2 depends on S1, S3 on S2; S4 waits for S1 to finish (overlapAfter)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = {**os.environ, **GIT_ENV, "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"), "PYTHONPATH": ROOT}
        for k in ("PODIUM_DIR", "PODIUM_STORY", "PODIUM_MILESTONE"):
            self.env.pop(k, None)
        self.main = os.path.join(self.tmp, "api")
        git(self.tmp, "init", "-q", "-b", "main", self.main)
        with open(os.path.join(self.main, "a.txt"), "w") as f:
            f.write("x")
        git(self.main, "add", "a.txt")
        git(self.main, "commit", "-q", "-m", "init")
        self.run_dir = os.path.join(self.tmp, "run")
        self.feature = os.path.join(self.run_dir, "repos", "api")
        git(self.main, "worktree", "add", "-q", "-b", "feat/m1", self.feature, "main")
        self.data = {
            "project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"}, "needsYou": None, "dispatcher": "agent",
            "assumptions": [{"question": "q0", "choice": "c", "why": "w", "status": "open"},
                            {"question": "q1", "choice": "c", "why": "w", "status": "confirmed"}],
            "epics": [{"id": "e", "title": "E", "milestones": [{
                "id": "M1", "title": "Feat", "status": "working", "phase": "build",
                "repos": {"api": {"branch": "feat/m1", "base": "main", "path": self.feature, "pr": None},
                          "web": {"branch": "feat/m1", "base": "main", "pr": {"number": 7, "state": "open"}}},
                "stories": [{"id": "S1", "title": "One", "status": "todo", "deps": [], "repos": ["api"]},
                            {"id": "S2", "title": "Two", "status": "todo", "deps": ["S1"], "repos": ["api", "events"]},
                            {"id": "S3", "title": "Three", "status": "todo", "deps": ["S2"]},
                            {"id": "S4", "title": "Four", "status": "todo", "deps": [], "overlapAfter": ["S1"]}]}]}]}
        self.write()

    def write(self):
        os.makedirs(os.path.join(self.run_dir, "podium"), exist_ok=True)
        with open(os.path.join(self.run_dir, "podium", "podium.json"), "w") as f:
            json.dump(self.data, f)

    def podium(self, *args, stdin=None, env=None, cwd=None, code=0):
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, *args], input=stdin,
                           capture_output=True, text=True, env={**self.env, **(env or {})}, cwd=cwd or self.tmp)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def state(self):
        with open(os.path.join(self.run_dir, "podium", "podium.json")) as f:
            return json.load(f)

    def milestone(self):
        return self.state()["epics"][0]["milestones"][0]

    def stories(self):
        return {s["id"]: s for s in self.milestone()["stories"]}

    def events(self):
        path = os.path.join(self.run_dir, "podium", "events.jsonl")
        with open(path) if os.path.exists(path) else io.StringIO() as f:
            return [json.loads(line) for line in f]


class Set(Run):
    def test_reaches_into_objects_and_lists_with_dotted_keys(self):
        with open(os.path.join(self.tmp, "pr.json"), "w") as f:
            json.dump({"number": 3, "state": "draft"}, f)
        self.podium("set", "milestone:", "repos.api.pr=@" + os.path.join(self.tmp, "pr.json"), "agent.id=x",
                    "assumptions.0.status=confirmed")
        self.podium("set", ".", "assumptions.1.status=reversed")
        m = self.milestone()
        self.assertEqual(m["repos"]["api"]["pr"], {"number": 3, "state": "draft"})
        self.assertEqual(m["agent"], {"id": "x"})
        self.assertEqual(self.state()["assumptions"][1]["status"], "reversed")

    def test_parses_json_values_and_stamps_now(self):
        self.podium("set", "S1", "attempts=2", "flag=true", "title=plain words", "startedAt=now")
        s = self.stories()["S1"]
        self.assertEqual((s["attempts"], s["flag"], s["title"]), (2, True, "plain words"))
        self.assertRegex(s["startedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertIn("updatedAt", self.state())

    def test_plus_equals_appends_to_a_list_and_adds_to_a_number(self):
        self.podium("set", "S1", "notes+=a", "attempts+=1")
        self.podium("set", "S1", "notes+=b", "attempts+=2")
        s = self.stories()["S1"]
        self.assertEqual((s["notes"], s["attempts"]), (["a", "b"], 3))

    def test_a_failed_story_blocks_every_story_that_depends_on_it_directly_or_not(self):
        out = self.podium("set", "S1", "status=failed")
        self.assertEqual(out.strip(), "blocked: S2 S3")
        self.assertEqual({k: s["status"] for k, s in self.stories().items()},
                         {"S1": "failed", "S2": "blocked", "S3": "blocked", "S4": "todo"})

    def test_an_event_names_the_targets_milestone_and_story(self):
        self.podium("set", "M1/S2", "status=working", "--event", "dispatched", "agent=x")
        e = self.events()[0]
        self.assertEqual((e["type"], e["milestone"], e["story"], e["agent"]), ("dispatched", "M1", "S2", "x"))

    def test_an_unknown_target_writes_nothing(self):
        before = self.state()
        self.podium("set", "S9", "note=x", code=1)
        self.podium("set", "epic:nope", "note=x", code=1)
        self.podium("set", "S1", "note", code=1)
        self.assertEqual(self.state(), before)

    def test_pairs_builds_nested_objects_and_a_list_needs_an_item_index(self):
        with self.assertRaises(SystemExit):
            state.assign({"xs": [1]}, "xs.x=2")
        obj = state.pairs(["a.b=1", "a.c+=x", "n+=2"])
        self.assertEqual(obj, {"a": {"b": 1, "c": ["x"]}, "n": 2})


class Get(Run):
    def test_prints_a_milestone_without_its_stories_and_the_project_with_its_epic_ids(self):
        m = json.loads(self.podium("get", "milestone:M1"))
        self.assertEqual((m["id"], m["stories"]), ("M1", "<4 stories>"))
        self.assertEqual(json.loads(self.podium("get", "."))["epics"], ["e"])
        self.assertEqual(json.loads(self.podium("get", "S2"))["deps"], ["S1"])


class Batch(Run):
    def test_applies_every_set_in_one_write_and_appends_events_in_order(self):
        out = self.podium("batch", stdin="S1 note=a --event note text=first\n# skipped\nset milestone: phase=gate --event phase phase=gate\n")
        self.assertEqual(out.strip(), "2 sets, 2 events")
        self.assertEqual(self.milestone()["phase"], "gate")
        self.assertEqual([e["type"] for e in self.events()], ["note", "phase"])

    def test_a_failing_op_writes_nothing(self):
        self.podium("batch", stdin="S1 note=a --event note text=x\nS9 note=b\n", code=1)
        self.assertNotIn("note", self.stories()["S1"])
        self.assertEqual(self.events(), [])


class Ready(Run):
    def test_lists_todo_stories_whose_deps_and_overlap_are_done_and_not_handed_off(self):
        self.assertEqual(self.podium("ready").strip(), "S1")
        self.podium("set", "S1", "status=done")
        self.assertEqual(self.podium("ready").strip(), "S2 S4")
        with open(os.path.join(self.run_dir, "podium", "handoffs.json"), "w") as f:
            json.dump({"M1/S2": {"at": "x"}, "M9/S4": {"at": "x"}}, f)
        self.assertEqual(self.podium("ready").strip(), "S4")
        self.assertIn("handed off", [l for l in self.podium("status").splitlines() if l.strip().startswith("S2")][0])


class TwoMilestones(Run):
    """M2 builds beside the active M1, with stories T1 and T2 (T2 after T1)."""

    def setUp(self):
        super().setUp()
        self.data["epics"][0]["milestones"].append({
            "id": "M2", "title": "Beside", "status": "working", "phase": "build",
            "repos": {"events": {"branch": "feat/m2", "base": "main", "pr": None}},
            "stories": [{"id": "T1", "title": "Ten", "status": "todo", "deps": []},
                        {"id": "T2", "title": "Eleven", "status": "todo", "deps": ["T1"]}]})
        self.write()

    def test_status_and_ready_show_each_building_milestone_with_its_build_all(self):
        self.podium("set", "milestone:M2", "buildAll=true")
        out = self.podium("status")
        self.assertIn("\nM1 Feat · working · phase build · branch - · buildAll off\n", out)
        self.assertIn("  repo api feat/m1 → main · no PR\n  repo web feat/m1 → main · PR #7 open\n", out)
        self.assertIn("\nM2 Beside · working · phase build · branch - · buildAll on\n", out)
        self.assertEqual([l for l in out.splitlines() if l.startswith("ready:")], ["ready: S1", "ready: T1"])
        self.assertNotIn("\nM1 ", self.podium("status", "--milestone", "M2"))
        self.assertEqual(self.podium("ready").strip(), "S1")
        self.assertEqual(self.podium("ready", "--milestone", "M2").strip(), "T1")

    def test_a_top_level_build_all_is_the_active_milestones_and_a_write_moves_it_there(self):
        self.data["buildAll"] = True
        self.write()
        self.assertIn("M1 Feat · working · phase build · branch - · buildAll on", self.podium("status"))
        self.podium("set", "M2/T1", "note=x")
        st = self.state()
        self.assertNotIn("buildAll", st)
        self.assertEqual([m.get("buildAll") for m in st["epics"][0]["milestones"]], [True, None])
        self.podium("set", ".", "buildAll=false")
        self.assertIs(self.milestone()["buildAll"], False)

    def test_an_assumption_about_a_story_of_another_milestone_names_that_milestone(self):
        self.podium("assume", "q?", "c", "w", "--story", "M2/T1")
        a = self.state()["assumptions"][-1]
        self.assertEqual((a["milestone"], a["story"]), ("M2", "T1"))
        self.assertEqual([(e["milestone"], e["story"]) for e in self.events()], [("M2", "T1")])


class Assumptions(Run):
    def test_records_lists_and_settles_assumptions(self):
        self.assertEqual(self.podium("assume", "Which db?", "sqlite", "simplest", "--short", "sqlite").strip(), "assumption 2")
        a = self.state()["assumptions"][2]
        self.assertEqual((a["milestone"], a["short"], a["status"]), ("M1", "sqlite", "open"))
        self.assertNotIn("story", a)
        self.assertEqual(self.podium("assumptions").splitlines(),
                         ["0 [] q0 → c (w)", "2 [M1] Which db? → sqlite (simplest)"])
        self.assertEqual(self.podium("settle", "0,2", "confirmed").strip(), "2 confirmed")
        self.assertEqual(self.podium("assumptions"), "")
        self.assertEqual({k: v for k, v in self.events()[-1].items() if k != "at"},
                         {"type": "settled", "status": "confirmed", "count": 2})

    def test_settling_one_names_its_question(self):
        self.podium("settle", "0", "reversed")
        self.assertEqual(self.events()[-1]["question"], "q0")
        self.assertEqual(self.state()["assumptions"][0]["status"], "reversed")

    def test_refuses_an_assumption_that_does_not_exist_or_a_bad_verdict(self):
        for args in (("5", "confirmed"), ("-1", "confirmed"), ("x", "confirmed"), ("0", "maybe"), ("0",)):
            self.podium("settle", *args, code=1)
        self.podium("assume", "only a question", code=1)
        self.assertEqual(self.events(), [])


class Human(Run):
    def test_sets_and_prints_hours_for_every_run(self):
        out = self.podium("hours", "Mon,Wed,Fri-Sun", "09:00-15:30")
        self.assertEqual(out.strip(), f"hours Mon,Wed,Fri-Sun 09:00-15:30 ({self.env['PODIUM_HUMAN']})")
        with open(self.env["PODIUM_HUMAN"]) as f:
            self.assertEqual(json.load(f)["hours"], {"days": "Mon,Wed,Fri-Sun", "from": "09:00", "to": "15:30"})
        self.podium("hours", "Mon-Funday", "09:00-15:30", code=1)
        self.podium("hours", "Mon-Fri", "9-15", code=1)

    def test_the_toggle_holds_until_it_ends(self):
        with open(self.env["PODIUM_HUMAN"], "w") as f:
            json.dump({"mode": "mobile", "until": "2099-01-01T10:00"}, f)
        self.assertEqual(self.podium("human").strip(), "mobile until Thu 10:00 (Podium toggle; hours Mon-Fri 07:00-17:00)")

    def test_availability_follows_the_hours_across_days_and_the_weekend(self):
        path = os.path.join(self.tmp, "h.json")
        with unittest.mock.patch.object(human, "HUMAN_FILE", path):
            monday = state.availability(datetime(2026, 10, 19, 8, 0))
            self.assertEqual((monday["mode"], monday["until"], monday["source"]), ("available", "2026-10-19T17:00", "hours"))
            friday = state.availability(datetime(2026, 10, 23, 17, 0))
            self.assertEqual((friday["mode"], friday["until"]), ("unavailable", "2026-10-26T07:00"))
            state.write_human(hours={"days": "Fri-Mon", "from": "22:00", "to": "23:00"})
            self.assertEqual(state.day_set("Fri-Mon"), {4, 5, 6, 0})
            self.assertEqual(state.availability(datetime(2026, 10, 20, 12, 0))["until"], "2026-10-23T22:00")
            state.write_human(mode="available", until="2026-10-20T13:00")
            toggled = state.availability(datetime(2026, 10, 20, 12, 0))
            self.assertEqual((toggled["mode"], toggled["source"]), ("available", "toggle"))
            self.assertEqual(state.availability(datetime(2026, 10, 20, 13, 0))["source"], "hours")


class Log(Run):
    def progress(self, sid="S1"):
        with open(os.path.join(self.run_dir, "podium", "stories", "M1", f"{sid}.progress")) as f:
            return f.read().splitlines()

    def test_appends_one_stamped_line_for_the_named_story(self):
        self.podium("log", "M1/S1", "RED", "3 failing", "tests")
        line = self.progress()[0].split(" ", 2)
        self.assertEqual(line[1:], ["RED", "3 failing tests"])
        self.assertRegex(line[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")

    def test_reads_the_story_from_the_environment_and_keeps_a_note_on_one_line(self):
        self.podium("log", "COMMITTED", "api:abc\nCOMMITTED fake", env={"PODIUM_STORY": "S2", "PODIUM_MILESTONE": "M1"})
        self.assertEqual([l.split(" ", 1)[1] for l in self.progress("S2")], ["COMMITTED api:abc COMMITTED fake"])

    def test_finds_the_story_from_the_branch_of_its_worktree(self):
        tree = os.path.join(self.tmp, "wt")
        git(self.main, "worktree", "add", "-q", "-b", "story/S2", tree, "main")
        self.podium("log", "STARTED", "go", cwd=tree)
        self.assertEqual(self.progress("S2")[0].split(" ", 1)[1], "STARTED go")

    def test_takes_a_fix_with_its_kind(self):
        self.podium("log", "M1/S1", "FIX", "bug", "UTC vs local midnight")
        self.assertEqual(self.progress()[0].split(" ", 1)[1], "FIX bug UTC vs local midnight")

    def test_takes_a_stage_of_the_orchestrators_own_stage_map(self):
        self.podium("set", ".", 'orchestrator={"stages": {"REVIEW": {"doing": "reviewing", "step": 2, "time": "review"}}}')
        self.podium("log", "M1/S1", "REVIEW", "looks fine")
        self.podium("log", "REVIEW", "again", env={"PODIUM_STORY": "S1", "PODIUM_MILESTONE": "M1"})
        self.assertEqual([l.split(" ", 1)[1] for l in self.progress()], ["REVIEW looks fine", "REVIEW again"])
        self.podium("log", "M1/S1", "DONE", "x", code=1)

    def test_rejects_an_unknown_stage(self):
        self.podium("log", "M1/S1", "DONE", "x", code=1)

    def test_refuses_an_id_that_is_not_a_plain_path_component(self):
        self.data["epics"][0]["milestones"][0]["id"] = "../../../x"
        self.data["epics"][0]["milestones"][0]["stories"][1]["id"] = "../../y"
        self.write()
        before = sorted(os.path.join(d, n) for d, _, ns in os.walk(self.tmp) for n in ns)
        self.podium("log", "../../../x/S1", "STARTED", "go", code=1)
        self.podium("log", "STARTED", "go", env={"PODIUM_MILESTONE": "../../../x", "PODIUM_STORY": "../../y"}, code=1)
        self.assertEqual(sorted(os.path.join(d, n) for d, _, ns in os.walk(self.tmp) for n in ns), before)

    def test_a_valid_id_is_one_short_plain_path_component(self):
        for good in ("M1", "s-2_b", "x" * 32):
            self.assertTrue(state.valid_id(good), good)
        for bad in ("", "..", "../x", "a/b", "a\\b", "x" * 33, "M1\n", "M 1", None, 7):
            self.assertFalse(state.valid_id(bad), bad)

    def test_asks_which_story_outside_a_story_branch(self):
        self.podium("log", "STARTED", "go", code=1)

    def test_appends_only_while_it_holds_the_runs_lock(self):
        folder = os.path.join(self.run_dir, "podium", "stories", "M1")
        with state.Podium(self.run_dir).locked():
            other = subprocess.Popen([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "log", "M1/S1", "STARTED", "go"],
                                     env=self.env, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.addCleanup(other.kill)
            deadline = time.time() + 10
            while not os.path.isdir(folder) and time.time() < deadline:
                time.sleep(0.05)
            time.sleep(0.5)
            self.assertIsNone(other.poll())
            self.assertFalse(os.path.exists(os.path.join(folder, "S1.progress")))
        out, _ = other.communicate(timeout=30)
        self.assertEqual(other.returncode, 0, out)
        self.assertEqual(self.progress()[0].split(" ", 1)[1], "STARTED go")


class Writes(Run):
    def test_a_write_waits_for_the_lock_and_neither_loses_the_other(self):
        p = state.Podium(self.run_dir)
        with p.locked():
            other = subprocess.Popen([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "set", "S2", "title=Theirs"],
                                     env=self.env, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.addCleanup(other.kill)
            time.sleep(1)
            self.assertIsNone(other.poll())
            p.story("S1")[1]["title"] = "Mine"
            p.save()
        out, _ = other.communicate(timeout=30)
        self.assertEqual(other.returncode, 0, out)
        self.assertEqual([s["title"] for s in self.milestone()["stories"][:2]], ["Mine", "Theirs"])

    def test_refresh_catches_up_and_keeps_this_commands_changes(self):
        p = state.Podium(self.run_dir)
        p.story("S1")[1]["status"] = "working"
        self.podium("set", "S2", "title=Meanwhile")
        p.refresh()
        self.assertEqual([s["title"] for s in p.milestone()["stories"][:2]], ["One", "Meanwhile"])
        self.assertEqual(p.story("S1")[1]["status"], "working")

    def test_rebase_puts_this_commands_changes_on_top_of_the_others(self):
        base = {"a": 1, "stories": [{"id": "S1", "status": "todo"}, {"id": "S2", "status": "todo"}], "log": ["x"], "gone": 1}
        mine = {"a": 2, "stories": [{"id": "S1", "status": "done"}, {"id": "S2", "status": "todo"}, {"id": "S3"}], "log": ["x", "m"]}
        theirs = {"a": 1, "stories": [{"id": "S1", "status": "todo"}, {"id": "S2", "status": "working"}], "log": ["x", "t"], "gone": 1, "new": 3}
        self.assertEqual(state.rebase(base, mine, theirs), {
            "a": 2, "stories": [{"id": "S1", "status": "done"}, {"id": "S2", "status": "working"}, {"id": "S3"}],
            "log": ["x", "t", "m"], "new": 3})

    def test_a_run_from_before_the_podium_folder_is_read_at_the_top(self):
        legacy = os.path.join(self.tmp, "legacy")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "podium.json"), "w") as f:
            json.dump(self.data, f)
        self.assertEqual(state.Podium(legacy).dir, legacy)
        self.podium("--dir", legacy, "set", "S1", "note=x")
        with open(os.path.join(legacy, "podium.json")) as f:
            self.assertEqual(json.load(f)["epics"][0]["milestones"][0]["stories"][0]["note"], "x")


class CheckoutPath(Run):
    def test_a_checkout_inside_the_run_dir_counts_only_under_repos_or_worktrees(self):
        p = state.Podium(self.run_dir)
        planted = os.path.join(self.run_dir, "podium", "stories", "x")
        os.makedirs(planted)
        os.symlink(planted, os.path.join(self.run_dir, "repos", "link"))
        self.assertEqual(state.checkout_path(p, "repos/api"), self.feature)
        self.assertEqual(state.checkout_path(p, "worktrees/w/"), os.path.join(self.run_dir, "worktrees", "w"))
        self.assertEqual(state.checkout_path(p, "~/code/api"), os.path.join(os.path.expanduser("~"), "code", "api"))
        self.assertEqual(state.checkout_path(p, "../api"), self.main)
        self.assertEqual(state.checkout_path(p, self.main), self.main)
        for path in ("podium/stories/x", planted, "repos/../podium/stories/x", "repos/link", "docs", ".", ""):
            self.assertIsNone(state.checkout_path(p, path), path)


class Requests(Run):
    def path(self, name):
        return os.path.join(self.run_dir, "podium", name)

    def queue(self, *lines):
        with open(self.path("requests.jsonl"), "a") as f:
            f.writelines(json.dumps(l) + "\n" for l in lines)

    def cursor(self):
        with open(self.path("cursor.json")) as f:
            return json.load(f)["requestsSeen"]

    def test_splits_the_users_answers_from_the_rest_and_passes_each_on_once(self):
        self.queue({"action": "confirm", "story": "0,1"}, {"action": "assign", "story": "S1"},
                   {"action": "reverse", "story": "1", "note": "no"}, {"action": "asana-done", "story": "M1", "note": "keep"})
        self.assertEqual(self.podium("requests").splitlines(), ["ACT confirm 0", "LIST assign S1", "ACT asana-done M1 note=keep"])
        self.assertEqual(self.podium("requests"), "")
        self.assertEqual(self.cursor(), os.path.getsize(self.path("requests.jsonl")))
        self.assertNotIn("requestsSeen", self.state())

    def test_skips_what_the_watcher_already_printed(self):
        self.queue({"action": "assign", "story": "S1"})
        size = os.path.getsize(self.path("requests.jsonl"))
        self.podium("requests")
        self.queue({"action": "assign", "story": "S2"})
        with open(self.path("watcher.json"), "w") as f:
            json.dump({"at": 0, "offsets": {self.path("requests.jsonl"): os.path.getsize(self.path("requests.jsonl"))},
                       "since": {self.path("requests.jsonl"): size}}, f)
        self.queue({"action": "plan", "story": "M1"})
        self.assertEqual(self.podium("requests").splitlines(), ["LIST plan M1"])

    def test_moves_a_cursor_kept_in_podium_json_to_cursor_json(self):
        self.queue({"action": "assign", "story": "S1"})
        self.data["requestsSeen"] = os.path.getsize(self.path("requests.jsonl"))
        self.write()
        self.queue({"action": "plan", "story": "M1"}, {"action": "stop", "story": "M1"})
        self.assertEqual(self.podium("requests").splitlines(), ["LIST plan M1", "LIST stop M1"])
        self.assertEqual(self.cursor(), os.path.getsize(self.path("requests.jsonl")))
        self.assertNotIn("requestsSeen", self.state())

    def test_without_requests_starts_the_cursor_at_zero_and_waits_for_a_whole_line(self):
        self.podium("requests")
        self.assertEqual(self.cursor(), 0)
        with open(self.path("requests.jsonl"), "w") as f:
            f.write('{"action": "assign", "story": "S1"}\n{"action": "pl')
        self.assertEqual(self.podium("requests").splitlines(), ["LIST assign S1"])
        with open(self.path("requests.jsonl"), "a") as f:
            f.write('an", "story": "M1"}\n')
        self.assertEqual(self.podium("requests").splitlines(), ["LIST plan M1"])

    def test_a_truncated_file_is_read_from_the_start(self):
        with open(self.path("cursor.json"), "w") as f:
            json.dump({"requestsSeen": 9999}, f)
        self.queue({"action": "assign", "story": "S1"})
        self.assertEqual(self.podium("requests").splitlines(), ["LIST assign S1"])


if __name__ == "__main__":
    unittest.main()
