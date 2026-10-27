"""Tests for `podium move`: folding a milestone into another, and waits that follow a move."""
import json
import os
import unittest

from tests.test_cli import Cli


def run_data(*milestones):
    return {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M10"},
            "epics": [{"id": "e", "milestones": [{"stories": [], **m} for m in milestones]}]}


class Move(Cli):
    def setUp(self):
        super().setUp()
        self.run = self.run_at(os.path.join(self.tmp, "run"), run_data(
            {"id": "M10", "status": "draft"}, {"id": "M11", "status": "todo"}, {"id": "M12", "status": "todo"}))

    def milestones(self):
        return {m["id"]: m for m in self.state(self.run)["epics"][0]["milestones"]}

    def events(self):
        path = os.path.join(self.run, "podium", "events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def test_moves_a_milestone_into_its_target_and_records_the_event(self):
        out = self.podium("--dir", self.run, "move", "M10", "--to", "M11", "--pattern", "workflow-steps").stdout
        self.assertEqual(out, "MOVED M10 → M11\n")
        ms = self.milestones()
        self.assertEqual((ms["M10"]["status"], ms["M10"]["movedTo"]), ("moved", "M11"))
        self.assertEqual(ms["M11"]["includes"], ["M10"])
        self.assertEqual(ms["M11"]["status"], "todo")
        [event] = self.events()
        self.assertEqual({k: event[k] for k in ("type", "milestone", "to", "pattern")},
                         {"type": "moved", "milestone": "M10", "to": "M11", "pattern": "workflow-steps"})

    def test_the_event_leaves_out_a_pattern_not_given(self):
        self.podium("--dir", self.run, "move", "M10", "--to", "M11")
        self.assertNotIn("pattern", self.events()[0])

    def test_includes_names_each_moved_milestone_once(self):
        self.podium("--dir", self.run, "move", "M10", "--to", "M11")
        self.podium("--dir", self.run, "move", "M10", "--to", "M11")
        self.podium("--dir", self.run, "move", "M12", "--to", "M11")
        self.assertEqual(self.milestones()["M11"]["includes"], ["M10", "M12"])

    def test_moving_again_takes_the_milestone_out_of_the_old_targets_includes(self):
        self.podium("--dir", self.run, "move", "M10", "--to", "M11")
        self.podium("--dir", self.run, "move", "M10", "--to", "M12")
        ms = self.milestones()
        self.assertEqual((ms["M11"]["includes"], ms["M12"]["includes"], ms["M10"]["movedTo"]), ([], ["M10"], "M12"))

    def test_refuses_an_unknown_milestone_or_target_and_writes_nothing(self):
        for args in (("M99", "--to", "M11"), ("M10", "--to", "M99")):
            r = self.podium("--dir", self.run, "move", *args, code=1)
            self.assertIn("no milestone 'M99'", r.stderr)
        self.assertEqual(self.milestones()["M10"]["status"], "draft")
        self.assertEqual(self.events(), [])

    def test_refuses_a_move_without_a_target(self):
        for args in (("M10",), ("M10", "--to"), ("--to", "M11")):
            self.assertIn("move <milestone> --to <target>", self.podium("--dir", self.run, "move", *args, code=1).stderr)

    def test_refuses_to_move_a_milestone_into_itself(self):
        self.assertIn("into itself", self.podium("--dir", self.run, "move", "M10", "--to", "M10", code=1).stderr)
        self.assertNotIn("includes", self.milestones()["M10"])

    def test_refuses_a_target_already_moved_into_the_milestone_directly_or_through_a_chain(self):
        self.podium("--dir", self.run, "move", "M11", "--to", "M12")
        self.podium("--dir", self.run, "move", "M12", "--to", "M10")
        for target in ("M12", "M11"):
            self.assertIn("makes a cycle", self.podium("--dir", self.run, "move", "M10", "--to", target, code=1).stderr)
        self.assertEqual(self.milestones()["M10"]["status"], "draft")
        self.assertEqual(len(self.events()), 2)

    def test_refuses_a_cycle_through_a_milestone_moved_before(self):
        self.podium("--dir", self.run, "move", "M10", "--to", "M11")
        self.podium("--dir", self.run, "move", "M12", "--to", "M10")
        self.assertIn("makes a cycle", self.podium("--dir", self.run, "move", "M10", "--to", "M12", code=1).stderr)


class WaitingThroughMoves(Cli):
    def status_line(self, *milestones):
        waiter = {"id": "M20", "status": "todo", "waitsFor": [{"milestone": "M10", "reason": "r"}]}
        run = self.run_at(os.path.join(self.tmp, "run"), run_data(*milestones, waiter))
        return next(line for line in self.podium("--dir", run, "status", "--all").stdout.splitlines() if line.startswith("  M20 "))

    def test_a_wait_on_a_moved_milestone_names_where_the_chain_ends(self):
        line = self.status_line({"id": "M10", "status": "moved", "movedTo": "M11"},
                                {"id": "M11", "status": "moved", "movedTo": "M12"}, {"id": "M12", "status": "todo"})
        self.assertTrue(line.endswith(" · waiting for M12 (was M10)"), line)

    def test_the_wait_is_met_once_the_final_target_lands_or_is_dropped(self):
        for status in ("done", "dropped"):
            line = self.status_line({"id": "M10", "status": "moved", "movedTo": "M11"},
                                    {"id": "M11", "status": "moved", "movedTo": "M12"}, {"id": "M12", "status": status})
            self.assertNotIn("waiting", line)

    def test_the_chain_stops_at_a_milestone_no_longer_moved(self):
        line = self.status_line({"id": "M10", "status": "moved", "movedTo": "M11"}, {"id": "M11", "status": "done", "movedTo": "M12"},
                                {"id": "M12", "status": "todo"})
        self.assertNotIn("waiting", line)

    def test_a_cycle_of_moves_stops_and_stays_unmet(self):
        line = self.status_line({"id": "M10", "status": "moved", "movedTo": "M11"}, {"id": "M11", "status": "moved", "movedTo": "M10"})
        self.assertTrue(line.endswith(" · waiting for M11 (was M10)"), line)

    def test_a_move_to_an_unknown_milestone_waits_for_it(self):
        line = self.status_line({"id": "M10", "status": "moved", "movedTo": "M99"})
        self.assertTrue(line.endswith(" · waiting for M99 (was M10)"), line)

    def test_a_move_into_the_waiter_itself_is_no_wait(self):
        self.assertNotIn("waiting", self.status_line({"id": "M10", "status": "moved", "movedTo": "M20"}))

    def test_a_moved_milestone_waits_for_nothing(self):
        run = self.run_at(os.path.join(self.tmp, "run"), run_data(
            {"id": "M10", "status": "todo"}, {"id": "M11", "status": "moved", "movedTo": "M12", "waitsFor": [{"milestone": "M10"}]},
            {"id": "M12", "status": "todo"}))
        out = self.podium("--dir", run, "status", "--all").stdout
        self.assertNotIn("waiting", out)

    def test_moves_of_two_awaited_milestones_into_one_name_it_once(self):
        waiter = {"id": "M20", "status": "todo", "waitsFor": [{"milestone": "M10"}, {"milestone": "M11"}]}
        run = self.run_at(os.path.join(self.tmp, "run"), run_data(
            {"id": "M10", "status": "moved", "movedTo": "M12"}, {"id": "M11", "status": "moved", "movedTo": "M12"},
            {"id": "M12", "status": "todo"}, waiter))
        line = next(x for x in self.podium("--dir", run, "status", "--all").stdout.splitlines() if x.startswith("  M20 "))
        self.assertTrue(line.endswith(" · waiting for M12 (was M10)"), line)


if __name__ == "__main__":
    unittest.main()
