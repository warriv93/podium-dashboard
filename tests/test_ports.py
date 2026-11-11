"""Tests for per-machine port leases: which port a run takes at start, what ports.json keeps, the hourly refresh, and
`podium ports`."""
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
from podium_dashboard import human, ports  # noqa: E402

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
FIRST, COUNT = 8765, 20


def ago(**delta):
    return (NOW - timedelta(**delta)).isoformat(timespec="seconds")


class Leases(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patch = unittest.mock.patch.object(human, "HUMAN_FILE", os.path.join(self.tmp, "home", "human.json"))
        patch.start()
        self.addCleanup(patch.stop)
        self.busy, self.serves = set(), {}
        for name, fake in (("busy", lambda port: port in self.busy), ("serving", lambda port: self.serves.get(port))):
            patch = unittest.mock.patch.object(ports, name, fake)
            patch.start()
            self.addCleanup(patch.stop)

    def run_dir(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path, exist_ok=True)
        return path

    def lease(self, slug, port, used=None, **more):
        leases = self.leases()
        leases[slug] = {"port": port, "used": used or ago(hours=1), "dir": self.run_dir(slug), **more}
        os.makedirs(os.path.dirname(ports.path()), exist_ok=True)
        with open(ports.path(), "w") as f:
            json.dump(leases, f)

    def leases(self):
        try:
            with open(ports.path()) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def take(self, slug, explicit=None):
        return ports.take(slug, self.run_dir(slug), FIRST, COUNT, explicit, NOW)

    def test_the_file_lies_beside_human_json(self):
        self.assertEqual(ports.path(), os.path.join(self.tmp, "home", "ports.json"))

    def test_a_run_whose_leased_port_is_free_takes_it_and_marks_it_used(self):
        self.lease("api", 8770, ago(days=2))
        self.assertEqual(self.take("api"), 8770)
        self.assertEqual(self.leases()["api"], {"port": 8770, "used": NOW.isoformat(timespec="seconds"), "dir": self.run_dir("api")})

    def test_a_run_already_served_on_its_leased_port_is_refused(self):
        self.lease("api", 8770)
        self.busy.add(8770)
        self.serves[8770] = "api"
        with self.assertRaises(ports.Served) as raised:
            self.take("api")
        self.assertEqual(raised.exception.port, 8770)
        self.assertEqual(self.leases()["api"]["used"], ago(hours=1))

    def test_a_leased_port_another_process_holds_gives_a_free_port_and_keeps_the_lease(self):
        self.lease("api", 8765)
        self.busy.add(8765)
        self.serves[8765] = "web"
        self.assertEqual(self.take("api"), 8766)
        self.assertEqual(self.leases()["api"]["port"], 8765)
        self.assertEqual(self.leases()["api"]["used"], NOW.isoformat(timespec="seconds"))

    def test_a_run_without_a_lease_takes_the_first_free_port_no_live_lease_holds(self):
        self.lease("web", 8765)
        self.lease("ops", 8766, ago(days=6, hours=23))
        self.busy.add(8767)
        self.assertEqual(self.take("api"), 8768)
        self.assertEqual(self.leases()["api"]["port"], 8768)
        self.assertEqual(set(self.leases()), {"web", "ops", "api"})

    def test_an_expired_lease_counts_as_free_and_goes_when_its_port_is_taken(self):
        self.lease("web", 8765, ago(days=7, seconds=1))
        self.lease("ops", 8766, ago(days=8))
        self.assertEqual(self.take("api"), 8765)
        self.assertEqual(set(self.leases()), {"ops", "api"})

    def test_a_run_takes_its_own_expired_lease_back_while_its_port_is_free(self):
        self.lease("api", 8770, ago(days=30))
        self.assertEqual(self.take("api"), 8770)

    def test_a_pinned_lease_never_expires(self):
        self.lease("web", 8765, ago(days=400), pinned=True)
        self.assertEqual(self.take("api"), 8766)
        self.assertTrue(self.leases()["web"]["pinned"])

    def test_every_port_held_by_a_live_lease_still_gives_a_free_one(self):
        for i in range(COUNT):
            self.lease(f"r{i}", FIRST + i)
        self.busy.add(FIRST)
        self.assertEqual(self.take("api"), FIRST + 1)

    def test_no_free_port_exits(self):
        self.busy.update(range(FIRST, FIRST + COUNT))
        with self.assertRaises(SystemExit) as raised:
            self.take("api")
        self.assertEqual(str(raised.exception), f"no free port in {FIRST}-{FIRST + COUNT - 1}")

    def test_an_explicit_port_overrides_the_lease_and_is_recorded(self):
        self.lease("api", 8770, pinned=True)
        self.busy.add(9000)
        self.assertEqual(self.take("api", explicit=9000), 9001)
        self.assertEqual(self.leases()["api"], {"port": 9001, "used": NOW.isoformat(timespec="seconds"), "dir": self.run_dir("api"),
                                                "pinned": True})

    def test_an_explicit_port_ignores_the_same_run_served_on_its_lease(self):
        self.lease("api", 8770)
        self.busy.add(8770)
        self.serves[8770] = "api"
        self.assertEqual(self.take("api", explicit=8770), 8771)

    def test_a_lease_whose_dir_is_gone_is_dropped_on_the_next_write(self):
        self.lease("gone", 8765)
        shutil.rmtree(self.run_dir("gone"))
        self.lease("web", 8766)
        self.assertEqual(set(self.leases()), {"gone", "web"})
        self.take("api")
        self.assertEqual(set(self.leases()), {"web", "api"})

    def test_a_broken_file_or_lease_counts_as_none(self):
        os.makedirs(os.path.dirname(ports.path()), exist_ok=True)
        for text in ("{", "[]", '{"web": {"port": "8765", "dir": "/"}, "ops": {"port": true, "dir": "/"}, "x": 3}'):
            with open(ports.path(), "w") as f:
                f.write(text)
            self.assertEqual(ports.read(), {})
        self.assertEqual(self.take("api"), 8765)

    def test_the_file_is_replaced_whole(self):
        self.take("api")
        self.assertEqual(os.listdir(os.path.dirname(ports.path())), ["ports.json"])

    def test_the_hourly_refresh_marks_the_lease_used_and_keeps_its_port_and_pin(self):
        self.lease("api", 8765, ago(days=3), pinned=True)
        ports.touch("api", self.run_dir("api"), 8766, NOW)
        self.assertEqual(self.leases()["api"], {"port": 8765, "used": NOW.isoformat(timespec="seconds"), "dir": self.run_dir("api"),
                                                "pinned": True})

    def test_the_refresh_brings_back_a_lease_released_while_serving(self):
        ports.touch("api", self.run_dir("api"), 8766, NOW)
        self.assertEqual(self.leases()["api"]["port"], 8766)

    def test_a_lease_is_live_for_seven_days_and_one_without_a_time_is_not(self):
        self.assertTrue(ports.live({"used": ago(days=6, hours=23)}, NOW))
        self.assertFalse(ports.live({"used": ago(days=7)}, NOW))
        self.assertFalse(ports.live({"used": "soon"}, NOW))
        self.assertFalse(ports.live({}, NOW))
        self.assertTrue(ports.live({"pinned": True}, NOW))
        self.assertFalse(ports.live({"pinned": "yes", "used": ago(days=8)}, NOW))


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = {**os.environ, "PODIUM_HUMAN": os.path.join(self.tmp, "human.json"), "PYTHONPATH": ROOT, "HOME": self.tmp}
        self.env.pop("PODIUM_DIR", None)
        self.file = os.path.join(self.tmp, "ports.json")
        self.web, self.ops = os.path.join(self.tmp, "web"), os.path.join(self.tmp, "ops")
        os.makedirs(self.web)
        os.makedirs(self.ops)
        recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(self.file, "w") as f:
            json.dump({"web": {"port": 1, "used": recent, "dir": self.web},
                       "ops": {"port": 2, "used": "2020-01-01T00:00:00+00:00", "dir": self.ops}}, f)

    def podium(self, *args, code=0):
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", *args], capture_output=True, text=True, env=self.env,
                           cwd=self.tmp)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def leases(self):
        with open(self.file) as f:
            return json.load(f)

    def test_lists_each_lease_by_port_with_whether_it_serves_and_needs_no_run(self):
        lines = self.podium("ports").stdout.splitlines()
        self.assertRegex(lines[0], rf"^web 1 stopped \S+ - {self.web}$")
        self.assertEqual(lines[1], f"ops 2 stopped 2020-01-01T00:00:00+00:00 expired {self.ops}")
        self.assertEqual(len(lines), 2)

    def test_says_where_the_file_is_when_there_are_no_leases(self):
        os.remove(self.file)
        self.assertEqual(self.podium("ports").stdout, f"no leases ({self.file})\n")

    def test_release_removes_a_lease(self):
        self.assertEqual(self.podium("ports", "release", "web").stdout, "released web\n")
        self.assertEqual(set(self.leases()), {"ops"})

    def test_pin_exempts_a_lease_from_expiry_and_unpin_takes_that_back(self):
        self.assertEqual(self.podium("ports", "pin", "ops").stdout, "pinned ops\n")
        self.assertIs(self.leases()["ops"]["pinned"], True)
        self.assertIn(" pinned ", self.podium("ports").stdout.splitlines()[1])
        self.assertEqual(self.podium("ports", "unpin", "ops").stdout, "unpinned ops\n")
        self.assertNotIn("pinned", self.leases()["ops"])

    def test_refuses_an_unknown_slug_or_verb_and_writes_nothing(self):
        before = self.leases()
        self.assertIn("no lease for nope", self.podium("ports", "release", "nope", code=1).stderr)
        self.assertIn("ports [release|pin|unpin <slug>]", self.podium("ports", "drop", "web", code=1).stderr)
        self.assertIn("ports [release|pin|unpin <slug>]", self.podium("ports", "pin", code=1).stderr)
        self.assertEqual(self.leases(), before)


if __name__ == "__main__":
    unittest.main()
