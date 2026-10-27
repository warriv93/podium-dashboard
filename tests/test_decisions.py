"""Tests for epic decisions: `podium decision add|claim|resolve|outscope|invalidate|unresolved`, `podium decisions` with
its frontier and state, their events, and a decision claim through a real sync."""
import json
import os
import unittest

from podium_dashboard import sync
from podium_dashboard.state import Podium
from tests.test_cli import Cli
from tests.test_collab import Machines

DATA = {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"},
        "epics": [{"id": "e", "milestones": [{"id": "M1", "status": "todo", "stories": []}]},
                  {"id": "f", "milestones": [{"id": "M2", "status": "todo", "stories": []}]}]}


class Decisions(Cli):
    def setUp(self):
        super().setUp()
        self.run = self.run_at(os.path.join(self.tmp, "run"), DATA)

    def podium(self, *args, me="a", code=0):
        return super().podium("--dir", self.run, *args, env={"PODIUM_ME": me}, code=code)

    def add(self, question="Which auth?", *flags, type_="discussion"):
        return self.podium("decision", "add", question, "--type", type_, *flags).stdout

    def decisions(self):
        return {d["id"]: d for d in self.state(self.run).get("decisions", [])}

    def events(self):
        path = os.path.join(self.run, "podium", "events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def listing(self, *args):
        return self.podium("decisions", *args).stdout.splitlines()

    def test_add_numbers_an_open_decision_on_the_active_epic_and_records_the_event(self):
        self.assertEqual(self.add("Which auth?", "--affects", "M1, login ,", type_="research"), "DECISION D1 open\n")
        self.assertEqual(self.add("Where do files live?", "--blocked-by", "D1"), "DECISION D2 open\n")
        d1, d2 = self.decisions()["D1"], self.decisions()["D2"]
        self.assertEqual({k: d1[k] for k in ("id", "epic", "question", "type", "affects", "blockedBy", "status")},
                         {"id": "D1", "epic": "e", "question": "Which auth?", "type": "research", "affects": ["M1", "login"],
                          "blockedBy": [], "status": "open"})
        self.assertIn("at", d1)
        self.assertNotIn("owner", d1)
        self.assertEqual((d2["blockedBy"], d2["affects"]), (["D1"], []))
        self.assertEqual([{k: e[k] for k in ("type", "decision", "epic", "kind", "question")} for e in self.events()],
                         [{"type": "decision", "decision": "D1", "epic": "e", "kind": "research", "question": "Which auth?"},
                          {"type": "decision", "decision": "D2", "epic": "e", "kind": "discussion", "question": "Where do files live?"}])

    def test_add_takes_the_next_number_after_the_highest_whatever_the_epic(self):
        self.add()
        self.add("Other", "--epic", "f")
        self.assertEqual(self.add(), "DECISION D3 open\n")
        self.assertEqual(self.decisions()["D2"]["epic"], "f")

    def test_add_refuses_a_bad_type_an_empty_question_an_unknown_epic_or_blocker_and_writes_nothing(self):
        self.assertIn("decision add", self.podium("decision", "add", "Q", "--type", "chat", code=1).stderr)
        self.assertIn("decision add", self.podium("decision", "add", "Q", code=1).stderr)
        self.assertIn("decision add", self.podium("decision", "add", " ", "--type", "research", code=1).stderr)
        self.assertIn("decision add", self.podium("decision", "add", "Q", "--type", code=1).stderr)
        self.assertIn("no epic 'zz'", self.podium("decision", "add", "Q", "--type", "research", "--epic", "zz", code=1).stderr)
        self.assertIn("no decision 'D9'", self.podium("decision", "add", "Q", "--type", "research", "--blocked-by", "D9", code=1).stderr)
        self.assertEqual((self.decisions(), self.events()), ({}, []))

    def test_add_without_an_active_epic_asks_for_one(self):
        self.run_at(self.run, {**DATA, "active": {}})
        self.assertIn("--epic", self.podium("decision", "add", "Q", "--type", "unblock", code=1).stderr)
        self.assertEqual(self.add("Q", "--epic", "f", type_="unblock"), "DECISION D1 open\n")

    def test_a_seventh_open_decision_on_an_epic_is_refused_unless_forced(self):
        for i in range(6):
            self.add(f"Q{i}")
        r = self.podium("decision", "add", "Q7", "--type", "discussion", code=1)
        self.assertEqual(r.stderr, "CAP 6 open decisions on e: resolve, rule out or fold one first\n")
        self.assertEqual(len(self.decisions()), 6)
        self.assertEqual(self.add("Other epic", "--epic", "f"), "DECISION D7 open\n")
        self.assertEqual(self.add("Q7", "--force"), "DECISION D8 open\n")

    def test_a_closed_decision_frees_a_place_under_the_cap(self):
        for i in range(6):
            self.add(f"Q{i}")
        self.podium("decision", "outscope", "D1", "later")
        self.assertEqual(self.add("Q7"), "DECISION D7 open\n")

    def test_claim_makes_an_open_decision_yours_once(self):
        self.add()
        self.assertEqual(self.podium("decision", "claim", "D1").stdout, "CLAIMED D1\n")
        self.assertEqual(self.podium("decision", "claim", "D1").stdout, "CLAIMED D1\n")
        self.assertEqual(self.decisions()["D1"]["owner"], "a")
        self.assertEqual([(e["type"], e["decision"], e["owner"], e.get("from")) for e in self.events()[1:]],
                         [("decision-claimed", "D1", "a", None)])

    def test_claiming_someone_elses_decision_is_refused_unless_forced(self):
        self.add()
        self.podium("decision", "claim", "D1")
        self.assertEqual(self.podium("decision", "claim", "D1", me="b", code=1).stderr, "podium: decision D1 is owned by a\n")
        self.assertEqual(self.decisions()["D1"]["owner"], "a")
        self.assertEqual(self.podium("decision", "claim", "D1", "--force", me="b").stdout, "CLAIMED D1\n")
        self.assertEqual(self.decisions()["D1"]["owner"], "b")
        self.assertEqual({k: self.events()[-1][k] for k in ("type", "owner", "from")}, {"type": "decision-claimed", "owner": "b", "from": "a"})

    def test_claim_refuses_an_unknown_or_closed_decision(self):
        self.assertIn("no decision 'D1'", self.podium("decision", "claim", "D1", code=1).stderr)
        self.add()
        self.podium("decision", "resolve", "D1", "JWT")
        self.assertEqual(self.podium("decision", "claim", "D1", code=1).stderr, "podium: decision D1 is resolved\n")
        self.assertNotIn("owner", self.decisions()["D1"])

    def test_resolve_outscope_and_invalidate_close_with_the_outcome_and_an_event(self):
        for _ in range(3):
            self.add()
        self.podium("decision", "unresolved", "D1", "a price list")
        self.assertEqual(self.podium("decision", "resolve", "D1", "JWT").stdout, "RESOLVED D1\n")
        self.assertEqual(self.podium("decision", "outscope", "D2", "not this epic").stdout, "OUT-OF-SCOPE D2\n")
        self.assertEqual(self.podium("decision", "invalidate", "D3", "the API changed").stdout, "INVALIDATED D3\n")
        ds = self.decisions()
        self.assertEqual([(ds[i]["status"], ds[i]["outcome"]) for i in ("D1", "D2", "D3")],
                         [("resolved", "JWT"), ("out-of-scope", "not this epic"), ("invalidated", "the API changed")])
        self.assertNotIn("missing", ds["D1"])
        self.assertEqual([(e["decision"], e["status"], e["outcome"]) for e in self.events() if e["type"] == "decision-closed"],
                         [("D1", "resolved", "JWT"), ("D2", "out-of-scope", "not this epic"), ("D3", "invalidated", "the API changed")])

    def test_a_resolved_decision_can_still_be_invalidated(self):
        self.add()
        self.podium("decision", "resolve", "D1", "JWT")
        self.assertEqual(self.podium("decision", "invalidate", "D1", "SSO came").stdout, "INVALIDATED D1\n")
        self.assertEqual((self.decisions()["D1"]["status"], self.decisions()["D1"]["outcome"]), ("invalidated", "SSO came"))

    def test_closing_needs_a_known_decision_and_an_outcome(self):
        self.add()
        self.assertIn("no decision 'D9'", self.podium("decision", "resolve", "D9", "x", code=1).stderr)
        self.assertIn('decision resolve <D<n>> "<outcome>"', self.podium("decision", "resolve", "D1", code=1).stderr)
        self.assertIn('decision outscope <D<n>> "<why>"', self.podium("decision", "outscope", "D1", " ", code=1).stderr)
        self.assertEqual(self.decisions()["D1"]["status"], "open")

    def test_unresolved_keeps_it_open_with_its_owner_and_what_is_missing(self):
        self.add()
        self.podium("decision", "claim", "D1")
        self.assertEqual(self.podium("decision", "unresolved", "D1", "the price list").stdout,
                         "OPEN D1 missing: the price list\n")
        d = self.decisions()["D1"]
        self.assertEqual((d["status"], d["owner"], d["missing"]), ("open", "a", "the price list"))
        self.assertEqual({k: self.events()[-1][k] for k in ("type", "decision", "missing")},
                         {"type": "decision-unresolved", "decision": "D1", "missing": "the price list"})

    def test_closing_or_unresolving_someone_elses_decision_is_refused_unless_forced(self):
        self.add()
        self.podium("decision", "claim", "D1")
        for args in (("resolve", "D1", "JWT"), ("outscope", "D1", "later"), ("invalidate", "D1", "gone"),
                     ("unresolved", "D1", "keys")):
            self.assertEqual(self.podium("decision", *args, me="b", code=1).stderr, "podium: decision D1 is owned by a\n")
        d = self.decisions()["D1"]
        self.assertEqual((d["status"], d["owner"], d.get("missing")), ("open", "a", None))
        self.assertEqual([e["type"] for e in self.events()], ["decision", "decision-claimed"])
        self.assertEqual(self.podium("decision", "unresolved", "D1", "keys", "--force", me="b").stdout, "OPEN D1 missing: keys\n")
        self.assertEqual(self.podium("decision", "resolve", "D1", "--force", "JWT", me="b").stdout, "RESOLVED D1\n")
        self.assertEqual((self.decisions()["D1"]["status"], self.decisions()["D1"]["owner"]), ("resolved", "a"))

    def test_anyone_may_close_or_unresolve_an_unclaimed_decision(self):
        self.add()
        self.add()
        self.assertEqual(self.podium("decision", "unresolved", "D1", "keys", me="b").stdout, "OPEN D1 missing: keys\n")
        self.assertEqual(self.podium("decision", "invalidate", "D1", "gone", me="b").stdout, "INVALIDATED D1\n")
        self.assertEqual(self.podium("decision", "outscope", "D2", "later", me="c").stdout, "OUT-OF-SCOPE D2\n")

    def test_unresolved_refuses_a_closed_decision_or_no_missing(self):
        self.add()
        self.assertIn('decision unresolved <D<n>> "<missing>"', self.podium("decision", "unresolved", "D1", code=1).stderr)
        self.podium("decision", "resolve", "D1", "JWT")
        self.assertIn("decision D1 is resolved", self.podium("decision", "unresolved", "D1", "x", code=1).stderr)

    def test_an_unknown_verb_prints_the_usage(self):
        for args in ((), ("drop", "D1")):
            self.assertIn("decision unresolved", self.podium("decision", *args, code=1).stderr)

    def test_decisions_lists_each_line_the_frontier_and_the_state(self):
        self.add("Which auth?")
        self.add("Where do files live?", "--blocked-by", "D1", type_="research")
        self.add("Get API keys", type_="unblock")
        self.podium("decision", "claim", "D3")
        self.assertEqual(self.listing(), ["DECISION D1 open discussion - blocked=- — Which auth?",
                                          "DECISION D2 open research - blocked=D1 — Where do files live?",
                                          "DECISION D3 open unblock a blocked=- — Get API keys",
                                          "FRONTIER D1", "STATE ACTIVE"])
        self.podium("decision", "resolve", "D1", "JWT")
        self.assertEqual(self.listing()[:2], ["DECISION D1 resolved discussion - blocked=- — Which auth?",
                                              "DECISION D2 open research - blocked=- — Where do files live?"])
        self.assertEqual(self.listing()[-2:], ["FRONTIER D2", "STATE ACTIVE"])

    def test_decisions_without_any_is_clear(self):
        self.assertEqual(self.listing(), ["FRONTIER none", "STATE CLEAR"])

    def test_the_state_ladder_falls_from_active_to_waiting_to_blocked_to_clear(self):
        self.add("A")
        self.add("B", "--blocked-by", "D1")
        self.assertEqual(self.listing()[-2:], ["FRONTIER D1", "STATE ACTIVE"])
        self.podium("decision", "claim", "D1")
        self.assertEqual(self.listing()[-2:], ["FRONTIER none", "STATE WAITING"])
        self.podium("decision", "invalidate", "D1", "gone")
        self.assertEqual(self.listing()[-2:], ["FRONTIER D2", "STATE ACTIVE"])
        self.podium("decision", "resolve", "D2", "done")
        self.assertEqual(self.listing()[-2:], ["FRONTIER none", "STATE CLEAR"])

    def test_open_decisions_held_only_by_open_blockers_on_another_epic_are_blocked(self):
        self.add("Elsewhere", "--epic", "f")
        self.podium("decision", "claim", "D1")
        self.add("Here", "--blocked-by", "D1")
        self.assertEqual(self.listing("--epic", "e"), ["DECISION D2 open discussion - blocked=D1 — Here", "FRONTIER none", "STATE BLOCKED"])
        self.assertEqual(self.listing("--epic", "f")[-1], "STATE WAITING")
        self.assertEqual(self.listing()[-1], "STATE WAITING")

    def test_decisions_json_carries_the_records_the_frontier_and_the_state(self):
        self.add("A")
        self.add("B", "--epic", "f")
        out = json.loads(self.podium("decisions", "--epic", "f", "--json").stdout)
        self.assertEqual(([d["id"] for d in out["decisions"]], out["frontier"], out["state"]), (["D2"], ["D2"], "ACTIVE"))

    def test_decisions_refuses_an_unknown_epic_or_argument(self):
        self.assertIn("no epic 'zz'", self.podium("decisions", "--epic", "zz", code=1).stderr)
        self.assertIn("decisions [--epic <id>] [--json]", self.podium("decisions", "D1", code=1).stderr)

    def test_decisions_reads_hostile_records_without_failing(self):
        self.run_at(self.run, {**DATA, "decisions": ["x", {"id": ["D1"], "status": "open", "blockedBy": [{}]},
                                                     {"id": "D2", "status": "open", "blockedBy": [["D1"], "D9"], "type": "research"}]})
        self.assertEqual(self.listing()[-2:], ["FRONTIER D2", "STATE ACTIVE"])
        self.assertEqual(self.add(), "DECISION D3 open\n")


class Major(Cli):
    def test_decision_and_decision_closed_are_major_for_sync_the_others_not(self):
        p = Podium(self.run_at(os.path.join(self.tmp, "run"), DATA))
        for kind, major in (("decision", True), ("decision-closed", True), ("decision-claimed", False), ("decision-unresolved", False)):
            self.assertEqual(sync.is_major(p, {"type": kind, "decision": "D1"}), major, kind)

    def test_a_save_message_names_the_decision(self):
        self.assertEqual(sync.describe({"type": "decision-closed", "decision": "D3", "status": "resolved"}), "D3 decision-closed resolved")


class SyncedDecisions(Machines):
    def test_adding_and_closing_a_decision_push_on_their_own(self):
        self.assertRegex(self.podium(self.a, "decision", "add", "Which auth?", "--type", "discussion", me="a").stdout,
                         r"DECISION D1 open\nSAVED [0-9a-f]{7} D1 decision\n")
        self.assertEqual(self.remote_state()["decisions"][0]["status"], "open")
        self.assertRegex(self.podium(self.a, "decision", "resolve", "D1", "JWT", me="a").stdout, r"SAVED [0-9a-f]{7} D1 decision-closed resolved")
        self.assertEqual(self.remote_state()["decisions"][0]["status"], "resolved")

    def test_a_decision_claimed_on_another_machine_is_refused_after_the_pull(self):
        self.podium(self.a, "decision", "add", "Which auth?", "--type", "discussion", me="a")
        self.podium(self.a, "decision", "claim", "D1", me="a")
        self.assertEqual(self.remote_state()["decisions"][0]["owner"], "a")
        r = self.podium(self.b, "decision", "claim", "D1", me="b", code=1)
        self.assertEqual(r.stderr, "podium: decision D1 is owned by a\n")
        self.podium(self.b, "decision", "claim", "D1", "--force", me="b")
        self.assertEqual(self.remote_state()["decisions"][0]["owner"], "b")

    def test_adding_pulls_first_so_two_machines_number_apart(self):
        self.podium(self.a, "decision", "add", "A", "--type", "discussion", me="a")
        self.assertIn("DECISION D2 open", self.podium(self.b, "decision", "add", "B", "--type", "research", me="b").stdout)
        self.assertEqual([d["id"] for d in self.remote_state()["decisions"]], ["D1", "D2"])


if __name__ == "__main__":
    unittest.main()
