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
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import human, sync  # noqa: E402
from podium_dashboard.state import Podium  # noqa: E402

REF = "refs/heads/podium-run/api"
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
        for k in ("PODIUM_DIR", "PODIUM_ME"):
            os.environ.pop(k, None)
        os.environ.update({"HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1", "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"),
                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        patched = unittest.mock.patch.object(human, "HUMAN_FILE", os.environ["PODIUM_HUMAN"])
        patched.start()
        self.addCleanup(patched.stop)
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

    def run_in(self, parent, data=DATA, hidden=True, **sync_block):
        run = os.path.join(parent, ".deep-plan") if hidden else parent
        block = {"enabled": True, "ref": REF, **sync_block}
        self.write(os.path.join(run, "podium", "podium.json"), json.dumps({**(data or {}), "sync": block}))
        return Podium(run)

    def machine(self, name):
        """A clone whose run dir syncs: the first saves its state, the others pull it."""
        first = not self.remote_tip()
        p = self.run_in(self.clone(name), DATA if first else None)
        self.assertRegex(sync.save(p) if first else sync.pull(p), r"^(SAVED|PULLED) ")
        return p

    def as_(self, person, p):
        os.environ["PODIUM_ME"] = person
        p._me = None
        self.assertEqual(p.me, person)
        return p

    def push_tree(self, files):
        """Put a commit holding `files` ({path: text}), built by hand, on the remote's ref."""
        def tree(entries):
            subs, lines = {}, []
            for path, text in entries.items():
                head, _, rest = path.partition("/")
                if rest:
                    subs.setdefault(head, {})[rest] = text
                else:
                    lines.append(f"100644 blob {plumb('hash-object', '-w', '--stdin', input=text)}\t{head}")
            lines += [f"040000 tree {tree(sub)}\t{name}" for name, sub in subs.items()]
            return plumb("mktree", input="".join(line + "\n" for line in lines))

        plumb = lambda *args, input=None: subprocess.run(["git", "--git-dir", self.bare, *args], input=input, text=True,
                                                         capture_output=True, check=True).stdout.strip()
        tip = self.remote_tip()
        sha = plumb("commit-tree", tree(files), *(["-p", tip] if tip else []), "-m", "by hand")
        plumb("update-ref", REF, sha)

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
        self.assertEqual(b.data["sync"], {"enabled": True, "ref": REF, "remote": "origin"})
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

    def test_a_local_file_the_remote_starts_carrying_stays_and_the_remote_one_lands_beside_it(self):
        a, b = self.machine("a"), self.machine("b")
        self.write(os.path.join(a.root, "docs", "plan.md"), "plan of a\n")
        for p in (a, b):
            p.data["sync"]["include"] = ["podium/podium.json", "docs/*.md"]
            p.save()
        sync.save(a)
        self.write(os.path.join(b.root, "docs", "plan.md"), "plan of b\n")
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md")), "plan of b\n")
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md.remote")), "plan of a\n")
        self.assertEqual(b.needs_you(), {"reason": "sync conflict in docs/plan.md"})

    def test_a_machine_that_shares_fewer_files_drops_no_one_elses(self):
        a = self.machine("a")
        progress = os.path.join(a.dir, "stories", "M1", "S1.progress")
        self.write(progress, "2026-10-20T10:00:00+00:00 RED x\n")
        sync.save(a)
        b = self.machine("b")
        b.data["sync"]["include"] = ["podium/podium.json", "podium/events.jsonl"]
        b.save()
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(self.remote_file("podium/stories/M1/S1.progress"), self.read(progress))
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertEqual((a.milestone("M2")["status"], self.read(progress)), ("working", "2026-10-20T10:00:00+00:00 RED x\n"))
        self.assertEqual(a.data["sync"], {"enabled": True, "ref": REF})

    def test_include_and_exclude_stay_with_their_machine(self):
        a, b = self.machine("a"), self.machine("b")
        a.data["sync"].update(include=["podium/podium.json", "docs/*.md"], exclude=["docs/draft-*"])
        a.save()
        self.write(os.path.join(a.root, "docs", "plan.md"), "# plan\n")
        self.write(os.path.join(a.root, "docs", "draft-idea.md"), "# idea\n")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertNotIn("sync", json.loads(self.remote_file("podium/podium.json")))
        self.assertIn("docs/plan.md", self.remote_files())
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.data["sync"], {"enabled": True, "ref": REF})
        self.assertFalse(os.path.exists(os.path.join(b.root, "docs")))

    def test_excluding_a_file_keeps_this_machines_copy_home_and_drops_no_one_elses(self):
        a = self.machine("a")
        progress = os.path.join("stories", "M1", "S1.progress")
        self.write(os.path.join(a.dir, progress), "2026-10-20T10:00:00+00:00 RED x\n")
        sync.save(a)
        b = self.machine("b")
        b.data["sync"]["exclude"] = ["*.progress"]
        b.save()
        self.append(b, progress, "2026-10-20T10:05:00+00:00 GREEN b")
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(self.remote_file("podium/" + progress), "2026-10-20T10:00:00+00:00 RED x\n")
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertEqual(self.read(os.path.join(a.dir, progress)), "2026-10-20T10:00:00+00:00 RED x\n")

    def test_a_remote_that_widens_include_changes_nothing_here(self):
        top = {".claude/settings.json": "{}\n", ".husky/pre-commit": "x\n", ".envrc": "x\n", "Makefile": "x\n",
               "notes.md": "notes\n"}
        self.push_tree({"podium/podium.json": json.dumps({**DATA, "sync": {"include": ["**"]}}), **top})
        b = self.run_in(self.clone("b"), None, hidden=False, include=["podium/**"])
        self.assertRegex(sync.pull(b), r"^PULLED ")
        for rel in top:
            self.assertFalse(os.path.exists(os.path.join(b.root, rel)), rel)
        self.assertEqual(b.data["sync"], {"enabled": True, "ref": REF, "include": ["podium/**"]})
        c = self.run_in(self.clone("c"), None, hidden=False)
        self.assertRegex(sync.pull(c), r"^PULLED ")
        self.assertEqual(self.read(os.path.join(c.root, "notes.md")), "notes\n")
        for rel in set(top) - {"notes.md"}:
            self.assertFalse(os.path.exists(os.path.join(c.root, rel)), rel)

    def test_a_machine_that_widens_its_include_gets_the_files_it_now_covers_and_drops_none(self):
        a = self.machine("a")
        a.data["sync"]["include"] = ["podium/**", "docs/*.md"]
        a.save()
        self.write(os.path.join(a.root, "docs", "plan.md"), "# plan\n")
        self.assertRegex(sync.save(a), r"^SAVED ")
        b = self.machine("b")
        self.assertFalse(os.path.exists(os.path.join(b.root, "docs")))
        b.data["sync"]["include"] = ["podium/**", "docs/*.md"]
        b.save()
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertIn("docs/plan.md", self.remote_files())
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md")), "# plan\n")
        os.remove(os.path.join(b.root, "docs", "plan.md"))
        self.assertRegex(sync.save(b, "drop plan"), r"^SAVED ")
        self.assertNotIn("docs/plan.md", self.remote_files())

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
        self.assertEqual(b.data["sync"], {"enabled": True, "ref": REF, "remote": self.bare})

    def test_pull_merges_with_changes_made_since_the_last_save_and_leaves_them_unsaved(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual((b.milestone("M1")["status"], b.milestone("M2")["status"]), ("done", "working"))
        self.assertTrue(sync.status(b).endswith("; changed since"))
        self.assertIn('"todo"', self.remote_file("podium/podium.json"))
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual([m["status"] for m in json.loads(self.remote_file("podium/podium.json"))["epics"][0]["milestones"]],
                         ["done", "working"])

    def test_pull_keeps_the_state_while_the_watcher_runs(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.write(os.path.join(b.dir, "watcher.json"), json.dumps({"pid": 1, "at": time.time()}))
        self.assertEqual(sync.pull(b), "KEPT the watcher is running")
        self.write(os.path.join(b.dir, "watcher.json"), json.dumps({"pid": 1, "at": time.time() - 600}))
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.milestone("M1")["status"], "done")

    def test_the_watcher_pulls_past_its_own_heartbeat_and_past_local_changes(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.write(os.path.join(b.dir, "watcher.json"), json.dumps({"pid": 1, "at": time.time()}))
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.pull(b, from_watcher=True), r"^PULLED ")
        self.assertEqual((b.milestone("M1")["status"], b.milestone("M2")["status"]), ("done", "working"))

    def test_pull_restores_only_what_this_machines_lists_carry(self):
        self.push_tree({"podium/podium.json": json.dumps({**DATA, "sync": {"include": ["podium/podium.json", "podium/stories/**"]}}),
                        "podium/stories/M1/S1.progress": "p\n", "docs/outside.md": "x\n"})
        b = self.run_in(self.clone("b"), None)
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertTrue(os.path.exists(os.path.join(b.dir, "stories", "M1", "S1.progress")))
        self.assertFalse(os.path.exists(os.path.join(b.root, "docs")))

    def test_pull_never_restores_machine_folders_logs_or_a_git_folder(self):
        self.push_tree({"podium/podium.json": json.dumps({**DATA, "sync": {"include": ["**"]}}), "docs/in.md": "x\n",
                        "repos/api/x": "x\n", "worktrees/w/x": "x\n", "S1.logs/out.txt": "x\n",
                        "podium/stories/M1/S1.logs/out.txt": "x\n", "podium/.GIT/config": "x\n",
                        "podium/.git\u200c/hooks/pre-commit": "x\n"})
        b = self.run_in(self.clone("b"), None, include=["**"])
        self.assertRegex(sync.pull(b), r"^PULLED ")
        found = sorted(os.path.relpath(os.path.join(d, n), b.root) for d, _, ns in os.walk(b.root) for n in ns
                       if n != "synced.json")
        self.assertEqual(found, ["docs/in.md", "podium/podium.json"])

    def test_python_code_never_syncs_either_way(self):
        a = self.run_in(self.clone("a"), {**DATA, "sync": {}}, include=["podium/**"])
        for name in ("tool.py", "tool.pyc", "site.pth", "ext.so", "ext.dylib", "ext.pyd", "notes.md"):
            self.write(os.path.join(a.dir, name), "x\n")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertEqual(self.remote_files(), ["podium/notes.md", "podium/podium.json"])
        self.push_tree({"podium/podium.json": json.dumps({**DATA, "sync": {"include": ["**"]}}), "podium/ext.py": "x\n",
                        "lib/ext.pyc": "x\n", "lib/evil.pth": "x\n", "lib/_ext.cpython-39-darwin.so": "x\n",
                        "lib/ext.dylib": "x\n", "lib/ext.pyd": "x\n", "docs/in.md": "x\n"})
        b = self.run_in(self.clone("b"), None, include=["**"])
        self.assertRegex(sync.pull(b), r"^PULLED ")
        found = sorted(os.path.relpath(os.path.join(d, n), b.root) for d, _, ns in os.walk(b.root) for n in ns
                       if n != "synced.json")
        self.assertEqual(found, ["docs/in.md", "podium/podium.json"])

    def test_the_never_synced_names_never_sync_either_way_in_any_case(self):
        def shouted(pattern):
            path = pattern.replace("**/", "docs/").replace("**", "x.md").replace("*", "x")
            return (path if "/" in pattern else f"docs/{path}").upper()

        never = [shouted(pattern) for pattern in sync.LOCAL] + ["podium/__pycache__/ext.cpython-39.PYC", "podium/ext.Py",
                                                                 "__PyCache__/data.txt", "podium/stories/__pycache__/data.txt"]
        a = self.run_in(self.clone("a"), include=["**"])
        for rel in never + ["DOCS/NOTES.MD"]:
            self.write(os.path.join(a.root, rel), "x\n")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertEqual(self.remote_files(), ["DOCS/NOTES.MD", "podium/podium.json"])
        self.push_tree({"podium/podium.json": json.dumps({**DATA, "sync": {"include": ["**"]}}), "DOCS/NOTES.MD": "y\n",
                        **{rel: "x\n" for rel in never}})
        b = self.run_in(self.clone("b"), None, include=["**"])
        self.assertRegex(sync.pull(b), r"^PULLED ")
        found = sorted(os.path.relpath(os.path.join(d, n), b.root) for d, _, ns in os.walk(b.root) for n in ns
                       if n != "synced.json")
        self.assertEqual(found, ["DOCS/NOTES.MD", "podium/podium.json"])

    def test_pull_never_writes_through_a_symlink(self):
        self.push_tree({"podium/podium.json": json.dumps(DATA), "podium/stories/M1/S1.progress": "p\n"})
        for elsewhere in (os.path.join(self.tmp, "elsewhere"), os.path.join(self.tmp, "b", ".deep-plan", "elsewhere")):
            b = self.run_in(self.clone("b"), None)
            os.makedirs(elsewhere)
            os.symlink(elsewhere, os.path.join(b.dir, "stories"))
            self.assertRegex(sync.pull(b), r"^PULLED ")
            self.assertEqual(os.listdir(elsewhere), [])
            shutil.rmtree(os.path.join(self.tmp, "b"))

    def test_a_remote_save_without_podium_json_leaves_the_local_one_alone(self):
        a, b = self.machine("a"), self.machine("b")
        a.data["sync"]["include"] = ["podium/events.jsonl"]
        a.save()
        self.append(a, "events.jsonl", json.dumps({"at": "2026-10-20T10:00:00+00:00", "type": "note"}))
        sync.save(a)
        self.assertEqual(self.remote_files(), ["podium/events.jsonl"])
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.read()["epics"], DATA["epics"])
        self.assertEqual(b.read()["sync"], {"enabled": True, "ref": REF})
        self.assertTrue(os.path.exists(os.path.join(b.dir, "events.jsonl")))

    def test_a_clone_with_run_state_but_no_save_merges_with_the_remote_and_loses_nothing(self):
        a = self.machine("a")
        self.write(os.path.join(a.dir, "stories", "M1", "S1.progress"), "2026-10-20T10:00:00+00:00 RED a\n")
        sync.save(a)
        b = self.run_in(self.clone("b"), {**DATA, "epics": json.loads(json.dumps(DATA["epics"]))})
        self.set_status(b, "M2", "working")
        self.write(os.path.join(b.dir, "stories", "M2", "S1.progress"), "2026-10-20T11:00:00+00:00 RED b\n")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(b.milestone("M2")["status"], "working")
        self.assertTrue(os.path.exists(os.path.join(b.dir, "stories", "M1", "S1.progress")))
        self.assertTrue(os.path.exists(os.path.join(b.dir, "stories", "M2", "S1.progress")))
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertEqual(a.milestone("M2")["status"], "working")
        c = self.run_in(self.clone("c"), {**DATA, "project": {"title": "C"}})
        self.assertRegex(sync.pull(c), r"^PULLED ")
        self.assertEqual(c.data["project"]["title"], "C")
        self.assertTrue(os.path.exists(os.path.join(c.dir, "stories", "M2", "S1.progress")))

    def test_save_behind_the_remote_with_nothing_new_says_behind(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.assertEqual(sync.save(b), "BEHIND")


class MidBuild(SyncCase):
    def podium(self, p, *args, me):
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", p.root, *args], capture_output=True,
                           text=True, env={**os.environ, "PYTHONPATH": ROOT, "PODIUM_ME": me})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_a_watcher_pull_mid_build_brings_anothers_claim_and_keeps_the_unsaved_progress(self):
        a, b = self.machine("a"), self.machine("b")
        progress = os.path.join(a.dir, "stories", "M1", "S1.progress")
        self.podium(a, "log", "M1/S1", "RED", "first", me="a")
        self.assertTrue(self.podium(b, "claim", "M2", me="b").startswith("claimed M2\n"))
        self.podium(a, "log", "M1/S1", "GREEN", "second", me="a")
        self.assertRegex(sync.pull(a, from_watcher=True), r"^PULLED ")
        self.assertEqual(a.milestone("M2")["owner"], "b")
        self.assertEqual([line.split()[1:] for line in self.read(progress).splitlines()], [["RED", "first"], ["GREEN", "second"]])
        self.assertNotIn("podium/stories/M1/S1.progress", self.remote_files())
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertEqual(self.remote_file("podium/stories/M1/S1.progress"), self.read(progress))
        self.assertEqual(json.loads(self.remote_file("podium/podium.json"))["epics"][0]["milestones"][1]["owner"], "b")

    def test_a_text_file_both_changed_keeps_the_local_one_writes_the_remote_beside_it_and_needs_you(self):
        a = self.machine("a")
        story = os.path.join("stories", "M1", "S1.md")
        self.write(os.path.join(a.dir, story), "plan\n")
        sync.save(a)
        b = self.machine("b")
        self.write(os.path.join(b.dir, story), "b's plan\n")
        self.write(os.path.join(a.dir, story), "a's plan\n")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertRegex(sync.pull(b, from_watcher=True), r"^PULLED ")
        self.assertEqual((self.read(os.path.join(b.dir, story)), self.read(os.path.join(b.dir, story + ".remote"))),
                         ("b's plan\n", "a's plan\n"))
        self.assertIn("sync conflict in podium/stories/M1/S1.md", str(b.needs_you()))

    def test_a_pull_after_an_unpushed_save_merges_the_unsaved_changes_too(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(b, "M2", "working")
        self.reject_pushes(3)
        self.assertIn("(not pushed: push rejected three times)", sync.save(b))
        self.set_status(a, "M1", "done")
        self.assertRegex(sync.save(a), r"^SAVED ")
        b.story("S1", "M2")[1]["status"] = "working"
        b.save()
        self.assertRegex(sync.pull(b, from_watcher=True), r"^PULLED ")
        self.assertEqual((b.milestone("M1")["status"], b.milestone("M2")["status"], b.story("S1", "M2")[1]["status"]),
                         ("done", "working", "working"))

    def test_a_progress_line_logged_while_a_pull_merged_stays(self):
        p = self.run_in(self.clone("a"))
        rel = "podium/stories/M1/S1.progress"
        self.write(os.path.join(p.root, rel), "2026-10-20T10:00:00+00:00 RED a\n2026-10-20T10:05:00+00:00 GREEN a\n")
        sync.apply(p, {rel: b"2026-10-20T10:00:00+00:00 RED a\n2026-10-20T10:02:00+00:00 RED b\n"}, set())
        self.assertEqual(self.read(os.path.join(p.root, rel)), "2026-10-20T10:00:00+00:00 RED a\n"
                         "2026-10-20T10:02:00+00:00 RED b\n2026-10-20T10:05:00+00:00 GREEN a\n")


class Join(SyncCase):
    def cli(self, run_dir, *args):
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", run_dir, *args], capture_output=True,
                           text=True, env={**os.environ, "PYTHONPATH": ROOT})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def shared_run(self):
        self.assertRegex(sync.save(self.run_in(os.path.join(self.tmp, "first"), remote=self.bare)), r"^SAVED ")

    def state(self, run_dir):
        with open(os.path.join(run_dir, "podium", "podium.json")) as f:
            return json.load(f)

    def test_sync_on_in_an_empty_dir_then_pull_joins_the_shared_run(self):
        self.shared_run()
        run = os.path.join(self.tmp, "join")
        os.makedirs(run)
        self.assertEqual(self.cli(run, "sync", "on", "--remote", self.bare, "--ref", REF), f"ON {self.bare} ref {REF}\n")
        machine = {"enabled": True, "remote": self.bare, "ref": REF}
        self.assertEqual({k: v for k, v in self.state(run).items() if k != "updatedAt"}, {"sync": machine})
        self.assertRegex(self.cli(run, "sync", "pull"), r"^PULLED ")
        data = self.state(run)
        self.assertEqual((data["project"], data["epics"], data["sync"]), (DATA["project"], DATA["epics"], machine))

    def test_a_run_only_init_wrote_takes_the_remotes_state_whole_but_its_own_extension(self):
        self.shared_run()
        run = os.path.join(self.tmp, "join")
        self.cli(run, "init", "--name", "o", "--command", "/o", "--extension", "~/o.py")
        self.cli(run, "sync", "on", "--remote", self.bare, "--ref", REF)
        self.assertRegex(self.cli(run, "sync", "pull"), r"^PULLED ")
        data = self.state(run)
        self.assertEqual((data["project"]["title"], data["epics"]), ("T", DATA["epics"]))
        self.assertEqual(data["orchestrator"], {"extension": "~/o.py"})
        self.assertEqual(data["sync"], {"enabled": True, "remote": self.bare, "ref": REF})

    def test_a_run_with_more_than_init_wrote_merges_with_the_remote(self):
        self.shared_run()
        run = os.path.join(self.tmp, "join")
        self.cli(run, "init", "--name", "o", "--command", "/o", "--extension", "o.py")
        self.cli(run, "assume", "q", "c", "w")
        self.cli(run, "sync", "on", "--remote", self.bare, "--ref", REF)
        self.assertRegex(self.cli(run, "sync", "pull"), r"^PULLED ")
        data = self.state(run)
        self.assertEqual((data["project"]["title"], data["orchestrator"]["name"], len(data["assumptions"])), ("join", "o", 1))

    def test_a_joiner_runs_the_runs_extension_until_it_registers_its_own_which_never_reaches_the_others(self):
        first, run = os.path.join(self.tmp, "first"), os.path.join(self.tmp, "join")
        self.run_in(first, hidden=False, remote=self.bare)
        exts = {}
        for who in ("a", "b"):
            exts[who] = os.path.join(self.tmp, f"ext_{who}.py")
            self.write(exts[who], f"COMMANDS = {{'hi': lambda p, args: print({who!r})}}\n")
        self.cli(first, "init", "--name", "o", "--command", "/o", "--extension", exts["a"])
        self.assertRegex(self.cli(first, "sync", "save"), r"^SAVED ")
        self.cli(run, "sync", "on", "--remote", self.bare, "--ref", REF)
        self.assertRegex(self.cli(run, "sync", "pull"), r"^PULLED ")
        self.assertEqual(self.cli(run, "hi"), "a\n")
        self.cli(run, "init", "--name", "o", "--command", "/o", "--extension", exts["b"])
        self.cli(run, "assume", "q", "c", "w")
        self.assertRegex(self.cli(run, "sync", "save"), r"^SAVED ")
        self.assertRegex(self.cli(first, "sync", "pull"), r"^PULLED ")
        self.assertEqual((self.cli(first, "hi"), self.cli(run, "hi")), ("a\n", "b\n"))
        self.assertEqual(json.loads(self.remote_file("podium/podium.json"))["orchestrator"]["extension"], exts["a"])

    def test_a_pulled_run_never_runs_code_the_remote_planted(self):
        marker = os.path.join(self.tmp, "ran")
        orchestrator = {"name": "evil", "command": "/evil", "extension": "ext.py"}
        self.push_tree({"podium/podium.json": json.dumps({**DATA, "sync": {"include": ["podium/**"]}, "orchestrator": orchestrator}),
                        "podium/ext.py": f"open({marker!r}, 'w').close()\nCOMMANDS = {{'hello': print}}\n"})
        run = os.path.join(self.tmp, "join")
        self.cli(run, "sync", "on", "--remote", self.bare, "--ref", REF)
        self.assertRegex(self.cli(run, "sync", "pull"), r"^PULLED ")
        self.assertEqual(self.state(run)["orchestrator"], orchestrator)
        planted = os.path.join(run, "podium", "ext.py")
        self.assertFalse(os.path.exists(planted))
        for args in ((), ("status",), ("ready",), ("hello",)):
            r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", run, *args], capture_output=True,
                               text=True, env={**os.environ, "PYTHONPATH": ROOT})
            self.assertIn(r.returncode, (0, 2) if args == ("hello",) else (0,), r.stderr)
        self.assertIn(f"extension {planted} not loadable: no such file", r.stderr)
        self.assertFalse(os.path.exists(marker))


class Extension(SyncCase):
    def orchestrate(self, p, name, extension):
        p.data["orchestrator"] = {"name": name, "command": "/o", "extension": extension}
        p.save()

    def remote_orchestrator(self):
        return json.loads(self.remote_file("podium/podium.json"))["orchestrator"]

    def test_the_first_save_seeds_the_extension_and_no_machine_changes_it_after(self):
        a = self.machine("a")
        self.orchestrate(a, "o", "~/a/ext.py")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertEqual(self.remote_orchestrator(), {"name": "o", "command": "/o", "extension": "~/a/ext.py"})
        b = self.machine("b")
        self.assertEqual(b.data["orchestrator"]["extension"], "~/a/ext.py")
        self.orchestrate(b, "o", "~/b/ext.py")
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(self.remote_orchestrator()["extension"], "~/a/ext.py")
        self.orchestrate(a, "o2", "~/a2/ext.py")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertEqual(self.remote_orchestrator(), {"name": "o2", "command": "/o", "extension": "~/a/ext.py"})
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.data["orchestrator"], {"name": "o2", "command": "/o", "extension": "~/b/ext.py"})
        self.assertNotIn("changed since", sync.status(b))

    def test_a_merge_keeps_each_machines_extension_and_the_seed_that_reached_the_remote_first(self):
        a, b = self.machine("a"), self.machine("b")
        self.orchestrate(a, "o", "~/a/ext.py")
        self.orchestrate(b, "o", "~/b/ext.py")
        self.set_status(a, "M1", "done")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual((b.read()["orchestrator"]["extension"], b.milestone("M1")["status"]), ("~/b/ext.py", "done"))
        self.assertEqual(self.remote_orchestrator()["extension"], "~/a/ext.py")
        self.assertRegex(sync.pull(a), r"^PULLED ")
        self.assertEqual((a.read()["orchestrator"]["extension"], a.milestone("M2")["status"]), ("~/a/ext.py", "working"))

    def test_a_join_takes_the_runs_extension_once(self):
        orchestrator = {"name": "o", "command": "/o", "extension": "~/skills/o/ext.py"}
        self.push_tree({"podium/podium.json": sync.dump({**DATA, "orchestrator": orchestrator}).decode()})
        b = self.run_in(self.clone("b"), None)
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.data["orchestrator"], orchestrator)
        self.assertNotIn("changed since", sync.status(b))
        moved = {**DATA, "project": {"title": "T2"}, "orchestrator": {**orchestrator, "extension": "~/other.py"}}
        self.push_tree({"podium/podium.json": json.dumps(moved)})
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual((b.data["project"]["title"], b.data["orchestrator"]["extension"]), ("T2", "~/skills/o/ext.py"))


    def test_a_machine_that_synced_before_the_run_had_an_extension_never_takes_the_one_a_later_save_names(self):
        a, b = self.machine("a"), self.machine("b")
        self.orchestrate(a, "o", "~/a/ext.py")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual((b.read()["orchestrator"], b.milestone("M2")["status"]), ({"name": "o", "command": "/o"}, "working"))
        self.orchestrate(a, "o2", "~/a/ext.py")
        self.assertRegex(sync.save(a), r"^SAVED ")
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(b.read()["orchestrator"], {"name": "o2", "command": "/o"})
        self.assertEqual(self.remote_orchestrator()["extension"], "~/a/ext.py")
        self.assertNotIn("changed since", sync.status(b))


class Merge(SyncCase):
    def test_two_machines_changing_different_milestones_keep_both_changes(self):
        a, b = self.machine("a"), self.machine("b")
        self.set_status(a, "M1", "done")
        sync.save(a)
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual((b.milestone("M1")["status"], b.milestone("M2")["status"]), ("done", "working"))
        self.assertEqual(b.data["sync"], {"enabled": True, "ref": REF})
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
        self.assertEqual(b.needs_you(), {"reason": "sync conflict in podium/stories/M1/notes.md"})
        self.assertNotIn("podium/stories/M1/notes.md.remote", self.remote_files())

    def test_a_merge_never_overwrites_a_local_file_this_machine_never_synced(self):
        a, b = self.machine("a"), self.machine("b")
        self.write(os.path.join(a.root, "docs", "plan.md"), "plan of a\n")
        for p in (a, b):
            p.data["sync"]["include"] = ["podium/podium.json", "docs/*.md"]
            p.save()
        sync.save(a)
        self.write(os.path.join(b.root, "docs", "plan.md"), "plan of b\n")
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md")), "plan of b\n")
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md.remote")), "plan of a\n")
        self.assertIn("sync conflict in docs/plan.md", b.needs_you()["reason"])

    def test_a_conflict_adds_to_this_persons_pending_need_and_leaves_the_others_alone(self):
        a = self.as_("ann", self.machine("a"))
        notes = os.path.join("stories", "M1", "notes.md")
        self.write(os.path.join(a.dir, notes), "plan\n")
        sync.save(a)
        b = self.as_("bob", self.machine("b"))
        a.own()["needsYou"] = {"reason": "ann's question"}
        a.save()
        self.write(os.path.join(a.dir, notes), "plan from a\n")
        sync.save(a)
        b.own()["needsYou"] = {"reason": "pick a db", "story": "M2/S1"}
        b.save()
        self.write(os.path.join(b.dir, notes), "plan from b\n")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(b.needs_you(), {"reason": "pick a db; sync conflict in podium/stories/M1/notes.md", "story": "M2/S1"})
        people = json.loads(self.remote_file("podium/podium.json"))["people"]
        self.assertEqual(people["ann"]["needsYou"], {"reason": "ann's question"})
        self.assertEqual(people["bob"]["needsYou"]["reason"], "pick a db; sync conflict in podium/stories/M1/notes.md")

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
        self.assertIsNone(b.needs_you())


class Ref(SyncCase):
    def test_the_default_ref_is_one_per_run_named_after_its_folder(self):
        hidden = self.run_in(os.path.join(self.tmp, "My Repo"))
        named = self.run_in(os.path.join(self.tmp, "Feature_X 2"), hidden=False)
        self.assertEqual((sync.default_ref(hidden), sync.default_ref(named)),
                         ("refs/heads/podium-run/my-repo", "refs/heads/podium-run/feature-x-2"))

    def test_sync_on_sets_the_runs_default_ref(self):
        repo = self.clone("api")
        run = os.path.join(repo, ".deep-plan")
        self.write(os.path.join(run, "podium", "podium.json"), json.dumps(DATA))
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "--dir", run, "sync", "on"], capture_output=True,
                           text=True, env={**os.environ, "PYTHONPATH": ROOT})
        self.assertEqual(r.stdout, "ON origin ref refs/heads/podium-run/api\n", r.stderr)

    def test_the_default_ref_lives_beside_an_existing_podium_branch(self):
        git("--git-dir", self.bare, "update-ref", "refs/heads/podium", git("--git-dir", self.bare, "rev-parse", "main").strip())
        repo = self.clone("api")
        run = os.path.join(repo, ".deep-plan")
        self.write(os.path.join(run, "podium", "podium.json"), json.dumps({**DATA, "sync": {"enabled": True}}))
        p = Podium(run)
        self.assertRegex(sync.save(p), r"^SAVED [0-9a-f]{7} save$")
        self.assertEqual(sync.status(p).split(" ON ")[0], "ref refs/heads/podium-run/api")
        self.assertTrue(git("--git-dir", self.bare, "rev-parse", "refs/heads/podium-run/api").strip())

    def test_sync_status_names_the_ref_even_when_off(self):
        p = self.run_in(os.path.join(self.tmp, "plain"), enabled=False, ref="refs/heads/podium")
        self.assertEqual(sync.status(p), "ref refs/heads/podium OFF")

    def test_the_ref_moves_only_from_the_value_this_machine_last_saw(self):
        p = self.run_in(self.clone("a"))
        sync.save(p)
        g, _ = sync.open_git(p)
        tip = g.rev(REF)
        self.set_status(p, "M1", "done")
        sync.save(p)
        with self.assertRaises(sync.SyncError):
            g.update_ref(tip, tip)
        self.assertNotEqual(g.rev(REF), tip)


class Defaults(SyncCase):
    def set_defaults(self, **lists):
        os.makedirs(os.path.dirname(sync.defaults_path()), exist_ok=True)
        with open(sync.defaults_path(), "w") as f:
            json.dump(lists, f)

    def test_a_run_with_no_lists_syncs_the_state_and_planning_docs_but_never_machine_files_or_code(self):
        p = self.run_in(self.clone("a"), hidden=False)
        for rel in ("notes.md", "spec/x.md", "mock/m.html", "domain-stories/d.egn", "docs/deep.md", ".envrc",
                    "spec/gen.py", "Makefile"):
            self.write(os.path.join(p.root, rel), "x\n")
        self.assertRegex(sync.save(p), r"^SAVED ")
        self.assertEqual(self.remote_files(), ["README.md", "domain-stories/d.egn", "mock/m.html", "notes.md",
                                               "podium/podium.json", "spec/x.md"])

    def test_the_machine_default_applies_to_a_run_with_no_lists(self):
        self.set_defaults(include=["podium/podium.json", "docs/*.md"], exclude=["docs/draft-*"])
        p = self.run_in(self.clone("a"))
        for rel in ("docs/plan.md", "docs/draft-idea.md", "notes.md"):
            self.write(os.path.join(p.root, rel), "x\n")
        self.assertRegex(sync.save(p), r"^SAVED ")
        self.assertEqual(self.remote_files(), ["docs/plan.md", "podium/podium.json"])
        self.assertEqual(sync.sources(p), 'include ["podium/podium.json", "docs/*.md"] (default) '
                                          'exclude ["docs/draft-*"] (default)')

    def test_a_runs_own_list_beats_the_default_and_each_list_resolves_on_its_own(self):
        self.set_defaults(include=["**"], exclude=["notes.md"])
        p = self.run_in(self.clone("a"), include=["podium/podium.json", "*.md"])
        for rel in ("notes.md", "plan.md", "docs/deep.md"):
            self.write(os.path.join(p.root, rel), "x\n")
        self.assertRegex(sync.save(p), r"^SAVED ")
        self.assertEqual(self.remote_files(), ["plan.md", "podium/podium.json"])
        self.assertEqual(sync.sources(p), 'include ["podium/podium.json", "*.md"] (run) exclude ["notes.md"] (default)')

    def test_with_no_default_a_run_falls_back_to_the_built_in_lists(self):
        p = self.run_in(self.clone("a"))
        self.assertEqual(sync.sources(p), 'include ["podium/podium.json", "podium/events.jsonl", "podium/handoffs.json", '
                                          '"podium/stories/**", "*.md", "spec/**", "mock/**", "domain-stories/**"] '
                                          '(built-in) exclude [] (built-in)')

    def test_widening_the_default_restores_the_files_it_now_covers_and_narrowing_it_deletes_none(self):
        a = self.machine("a")
        a.data["sync"]["include"] = ["podium/**", "docs/*.md"]
        a.save()
        self.write(os.path.join(a.root, "docs", "plan.md"), "# plan\n")
        self.assertRegex(sync.save(a), r"^SAVED ")
        b = self.machine("b")
        self.assertFalse(os.path.exists(os.path.join(b.root, "docs")))
        self.set_defaults(include=["podium/**", "docs/*.md"])
        self.set_status(b, "M2", "working")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md")), "# plan\n")
        self.set_defaults(include=["podium/**"])
        self.set_status(b, "M2", "done")
        self.assertRegex(sync.save(b), r"^SAVED ")
        self.assertRegex(sync.pull(b), r"^(UP-TO-DATE|PULLED )")
        self.assertEqual(self.read(os.path.join(b.root, "docs", "plan.md")), "# plan\n")
        self.assertIn("docs/plan.md", self.remote_files())

    def test_a_pull_never_touches_the_machine_default(self):
        self.set_defaults(include=["podium/**"])
        before = self.read(sync.defaults_path())
        self.push_tree({"podium/podium.json": json.dumps({**DATA, "sync": {"include": ["**"], "exclude": ["*"]},
                                                          "defaults": {"include": ["**"]}}),
                        "podium/sync.json": json.dumps({"include": ["**"]}), "sync.json": "{}\n"})
        b = self.run_in(self.clone("b"), None)
        self.assertRegex(sync.pull(b), r"^PULLED ")
        self.assertEqual(self.read(sync.defaults_path()), before)
        self.assertEqual(os.path.dirname(sync.defaults_path()), self.tmp)
        self.assertEqual(sync.lists(b), {"include": ["podium/**"], "exclude": []})


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
        self.assertEqual(self.podium(p, "sync", "on", "--remote", self.bare), f"ON {self.bare} ref {REF}\n")
        self.assertRegex(self.podium(p, "sync", "save"), r"^SAVED ")
        self.assertRegex(self.podium(p, "sync", "status"), rf"^ref {REF} ON .* last save [0-9a-f]{{7}}\ninclude .*\n$")


if __name__ == "__main__":
    unittest.main()
