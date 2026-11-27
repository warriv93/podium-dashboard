"""Tests for the suite runner: planning test files into timed chunks, listing and running them, and the
`python3 -m tests.check` steps."""
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from tests import check, shards


def ids(file, n):
    return [f"{file}.T.test_{i}" for i in range(n)]


class Plan(unittest.TestCase):
    def test_timings_split_a_heavy_file_and_keep_a_light_file_whole(self):
        chunks = shards.plan({"heavy": ids("heavy", 40), "light": ids("light", 5)}, {"heavy": 300.0, "light": 12.0})

        self.assertEqual([c.file for c in chunks].count("heavy"), 10)
        self.assertEqual([c.file for c in chunks].count("light"), 1)
        self.assertEqual({c.weight for c in chunks if c.file == "heavy"}, {30.0})

    def test_without_timings_a_file_weighs_by_its_test_count(self):
        chunks = shards.plan({"big": ids("big", 90), "small": ids("small", 3)}, {})

        self.assertEqual([c.file for c in chunks].count("big"), 3)
        self.assertEqual([c.file for c in chunks].count("small"), 1)

    def test_an_untimed_file_weighs_by_the_mean_seconds_per_test_of_the_timed_files(self):
        chunks = shards.plan({"timed": ids("timed", 10), "new": ids("new", 30)}, {"timed": 20.0, "gone": 999.0})

        self.assertEqual([c.weight for c in chunks if c.file == "new"], [30.0, 30.0])

    def test_every_id_lands_in_exactly_one_chunk_of_its_own_file(self):
        files = {"a": ids("a", 37), "b": ids("b", 4), "c": ids("c", 1)}

        chunks = shards.plan(files, {"a": 200.0, "b": 90.0, "c": 5.0})

        for c in chunks:
            self.assertTrue(set(c.ids) <= set(files[c.file]))
        planned = [i for c in chunks for i in c.ids]
        self.assertCountEqual(planned, [i for f in files.values() for i in f])

    def test_chunks_come_heaviest_first(self):
        chunks = shards.plan({"a": ids("a", 20), "b": ids("b", 3), "c": ids("c", 9)}, {"a": 100.0, "b": 25.0, "c": 50.0})

        weights = [c.weight for c in chunks]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_a_file_never_has_more_chunks_than_tests(self):
        chunks = shards.plan({"slow": ids("slow", 2)}, {"slow": 600.0})

        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(c.ids) == 1 for c in chunks))

    def test_a_file_without_tests_has_no_chunk(self):
        self.assertEqual(shards.plan({"empty": []}, {"empty": 3.0}), [])


PACKAGE = "shardfixture"

FILES = {
    "__init__.py": "",
    "test_pass.py": """
        import unittest

        class Base(unittest.TestCase):
            def test_one(self):
                pass

            def test_two(self):
                pass
        """,
    "test_fail.py": """
        import unittest

        class Mixed(unittest.TestCase):
            def test_fine(self):
                pass

            def test_broken(self):
                self.assertEqual(1, 2)
        """,
    "test_import.py": f"""
        import unittest

        from {PACKAGE}.test_pass import Base

        class Own(unittest.TestCase):
            def test_own(self):
                pass
        """,
    "test_overlap.py": """
        import os
        import time
        import unittest

        class Overlap(unittest.TestCase):
            def test_overlap(self):
                os.makedirs("running", exist_ok=True)
                me = os.path.join("running", str(os.getpid()))
                open(me, "w").close()
                time.sleep(0.4)
                with open("most-running", "a") as f:
                    f.write(f"{len(os.listdir('running'))}\\n")
                os.remove(me)
        """,
    "test_unimportable.py": "import no_such_module\n",
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, PACKAGE))
        for name, source in FILES.items():
            with open(os.path.join(self.tmp, PACKAGE, name), "w") as f:
                f.write(textwrap.dedent(source))
        self.logs = os.path.join(self.tmp, ".check", "logs")
        sys.path.insert(0, self.tmp)
        self.addCleanup(sys.path.remove, self.tmp)
        self.addCleanup(self.forget_package)

    def forget_package(self):
        for name in [m for m in sys.modules if m == PACKAGE or m.startswith(PACKAGE + ".")]:
            del sys.modules[name]

    def chunk(self, file, *names):
        return shards.Chunk(f"{PACKAGE}/{file}.py", tuple(f"{PACKAGE}.{file}.{n}" for n in names), 1.0)

    def run_chunks(self, chunks, workers=4):
        return shards.run(chunks, workers, self.logs, cwd=self.tmp)


class TestIds(Fixture):
    def test_lists_a_files_own_tests(self):
        self.assertEqual(shards.test_ids(f"{PACKAGE}.test_pass"),
                         [f"{PACKAGE}.test_pass.Base.test_one", f"{PACKAGE}.test_pass.Base.test_two"])

    def test_leaves_out_tests_of_a_base_class_imported_from_another_file(self):
        self.assertEqual(shards.test_ids(f"{PACKAGE}.test_import"), [f"{PACKAGE}.test_import.Own.test_own"])

    def test_a_file_that_fails_to_import_is_listed_as_itself_so_its_run_fails(self):
        module = f"{PACKAGE}.test_unimportable"
        self.assertEqual(shards.test_ids(module), [module])
        result = self.run_chunks([shards.Chunk(f"{PACKAGE}/test_unimportable.py", (module,), 1.0)])
        self.assertFalse(result.ok)

    def test_discovers_every_test_file_by_name(self):
        found = shards.discover(self.tmp, pattern=f"{PACKAGE}/test_*.py")

        self.assertEqual(sorted(found), sorted(f"{PACKAGE}/{n}" for n in FILES if n.startswith("test_")))
        self.assertEqual(found[f"{PACKAGE}/test_import.py"], [f"{PACKAGE}.test_import.Own.test_own"])


class Run(Fixture):
    def test_a_passing_run_reports_the_tests_it_ran_and_each_files_seconds(self):
        result = self.run_chunks([self.chunk("test_pass", "Base.test_one"), self.chunk("test_pass", "Base.test_two"),
                                  self.chunk("test_import", "Own.test_own")])

        self.assertTrue(result.ok)
        self.assertEqual(result.ran, 3)
        self.assertEqual(result.failed_chunks, [])
        self.assertEqual(set(result.seconds_by_file), {f"{PACKAGE}/test_pass.py", f"{PACKAGE}/test_import.py"})
        self.assertTrue(all(s > 0 for s in result.seconds_by_file.values()))

    def test_a_failing_test_fails_the_run_and_names_its_chunk_and_log(self):
        failing = self.chunk("test_fail", "Mixed.test_fine", "Mixed.test_broken")

        result = self.run_chunks([self.chunk("test_pass", "Base.test_one"), failing])

        self.assertFalse(result.ok)
        self.assertEqual(result.ran, 3)
        self.assertEqual([f.chunk for f in result.failed_chunks], [failing])
        with open(result.failed_chunks[0].log) as f:
            self.assertIn("FAIL: test_broken", f.read())

    def test_at_most_workers_chunks_run_at_once(self):
        self.run_chunks([self.chunk("test_overlap", "Overlap.test_overlap")] * 6, workers=2)

        with open(os.path.join(self.tmp, "most-running")) as f:
            self.assertLessEqual(max(int(n) for n in f.read().split()), 2)

    def test_a_run_replaces_the_logs_of_the_run_before(self):
        self.run_chunks([self.chunk("test_pass", "Base.test_one")] * 3)
        self.run_chunks([self.chunk("test_pass", "Base.test_one")])

        self.assertEqual(len(os.listdir(self.logs)), 1)


class Timings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, ".check", "timings.json")

    def test_missing_timings_are_empty(self):
        self.assertEqual(shards.load_timings(self.path), {})

    def test_unreadable_timings_are_empty(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(shards.load_timings(self.path), {})

    def test_saving_merges_over_the_old_timings(self):
        shards.save_timings(self.path, {"a": 10.0, "b": 20.0})
        shards.save_timings(self.path, {"b": 25.0, "c": 5.0})

        self.assertEqual(shards.load_timings(self.path), {"a": 10.0, "b": 25.0, "c": 5.0})


class Main(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.updated = os.path.join(self.tmp, "updated")
        steps = [check.Step("first", run=self.step("first", 0)),
                 check.Step("second", run=self.step("second", 1),
                            update=[sys.executable, "-c", f"open({self.updated!r}, 'w').close()"])]
        patcher = mock.patch.object(check, "STEPS", steps)
        patcher.start()
        self.addCleanup(patcher.stop)

    def step(self, name, code):
        def run(workers):
            self.calls.append((name, workers))
            return code
        return run

    def main(self, *argv):
        out = StringIO()
        with redirect_stdout(out):
            code = check.main(list(argv))
        return code, out.getvalue()

    def test_an_unknown_step_exits_2_and_lists_the_steps(self):
        code, out = self.main("first", "nope")

        self.assertEqual(code, 2)
        self.assertIn("unknown step nope; steps: first, second", out)
        self.assertEqual(self.calls, [])

    def test_a_named_step_runs_alone(self):
        code, out = self.main("first", "--workers", "3")

        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [("first", 3)])
        self.assertRegex(out, r"first  PASS  \d+s")

    def test_every_step_runs_in_order_and_one_failure_fails_the_check(self):
        code, out = self.main()

        self.assertEqual(code, 1)
        self.assertEqual([name for name, _ in self.calls], ["first", "second"])
        self.assertRegex(out, r"second  FAIL  \d+s")

    def test_update_runs_a_steps_update_and_skips_a_step_without_one(self):
        code, out = self.main("--update")

        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.updated))
        self.assertEqual(self.calls, [])
        self.assertIn("first: nothing to update, skipped", out)


class Unit(unittest.TestCase):
    def test_without_node_it_fails_before_any_test(self):
        out = StringIO()
        with mock.patch.object(check.shutil, "which", return_value=None), \
                mock.patch.object(check.shards, "discover") as discover, \
                mock.patch.object(check.shards, "run") as run, redirect_stdout(out):
            code = check.unit(4)

        self.assertEqual(code, 1)
        self.assertIn("node not found: the page tests need Node, install it and rerun", out.getvalue())
        discover.assert_not_called()
        run.assert_not_called()

    def test_reports_each_failing_chunks_file_failing_tests_and_log_tail(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        log = os.path.join(tmp, "chunk.log")
        with open(log, "w") as f:
            f.write("\n".join([f"noise {i}" for i in range(60)] + ["FAIL: test_broken (tests.test_x.T.test_broken)",
                                                                   "ERROR: test_crash (tests.test_x.T.test_crash)",
                                                                   "Ran 2 tests in 0.1s", "FAILED (failures=1)"]))
        chunk = shards.Chunk("tests/test_x.py", ("tests.test_x.T.test_broken",), 1.0)
        result = shards.Result(False, 2, [shards.FailedChunk(chunk, log)], {"tests/test_x.py": 1.5})
        out = StringIO()
        with mock.patch.object(check.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(check.shards, "discover", return_value={"tests/test_x.py": list(chunk.ids)}), \
                mock.patch.object(check.shards, "run", return_value=result), \
                mock.patch.object(check, "CHECK_DIR", os.path.join(tmp, ".check")), redirect_stdout(out):
            code = check.unit(4)

        printed = out.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("ran 2 tests in 1 files, 1 chunks", printed)
        self.assertIn("tests/test_x.py", printed)
        self.assertIn("FAIL: test_broken (tests.test_x.T.test_broken)", printed)
        self.assertIn("ERROR: test_crash (tests.test_x.T.test_crash)", printed)
        self.assertIn("noise 59", printed)
        self.assertNotIn("noise 20\n", printed)
        self.assertEqual(shards.load_timings(os.path.join(tmp, ".check", "timings.json")), {"tests/test_x.py": 1.5})


if __name__ == "__main__":
    unittest.main()
