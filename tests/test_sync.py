"""Tests for `podium sync`: the run state saved to a git ref and pulled back, between real clones and a bare remote."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import sync  # noqa: E402
from podium_dashboard.state import Podium  # noqa: E402

REF = "refs/heads/podium"
DATA = {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"}, "needsYou": None,
        "epics": [{"id": "e", "milestones": [
            {"id": "M1", "status": "working", "phase": "build", "stories": [{"id": "S1", "status": "todo", "deps": []}]},
            {"id": "M2", "status": "todo", "phase": "plan", "stories": [{"id": "S1", "status": "todo", "deps": []}]}]}]}


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout


class SyncCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.pop("PODIUM_DIR", None)
        os.environ.update({"HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1", "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"),
                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.bare = os.path.join(self.tmp, "remote.git")
        git("init", "-q", "--bare", "-b", "main", self.bare)
        seed = os.path.join(self.tmp, "seed")
        git("init", "-q", "-b", "main", seed)
        self.write(os.path.join(seed, "README.md"), "api\n")
        git("add", "README.md", cwd=seed)
        git("commit", "-q", "-m", "init", cwd=seed)
        git("push", "-q", self.bare, "HEAD:refs/heads/main", cwd=seed)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def clone(self, name):
        path = os.path.join(self.tmp, name)
        git("clone", "-q", self.bare, path)
        return path

    def run_in(self, parent, data=DATA, **sync_block):
        run = os.path.join(parent, ".deep-plan")
        block = {"enabled": True, **sync_block}
        self.write(os.path.join(run, "podium", "podium.json"), json.dumps({**(data or {}), "sync": block}))
        return Podium(run)

    def machine(self, name):
        """A clone whose run dir syncs: the first saves its state, the others pull it."""
        first = not self.remote_tip()
        p = self.run_in(self.clone(name), DATA if first else None)
        self.assertRegex(sync.save(p) if first else sync.pull(p), r"^(SAVED|PULLED) ")
        return p

    def remote_tip(self):
        return git("--git-dir", self.bare, "for-each-ref", "--format=%(objectname)", REF).strip() or None

    def remote_files(self):
        return git("--git-dir", self.bare, "ls-tree", "-r", "--name-only", REF).split()

    def remote_file(self, rel):
        return git("--git-dir", self.bare, "show", f"{REF}:{rel}")

    def set_status(self, p, mid, status):
        p.milestone(mid)["status"] = status
        p.save()

    def append(self, p, rel, *lines):
        with open(os.path.join(p.dir, rel), "a") as f:
            f.writelines(line + "\n" for line in lines)


class Save(SyncCase):
    def test_save_commits_the_run_state_onto_the_ref_and_leaves_the_checkout_alone(self):
        repo = self.clone("a")
        p = self.run_in(repo)
        self.append(p, "events.jsonl", json.dumps({"at": "2026-10-20T10:00:00+00:00", "type": "status"}))
        self.write(os.path.join(p.dir, "stories", "M1", "S1.progress"), "2026-10-20T10:00:00+00:00 RED x\n")
        head, before = git("rev-parse", "HEAD", cwd=repo), git("status", "--porcelain", cwd=repo)
        out = sync.save(p, "first")
        self.assertRegex(out, r"^SAVED [0-9a-f]{7} first$")
        self.assertEqual(self.remote_files(), ["podium/events.jsonl", "podium/podium.json", "podium/stories/M1/S1.progress"])
        self.assertEqual(git("rev-parse", "HEAD", cwd=repo), head)
        self.assertEqual(git("status", "--porcelain", cwd=repo), before)
        self.assertEqual(git("diff", "--cached", "--name-only", cwd=repo), "")

    def test_the_sync_block_stays_out_of_the_synced_podium_json(self):
        p = self.run_in(self.clone("a"))
        sync.save(p)
        self.assertNotIn("sync", json.loads(self.remote_file("podium/podium.json")))
        self.assertEqual(json.loads(self.remote_file("podium/podium.json"))["epics"], DATA["epics"])

    def test_a_second_save_with_nothing_new_is_unchanged(self):
        p = self.run_in(self.clone("a"))
        sync.save(p)
        tip = self.remote_tip()
        self.assertEqual(sync.save(p), "UNCHANGED")
        self.assertEqual(self.remote_tip(), tip)

    def test_the_machines_own_files_never_sync_even_when_included(self):
        p = self.run_in(self.clone("a"), include=["podium/**"])
        for name in ("cursor.json", "requests.jsonl", "watcher.json", "server.log", "podium.json.1.tmp"):
            self.write(os.path.join(p.dir, name), "{}\n")
        sync.save(p)
        self.assertEqual(self.remote_files(), ["podium/podium.json"])

    def test_include_syncs_planning_docs_and_exclude_keeps_files_out(self):
        p = self.run_in(self.clone("a"), include=["podium/podium.json", "docs/*.md"], exclude=["docs/draft-*"])
        self.write(os.path.join(p.root, "docs", "plan.md"), "# plan\n")
        self.write(os.path.join(p.root, "docs", "draft-idea.md"), "# idea\n")
        sync.save(p)
        self.assertEqual(self.remote_files(), ["docs/plan.md", "podium/podium.json"])

    def reject_pushes(self, times):
        hook = os.path.join(self.bare, "hooks", "pre-receive")
        self.write(hook, textwrap.dedent(f"""\
            #!/bin/sh
            n=$(cat rejected 2>/dev/null || echo 0)
            [ "$n" -ge {times} ] && exit 0
            echo $((n + 1)) > rejected
            exit 1
        """))
        os.chmod(hook, 0o755)

    def test_a_rejected_push_is_retried(self):
        p = self.run_in(self.clone("a"))
        self.reject_pushes(1)
        self.assertRegex(sync.save(p, "x"), r"^SAVED [0-9a-f]{7} x$")
        self.assertEqual(self.remote_tip(), git("rev-parse", REF, cwd=p.root).strip())

    def test_a_push_rejected_every_time_is_saved_here_only(self):
        p = self.run_in(self.clone("a"))
        self.reject_pushes(99)
        self.assertRegex(sync.save(p, "x"), r"^SAVED [0-9a-f]{7} x \(not pushed: push rejected three times\)$")
        self.assertIsNone(self.remote_tip())

    def test_sync_off_saves_and_pulls_nothing(self):
        p = self.run_in(self.clone("a"), enabled=False)
        self.assertEqual((sync.save(p), sync.pull(p)), ("OFF", "OFF"))
        self.assertIsNone(self.remote_tip())
        self.assertEqual(git("for-each-ref", REF, cwd=p.root), "")

    def test_a_run_outside_any_repo_is_off_with_a_remote_name(self):
        p = self.run_in(os.path.join(self.tmp, "plain"))
        self.assertEqual((sync.save(p), sync.pull(p)), ("OFF (not in a git repo)", "OFF (not in a git repo)"))

    def test_a_run_outside_any_repo_syncs_through_a_url(self):
        a = self.run_in(os.path.join(self.tmp, "plain-a"), remote=self.bare)
        self.assertRegex(sync.save(a), r"^SAVED ")
        b = self.run_in(os.path.join(self.tmp, "plain-b"), None, remote=self.bare)
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.data["epics"], DATA["epics"])
        self.assertEqual(b.data["sync"]["remote"], self.bare)

    def test_save_while_the_remote_is_out_of_reach_commits_here_and_says_so(self):
        p = self.run_in(self.clone("a"), remote="nowhere")
        self.assertRegex(sync.save(p, "x"), r"^SAVED [0-9a-f]{7} x \(not pushed: .+\)$")
        self.assertTrue(git("for-each-ref", REF, cwd=p.root))


class Pull(SyncCase):
    def test_pull_on_a_second_clone_restores_the_run_state_and_keeps_its_sync_block(self):
        a = self.machine("a")
        self.append(a, "events.jsonl", json.dumps({"at": "2026-10-20T10:00:00+00:00", "type": "status"}))
        sync.save(a)
        b = self.run_in(self.clone("b"), None, remote="origin")
        self.assertEqual(sync.pull(b), f"PULLED {self.remote_tip()[:7]}")
        self.assertEqual(self.read(os.path.join(b.dir, "events.jsonl")), self.read(os.path.join(a.dir, "events.jsonl")))
        self.assertEqual(b.data["epics"], DATA["epics"])
        self.assertEqual(b.data["sync"], {"enabled": True, "remote": "origin"})
        self.assertEqual(sync.pull(b), "UP-TO-DATE")

    def test_pull_deletes_a_synced_file_the_remote_no_longer_has(self):
        a = self.machine("a")
        self.write(os.path.join(a.dir, "stories", "M1", "S1.progress"), "2026-10-20T10:00:00+00:00 RED x\n")
        sync.save(a)
        b = self.machine("b")
        os.remove(os.path.join(a.dir, "stories", "M1", "S1.progress"))
        sync.save(a)
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertFalse(os.path.exists(os.path.join(b.dir, "stories", "M1", "S1.progress")))
        self.assertTrue(os.path.exists(b.path))

    def test_pull_keeps_files_this_machine_never_synced_and_files_the_remote_stopped_syncing(self):
        a = self.machine("a")
        self.write(os.path.join(a.dir, "stories", "M1", "S1.progress"), "2026-10-20T10:00:00+00:00 RED x\n")
        sync.save(a)
        b = self.machine("b")
        self.write(os.path.join(a.dir, "scratch.md"), "mine\n")
        b.data["sync"]["include"] = ["podium/podium.json", "podium/events.jsonl"]
        b.save()
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertEqual(self.read(os.path.join(a.dir, "scratch.md")), "mine\n")
        self.assertTrue(os.path.exists(os.path.join(a.dir, "stories", "M1", "S1.progress")))
        self.assertEqual(a.data["sync"], {"enabled": True, "include": ["podium/podium.json", "podium/events.jsonl"]})

    def test_include_and_exclude_set_on_one_machine_reach_the_other(self):
        a, b = self.machine("a"), self.machine("b")
        a.data["sync"].update(include=["podium/podium.json", "docs/*.md"], exclude=["docs/draft-*"])
        a.save()
        self.write(os.path.join(a.root, "docs", "plan.md"), "# plan\n")
        self.write(os.path.join(a.root, "docs", "draft-idea.md"), "# idea\n")
        sync.save(a)
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.data["sync"], {"enabled": True, "include": ["podium/podium.json", "docs/*.md"],
                                          "exclude": ["docs/draft-*"]})
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md")), "# plan\n")
        self.assertFalse(os.path.exists(os.path.join(b.root, "docs", "draft-idea.md")))

    def test_widening_exclude_stops_syncing_a_file_without_deleting_it_elsewhere(self):
        a = self.machine("a")
        self.write(os.path.join(a.dir, "stories", "M1", "S1.progress"), "2026-10-20T10:00:00+00:00 RED x\n")
        sync.save(a)
        b = self.machine("b")
        b.data["sync"]["exclude"] = ["*.progress"]
        b.save()
        sync.save(b)
        self.assertNotIn("podium/stories/M1/S1.progress", self.remote_files())
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertTrue(os.path.exists(os.path.join(a.dir, "stories", "M1", "S1.progress")))

    def test_enabled_remote_and_ref_stay_with_their_machine(self):
        a = self.run_in(self.clone("a"), remote="origin", ref=REF)
        sync.save(a)
        b = self.run_in(self.clone("b"), None, remote=self.bare)
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertNotIn("sync", json.loads(self.remote_file("podium/podium.json")))
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertEqual(a.milestone("M2")["status"], "working")
        self.assertEqual(a.data["sync"], {"enabled": True, "remote": "origin", "ref": REF})
        self.assertEqual(b.data["sync"], {"enabled": True, "remote": self.bare})

    def test_pull_keeps_changes_made_since_the_last_save(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.set_status(b, "M2", "working")
        self.assertEqual(sync.pull(b), "KEPT this machine has changes since its last save")
        self.assertEqual(b.milestone("M1")["status"], "working")

    def test_pull_keeps_the_state_while_the_watcher_runs(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.write(os.path.join(b.dir, "watcher.json"), json.dumps({"pid": 1, "at": time.time()}))
        self.assertEqual(sync.pull(b), "KEPT the watcher is running")
        self.write(os.path.join(b.dir, "watcher.json"), json.dumps({"pid": 1, "at": time.time() - 600}))
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.milestone("M1")["status"], "done")

    def test_save_behind_the_remote_with_nothing_new_says_behind(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.assertEqual(sync.save(b), "BEHIND")


class Merge(SyncCase):
    def test_two_machines_changing_different_milestones_keep_both_changes(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual((b.milestone("M1")["status"], b.milestone("M2")["status"]), ("done", "working"))
        self.assertEqual(b.data["sync"], {"enabled": True})
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertEqual((a.milestone("M1")["status"], a.milestone("M2")["status"]), ("done", "working"))
        merge = git("--git-dir", self.bare, "rev-list", "--parents", "-n", "1", REF).split()
        self.assertEqual(len(merge), 3)

    def test_a_file_one_machine_deleted_and_the_other_left_alone_is_deleted_by_the_merge(self):
        a = self.machine("a")
        self.write(os.path.join(a.dir, "stories", "M1", "S1.progress"), "2026-10-20T10:00:00+00:00 RED x\n")
        sync.save(a)
        b = self.machine("b")
        os.remove(os.path.join(a.dir, "stories", "M1", "S1.progress"))
        sync.save(a)
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertFalse(os.path.exists(os.path.join(b.dir, "stories", "M1", "S1.progress")))
        self.assertNotIn("podium/stories/M1/S1.progress", self.remote_files())

    def test_events_both_machines_appended_become_their_union_in_time_order(self):
        a = self.machine("a")
        self.append(a, "events.jsonl", json.dumps({"at": "2026-10-20T09:00:00+00:00", "type": "planned"}))
        sync.save(a)
        b = self.machine("b")
        line = lambda hour, who: json.dumps({"at": f"2026-10-20T{hour}:00:00+00:00", "type": "note", "who": who})
        self.append(a, "events.jsonl", line(10, "a"), line(12, "a"))
        sync.save(a)
        self.append(b, "events.jsonl", line(11, "b"))
        sync.save(b)
        events = [json.loads(l) for l in self.read(os.path.join(b.dir, "events.jsonl")).splitlines()]
        self.assertEqual([(e["type"], e.get("who")) for e in events],
                         [("planned", None), ("note", "a"), ("note", "b"), ("note", "a")])
        self.assertEqual(self.remote_file("podium/events.jsonl"), self.read(os.path.join(b.dir, "events.jsonl")))

    def test_a_text_conflict_keeps_this_machines_file_writes_the_other_beside_it_and_needs_you(self):
        a = self.machine("a")
        notes = os.path.join("stories", "M1", "notes.md")
        self.write(os.path.join(a.dir, notes), "plan\n")
        sync.save(a)
        b = self.machine("b")
        self.write(os.path.join(a.dir, notes), "plan from a\n")
        sync.save(a)
        self.write(os.path.join(b.dir, notes), "plan from b\n")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(self.read(os.path.join(b.dir, notes)), "plan from b\n")
        self.assertEqual(self.read(os.path.join(b.dir, notes + ".remote")), "plan from a\n")
        self.assertEqual(b.data["needsYou"], {"reason": "sync conflict in podium/stories/M1/notes.md"})
        self.assertNotIn("podium/stories/M1/notes.md.remote", self.remote_files())

    def test_a_text_change_on_each_side_of_one_file_merges_cleanly(self):
        a = self.machine("a")
        notes = os.path.join("stories", "M1", "notes.md")
        self.write(os.path.join(a.dir, notes), "one\ntwo\nthree\nfour\nfive\n")
        sync.save(a)
        b = self.machine("b")
        self.write(os.path.join(a.dir, notes), "ONE\ntwo\nthree\nfour\nfive\n")
        sync.save(a)
        self.write(os.path.join(b.dir, notes), "one\ntwo\nthree\nfour\nFIVE\n")
        sync.save(b)
        self.assertEqual(self.read(os.path.join(b.dir, notes)), "ONE\ntwo\nthree\nfour\nFIVE\n")
        self.assertIsNone(b.data["needsYou"])


class Major(SyncCase):
    def test_status_landed_core_phases_and_a_wave_merge_are_major(self):
        p = self.run_in(os.path.join(self.tmp, "plain"))
        major = lambda **e: sync.is_major(p, e)
        self.assertTrue(major(type="status", status="done"))
        self.assertTrue(major(type="landed"))
        self.assertTrue(major(type="phase", phase="spec"))
        self.assertFalse(major(type="phase", phase="mock"))
        self.assertTrue(major(type="merged", wave=True))
        self.assertFalse(major(type="merged"))
        self.assertFalse(major(type="commit"))


class AutoSave(SyncCase):
    def podium(self, p, *args):
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", p.root, *args], capture_output=True,
                           text=True, env={**os.environ, "PYTHONPATH": ROOT})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_a_status_event_saves_on_its_own_when_sync_is_on(self):
        p = self.run_in(self.clone("a"))
        out = self.podium(p, "set", "S1", "status=working", "--event", "status", "status=working")
        self.assertRegex(out, r"SAVED [0-9a-f]{7} M1/S1 status working")
        self.assertIn('"working"', self.remote_file("podium/podium.json"))

    def test_nothing_saves_on_its_own_when_sync_is_off(self):
        p = self.run_in(self.clone("a"), enabled=False)
        self.assertEqual(self.podium(p, "set", "S1", "status=working", "--event", "status", "status=working"), "")
        self.assertIsNone(self.remote_tip())

    def test_a_backdated_or_minor_event_saves_nothing(self):
        p = self.run_in(self.clone("a"))
        self.podium(p, "set", "S1", "--event", "status", "status=working", "at=2026-01-01T00:00:00+00:00")
        self.podium(p, "set", "S1", "--event", "commit", "sha=abc")
        self.assertIsNone(self.remote_tip())

    def test_the_extensions_sync_major_decides_which_events_save(self):
        ext = os.path.join(self.tmp, "ext.py")
        self.write(ext, textwrap.dedent("""\
            def SYNC_MAJOR(event):
                return event["type"] == "note"
        """))
        p = self.run_in(self.clone("a"), {**DATA, "orchestrator": {"name": "o", "command": "/o", "extension": ext}})
        self.podium(p, "set", "S1", "--event", "status", "status=working")
        self.assertIsNone(self.remote_tip())
        self.assertRegex(self.podium(p, "set", "S1", "--event", "note"), r"SAVED ")
        self.assertIsNotNone(self.remote_tip())

    def test_sync_on_outside_any_repo_is_refused_unless_the_remote_is_a_url(self):
        p = self.run_in(os.path.join(self.tmp, "plain"), enabled=False)
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", p.root, "sync", "on"], capture_output=True,
                           text=True, env={**os.environ, "PYTHONPATH": ROOT})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not in a git repo", r.stderr)
        self.assertEqual(self.podium(p, "sync", "on", "--remote", self.bare), f"ON {self.bare} {REF}\n")
        self.assertRegex(self.podium(p, "sync", "save"), r"^SAVED ")
        self.assertRegex(self.podium(p, "sync", "status"), r"^ON .* last save [0-9a-f]{7}\n$")


if __name__ == "__main__":
    unittest.main()
