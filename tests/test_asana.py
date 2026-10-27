"""Tests for the Asana plugin: `podium asana link` and `podium asana refresh` in process against a fake Asana (the
plugin's `fetch`), the run extension's on_asana_refresh hook, and the server's Asana requests."""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from podium_dashboard import cli  # noqa: E402
from podium_dashboard.plugins import asana  # noqa: E402
from podium_dashboard.state import Podium  # noqa: E402
from test_server import Server  # noqa: E402

DATA = {"project": {"title": "T"}, "active": {"epic": "e", "milestone": "M1"},
        "epics": [{"id": "e", "title": "E", "milestones": [{"id": "M1", "title": "Feat", "status": "working", "phase": "build",
                                                             "deps": [], "stories": []}]}]}

HOOK = """
def on_asana_refresh(p, task_json):
    m = next((m for m in p.milestones() if (m.get("asana") or {}).get("gid") == task_json["gid"]), None)
    obj = m or p.data["project"]
    p.data.setdefault("hooked", []).append([task_json["gid"], [s["gid"] for s in task_json.get("subtasks", [])],
                                            "syncedAt" in (obj.get("asana") or {})])
    if m and m.get("kind") == "research" and task_json.get("completed"):
        m["status"] = "done"
"""


def task(gid, name, completed=False, subtasks=None):
    t = {"gid": gid, "name": name, "completed": completed, "permalink_url": f"https://app.asana.com/0/0/{gid}",
         "assignee": {"name": "Ann"}, "custom_fields": [{"name": "Size", "display_value": "M"}, {"name": "Empty", "display_value": None}]}
    return {**t, "subtasks": subtasks} if subtasks is not None else t


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.run_dir = os.path.join(self.tmp, "run")
        self.data = copy.deepcopy(DATA)
        env = unittest.mock.patch.dict(os.environ, {"PODIUM_HUMAN": os.path.join(self.tmp, "human.json"), "ASANA_TOKEN": "t"})
        env.start()
        self.addCleanup(env.stop)
        for k in ("PODIUM_DIR", "PODIUM_ME"):
            os.environ.pop(k, None)
        self.tasks, self.projects, self.calls = {}, {}, []

    def write(self):
        os.makedirs(os.path.join(self.run_dir, "podium"), exist_ok=True)
        with open(os.path.join(self.run_dir, "podium", "podium.json"), "w") as f:
            json.dump(self.data, f)

    def state(self):
        with open(os.path.join(self.run_dir, "podium", "podium.json")) as f:
            return json.load(f)

    def events(self):
        try:
            with open(os.path.join(self.run_dir, "podium", "events.jsonl")) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def milestone(self, mid="M1"):
        return next(m for e in self.state()["epics"] for m in e["milestones"] if m["id"] == mid)

    def extension(self, source):
        path = os.path.join(self.tmp, "ext", "orch.py")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(textwrap.dedent(source))
        self.data["orchestrator"] = {"name": "orch", "command": "/orch", "extension": path}

    def fetch(self, path, token, **params):
        self.calls.append((path, token))
        _, kind, gid, *rest = path.split("/")
        found = (self.projects if kind == "projects" else self.tasks).get(gid)
        if found is None:
            raise asana.AsanaError("404 Not Found")
        return copy.deepcopy(found.get("subtasks", []) if rest else found)

    def podium(self, *args):
        self.write()
        out, code = io.StringIO(), 0
        with contextlib.redirect_stdout(out), unittest.mock.patch.object(asana, "fetch", self.fetch):
            try:
                cli.main(["--dir", self.run_dir, *args])
            except SystemExit as e:
                code = e.code
        return out.getvalue().splitlines(), code


class Link(Run):
    def test_links_the_project_an_epic_or_a_milestone_by_the_kind_its_url_names(self):
        self.assertEqual(self.podium("asana", "link", "https://app.asana.com/0/100/200/f"), (["LINKED . to Asana task 200"], 0))
        self.data = self.state()
        self.assertEqual(self.podium("asana", "link", "https://app.asana.com/0/300/list", "epic:e")[1], 0)
        self.data = self.state()
        self.assertEqual(self.podium("asana", "link", "https://app.asana.com/1/9/project/100/task/400?focus=true", "milestone:M1")[1], 0)
        s = self.state()
        self.assertEqual(s["project"]["asana"], {"kind": "task", "gid": "200", "url": "https://app.asana.com/0/100/200/f"})
        self.assertEqual((s["epics"][0]["asana"]["kind"], s["epics"][0]["asana"]["gid"]), ("project", "300"))
        self.assertEqual((self.milestone()["asana"]["kind"], self.milestone()["asana"]["gid"]), ("task", "400"))
        self.assertEqual([(e["type"], e.get("milestone"), e["text"]) for e in self.events()],
                         [("asana", None, "LINKED . to Asana task 200"), ("asana", None, "LINKED epic:e to Asana project 300"),
                          ("asana", "M1", "LINKED milestone:M1 to Asana task 400")])
        self.assertEqual(self.calls, [])

    def test_tells_a_project_link_from_a_task_link(self):
        for url, kind in [("https://app.asana.com/0/100/list", ("project", "100")), ("https://app.asana.com/0/100/board/", ("project", "100")),
                          ("https://app.asana.com/0/100", ("project", "100")), ("https://app.asana.com/0/100/100", ("project", "100")),
                          ("https://app.asana.com/projects/100", ("project", "100")),
                          ("https://app.asana.com/1/9/project/100/overview/7", ("project", "100")),
                          ("https://app.asana.com/0/100/200", ("task", "200")), ("https://app.asana.com/0/0/200/f", ("task", "200")),
                          ("https://app.asana.com/1/9/task/200", ("task", "200")), ("https://app.asana.com/0/inbox/5", None),
                          ("https://app.asana.com/0/0", None), ("http://app.asana.com/0/100/200", None),
                          ("https://evil.example/0/100/200", None), ("not a url", None)]:
            self.assertEqual(asana.parse(url), kind, url)

    def test_refuses_another_link_a_story_or_a_task_another_object_links(self):
        self.data["epics"][0]["asana"] = {"kind": "task", "gid": "200"}
        lines, code = self.podium("asana", "link", "https://app.asana.com/0/inbox/5")
        self.assertIn("not an Asana project or task link", code)
        self.assertIn("already linked to e", self.podium("asana", "link", "https://app.asana.com/0/100/200", "milestone:M1")[1])
        self.assertIn("asana link <url>", self.podium("asana", "link", "https://app.asana.com/0/100/300", "S1")[1])
        self.assertNotIn("asana", self.milestone())
        self.assertEqual(self.events(), [])

    def test_refuses_a_link_whose_id_is_not_ascii_digits(self):
        for url in ("https://app.asana.com/1/9/task/\u0661\u0662", "https://app.asana.com/0/\u00b2/list",
                    "https://app.asana.com/projects/" + "1" * 33, "https://app.asana.com/1/9/task/1%2F2"):
            self.assertIsNone(asana.parse(url), url)
            self.assertIn("not an Asana project or task link", self.podium("asana", "link", url)[1])
        self.assertEqual(asana.parse("https://app.asana.com/projects/" + "1" * 32), ("project", "1" * 32))
        self.assertNotIn("asana", self.state()["project"])

    def test_a_new_link_drops_what_the_old_task_left_and_the_same_one_keeps_it(self):
        self.data["project"]["asana"] = {"gid": "200", "keep": True, "assignee": "Ann", "syncedAt": "2026-10-01T00:00:00+00:00"}
        self.podium("asana", "link", "https://app.asana.com/0/100/200")
        self.assertEqual(self.state()["project"]["asana"]["keep"], True)
        self.data = self.state()
        self.podium("asana", "link", "https://app.asana.com/0/100/300")
        self.assertEqual(self.state()["project"]["asana"], {"kind": "task", "gid": "300", "url": "https://app.asana.com/0/100/300"})


class Refresh(Run):
    def test_without_a_token_says_so_and_exits_3(self):
        self.data["project"]["asana"] = {"kind": "task", "gid": "1"}
        os.environ.pop("ASANA_TOKEN")
        with unittest.mock.patch.object(asana, "KEYCHAIN", "podium-asana-test-absent-item"):
            self.assertEqual(self.podium("asana", "refresh"), (["NO_TOKEN"], 3))
            self.assertEqual(asana.refresh(Podium(self.run_dir)), ["ASANA NO_TOKEN"])
        self.assertEqual(self.calls, [])

    def test_a_run_that_links_nothing_reads_nothing(self):
        self.assertEqual(self.podium("asana", "refresh"), (["ASANA nothing linked"], 0))
        self.assertEqual(asana.refresh(Podium(self.run_dir)), [])
        self.assertEqual(self.calls, [])

    def test_links_obvious_subtasks_asks_about_the_rest_and_never_lands_a_completed_one(self):
        e = self.data["epics"][0]
        e["asana"] = {"kind": "task", "gid": "1"}
        e["milestones"].append({"id": "M2", "title": "Other", "status": "todo"})
        e["milestones"].append({"id": "M3", "title": "Third", "status": "todo"})
        e["milestones"].append({"id": "M4", "title": "Linked", "status": "todo", "asana": {  # read before, unchanged since
            "kind": "task", "gid": "12", "url": "https://app.asana.com/0/0/12", "assignee": "Ann",
            "fields": [{"name": "Size", "value": "M"}], "completed": False, "syncedAt": "2026-10-01T00:00:00+00:00"}})
        self.tasks["1"] = task("1", "Epic", subtasks=[task("10", "M1: feat", completed=True), task("11", "Something new"),
                                                      task("12", "Linked")])
        lines, code = self.podium("asana", "refresh")
        self.assertEqual(code, 0)
        self.assertEqual(lines, ['LINKED M1 to subtask "M1: feat"', "COMPLETED M1 in Asana, not landed: the Podium asks Done?",
                                 'ASK 11 "Something new" → M2 M3 new'])
        m = self.milestone()
        self.assertEqual(m["status"], "working")
        self.assertEqual({k: v for k, v in m["asana"].items() if k != "syncedAt"},
                         {"kind": "task", "gid": "10", "url": "https://app.asana.com/0/0/10", "assignee": "Ann",
                          "fields": [{"name": "Size", "value": "M"}], "completed": True})
        self.assertTrue(m["asana"]["syncedAt"])
        self.assertEqual(self.state()["epics"][0]["asana"]["url"], "https://app.asana.com/0/0/1")
        self.assertEqual(self.calls, [("/tasks/1", "t")])
        self.assertEqual([e["text"] for e in self.events()], lines[:2])

    def test_a_new_subtask_no_milestone_can_take_becomes_a_milestone(self):
        self.data["epics"][0]["asana"] = {"kind": "task", "gid": "1"}
        self.data["epics"][0]["milestones"][0]["asana"] = {"kind": "task", "gid": "10"}
        self.tasks["1"] = task("1", "Epic", subtasks=[task("10", "Feat"), {**task("11", "Billing", completed=True), "notes": "Pay.\n\nMore."}])
        self.assertEqual(self.podium("asana", "refresh")[0], ['NEW M2 done "Billing" in e'])
        m = self.milestone("M2")
        self.assertEqual((m["summary"], m["asana"]["gid"], m["asana"]["completed"]), ("Pay.", "11", True))

    def test_a_milestone_completed_in_asana_asks_done_unless_it_landed(self):
        ms = self.data["epics"][0]["milestones"]
        ms[0]["asana"] = {"kind": "task", "gid": "30"}
        ms.append({"id": "M2", "title": "Shipped", "status": "done", "asana": {"kind": "task", "gid": "31"}})
        self.tasks.update({"30": task("30", "Feat", completed=True, subtasks=[]), "31": task("31", "Shipped", completed=True, subtasks=[])})
        self.assertEqual(self.podium("asana", "refresh"), (["COMPLETED M1 in Asana, not landed: the Podium asks Done?"], 0))
        self.assertEqual((self.milestone()["status"], self.milestone("M2")["asana"]["completed"]), ("working", True))
        self.data = self.state()
        self.assertEqual(self.podium("asana", "refresh"), (["ASANA 2 tasks read, no changes"], 0))

    def test_a_moved_milestone_completed_in_asana_asks_nothing(self):
        ms = self.data["epics"][0]["milestones"]
        ms[0]["asana"] = {"kind": "task", "gid": "30"}
        ms.append({"id": "M2", "title": "Folded", "status": "moved", "movedTo": "M1", "asana": {"kind": "task", "gid": "31"}})
        self.tasks.update({"30": task("30", "Feat", subtasks=[]), "31": task("31", "Folded", completed=True, subtasks=[])})
        self.assertEqual(self.podium("asana", "refresh"), (["ASANA 2 tasks read, no changes"], 0))

    def test_a_new_subtask_never_goes_to_a_moved_milestone(self):
        e = self.data["epics"][0]
        e["asana"] = {"kind": "task", "gid": "1"}
        e["milestones"][0]["asana"] = {"kind": "task", "gid": "10"}
        e["milestones"].append({"id": "M2", "title": "Folded", "status": "moved", "movedTo": "M1"})
        self.tasks["1"] = task("1", "Epic", subtasks=[task("10", "Feat"), task("11", "Folded")])
        self.assertEqual(self.podium("asana", "refresh")[0], ['NEW M3 draft "Folded" in e'])

    def test_refreshes_a_linked_project(self):
        self.data["project"]["asana"] = {"kind": "project", "gid": "300", "syncedAt": "2026-10-01T00:00:00+00:00", "url": "old"}
        self.projects["300"] = {"gid": "300", "name": "P", "permalink_url": "https://app.asana.com/0/300/300", "owner": {"name": "Bo"}, "custom_fields": []}
        self.assertEqual(self.podium("asana", "refresh"),
                         (["ASANA project url https://app.asana.com/0/300/300, assignee Bo, fields, completed False"], 0))
        self.assertEqual((self.state()["project"]["asana"]["assignee"], self.calls), ("Bo", [("/projects/300", "t")]))

    def test_an_older_run_without_a_kind_reads_each_link_as_its_url_says_else_as_a_task(self):
        self.data["project"]["asana"] = {"gid": "200", "url": "https://app.asana.com/0/200/200"}
        self.data["epics"][0]["asana"] = {"gid": "1", "url": "https://app.asana.com/0/200/1"}
        self.data["epics"][0]["milestones"][0]["asana"] = {"gid": "10"}
        self.projects["200"] = {"gid": "200", "name": "P", "permalink_url": "https://app.asana.com/0/200/200"}
        self.tasks.update({"1": task("1", "Epic", subtasks=[]), "10": task("10", "Feat", subtasks=[])})
        self.assertEqual(self.podium("asana", "refresh")[1], 0)
        self.assertEqual(self.calls, [("/tasks/1", "t"), ("/projects/200", "t"), ("/tasks/10", "t")])
        s = self.state()
        self.assertEqual([s["project"]["asana"]["kind"], s["epics"][0]["asana"]["kind"], self.milestone()["asana"]["kind"]],
                         ["project", "task", "task"])

    def test_reads_the_subtasks_apart_when_asana_does_not_embed_them(self):
        self.data["epics"][0]["asana"] = {"kind": "task", "gid": "1"}
        self.data["epics"][0]["milestones"][0]["asana"] = {"kind": "task", "gid": "10"}
        self.tasks["1"] = task("1", "Epic")
        fetch = self.fetch
        self.fetch = lambda path, token, **params: [task("10", "Feat", completed=True)] if path.endswith("/subtasks") else fetch(path, token, **params)
        self.assertEqual(self.podium("asana", "refresh")[0], ["COMPLETED M1 in Asana, not landed: the Podium asks Done?"])

    def test_a_link_whose_gid_is_not_an_asana_id_is_skipped_as_an_error_and_never_read(self):
        self.data["project"]["asana"] = {"kind": "project", "gid": "../users/me"}
        self.data["epics"][0]["asana"] = {"kind": "task", "url": "https://app.asana.com/1/9/task/\u0661\u0662"}
        self.data["epics"][0]["milestones"][0]["asana"] = {"kind": "task", "gid": "1" * 33}
        self.assertEqual(self.podium("asana", "refresh"), (["ASANA-ERROR epic e: not an Asana id", "ASANA-ERROR project: not an Asana id",
                                                            "ASANA-ERROR M1: not an Asana id"], 1))
        self.assertEqual(self.calls, [])
        self.data = self.state()
        self.data["epics"][0]["milestones"][0]["asana"]["gid"] = "1" * 32
        self.tasks["1" * 32] = task("1" * 32, "Feat", subtasks=[])
        self.assertEqual(self.podium("asana", "refresh")[0][-1], "ASANA-ERROR project: not an Asana id")
        self.assertEqual(self.calls, [(f"/tasks/{'1' * 32}", "t")])

    def test_an_unreadable_task_is_an_error_that_exits_1_and_the_rest_still_refreshes(self):
        self.data["epics"][0]["asana"] = {"kind": "task", "gid": "9"}
        self.data["epics"][0]["milestones"][0]["asana"] = {"kind": "task", "gid": "10"}
        self.tasks["10"] = task("10", "Feat", subtasks=[])
        self.assertEqual(self.podium("asana", "refresh"), (["ASANA-ERROR 9: 404 Not Found"], 1))
        self.assertEqual(self.milestone()["asana"]["url"], "https://app.asana.com/0/0/10")


class Hook(Run):
    def test_the_extension_sees_each_task_with_its_subtasks_first_and_can_finish_research(self):
        self.extension(HOOK)
        self.data["project"]["asana"] = {"kind": "task", "gid": "40"}
        ms = self.data["epics"][0]["milestones"]
        ms[0]["asana"] = {"kind": "task", "gid": "30"}
        ms.append({"id": "R1", "kind": "research", "title": "Old", "status": "todo", "asana": {"kind": "task", "gid": "20"}})
        self.tasks.update({"40": task("40", "Quest", subtasks=[task("20", "US1: Old question", completed=True), task("21", "US1: New")]),
                           "20": task("20", "US1: Old question", completed=True, subtasks=[]),
                           "30": task("30", "Feat", completed=True, subtasks=[task("31", "Sub")])})
        lines, code = self.podium("asana", "refresh")
        self.assertEqual((lines, code), (["COMPLETED M1 in Asana, not landed: the Podium asks Done?"], 0))
        s = self.state()
        self.assertEqual(s["hooked"], [["40", ["20", "21"], False], ["30", ["31"], False], ["20", [], False]])
        self.assertEqual((self.milestone("R1")["status"], self.milestone("R1")["asana"]["completed"]), ("done", True))
        self.assertTrue(s["project"]["asana"]["syncedAt"])

    def test_an_extension_that_does_not_load_is_an_error_but_the_links_still_refresh(self):
        self.extension("raise RuntimeError('broken')\n")
        self.data["project"]["asana"] = {"kind": "task", "gid": "40"}
        self.tasks["40"] = task("40", "Quest", subtasks=[])
        lines, code = self.podium("asana", "refresh")
        self.assertEqual((len(lines), code), (1, 1))
        self.assertRegex(lines[0], r"^ASANA-ERROR extension .*orch\.py not loadable: RuntimeError: broken$")
        self.assertTrue(self.state()["project"]["asana"]["syncedAt"])


class Requests(Server):
    def test_queues_an_asana_link_and_answer_without_a_watcher_from_the_podium_only(self):
        self.serve()
        link = "/asana?url=https%3A%2F%2Fapp.asana.com%2F0%2F100%2F200"
        self.assertEqual(self.call("POST", link, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("POST", "/asana-done/M1?choice=keep", {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("POST", link, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.requests(), [])
        self.assertEqual(self.call("POST", link, {"Origin": f"http://127.0.0.1:{self.port}"})[0], 202)
        self.assertEqual(self.call("POST", link.replace("/asana", "/asana/e"))[0], 202)
        self.assertEqual(self.call("POST", link.replace("/asana", "/asana/nope"))[0], 404)
        self.assertEqual(self.call("POST", "/asana?url=https%3A%2F%2Fevil.example%2F0%2F1")[0], 400)
        self.assertEqual(self.call("POST", "/asana-done/M1?choice=keep")[0], 202)
        self.assertEqual(self.call("POST", "/asana-done/M1?choice=maybe")[0], 404)
        self.assertEqual(self.requests(), [("asana", None), ("asana", "e"), ("asana-done", "M1")])


if __name__ == "__main__":
    unittest.main()
