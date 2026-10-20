"""Tests for two people sharing one run: who `me` is, each person's own active, needsYou and assumptions, milestone
ownership (claim, release, require_owner), and both through a real sync between two clones and a bare remote."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import sync  # noqa: E402
from podium_dashboard.state import Podium, rebase, require_owner  # noqa: E402

DATA = {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"}, "needsYou": {"reason": "old"},
        "assumptions": [{"question": "q0", "choice": "c", "why": "w", "status": "open"}],
        "epics": [{"id": "e", "milestones": [
            {"id": "M1", "status": "working", "phase": "build",
             "stories": [{"id": "S1", "status": "todo", "deps": []}, {"id": "S2", "status": "todo", "deps": ["S1"]}]},
            {"id": "M2", "status": "working", "phase": "build", "stories": [{"id": "S1", "status": "done", "deps": []},
                                                                          {"id": "S2", "status": "todo", "deps": ["S1"]}]},
            {"id": "M3", "status": "todo", "phase": "plan", "stories": []}]}]}


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        for k in ("PODIUM_DIR", "PODIUM_ME", "PODIUM_STORY", "PODIUM_MILESTONE"):
            os.environ.pop(k, None)
        os.environ.update({"HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.path.join(self.tmp, "gitconfig"),
                           "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"), "USER": "u",
                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

    def run_at(self, run_dir, data=DATA):
        os.makedirs(os.path.join(run_dir, "podium"), exist_ok=True)
        with open(os.path.join(run_dir, "podium", "podium.json"), "w") as f:
            json.dump(data, f)
        return run_dir

    def podium(self, run_dir, *args, me="a", code=0):
        env = {**os.environ, "PYTHONPATH": ROOT, **({"PODIUM_ME": me} if me else {})}
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", *(["--dir", run_dir] if run_dir else []), *args],
                           capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def state(self, run_dir):
        with open(os.path.join(run_dir, "podium", "podium.json")) as f:
            return json.load(f)

    def events(self, run_dir):
        try:
            with open(os.path.join(run_dir, "podium", "events.jsonl")) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def owners(self, data):
        return {m["id"]: m.get("owner") for e in data["epics"] for m in e["milestones"]}

    def as_(self, name, run_dir):
        os.environ["PODIUM_ME"] = name
        p = Podium(run_dir)
        self.assertEqual(p.me, name)
        return p


class Identity(Case):
    def whoami(self, *args, me=None, code=0):
        return self.podium(None, "whoami", *args, me=me, code=code).stdout

    def test_without_a_name_or_an_email_it_is_the_login(self):
        self.assertEqual(self.whoami(), "u\n")

    def test_the_local_part_of_the_git_email_beats_the_login(self):
        git("config", "--global", "user.email", "ann@t")
        self.assertEqual(self.whoami(), "ann\n")

    def test_a_name_set_with_whoami_beats_the_email_and_stays(self):
        git("config", "--global", "user.email", "ann@t")
        self.assertEqual(self.whoami("bo"), "bo\n")
        self.assertEqual(self.whoami(), "bo\n")
        with open(os.environ["PODIUM_HUMAN"]) as f:
            self.assertEqual(json.load(f)["me"], "bo")

    def test_podium_me_beats_everything_and_says_so(self):
        self.whoami("bo")
        self.assertEqual(self.whoami(me="cy"), "cy ($PODIUM_ME)\n")

    def test_whoami_takes_one_name_at_most(self):
        self.whoami("a", "b", code=1)


class PersonalState(Case):
    def test_a_run_without_people_or_sync_keeps_reading_and_writing_the_top_level(self):
        run = self.run_at(os.path.join(self.tmp, "run"))
        self.podium(run, "set", "me", "needsYou=x")
        self.podium(run, "set", ".", "active.milestone=M2")
        self.podium(run, "assume", "q", "c", "w")
        data = self.state(run)
        self.assertNotIn("people", data)
        self.assertEqual((data["needsYou"], data["active"]["milestone"], len(data["assumptions"])), ("x", "M2", 2))

    def test_reading_falls_back_to_the_top_level_key_the_person_lacks(self):
        run = self.run_at(os.path.join(self.tmp, "run"), {**DATA, "people": {"a": {"active": {"milestone": "M2"}}}})
        a, b = self.as_("a", run), self.as_("b", run)
        self.assertEqual((a.active(), a.needs_you(), len(a.assumptions_list())), ({"milestone": "M2"}, {"reason": "old"}, 1))
        self.assertEqual((b.active()["milestone"], b.milestone()["id"]), ("M1", "M1"))
        self.assertEqual(self.podium(run, "ready").stdout, "S2\n")
        self.assertEqual(self.podium(run, "ready", me="b").stdout, "S1\n")
        self.assertEqual(json.loads(self.podium(run, "get", "milestone:").stdout)["id"], "M2")

    def test_set_me_and_set_dot_write_the_persons_own_keys_in_a_run_with_people(self):
        run = self.run_at(os.path.join(self.tmp, "run"), {**DATA, "people": {}})
        self.podium(run, "set", "me", "needsYou={\"reason\": \"mine\"}")
        self.podium(run, "set", ".", "active.milestone=M2", "dispatcher=agent", me="b")
        data = self.state(run)
        self.assertEqual(data["people"], {"a": {"needsYou": {"reason": "mine"}}, "b": {"active": {"milestone": "M2"}}})
        self.assertEqual((data["needsYou"], data["active"]["milestone"], data["dispatcher"]), ({"reason": "old"}, "M1", "agent"))
        self.assertEqual(json.loads(self.podium(run, "get", "me").stdout), {"needsYou": {"reason": "mine"}})

    def test_a_synced_run_writes_the_persons_own_keys_before_it_has_people(self):
        run = self.run_at(os.path.join(self.tmp, "run"), {**DATA, "sync": {"enabled": True, "remote": "/nowhere"}})
        self.podium(run, "set", ".", "needsYou=null")
        self.assertEqual(self.state(run)["people"], {"a": {"needsYou": None}})
        self.assertEqual(self.state(run)["needsYou"], {"reason": "old"})

    def test_assumptions_are_the_persons_own_once_they_made_one(self):
        run = self.run_at(os.path.join(self.tmp, "run"), {**DATA, "people": {}})
        self.assertEqual(self.podium(run, "assume", "q", "c", "w", "--story", "S1").stdout, "assumption 0\n")
        self.assertEqual(self.podium(run, "assumptions").stdout, "0 [M1/S1] q → c (w)\nt0 [] q0 → c (w)\n")
        self.assertEqual(self.podium(run, "assumptions", me="b").stdout, "t0 [] q0 → c (w)\n")
        self.podium(run, "settle", "0", "confirmed")
        self.podium(run, "set", ".", "assumptions.0.why=w2")
        data = self.state(run)
        self.assertEqual((data["people"]["a"]["assumptions"][0]["status"], data["people"]["a"]["assumptions"][0]["why"]),
                         ("confirmed", "w2"))
        self.assertEqual(data["assumptions"][0]["status"], "open")

    def test_settle_reaches_the_persons_own_and_the_older_top_level_assumptions(self):
        run = self.run_at(os.path.join(self.tmp, "run"), {**DATA, "people": {}})
        self.podium(run, "assume", "q", "c", "w")
        self.assertEqual(self.podium(run, "settle", "0,t0", "reversed").stdout, "2 reversed\n")
        data = self.state(run)
        self.assertEqual((data["people"]["a"]["assumptions"][0]["status"], data["assumptions"][0]["status"]),
                         ("reversed", "reversed"))
        self.assertEqual(self.podium(run, "assumptions").stdout, "")
        self.podium(run, "settle", "t1", "confirmed", code=1)

    def test_build_all_set_on_the_project_goes_to_the_persons_active_milestone(self):
        run = self.run_at(os.path.join(self.tmp, "run"), {**DATA, "people": {"a": {"active": {"milestone": "M2"}}}})
        self.podium(run, "set", ".", "buildAll=true")
        self.assertEqual({m["id"]: m.get("buildAll") for m in self.state(run)["epics"][0]["milestones"]},
                         {"M1": None, "M2": True, "M3": None})

    def test_status_shows_the_persons_active_each_persons_active_and_the_owners(self):
        data = json.loads(json.dumps(DATA))
        data["people"] = {"a": {"active": {"milestone": "M2"}, "needsYou": None}, "b": {"active": {"milestone": "M1"}}}
        data["epics"][0]["milestones"][1]["owner"] = "a"
        run = self.run_at(os.path.join(self.tmp, "run"), data)
        out = self.podium(run, "status", "--all").stdout
        self.assertIn(" · active -/M2 · ", out)
        self.assertNotIn("needsYou", out)
        self.assertIn("people: a → M2 · b → M1\n", out)
        self.assertIn("epic e: 2 working, 1 todo · owners M2 a\n", out)
        self.assertIn("  M2 working build  (2 stories) · owner a\n", out)
        self.assertIn("buildAll off · owner a\n", out)

    def test_rebase_merges_an_object_both_sides_added(self):
        merged = rebase({}, {"people": {"a": {"active": 1}}}, {"people": {"b": {"active": 2}}})
        self.assertEqual(merged, {"people": {"a": {"active": 1}, "b": {"active": 2}}})


class Ownership(Case):
    def setUp(self):
        super().setUp()
        self.run = self.run_at(os.path.join(self.tmp, "run"))

    def test_claim_makes_the_milestone_yours_with_an_owner_event(self):
        self.assertEqual(self.podium(self.run, "claim", "M1").stdout, "claimed M1\n")
        self.assertEqual(self.owners(self.state(self.run))["M1"], "a")
        self.assertEqual([(e["type"], e["milestone"], e["owner"]) for e in self.events(self.run)], [("owner", "M1", "a")])

    def test_claiming_your_own_milestone_again_changes_nothing(self):
        self.podium(self.run, "claim", "M1")
        self.podium(self.run, "claim", "M1")
        self.assertEqual(len(self.events(self.run)), 1)

    def test_claiming_someone_elses_milestone_is_refused(self):
        self.podium(self.run, "claim", "M1")
        r = self.podium(self.run, "claim", "M1", me="b", code=1)
        self.assertEqual(r.stderr, "podium: milestone M1 is owned by a\n")
        self.assertEqual(self.owners(self.state(self.run))["M1"], "a")

    def test_force_takes_it_over_with_a_handover_event(self):
        self.podium(self.run, "claim", "M1")
        self.podium(self.run, "claim", "M1", "--force", me="b")
        self.assertEqual(self.owners(self.state(self.run))["M1"], "b")
        handover = self.events(self.run)[1]
        self.assertEqual((handover["type"], handover["from"], handover["to"]), ("handover", "a", "b"))
        self.assertEqual(self.events(self.run)[2]["owner"], "b")

    def test_release_gives_up_your_milestone_and_refuses_someone_elses(self):
        self.podium(self.run, "claim", "M1")
        self.assertEqual(self.podium(self.run, "release", "M1", me="b", code=1).stderr, "podium: milestone M1 is owned by a\n")
        self.assertEqual(self.podium(self.run, "release", "M1").stdout, "released M1\n")
        self.assertNotIn("owner", self.state(self.run)["epics"][0]["milestones"][0])
        self.assertEqual(self.events(self.run)[-1]["owner"], None)

    def test_an_unknown_milestone_is_refused(self):
        self.podium(self.run, "claim", "M9", code=1)

    def test_owner_events_are_major_for_sync(self):
        self.assertTrue(sync.is_major(Podium(self.run), {"type": "owner", "owner": "a"}))


class RequireOwner(Case):
    def require(self, data, me, mid="M1", force=False, claim=True):
        p = self.as_(me, self.run_at(os.path.join(self.tmp, "run"), data))
        require_owner(p, mid, force, claim)
        return p

    def owned(self, **owners):
        data = json.loads(json.dumps(DATA))
        for m in data["epics"][0]["milestones"]:
            if m["id"] in owners:
                m["owner"] = owners[m["id"]]
        return data

    def refusal(self, *args, **kwargs):
        with self.assertRaises(SystemExit) as cm:
            self.require(*args, **kwargs)
        return cm.exception.code

    def test_a_single_person_run_without_owners_or_sync_is_unchanged(self):
        self.require(DATA, "a")
        self.require(DATA, "a", mid=None)

    def test_someone_elses_milestone_is_refused_and_your_own_allowed(self):
        self.assertEqual(self.refusal(self.owned(M1="b"), "a"), "podium: milestone M1 is owned by b")
        self.require(self.owned(M1="a"), "a")

    def test_an_unowned_milestone_beside_owned_ones_is_free_while_the_run_does_not_sync(self):
        self.require(self.owned(M2="b"), "a")

    def test_claim_false_lets_a_synced_runs_unowned_milestone_pass_unclaimed(self):
        p = self.require({**DATA, "sync": {"enabled": True}}, "a", claim=False)
        self.assertEqual((self.owners(self.state(p.root))["M1"], self.events(p.root)), (None, []))

    def test_claim_false_still_refuses_someone_elses_milestone(self):
        self.assertEqual(self.refusal({**self.owned(M1="b"), "sync": {"enabled": True}}, "a", claim=False),
                         "podium: milestone M1 is owned by b")

    def test_force_skips_the_check(self):
        self.require(self.owned(M1="b"), "a", force=True)


class TwoMachines(Case):
    """Two clones of one repo, a and b, syncing one run through a bare remote."""

    def setUp(self):
        super().setUp()
        self.bare = os.path.join(self.tmp, "remote.git")
        git("init", "-q", "--bare", "-b", "main", self.bare)
        seed = os.path.join(self.tmp, "seed")
        git("init", "-q", "-b", "main", seed)
        with open(os.path.join(seed, "README.md"), "w") as f:
            f.write("api\n")
        git("add", "README.md", cwd=seed)
        git("commit", "-q", "-m", "init", cwd=seed)
        git("push", "-q", self.bare, "HEAD:refs/heads/main", cwd=seed)
        self.a, self.b = self.machine("a", DATA), self.machine("b", None)

    def watching(self, run):
        with open(os.path.join(run, "podium", "watcher.json"), "w") as f:
            json.dump({"pid": 1, "at": time.time()}, f)

    def machine(self, name, data):
        clone = os.path.join(self.tmp, name)
        git("clone", "-q", self.bare, clone)
        run = self.run_at(os.path.join(clone, ".deep-plan"), {**(data or {}), "sync": {"enabled": True, "ref": "refs/heads/podium"}})
        p = Podium(run)
        self.assertRegex(sync.save(p) if data else sync.pull(p), r"^(SAVED|PULLED) ")
        return run

    def with_launch(self):
        """Give the run an extension whose `launch <milestone>` changes the milestone after require_owner, as an
        orchestrator's verbs do, and share it with b."""
        ext = os.path.join(self.tmp, "ext.py")
        with open(ext, "w") as f:
            f.write("from podium_dashboard.state import require_owner\n\n\n"
                    "def launch(p, args):\n"
                    "    require_owner(p, args[0])\n"
                    "    p.milestone(args[0])['launched'] = p.me\n"
                    "    p.save()\n"
                    "    print('launched', args[0])\n\n\n"
                    "COMMANDS = {'launch': launch}\n")
        self.podium(self.a, "init", "--name", "o", "--command", "/o", "--extension", ext, me="a")
        self.assertRegex(self.podium(self.a, "sync", "save", me="a").stdout, r"^SAVED ")
        self.assertRegex(self.podium(self.b, "sync", "pull", me="b").stdout, r"^PULLED ")

    def remote_state(self):
        return json.loads(git("--git-dir", self.bare, "show", "refs/heads/podium:podium/podium.json"))

    def remote_events(self):
        out = git("--git-dir", self.bare, "show", "refs/heads/podium:podium/events.jsonl")
        return [json.loads(line) for line in out.splitlines()]

    def test_each_claims_a_milestone_and_both_people_survive_the_merge(self):
        self.podium(self.a, "claim", "M1", me="a")
        self.podium(self.b, "claim", "M2", me="b")
        self.podium(self.a, "set", "me", "active.milestone=M1", me="a")
        self.podium(self.b, "set", "me", "active.milestone=M2", me="b")
        self.assertRegex(self.podium(self.a, "sync", "save", me="a").stdout, r"^SAVED ")
        self.assertRegex(self.podium(self.b, "sync", "save", me="b").stdout, r"^SAVED ")
        self.assertRegex(self.podium(self.a, "sync", "pull", me="a").stdout, r"^PULLED ")
        for run in (self.a, self.b):
            data = self.state(run)
            self.assertEqual(data["people"], {"a": {"active": {"milestone": "M1"}}, "b": {"active": {"milestone": "M2"}}})
            self.assertEqual(self.owners(data), {"M1": "a", "M2": "b", "M3": None})
            self.assertIn("people: a → M1 · b → M2\n", self.podium(run, "status").stdout)
        self.assertEqual(self.podium(self.a, "ready", me="a").stdout, "S1\n")
        self.assertEqual(self.podium(self.a, "ready", me="b").stdout, "S2\n")

    def test_claiming_a_milestone_whose_claim_reached_the_remote_is_refused(self):
        self.podium(self.a, "claim", "M1", me="a")
        r = self.podium(self.b, "claim", "M1", me="b", code=1)
        self.assertEqual(r.stderr, "podium: milestone M1 is owned by a\n")
        self.assertEqual(self.owners(self.state(self.b))["M1"], "a")

    def test_force_hands_a_milestone_over_through_the_remote(self):
        self.podium(self.a, "claim", "M1", me="a")
        self.podium(self.b, "claim", "M1", "--force", me="b")
        self.assertRegex(self.podium(self.a, "sync", "pull", me="a").stdout, r"^PULLED ")
        self.assertEqual(self.owners(self.state(self.a))["M1"], "b")
        self.assertIn(("handover", "a", "b"), [(e["type"], e.get("from"), e.get("to")) for e in self.remote_events()])

    def test_two_claims_racing_for_one_milestone_leave_the_first_to_reach_the_remote(self):
        self.podium(self.b, "set", "me", "needsYou=busy", me="b")
        self.watching(self.b)  # b's pull before its claim keeps its state, so the claim races a's
        self.podium(self.a, "claim", "M3", me="a")
        r = self.podium(self.b, "claim", "M3", me="b", code=1)
        self.assertEqual(r.stderr, "podium: milestone M3 is owned by a\n")
        self.podium(self.a, "sync", "pull", me="a")
        self.podium(self.b, "sync", "pull", me="b")
        for run in (self.a, self.b):
            self.assertEqual(self.owners(self.state(run))["M3"], "a")
            self.assertEqual([e["owner"] for e in self.events(run) if e["type"] == "owner"], ["a"])
        self.assertEqual(self.state(self.a)["people"], {"b": {"needsYou": "busy"}})

    def test_a_verb_changing_an_unowned_milestone_claims_it_pushes_the_claim_and_goes_on(self):
        self.with_launch()
        r = self.podium(self.a, "launch", "M3", me="a")
        self.assertEqual(r.stdout.splitlines()[:2], ["claimed M3", "launched M3"])
        self.assertEqual(self.state(self.a)["epics"][0]["milestones"][2]["launched"], "a")
        self.assertEqual(self.owners(self.remote_state())["M3"], "a")
        self.assertIn(("owner", "M3", "a"), [(e["type"], e.get("milestone"), e.get("owner")) for e in self.remote_events()])

    def test_a_verb_on_a_milestone_another_clone_claimed_meanwhile_is_refused(self):
        self.with_launch()
        self.podium(self.a, "launch", "M3", me="a")
        r = self.podium(self.b, "launch", "M3", me="b", code=1)
        self.assertEqual((r.stdout, r.stderr), ("", "podium: milestone M3 is owned by a\n"))
        self.assertEqual(self.state(self.b)["epics"][0]["milestones"][2]["launched"], "a")

    def test_a_verb_whose_auto_claim_loses_the_race_is_refused_and_changes_nothing(self):
        self.with_launch()
        self.podium(self.b, "set", "me", "needsYou=busy", me="b")
        self.watching(self.b)  # b's pull before its claim keeps its state, so the claim races a's
        self.podium(self.a, "launch", "M3", me="a")
        r = self.podium(self.b, "launch", "M3", me="b", code=1)
        self.assertEqual(r.stderr, "podium: milestone M3 is owned by a\n")
        self.assertNotIn("launched M3", r.stdout)
        b = self.state(self.b)["epics"][0]["milestones"][2]
        self.assertEqual((b["owner"], b.get("launched")), ("a", "a"))
        self.assertEqual(self.owners(self.remote_state())["M3"], "a")


if __name__ == "__main__":
    unittest.main()
