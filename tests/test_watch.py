"""Tests for the Podium watcher, run as `podium watch --once` against a temp run: the lines it prints for requests,
progress, the user's availability, Paseo agents, and another machine's saves pulled through a real sync."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import sync, watch  # noqa: E402
from podium_dashboard.state import Podium  # noqa: E402

REF = "refs/heads/podium-run/api"
DATA = {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"}, "needsYou": None,
        "epics": [{"id": "e", "milestones": [
            {"id": "M1", "status": "working", "phase": "build", "stories": [{"id": "S1", "status": "todo", "deps": []}]},
            {"id": "M2", "status": "todo", "phase": "plan", "stories": [{"id": "T1", "status": "todo", "deps": []}]}]}]}


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout


class Watcher(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        for k in ("PODIUM_DIR", "PODIUM_ME"):
            os.environ.pop(k, None)
        os.environ.update({"HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1", "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"),
                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.run_dir = self.run_at(os.path.join(self.tmp, "api", ".deep-plan"), DATA)
        self.human("available")

    def run_at(self, run_dir, data):
        os.makedirs(os.path.join(run_dir, "podium"), exist_ok=True)
        with open(os.path.join(run_dir, "podium", "podium.json"), "w") as f:
            json.dump(data, f)
        return run_dir

    def human(self, mode):
        with open(os.environ["PODIUM_HUMAN"], "w") as f:
            json.dump({"mode": mode, "until": "2099-01-01T00:00+00:00"}, f)

    def pod(self, *rel, run_dir=None):
        return os.path.join(run_dir or self.run_dir, "podium", *rel)

    def append(self, path, *lines):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.writelines(line + "\n" for line in lines)

    def start(self, *args, run_dir=None, me="bob"):
        w = subprocess.Popen([sys.executable, "-m", "podium_dashboard", "--dir", run_dir or self.run_dir, "watch", "--once", *args],
                             stdout=subprocess.PIPE, text=True, env={**os.environ, "PYTHONPATH": ROOT, "PODIUM_ME": me},
                             cwd=self.tmp)
        self.addCleanup(lambda: (w.kill(), w.wait(), w.stdout.close()))
        return w

    def started(self, run_dir=None):
        beat = self.pod("watcher.json", run_dir=run_dir)
        for _ in range(400):
            if os.path.exists(beat):
                return beat
            time.sleep(0.05)
        self.fail("the watcher never wrote its heartbeat")

    def lines(self, w):
        out, _ = w.communicate(timeout=30)
        return out.splitlines()


class Lines(Watcher):
    def requests(self):
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", self.run_dir, "requests"],
                           capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ROOT})
        return r.stdout.splitlines()

    def test_prints_a_request_queued_after_it_started_and_records_where_its_reading_started(self):
        self.assertEqual(self.requests(), [])
        path = self.pod("requests.jsonl")
        self.append(path, json.dumps({"action": "plan", "story": "M1"}))
        start = os.path.getsize(path)
        w = self.start()
        beat = self.started()
        self.append(path, json.dumps({"action": "confirm", "story": "t0", "note": "fine"}))
        self.assertEqual(self.lines(w), ["REQUEST confirm t0 note=fine"])
        with open(beat) as f:
            got = json.load(f)
        self.assertEqual((got["since"][path], got["offsets"][path]), (start, os.path.getsize(path)))
        self.assertEqual(self.requests(), ["LIST plan M1"])

    def test_prints_a_proceed_request_with_its_milestone_and_requests_lists_one_it_missed(self):
        self.assertEqual(self.requests(), [])
        path = self.pod("requests.jsonl")
        self.append(path, json.dumps({"action": "proceed", "story": "M1"}))
        w = self.start()
        self.started()
        self.append(path, json.dumps({"action": "proceed", "story": "M2"}))
        self.assertEqual(self.lines(w), ["REQUEST proceed M2"])
        self.assertEqual(self.requests(), ["LIST proceed M1"])

    def test_prints_a_share_request_with_no_id(self):
        w = self.start()
        self.started()
        self.append(self.pod("requests.jsonl"), json.dumps({"action": "share", "story": None}))
        self.assertEqual(self.lines(w), ["REQUEST share"])

    def test_prints_a_storys_committed_line_but_not_its_other_stages(self):
        progress = self.pod("stories", "M1", "S1.progress")
        self.append(progress, "2026-01-01T00:00:00+00:00 STARTED")
        w = self.start()
        self.started()
        self.append(progress, "2026-01-01T00:01:00+00:00 GREEN tests pass", "2026-01-01T00:02:00+00:00 COMMITTED abc1234")
        self.assertEqual(self.lines(w), ["PROGRESS S1 2026-01-01T00:02:00+00:00 COMMITTED abc1234"])

    def test_resuming_prints_a_progress_file_new_since_the_last_watcher_only_for_a_milestone_the_run_has(self):
        with open(self.pod("watcher.json"), "w") as f:
            json.dump({"at": time.time(), "offsets": {}, "mode": "available"}, f)
        self.append(self.pod("stories", "M9", "S1.progress"), "2026-01-01T00:01:00+00:00 COMMITTED forged")
        self.append(self.pod("stories", "M1", "S1.progress"), "2026-01-01T00:02:00+00:00 COMMITTED abc1234")
        self.assertEqual(self.lines(self.start()), ["PROGRESS S1 2026-01-01T00:02:00+00:00 COMMITTED abc1234"])

    def test_prints_the_users_availability_when_it_flipped_since_the_last_watcher(self):
        data = json.loads(json.dumps(DATA))
        data["epics"][0]["milestones"][0]["stories"][0]["status"] = "working"
        self.run_at(self.run_dir, data)
        with open(self.pod("watcher.json"), "w") as f:
            json.dump({"at": time.time(), "offsets": {}, "mode": "unavailable"}, f)
        self.assertEqual(self.lines(self.start()), ["HUMAN available"])

    def test_lapses_when_the_user_is_away_and_nothing_is_building(self):
        self.run_at(self.run_dir, {**DATA, "epics": []})
        self.human("unavailable")
        self.assertEqual(self.lines(self.start()), ["LAPSE unavailable, nothing building"])

    def test_follows_the_paseo_agents_of_every_milestone(self):
        data = json.loads(json.dumps(DATA))
        data["epics"][0]["milestones"][1]["stories"][0].update(status="working", agent={"backend": "paseo", "id": "agent-t1"})
        self.run_at(self.run_dir, data)
        self.human("unavailable")
        fake = os.path.join(self.tmp, "bin", "paseo")
        self.append(fake, "#!/bin/sh", "case \"$1\" in",
                    "  permit) echo '[{\"agentId\": \"agent-t1\", \"name\": \"Bash\"}]';;",
                    "  ls) echo '[{\"id\": \"agent-t1\", \"status\": \"idle\"}]';;", "esac")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        self.assertEqual(self.lines(self.start("--paseo", fake)), ["PERMISSION T1 Bash", "IDLE T1"])


class Synced(Watcher):
    def setUp(self):
        super().setUp()
        self.bare = os.path.join(self.tmp, "remote.git")
        git("init", "-q", "--bare", "-b", "main", self.bare)
        seed = os.path.join(self.tmp, "seed")
        git("init", "-q", "-b", "main", seed)
        self.append(os.path.join(seed, "README.md"), "api")
        git("add", "README.md", cwd=seed)
        git("commit", "-q", "-m", "init", cwd=seed)
        git("push", "-q", self.bare, "HEAD:refs/heads/main", cwd=seed)
        self.ann = self.machine("ann", DATA)
        self.assertRegex(sync.save(self.ann), r"^SAVED ")
        self.bob = self.machine("bob", None)
        self.assertRegex(sync.pull(self.bob), r"^PULLED ")

    def machine(self, name, data):
        clone = os.path.join(self.tmp, name)
        git("clone", "-q", self.bare, clone)
        run = self.run_at(os.path.join(clone, ".deep-plan"), {**(data or {}), "sync": {"enabled": True, "ref": REF}})
        os.environ["PODIUM_ME"] = name
        p = Podium(run)
        self.assertEqual(p.me, name)
        return p

    def tip(self):
        return git("--git-dir", self.bare, "rev-parse", REF).strip()[:7]

    def test_prints_another_machines_new_events_by_who_made_them(self):
        self.ann.milestone("M2")["owner"] = "ann"
        self.ann.save()
        self.ann.event("owner", "M2", owner="ann")
        self.ann.event("status", "M1", "S1", status="working")
        self.ann.event("status", "M1", "S1", status="done")
        self.assertRegex(sync.save(self.ann, "M2 owner"), r"^SAVED ")
        self.assertEqual(self.lines(self.start(run_dir=self.bob.root)), [f"SYNCED {self.tip()} ann: owner, status×2"])
        self.assertEqual(Podium(self.bob.root).milestone("M2").get("owner"), "ann")

    def test_tells_the_owner_who_looked_at_their_pr_and_nobody_else(self):
        self.ann.event("reviewed", "M2", repo="core", number=7, state="draft", owner="bob")
        self.ann.event("reviewed", "M1", number=3, state="draft", owner="cid")
        self.assertRegex(sync.save(self.ann, "reviewed"), r"^SAVED ")
        self.assertEqual(self.lines(self.start(run_dir=self.bob.root)),
                         [f"SYNCED {self.tip()} ann: reviewed×2", "REVIEWED M2 core#7 by=ann"])

    def test_names_the_save_when_it_brought_no_events_and_never_prints_the_progress_it_brought(self):
        self.append(self.pod("stories", "M1", "S1.progress", run_dir=self.ann.root), "2026-01-01T00:02:00+00:00 COMMITTED abc1234")
        self.ann.milestone("M2")["title"] = "Renamed"
        self.ann.save()
        self.assertRegex(sync.save(self.ann, "rename M2"), r"^SAVED ")
        self.assertEqual(self.lines(self.start(run_dir=self.bob.root)), [f"SYNCED {self.tip()} podium: rename M2"])
        self.assertTrue(os.path.exists(self.pod("stories", "M1", "S1.progress", run_dir=self.bob.root)))

    def test_prints_the_progress_logged_here_while_a_pull_ran_but_not_the_progress_it_brought(self):
        s1, s2 = (self.pod("stories", "M1", name, run_dir=self.bob.root) for name in ("S1.progress", "S2.progress"))
        self.append(self.pod("stories", "M1", "S1.progress", run_dir=self.ann.root), "2026-01-01T00:00:00+00:00 STARTED")
        self.assertRegex(sync.save(self.ann), r"^SAVED ")
        self.assertRegex(sync.pull(self.bob), r"^PULLED ")
        self.append(s2, "2026-01-01T00:00:00+00:00 STARTED")
        offsets, seen = watch.fresh(self.bob.dir)
        self.append(self.pod("stories", "M1", "S1.progress", run_dir=self.ann.root), "2026-01-01T00:03:00+00:00 COMMITTED ann")
        self.append(self.pod("stories", "M2", "T1.progress", run_dir=self.ann.root), "2026-01-01T00:04:00+00:00 FAILED ann")
        self.assertRegex(sync.save(self.ann), r"^SAVED ")
        self.append(s1, "2026-01-01T00:02:00+00:00 COMMITTED before")
        fetch = sync.Git.remote_tip

        def fetch_while_logging(g):
            self.append(s1, "2026-01-01T00:05:00+00:00 COMMITTED during")
            self.append(s2, "2026-01-01T00:05:00+00:00 FAILED during")
            return fetch(g)

        with unittest.mock.patch.object(sync.Git, "remote_tip", fetch_while_logging):
            printed = watch.pull(self.bob, offsets, seen)
        printed += [line for path in watch.watched(self.bob.dir) if os.path.exists(path)
                    for line in watch.news(path, offsets, seen, lambda path: True)]
        self.assertEqual([line for line in printed if not line.startswith("SYNCED ")],
                         ["PROGRESS S1 2026-01-01T00:02:00+00:00 COMMITTED before",
                          "PROGRESS S1 2026-01-01T00:05:00+00:00 COMMITTED during",
                          "PROGRESS S2 2026-01-01T00:05:00+00:00 FAILED during"])
        self.assertEqual(printed[2], f"SYNCED {self.tip()} podium: save")
        self.assertIn("COMMITTED ann", "".join(watch.lines_of(s1)))

    def test_after_a_save_merged_behind_it_prints_each_line_logged_here_once_and_none_it_brought(self):
        mine = self.pod("stories", "M1", "S1.progress", run_dir=self.bob.root)
        theirs = self.pod("stories", "M2", "T1.progress", run_dir=self.ann.root)
        self.ann.milestone("M1")["owner"], self.ann.milestone("M2")["owner"] = "bob", "ann"
        self.ann.save()
        self.append(self.pod("stories", "M1", "S1.progress", run_dir=self.ann.root), "2026-01-01T00:00:00+00:00 STARTED")
        self.append(theirs, "2026-01-01T00:00:00+00:00 STARTED")
        self.assertRegex(sync.save(self.ann), r"^SAVED ")
        self.assertRegex(sync.pull(self.bob), r"^PULLED ")
        w = self.start(run_dir=self.bob.root)
        self.started(run_dir=self.bob.root)
        self.append(mine, "2026-01-01T00:01:00+00:00 COMMITTED one")
        self.assertEqual(self.lines(w), ["PROGRESS S1 2026-01-01T00:01:00+00:00 COMMITTED one"])
        self.append(self.pod("stories", "M1", "S1.progress", run_dir=self.ann.root), "2026-01-01T00:02:00+00:00 GREEN ann")
        self.append(theirs, "2026-01-01T00:03:00+00:00 COMMITTED ann")
        self.assertRegex(sync.save(self.ann), r"^SAVED ")
        self.append(mine, "2026-01-01T00:04:00+00:00 COMMITTED two")
        self.assertRegex(sync.save(self.bob), r"^SAVED ")
        self.assertNotIn("GREEN ann", "".join(watch.lines_of(mine)))
        self.append(mine, "2026-01-01T00:05:00+00:00 COMMITTED three")
        self.assertEqual(self.lines(self.start(run_dir=self.bob.root)), ["PROGRESS S1 2026-01-01T00:04:00+00:00 COMMITTED two",
                                                                        "PROGRESS S1 2026-01-01T00:05:00+00:00 COMMITTED three"])

    def test_a_commit_another_machine_logs_for_a_story_of_yours_never_lands_here_nor_prints(self):
        os.environ["PODIUM_ME"] = "ann"
        self.ann.milestone("M1")["owner"], self.ann.milestone("M2")["owner"] = "ann", "bob"
        self.ann.save()
        mine, theirs = (self.pod("stories", *rel, run_dir=self.ann.root) for rel in (("M1", "S1.progress"), ("M2", "T1.progress")))
        self.append(mine, "2026-01-01T00:00:00+00:00 STARTED")
        self.assertRegex(sync.save(self.ann), r"^SAVED ")
        self.assertRegex(sync.pull(self.bob), r"^PULLED ")
        offsets, seen = watch.fresh(self.ann.dir)
        forged, built = (self.pod("stories", *rel, run_dir=self.bob.root) for rel in (("M1", "S1.progress"), ("M2", "T1.progress")))
        self.append(forged, "2026-01-01T00:09:00+00:00 COMMITTED forged")
        self.append(built, "2026-01-01T00:01:00+00:00 COMMITTED bob")
        self.assertRegex(sync.save(self.bob), r"^SAVED ")
        self.append(mine, "2026-01-01T00:02:00+00:00 GREEN ann")
        self.assertRegex(sync.save(self.ann), r"^SAVED ")
        self.append(forged, "2026-01-01T00:10:00+00:00 FAILED forged")
        self.assertRegex(sync.save(self.bob), r"^SAVED ")
        printed = watch.pull(self.ann, offsets, seen)
        printed += [line for path in watch.watched(self.ann.dir) if os.path.exists(path)
                    for line in watch.news(path, offsets, seen, lambda path: watch.built_here(self.ann.root, path))]
        self.assertEqual([line for line in printed if not line.startswith("SYNCED ")], [])
        self.assertEqual(watch.lines_of(mine), ["2026-01-01T00:00:00+00:00 STARTED", "2026-01-01T00:02:00+00:00 GREEN ann"])
        self.assertEqual(watch.lines_of(theirs), ["2026-01-01T00:01:00+00:00 COMMITTED bob"])
        self.assertIn("COMMITTED forged", "".join(watch.lines_of(forged)))

    def test_a_progress_file_of_a_milestone_the_run_lacks_is_not_built_here(self):
        os.environ["PODIUM_ME"] = "ann"
        self.assertTrue(watch.built_here(self.ann.root, self.pod("stories", "M1", "S1.progress", run_dir=self.ann.root)))
        self.assertFalse(watch.built_here(self.ann.root, self.pod("stories", "M9", "S1.progress", run_dir=self.ann.root)))

    def test_skips_a_pull_while_another_podium_command_holds_the_lock(self):
        self.assertFalse(watch.busy(self.bob))
        with self.bob.locked():
            self.assertTrue(watch.busy(self.bob))
        self.assertFalse(watch.busy(self.bob))


if __name__ == "__main__":
    unittest.main()
