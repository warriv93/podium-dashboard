"""Tests for `podium self-update`, with the installed dist's metadata and every git and pip call faked."""
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
from podium_dashboard import cli, human, update  # noqa: E402

URL = "https://github.com/warriv93/podium-dashboard"
OLD = "a" * 40
NEW = "b" * 40
FROM_GIT = {"url": URL, "vcs_info": {"vcs": "git", "commit_id": OLD}}


class SelfUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.calls = []
        self.head, self.pip_version, self.ls_remote_fails = NEW, "24.0", None
        self.dist = FROM_GIT
        for target, name, value in ((human, "HUMAN_FILE", os.path.join(self.tmp, "podium", "human.json")),
                                    (update, "run", self.fake_run),
                                    (update, "direct_url", lambda: self.dist)):
            patched = unittest.mock.patch.object(target, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def fake_run(self, argv, timeout):
        self.calls.append((argv, timeout))
        if "ls-remote" in argv:
            if self.ls_remote_fails:
                raise self.ls_remote_fails
            return subprocess.CompletedProcess(argv, 0, f"{self.head}\tHEAD\n", "")
        if argv[1:] == ["-m", "pip", "--version"]:
            return subprocess.CompletedProcess(argv, 0, f"pip {self.pip_version} from /x (python 3.9)\n", "")
        if argv[1:3] == ["-m", "pip"]:
            if argv[-1] == "pip":
                self.pip_version = "24.0"
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"unexpected command {argv}")

    def podium(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["self-update", *args])
        return out.getvalue().splitlines()

    def installs(self):
        return [argv[4:] for argv, _ in self.calls if argv[1:4] == ["-m", "pip", "install"]]

    def stamp(self, at=None, **others):
        os.makedirs(os.path.dirname(update.stamp_file()), exist_ok=True)
        data = {**others, **({"podium": {"at": at.isoformat(timespec="seconds")}} if at else {})}
        with open(update.stamp_file(), "w") as f:
            json.dump(data, f)

    def stamps(self):
        with open(update.stamp_file()) as f:
            return json.load(f)

    def test_an_editable_install_is_skipped_without_a_network_call(self):
        self.dist = {"url": "file:///src/podium-dashboard", "dir_info": {"editable": True}}
        self.assertEqual(self.podium(), ["SKIP podium editable"])
        self.assertEqual(self.calls, [])

    def test_an_install_not_from_git_is_skipped(self):
        for dist in (None, {"url": "file:///tmp/podium.whl", "archive_info": {}}):
            self.dist = dist
            self.assertEqual(self.podium(), ["SKIP podium not from git"])
        self.assertEqual(self.calls, [])

    def test_an_install_at_the_remote_head_is_ok(self):
        self.head = OLD
        self.assertEqual(self.podium(), ["OK podium aaaaaaa"])
        self.assertEqual(self.installs(), [])

    def test_an_install_behind_the_remote_head_is_upgraded_and_asks_for_a_server_restart(self):
        self.assertEqual(self.podium(), ["UPDATED podium aaaaaaa→bbbbbbb", "RESTART server"])
        self.assertEqual(self.installs(), [["--user", "--quiet", "--upgrade", f"git+{URL}"]])
        self.assertEqual([t for argv, t in self.calls if "ls-remote" in argv], [20])
        self.assertTrue(all(t == 300 for argv, t in self.calls if "ls-remote" not in argv))

    def test_check_reports_behind_and_installs_nothing(self):
        self.assertEqual(self.podium("--check"), ["BEHIND podium aaaaaaa→bbbbbbb"])
        self.assertEqual(self.installs(), [])
        self.assertFalse(os.path.exists(update.stamp_file()))

    def test_a_check_within_six_hours_is_skipped_unless_forced(self):
        self.stamp(datetime.now(timezone.utc) - timedelta(hours=5, minutes=59))
        self.assertEqual(self.podium(), ["SKIP podium checked within 6h"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.podium("--force"), ["UPDATED podium aaaaaaa→bbbbbbb", "RESTART server"])

    def test_a_check_six_hours_ago_runs_again_and_stamps_the_machine(self):
        self.stamp(datetime.now(timezone.utc) - timedelta(hours=6))
        self.head = OLD
        self.assertEqual(self.podium(), ["OK podium aaaaaaa"])
        self.assertEqual(self.podium(), ["SKIP podium checked within 6h"])
        self.assertEqual(os.path.dirname(update.stamp_file()), os.path.dirname(human.HUMAN_FILE))

    def test_the_stamp_keeps_the_skills_keys_and_only_its_own_key_throttles(self):
        recent = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.stamp(**{"skills:/x": recent})
        self.head = OLD
        self.assertEqual(self.podium(), ["OK podium aaaaaaa"])
        self.assertEqual(self.stamps()["skills:/x"], recent)
        self.assertEqual(sorted(self.stamps()), ["podium", "skills:/x"])

    def test_a_malformed_stamp_file_is_replaced(self):
        os.makedirs(os.path.dirname(update.stamp_file()), exist_ok=True)
        with open(update.stamp_file(), "w") as f:
            f.write("[not json")
        self.head = OLD
        self.assertEqual(self.podium(), ["OK podium aaaaaaa"])
        self.assertEqual(list(self.stamps()), ["podium"])

    def test_a_stamp_in_the_future_does_not_hold_the_check_back(self):
        self.stamp(datetime.now(timezone.utc) + timedelta(days=2))
        self.head = OLD
        self.assertEqual(self.podium(), ["OK podium aaaaaaa"])

    def test_an_ls_remote_failure_warns_and_exits_zero(self):
        for failure, why in ((subprocess.TimeoutExpired("git", 20), "git ls-remote timed out after 20s"),
                             (OSError("No such file or directory: 'git'"), "git ls-remote: No such file")):
            self.ls_remote_fails = failure
            lines = self.podium("--force")
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith(f"WARN podium {why}"), lines)
        self.assertEqual(self.installs(), [])

    def test_a_pip_install_failure_warns(self):
        def failing(argv, timeout):
            if argv[1:4] == ["-m", "pip", "install"]:
                return subprocess.CompletedProcess(argv, 1, "", "Collecting…\nERROR: could not resolve host\n")
            return self.fake_run(argv, timeout)
        update.run = failing
        self.assertEqual(self.podium(), ["WARN podium pip install: ERROR: could not resolve host"])

    def test_a_pip_before_22_is_upgraded_first(self):
        self.pip_version = "21.2.4"
        self.assertEqual(self.podium(), ["UPDATED podium aaaaaaa→bbbbbbb", "RESTART server"])
        self.assertEqual(self.installs(), [["--user", "--quiet", "--upgrade", "pip"],
                                           ["--user", "--quiet", "--upgrade", f"git+{URL}"]])

    def test_a_current_pip_is_left_alone(self):
        self.pip_version = "22.0"
        self.podium()
        self.assertEqual(self.installs(), [["--user", "--quiet", "--upgrade", f"git+{URL}"]])

    def test_an_unknown_flag_is_refused(self):
        with self.assertRaises(SystemExit):
            self.podium("--now")


if __name__ == "__main__":
    unittest.main()
