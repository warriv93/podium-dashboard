"""Tests for the Podium version each person runs, with git, the install's metadata and GitHub faked."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import version  # noqa: E402
from podium_dashboard.state import Podium  # noqa: E402

URL = "https://github.com/warriv93/podium-dashboard"
OLD, NEW, MINE = "a" * 40, "b" * 40, "c" * 40


class Running(unittest.TestCase):
    def test_a_git_install_runs_its_recorded_commit_from_its_url(self):
        with unittest.mock.patch.object(version, "direct_url", lambda: {"url": URL, "vcs_info": {"vcs": "git", "commit_id": OLD}}):
            self.assertEqual(version.running(), (OLD, URL))

    def test_code_run_from_a_checkout_runs_its_head_from_its_origin(self):
        answers = {("rev-parse", "HEAD"): MINE, ("remote", "get-url", "origin"): URL + ".git"}
        with unittest.mock.patch.object(version, "direct_url", lambda: {"url": "file:///src/podium", "dir_info": {"editable": True}}), \
                unittest.mock.patch.object(version, "git", lambda folder, *args: answers.get(args)):
            self.assertEqual(version.running(), (MINE, URL))

    def test_an_install_with_neither_runs_nothing_known(self):
        with unittest.mock.patch.object(version, "direct_url", lambda: None), unittest.mock.patch.object(version, "git", lambda folder, *args: None):
            self.assertEqual(version.running(), (None, None))


class Behind(unittest.TestCase):
    def setUp(self):
        self.asked = []
        version.COMPARED.clear()
        self.addCleanup(version.COMPARED.clear)

    def compare(self, url, timeout):
        self.asked.append(url)
        return io.BytesIO(json.dumps({"ahead_by": 4, "behind_by": 0}).encode())

    def test_counts_the_commits_a_person_lacks_through_githubs_compare_once_per_pair(self):
        with unittest.mock.patch.object(version, "urlopen", self.compare):
            self.assertEqual(version.behind(URL, OLD, NEW), 4)
            self.assertEqual(version.behind(URL, OLD, NEW), 4)
        self.assertEqual(self.asked, [f"https://api.github.com/repos/warriv93/podium-dashboard/compare/{OLD}...{NEW}"])

    def test_the_latest_commit_or_an_unknown_answer_is_not_behind(self):
        def failing(url, timeout):
            raise OSError("rate limited")
        with unittest.mock.patch.object(version, "urlopen", failing):
            self.assertEqual(version.behind(URL, NEW, NEW), 0)
            self.assertIsNone(version.behind(URL, OLD, NEW))
            self.assertIsNone(version.behind("https://gitlab.com/x/y", OLD, NEW))


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        os.makedirs(os.path.join(self.tmp, "podium"))
        self.data = {"project": {"title": "T"}, "epics": [], "people": {"ann": {}, "bob": {"podium": OLD}}}
        self.write()
        patched = unittest.mock.patch.dict(os.environ, {"PODIUM_ME": "ann"})
        patched.start()
        self.addCleanup(patched.stop)

    def write(self):
        with open(os.path.join(self.tmp, "podium", "podium.json"), "w") as f:
            json.dump(self.data, f)

    def people(self):
        with open(os.path.join(self.tmp, "podium", "podium.json")) as f:
            return json.load(f)["people"]

    def podium(self):
        return Podium(self.tmp)

    def test_records_the_commit_this_person_runs_in_their_people_entry(self):
        version.record(self.podium(), NEW)
        self.assertEqual(self.people(), {"ann": {"podium": NEW}, "bob": {"podium": OLD}})

    def test_a_run_without_people_or_an_unknown_commit_records_nothing(self):
        version.record(self.podium(), None)
        self.assertEqual(self.people()["ann"], {})
        del self.data["people"]
        self.write()
        version.record(self.podium(), NEW)
        with open(os.path.join(self.tmp, "podium", "podium.json")) as f:
            self.assertNotIn("people", json.load(f))


if __name__ == "__main__":
    unittest.main()
