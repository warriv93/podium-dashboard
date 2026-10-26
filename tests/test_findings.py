"""Tests for `podium finding` and `podium findings`: records pushed to findings refs on a bare remote, and grouped back."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import findings, human, sync  # noqa: E402
from podium_dashboard.state import Podium  # noqa: E402

FINDING = ["--kind", "retro", "--target", "feature-qa", "--title", "Gate reran", "--moment", "events.jsonl:12",
           "--fix", "check", "--severity", "normal"]


def git(*args, cwd=None, input=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, input=input)
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        for k in ("PODIUM_DIR", "PODIUM_ME"):
            os.environ.pop(k, None)
        os.environ.update({"HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.path.join(self.tmp, "gitconfig"),
                           "PODIUM_HUMAN": os.path.join(self.tmp, ".podium", "human.json"),
                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        patched = unittest.mock.patch.object(human, "HUMAN_FILE", os.environ["PODIUM_HUMAN"])
        patched.start()
        self.addCleanup(patched.stop)
        self.remote = os.path.join(self.tmp, "findings.git")
        git("init", "-q", "--bare", self.remote)
        self.ext = os.path.join(self.tmp, "ext.py")
        with open(self.ext, "w") as f:
            f.write(f"FINDINGS_REMOTE = {self.remote!r}\n")

    def run_at(self, project, extension=True, **data):
        run = os.path.join(self.tmp, project, ".deep-plan")
        os.makedirs(os.path.join(run, "podium"), exist_ok=True)
        data = {"active": {"milestone": "M1"}, **data, **({"orchestrator": {"extension": self.ext}} if extension else {})}
        with open(os.path.join(run, "podium", "podium.json"), "w") as f:
            json.dump(data, f)
        return run

    def podium(self, run_dir, *args, me="ann", code=0, home=None):
        env = {**os.environ, "PYTHONPATH": ROOT, "PODIUM_ME": me, **({"HOME": home} if home else {})}
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", *(["--dir", run_dir] if run_dir else []), *args],
                           capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout.splitlines()

    def on_ref(self, slug):
        r = subprocess.run(["git", "--git-dir", self.remote, "cat-file", "blob", f"refs/heads/findings/{slug}:findings.jsonl"],
                           capture_output=True, text=True)
        return [json.loads(line) for line in r.stdout.splitlines()] if r.returncode == 0 else []

    def events(self, run_dir):
        with open(os.path.join(run_dir, "podium", "events.jsonl")) as f:
            return [json.loads(line) for line in f]

    def seed(self, slug, *records):
        blob = git("--git-dir", self.remote, "hash-object", "-w", "--stdin",
                   input="".join(json.dumps(r) + "\n" for r in records)).strip()
        tree = git("--git-dir", self.remote, "mktree", input=f"100644 blob {blob}\tfindings.jsonl\n").strip()
        commit = git("--git-dir", self.remote, "commit-tree", tree, "-m", "seed").strip()
        git("--git-dir", self.remote, "update-ref", f"refs/heads/findings/{slug}", commit)

    def all(self, *args):
        return self.podium(None, "findings", "--all", "--remote", self.remote, *args)


def found(key, run, at, by="ann", **fields):
    return {"key": key, "kind": "retro", "target": "feature-qa", "title": f"{key} title", "moment": "m", "fix": "check",
            "severity": "normal", "by": by, "at": at, "run": run, **fields}


class Add(Case):
    def test_a_finding_lands_on_the_runs_ref_and_in_its_events(self):
        run = self.run_at("api")
        self.assertEqual(self.podium(run, "finding", "add", "--key", "gate-reran", *FINDING),
                         ["FINDING gate-reran recorded (pushed)"])
        [record] = self.on_ref("api")
        self.assertEqual({k: record[k] for k in ("key", "kind", "target", "fix", "severity", "by", "run", "milestone")},
                         {"key": "gate-reran", "kind": "retro", "target": "feature-qa", "fix": "check", "severity": "normal",
                          "by": "ann", "run": "api", "milestone": "M1"})
        [event] = self.events(run)
        self.assertEqual((event["type"], event["key"], event["milestone"]), ("finding", "gate-reran", "M1"))

    def test_without_a_findings_remote_the_finding_is_recorded_but_not_pushed(self):
        run = self.run_at("api", extension=False)
        self.assertEqual(self.podium(run, "finding", "add", "--key", "gate-reran", *FINDING),
                         ["FINDING gate-reran recorded (not pushed: no FINDINGS_REMOTE)"])
        self.assertEqual([e["type"] for e in self.events(run)], ["finding"])
        self.assertEqual(self.podium(run, "findings"), ["FINDING gate-reran ×1 open retro feature-qa normal — Gate reran"])

    def test_a_synced_run_files_its_findings_under_its_sync_refs_last_part(self):
        run = self.run_at("api", sync={"enabled": True, "ref": "refs/heads/podium-run/shared-api"})
        self.podium(run, "finding", "add", "--key", "gate-reran", *FINDING)
        self.assertEqual([r["run"] for r in self.on_ref("shared-api")], ["shared-api"])

    def test_finding_events_are_major_even_when_the_extension_decides_the_rest(self):
        with open(self.ext, "a") as f:
            f.write("def SYNC_MAJOR(event):\n    return False\n")
        p = Podium(self.run_at("api"))
        self.assertTrue(sync.is_major(p, {"type": "finding"}))
        self.assertTrue(sync.is_major(p, {"type": "finding-resolved"}))
        self.assertFalse(sync.is_major(p, {"type": "status"}))

    def test_turning_sync_on_or_off_keeps_the_runs_slug(self):
        run = self.run_at("api", sync={"enabled": True, "ref": "refs/heads/podium-run/shared-api"})
        self.podium(run, "finding", "add", "--key", "while-on", *FINDING)
        self.run_at("api", sync={"enabled": False, "ref": "refs/heads/podium-run/shared-api"})
        self.podium(run, "finding", "add", "--key", "while-off", *FINDING)
        self.assertEqual([r["key"] for r in self.on_ref("shared-api")], ["while-on", "while-off"])

    def test_a_remote_that_looks_like_a_flag_is_refused(self):
        run = self.run_at("api")
        self.podium(run, "finding", "wontfix", "gate-reran", "--why", "rare", "--remote", "--upload-pack=x", code=1)
        self.podium(None, "findings", "--all", "--remote", "-x", code=1)
        self.podium(None, "findings", "--recur", "--remote", "--upload-pack=x", code=1)
        self.assertFalse(os.path.exists(os.path.join(run, "podium", "events.jsonl")))

    def test_an_unsynced_run_is_named_after_its_folder_or_its_repo_for_a_hidden_one(self):
        feature = os.path.join(self.tmp, "parkster-features", "Pay Later")
        os.makedirs(os.path.join(feature, "podium"))
        with open(os.path.join(feature, "podium", "podium.json"), "w") as f:
            json.dump({"orchestrator": {"extension": self.ext}}, f)
        self.podium(feature, "finding", "add", "--key", "gate-reran", *FINDING)
        self.podium(self.run_at("api"), "finding", "add", "--key", "gate-reran", *FINDING)
        self.assertEqual([r["run"] for r in self.on_ref("pay-later")], ["pay-later"])
        self.assertEqual([r["run"] for r in self.on_ref("api")], ["api"])

    def test_two_people_pushing_to_one_runs_ref_at_once_keep_both_lines(self):
        run = self.run_at("api")
        push = sync.Git.push
        raced = []

        def bob_pushes_first(g, sha):
            if not raced:
                raced.append(True)
                self.podium(run, "finding", "add", "--key", "bob-found", *FINDING, me="bob", home=os.path.join(self.tmp, "bob"))
            return push(g, sha)

        os.environ["PODIUM_ME"] = "ann"
        out = io.StringIO()
        with unittest.mock.patch.object(sync.Git, "push", bob_pushes_first), contextlib.redirect_stdout(out):
            findings.cmd_finding(Podium(run), ["add", "--key", "ann-found", *FINDING])
        self.assertEqual(out.getvalue(), "FINDING ann-found recorded (pushed)\n")
        self.assertEqual(sorted(r["key"] for r in self.on_ref("api")), ["ann-found", "bob-found"])

    def test_two_runs_push_to_their_own_refs(self):
        self.podium(self.run_at("api"), "finding", "add", "--key", "gate-reran", *FINDING)
        self.podium(self.run_at("web"), "finding", "add", "--key", "gate-reran", *FINDING, me="bo")
        self.assertEqual([r["by"] for r in self.on_ref("api")], ["ann"])
        self.assertEqual([r["by"] for r in self.on_ref("web")], ["bo"])
        self.assertEqual(self.all(), ["FINDING gate-reran ×2 open retro feature-qa normal — Gate reran"])

    def test_a_finding_the_remote_could_not_take_goes_with_the_next_push(self):
        run = self.run_at("api")
        shutil.move(self.remote, self.remote + ".away")
        [line] = self.podium(run, "finding", "add", "--key", "first-one", *FINDING)
        self.assertRegex(line, r"^FINDING first-one recorded \(not pushed: .+\)$")
        shutil.move(self.remote + ".away", self.remote)
        self.podium(run, "finding", "add", "--key", "second-one", *FINDING)
        self.assertEqual(sorted(r["key"] for r in self.on_ref("api")), ["first-one", "second-one"])

    def test_resolve_and_wontfix_push_resolution_records_and_events(self):
        run = self.run_at("api")
        self.assertEqual(self.podium(run, "finding", "resolve", "gate-reran", "--sha", "abcdef0123", "--repo", "skills"),
                         ["FINDING gate-reran resolved abcdef0 (pushed)"])
        self.assertEqual(self.podium(run, "finding", "wontfix", "slow-docs", "--why", "rare"),
                         ["FINDING slow-docs wontfix (pushed)"])
        self.assertEqual([(r["type"], r["key"], r.get("sha"), r.get("why")) for r in self.on_ref("api")],
                         [("resolved", "gate-reran", "abcdef0123", None), ("wontfix", "slow-docs", None, "rare")])
        self.assertEqual([(e["type"], e["resolution"]) for e in self.events(run)],
                         [("finding-resolved", "resolved"), ("finding-resolved", "wontfix")])

    def test_a_malformed_finding_is_refused_and_records_nothing(self):
        run = self.run_at("api")
        self.podium(run, "finding", "add", "--key", "Not A Slug", *FINDING, code=1)
        self.podium(run, "finding", "add", "--key", "gate-reran", *FINDING, "--saving", "100", code=1)
        self.podium(run, "finding", "add", "--key", "gate-reran", *FINDING[:-1], "urgent", code=1)
        self.podium(run, "finding", "resolve", "gate-reran", "--sha", "abc", code=1)
        self.assertFalse(os.path.exists(os.path.join(run, "podium", "events.jsonl")))
        self.assertEqual(self.on_ref("api"), [])

    def test_adding_a_finding_needs_a_run(self):
        self.podium(None, "finding", "add", "--key", "gate-reran", *FINDING, code=1)

    def test_outside_a_run_resolve_and_wontfix_push_to_the_resolutions_ref_of_each_remote(self):
        other = os.path.join(self.tmp, "other.git")
        git("init", "-q", "--bare", other)
        self.assertEqual(self.podium(None, "finding", "resolve", "gate-reran", "--sha", "abcdef0123", "--repo", "skills",
                                     "--remote", self.remote, "--remote", other),
                         ["FINDING gate-reran resolved abcdef0 (pushed)"] * 2)
        self.assertEqual(self.podium(None, "finding", "wontfix", "slow-docs", "--why", "rare", "--remote", self.remote),
                         ["FINDING slow-docs wontfix (pushed)"])
        self.assertEqual([(r["type"], r["key"], r["by"]) for r in self.on_ref("resolutions")],
                         [("resolved", "gate-reran", "ann"), ("wontfix", "slow-docs", "ann")])
        self.assertEqual(git("--git-dir", other, "for-each-ref", "--format=%(refname)"), "refs/heads/findings/resolutions\n")

    def test_outside_a_run_resolve_and_wontfix_need_a_remote(self):
        self.podium(None, "finding", "resolve", "gate-reran", "--sha", "abc", "--repo", "skills", code=1)
        self.podium(None, "finding", "wontfix", "gate-reran", "--why", "rare", code=1)

    def test_a_resolution_on_the_resolutions_ref_closes_a_key_found_in_a_run(self):
        self.podium(self.run_at("api"), "finding", "add", "--key", "gate-reran", *FINDING)
        self.podium(None, "finding", "resolve", "gate-reran", "--sha", "abcdef0123", "--repo", "skills", "--remote", self.remote)
        self.assertEqual(self.all(), ["FINDING gate-reran ×1 resolved abcdef0 retro feature-qa normal — Gate reran"])


class Listing(Case):
    def test_all_groups_a_key_across_runs_people_and_kinds(self):
        self.seed("api", found("gate-reran", "api", "2026-10-01T10:00:00+00:00"),
                  found("gate-reran", "api", "2026-10-02T10:00:00+00:00", moment="later"),
                  found("big-reads", "api", "2026-10-02T10:00:00+00:00", kind="tokens", saving=300))
        self.seed("web", found("gate-reran", "web", "2026-10-03T10:00:00+00:00", by="bo", kind="tokens", saving=50,
                               title="Gate reran again"),
                  found("big-reads", "web", "2026-10-03T10:00:00+00:00", kind="tokens", saving=200))
        self.assertEqual(self.all(), [
            "FINDING big-reads ×2 open tokens feature-qa normal ~500/wk — big-reads title",
            "FINDING gate-reran ×2 open retro,tokens feature-qa normal ~50/wk — Gate reran again"])
        group = next(g for g in json.loads(self.all("--json")[0]) if g["key"] == "gate-reran")
        self.assertEqual((group["runs"], group["people"], group["moment"]), (["api", "web"], ["ann", "bo"], "m"))

    def test_resolution_closes_a_key_until_a_newer_occurrence_reopens_it(self):
        self.seed("api", found("fixed-key", "api", "2026-10-01T10:00:00+00:00"),
                  found("reopened", "api", "2026-10-01T10:00:00+00:00"),
                  found("declined", "api", "2026-10-01T10:00:00+00:00"),
                  {"type": "resolved", "key": "fixed-key", "sha": "1234567890", "repo": "skills", "by": "ann",
                   "at": "2026-10-02T10:00:00+00:00"},
                  {"type": "resolved", "key": "reopened", "sha": "abcdef9", "repo": "skills", "by": "ann",
                   "at": "2026-10-02T10:00:00+00:00"},
                  {"type": "wontfix", "key": "declined", "why": "rare", "by": "ann", "at": "2026-10-02T10:00:00+00:00"},
                  {"type": "resolved", "key": "nobody-found", "sha": "1", "repo": "x", "by": "ann",
                   "at": "2026-10-02T10:00:00+00:00"})
        self.seed("web", found("reopened", "web", "2026-10-03T10:00:00+00:00"))
        self.assertEqual(self.all(), [
            "FINDING reopened ×2 open retro feature-qa normal — reopened title",
            "FINDING declined ×1 wontfix retro feature-qa normal — declined title",
            "FINDING fixed-key ×1 resolved 1234567 retro feature-qa normal — fixed-key title"])
        self.assertEqual(self.all("--open"), ["FINDING reopened ×2 open retro feature-qa normal — reopened title"])

    def test_an_occurrence_at_the_moment_of_its_resolution_stays_resolved(self):
        self.seed("api", found("same-time", "api", "2026-10-02T10:00:00+00:00"),
                  {"type": "wontfix", "key": "same-time", "why": "w", "by": "ann", "at": "2026-10-02T10:00:00+00:00"})
        self.assertEqual(self.all(), ["FINDING same-time ×1 wontfix retro feature-qa normal — same-time title"])

    def test_a_run_lists_its_own_findings_from_its_events(self):
        run = self.run_at("api")
        self.podium(run, "finding", "add", "--key", "gate-reran", *FINDING)
        self.podium(run, "finding", "wontfix", "gate-reran", "--why", "rare")
        self.assertEqual(self.podium(run, "findings"), ["FINDING gate-reran ×1 wontfix retro feature-qa normal — Gate reran"])
        self.assertEqual(self.podium(run, "findings", "--all"), self.podium(run, "findings"))

    def test_a_finding_event_without_a_key_from_an_older_run_is_no_finding(self):
        run = self.run_at("api")
        os.makedirs(os.path.join(run, "podium"), exist_ok=True)
        with open(os.path.join(run, "podium", "events.jsonl"), "w") as f:
            f.write(json.dumps({"at": "2026-10-01T10:00:00+00:00", "type": "finding", "text": "gate: missing test"}) + "\n")
            f.write(json.dumps({"at": "2026-10-01T10:00:00+00:00", "type": "finding", "key": " ", "text": "blank"}) + "\n")
            f.write(json.dumps({"at": "2026-10-02T10:00:00+00:00", "type": "finding-resolved", "resolution": "wontfix"}) + "\n")
        self.podium(run, "finding", "add", "--key", "gate-reran", *FINDING)
        self.assertEqual(self.podium(run, "findings"), ["FINDING gate-reran ×1 open retro feature-qa normal — Gate reran"])
        self.seed("web", {"text": "legacy", "at": "2026-10-01T10:00:00+00:00"}, {"type": "wontfix", "why": "w"})
        self.assertEqual(self.all(), ["FINDING gate-reran ×1 open retro feature-qa normal — Gate reran"])

    def test_outside_a_run_all_needs_a_remote(self):
        self.podium(None, "findings", "--all", code=1)
        self.podium(None, "findings", code=1)

    def test_an_unreachable_remote_warns_and_lists_what_it_has(self):
        missing = os.path.join(self.tmp, "missing.git")
        [warning] = self.podium(None, "findings", "--all", "--remote", missing)
        self.assertTrue(warning.startswith(f"WARN findings {missing} "), warning)


class Recur(Case):
    def setUp(self):
        super().setUp()
        self.seed("api", found("twice", "api", "2026-10-01T10:00:00+00:00"), found("once", "api", "2026-10-01T10:00:00+00:00"),
                  found("urgent", "api", "2026-10-01T10:00:00+00:00", severity="high"),
                  found("fixed", "api", "2026-10-01T10:00:00+00:00", severity="high"),
                  {"type": "resolved", "key": "fixed", "sha": "1", "repo": "x", "by": "ann", "at": "2026-10-02T10:00:00+00:00"})
        self.seed("web", found("twice", "web", "2026-10-02T10:00:00+00:00"))
        self.stamp_file = os.path.join(self.tmp, ".podium", "update.json")

    def recur(self, run_dir=None):
        return self.podium(run_dir, "findings", "--recur", *([] if run_dir else ["--remote", self.remote]))

    def stamp(self, at, **others):
        os.makedirs(os.path.dirname(self.stamp_file), exist_ok=True)
        with open(self.stamp_file, "w") as f:
            json.dump({**others, "recur": {"at": at.isoformat(timespec="seconds")}}, f)

    def test_it_lists_open_keys_seen_in_two_runs_or_high(self):
        self.assertEqual(self.recur(), ["RECUR twice ×2 — twice title", "RECUR urgent ×1 — urgent title"])

    def test_a_run_reads_its_extensions_findings_remote(self):
        self.assertEqual(self.recur(self.run_at("api")), ["RECUR twice ×2 — twice title", "RECUR urgent ×1 — urgent title"])

    def test_it_lists_at_most_once_a_day_and_keeps_the_other_stamps(self):
        self.stamp(datetime.now(timezone.utc) - timedelta(hours=23, minutes=59), podium={"at": "x"})
        self.assertEqual(self.recur(), [])
        self.stamp(datetime.now(timezone.utc) - timedelta(hours=24), podium={"at": "x"})
        self.assertEqual(len(self.recur()), 2)
        with open(self.stamp_file) as f:
            stamps = json.load(f)
        self.assertEqual(sorted(stamps), ["podium", "recur"])
        self.assertEqual(stamps["podium"], {"at": "x"})
        self.assertEqual(self.recur(), [])

    def test_a_stamp_in_the_future_does_not_hold_it_back(self):
        self.stamp(datetime.now(timezone.utc) + timedelta(days=2))
        self.assertEqual(len(self.recur()), 2)

    def test_outside_a_run_without_a_remote_it_is_silent_and_leaves_the_stamp(self):
        self.assertEqual(self.podium(None, "findings", "--recur"), [])
        self.assertFalse(os.path.exists(self.stamp_file))

    def test_a_failed_fetch_leaves_the_stamp_so_the_next_turn_tries_again(self):
        missing = os.path.join(self.tmp, "missing.git")
        [warning] = self.podium(None, "findings", "--recur", "--remote", missing)
        self.assertTrue(warning.startswith(f"WARN findings {missing} "), warning)
        self.assertFalse(os.path.exists(self.stamp_file))
        self.assertEqual(len(self.recur()), 2)
        self.assertTrue(os.path.exists(self.stamp_file))


if __name__ == "__main__":
    unittest.main()
