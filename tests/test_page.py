"""Tests for podium.html against a run whose state a hostile collaborator wrote: the page's own script, run in Node
with a stand-in DOM, renders every view and sheet, and what it would put into the document is parsed for markup or
links the run's strings smuggled in. Skipped where Node isn't installed."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "podium_dashboard", "podium.html")

X = "\"'><i id=pwn onmouseover=alert(1)>x</i>"
JS = "javascript:alert(1)"
DONE = "2026-10-20T08:00:00+00:00"

RUN = {
    "project": {"title": X, "summary": X, "asana": {"url": JS, "syncedAt": X},
                "quest": {"doc": X, "links": [{"url": JS, "label": X}, {"url": "https://docs.google.com/document/d/1", "label": X}],
                          "tasks": [{"title": X, "asana": {"url": " JaVaScRiPt:alert(1)", "completed": False}}]}},
    "orchestrator": {"name": X, "command": X, "maxAttempts": X, "phases": [["recon", X], ["build", X], X],
                     "stages": {"STARTED": {"doing": X, "step": X, "time": X}}},
    "active": {"epic": "e1", "milestone": "M1"},
    "needsYou": {"story": "M1/S1", "reason": X},
    "repoUrl": JS,
    "assumptions": [{"question": X, "choice": X, "why": X, "short": X, "status": "open", "story": "S1", "milestone": "M1"}],
    "epics": [{
        "id": "e1", "title": X, "summary": X, "mock": {"url": JS},
        "asana": {"url": "java\tscript:alert(1)", "assignee": X, "fields": [{"name": X, "value": X}]},
        "domainStories": {"at": X, "questions": "//evil.example/q", "stories": [{"title": X, "path": "//evil.example/a.svg"}]},
        "milestones": [
            {"id": "M1", "title": X, "summary": X, "status": "working", "phase": "build", "owner": X, "note": X, "branch": X,
             "deps": [X], "covers": [X], "open": [X], "mock": {"path": "/\\evil.example/m.html", "url": JS},
             "asana": {"url": JS, "completed": True},
             "repos": {X: {"branch": X, "base": X, "pr": {"number": X, "url": JS, "state": X}},
                       "api": {"branch": "b", "pr": {"number": 1, "url": "JaVaScRiPt:alert(1)/pull/1", "state": "draft"}}},
             "quality": {"contract": [{"cmd": X, "ok": False, "at": X}],
                         "gate": {"findings": X, "fixed": X, "skipped": X, "note": X, "file": X},
                         "criteria": [{"id": X, "text": X, "pass": False}]},
             "stories": [
                 {"id": "S1", "title": X, "summary": X, "status": "working", "startedAt": X, "model": X, "branch": X,
                  "agent": {"backend": X, "id": X}, "repos": [X], "files": [X], "tasks": [X], "note": X, "failure": X,
                  "approval": {"tool": X, "detail": X}, "deps": [], "brief": X},
                 {"id": "S2", "title": X, "status": "failed", "attempts": X, "deps": ["S1"]},
                 {"id": "S3", "title": X, "status": X, "deps": []},
                 {"id": "S4", "title": X, "status": "done", "finishedAt": DONE, "startedAt": "2026-10-20T07:00:00+00:00",
                  "commits": [{"sha": "abcdef1234", "subject": X, "plus": X, "minus": X, "repo": "api"}]}]},
            {"id": "M2", "title": X, "status": X, "phase": X, "deps": ["M1"], "grilled": True, "shippedAt": X,
             "landedSha": {X: "abc1234"}, "mock": {"url": JS}, "artifacts": [{"name": X, "path": X, "phase": X}]}]}]}

EVENTS = [
    {"type": "planned", "milestone": "M1", "at": "2026-10-20T06:00:00+00:00"},
    {"type": "phase", "milestone": "M1", "phase": "recon", "at": "2026-10-20T06:00:00+00:00"},
    {"type": "phase", "milestone": "M1", "phase": "build", "at": "2026-10-20T06:30:00+00:00"},
    {"type": "pr", "milestone": "M1", "number": X, "url": JS, "state": X, "repo": X, "was": X, "at": X, "by": X},
    {"type": "retry", "story": "S1", "milestone": "M1", "attempt": X, "reason": X, "at": X},
    {"type": X, "text": X, "at": X},
]

PROGRESS = f"2026-10-20T07:00:00+00:00 STARTED {X}\n2026-10-20T07:30:00+00:00 RED {X}\n{DONE} COMMITTED {X}\n"

KEYS = ["constructor", "__proto__", "toString"]
PROTO_RUN = {
    "project": {"title": "T", "quest": {"doc": "toString"}},
    "orchestrator": {"name": "o", "command": "/o", "phases": ["recon", "constructor", "build"],
                     "stages": {"toString": {"doing": "x", "step": 1, "time": "__proto__"}, "constructor": {"time": "toString"}}},
    "active": {"epic": "e1", "milestone": "M1"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "M", "status": "working", "phase": "build", "deps": KEYS,
         "repos": {"__proto__": {"pr": {"number": 1, "state": "constructor"}}, "constructor": {"pr": {"number": 2, "state": "__proto__"}},
                   "toString": {}},
         "stories": [{"id": "constructor", "title": "c", "status": "working", "deps": ["__proto__", "toString"],
                      "startedAt": "2026-10-20T07:00:00+00:00", "spec": "constructor"},
                     {"id": "__proto__", "title": "p", "status": "toString", "deps": ["toString"], "brief": "__proto__"},
                     {"id": "toString", "title": "t", "status": "done", "deps": [], "finishedAt": "2026-10-20T09:00:00+00:00"},
                     {"id": "S1", "title": "s", "status": "constructor", "deps": KEYS}]},
        {"id": "constructor", "title": "c", "status": "__proto__", "phase": "toString", "deps": ["__proto__"]}]}]}
PROTO_EVENTS = [{"type": kind, "milestone": "M1", "story": "constructor", "phase": kind, "state": kind, "at": DONE} for kind in KEYS] + [
    {"type": "phase", "milestone": "M1", "phase": kind, "at": f"2026-10-20T0{i}:00:00+00:00"} for i, kind in enumerate(KEYS)] + [
    {"type": "pr", "milestone": "M1", "number": 3, "state": kind, "at": DONE} for kind in KEYS]
CYCLIC_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "dispatcher": "elsewhere-only",
    "active": {"epic": "e1", "milestone": "M1"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "M", "status": "working", "phase": "build", "deps": ["M2"],
         "stories": [{"id": "S1", "title": "a", "status": "working", "deps": ["S3"], "startedAt": "2026-10-20T07:00:00+00:00"},
                     {"id": "S2", "title": "b", "status": "done", "deps": ["S1"], "overlapAfter": ["S2"],
                      "startedAt": "2026-10-20T07:00:00+00:00", "finishedAt": DONE},
                     {"id": "S3", "title": "c", "status": "todo", "deps": ["S2"], "startedAt": "2026-10-20T07:30:00+00:00"},
                     {"id": "S4", "title": "d", "status": "todo", "deps": ["S1"]}]},
        {"id": "M2", "title": "N", "status": "todo", "deps": ["M1"]}]}]}
PROTO_PROGRESS = "".join(f"2026-10-20T0{i + 6}:00:00+00:00 {kind} note\n" for i, kind in enumerate(reversed(KEYS)))

HARNESS = r"""
const OUT = [];
const els = {};
function element() {
  let html = "";
  const e = {
    get innerHTML() { return html; }, set innerHTML(v) { html = v; OUT.push(v); },
    insertAdjacentHTML(_, v) { OUT.push(v); },
    textContent: "", hidden: false, style: {}, dataset: {}, title: "", value: "", href: "", placeholder: "", open: false,
    outerHTML: "<svg></svg>", clientWidth: 1200, scrollWidth: 1200, scrollHeight: 800, offsetHeight: 50, offsetLeft: 0,
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    setAttribute() {}, removeAttribute() {}, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
  };
  e.parentElement = e; e.lastElementChild = e;
  return e;
}
const node = (key) => (els[key] ||= element());
const FILES = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
Object.assign(globalThis, {
  window: globalThis, location: { href: "http://127.0.0.1:8765/", port: "8765" }, innerWidth: 1400, scrollY: 0,
  document: { getElementById: node, querySelector: (s) => node("query " + s), querySelectorAll: () => [], documentElement: element(),
              addEventListener() {}, visibilityState: "visible", hidden: false, title: "", createElement: element },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  addEventListener() {}, matchMedia: () => ({ matches: false }), scrollTo() {}, requestAnimationFrame: () => 0,
  setInterval: () => 0, setTimeout: () => 0, MutationObserver: class { observe() {} }, CSS: { escape: String }, Node: { TEXT_NODE: 3 },
  fetch: async (path) => {
    const at = String(path).split("?")[0], body = Object.hasOwn(FILES, at) ? FILES[at] : undefined;
    return { ok: body !== undefined, status: body === undefined ? 404 : 200, headers: { get: () => "application/json" },
             text: async () => body, json: async () => JSON.parse(body) };
  },
});
const PROTO = Object.getOwnPropertyNames(Object.prototype);
/*PAGE*/
(async () => {
  await poll();
  for (const [k, v] of Object.entries(JSON.parse(FILES.progress))) S.progress[k] = v;
  S.digestSince = 0;
  render();
  renderEvents();
  await openSheet("__quest");
  for (const E of S.project.epics) {
    setEpic(E.id);
    await openSheet("__root");
    for (const m of E.milestones) {
      setEpic(E.id);
      await openSheet(m.id);
      setView(m.id);
      await openSheet("__root");
      for (const s of m.stories || []) await openSheet(s.id);
      for (let i = 0; i < (m.artifacts || []).length; i++) await openSheet(`A${i + 1}`);
    }
    S.ds = { id: E.id, tab: 0 };
    renderDs();
  }
  const gained = Object.getOwnPropertyNames(Object.prototype).filter((k) => !PROTO.includes(k));
  if (gained.length) throw new Error(`Object.prototype gained ${gained}`);
  process.stdout.write(JSON.stringify(OUT));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs, self.text = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs += [(tag, k, v or "") for k, v in attrs]

    def handle_data(self, data):
        self.text.append(data)


class Avatars(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "span" and "av" in (attrs.get("class") or "").split():
            self.found.append({"cls": attrs["class"].split(), "title": attrs.get("title"), "text": "", "dot": False})
        elif tag == "i" and self.found:
            self.found[-1]["dot"] = True

    def handle_data(self, data):
        if self.found:
            self.found[-1]["text"] += data


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


@unittest.skipUnless(shutil.which("node"), "needs Node to run the page's script")
class HostileRun(unittest.TestCase):
    def rendered(self, run=RUN, events=EVENTS, progress=PROGRESS, stories=("S1", "S2", "S4"), **files):
        with open(PAGE) as f:
            page = f.read()
        script = page[page.index("<script>") + len("<script>"):page.rindex("</script>")]
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        files = {**files, "podium/podium.json": json.dumps(run), "podium/events.jsonl": "".join(json.dumps(e) + "\n" for e in events),
                 "/info": json.dumps({"runDir": "/run", "repoDir": "/repo", "watching": True, "me": "ann", "people": {},
                                      "orchestrator": run["orchestrator"], "paseoServer": X, "stale": False}),
                 "/human": json.dumps({"mode": "available", "until": None, "source": "hours",
                                       "hours": {"days": "Mon-Fri", "from": "07:00", "to": "17:00"}}),
                 "/git": json.dumps({"repos": [], "at": None}),
                 "progress": json.dumps({f"M1/{sid}": progress for sid in stories})}
        with open(os.path.join(tmp, "files.json"), "w") as f:
            json.dump(files, f)
        with open(os.path.join(tmp, "harness.js"), "w") as f:
            f.write(HARNESS.replace("/*PAGE*/", script))
        r = subprocess.run(["node", os.path.join(tmp, "harness.js"), os.path.join(tmp, "files.json")],
                           capture_output=True, text=True, cwd=tmp, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        scan = Scan()
        self.html = json.loads(r.stdout)
        for html in self.html:
            scan.feed(html)
            scan.close()
            scan.reset()
        return scan

    def share_button(self, run):
        """The Share button's label and tooltip, as the last render of the header put them."""
        self.rendered(run, [], PROGRESS, ())
        scan = Scan()
        scan.feed([html for html in self.html if 'data-act="share"' in html][-1])
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        return "".join(scan.text), dict((k, v) for tag, k, v in scan.attrs if tag == "button")["title"]

    def crew(self, people, events, owners=()):
        """The header's avatars, as the last render put them: [] when it showed none."""
        run = json.loads(json.dumps({**CYCLIC_RUN, "people": people}))
        for m, owner in zip(run["epics"][0]["milestones"], owners):
            m["owner"] = owner
        self.rendered(run, events, PROGRESS, ())
        crews = [html for html in self.html if 'class="av ' in html]
        if not crews:
            return []
        scan = Scan()
        scan.feed(crews[-1])
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        avatars = Avatars()
        avatars.feed(crews[-1])
        return avatars.found

    def test_renders_every_string_of_the_run_as_text_and_links_only_http(self):
        scan = self.rendered()
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])
        self.assertEqual({"script", "iframe", "object", "embed"} & set(scan.tags), set())
        links = [v.strip() for _, k, v in scan.attrs if k in ("href", "src")]
        self.assertTrue(links)
        for v in links:
            same_site = v.startswith("/") and not v.startswith(("//", "/\\"))
            self.assertTrue(same_site or v.startswith(("http://", "https://", "vscode://file/", "paseo://h/")), v)
        self.assertIn("https://docs.google.com/document/d/1", links)

        text = "".join(scan.text)
        self.assertGreater(text.count(X), 40)
        steps = [v for _, k, v in scan.attrs if k == "title" and v.startswith(X + ": ")]
        self.assertTrue(steps, "a stepper label in its title")
        for shown in ("Failed · 0/2", "0 findings · 0 fixed · 0 skipped", "Gate · 0 of 0 fixed", "+0 −0", "Attempts0 of 2"):
            self.assertIn(shown, text)
        self.assertIn("Re-read the Asana task and its subtasks", [v for _, k, v in scan.attrs if k == "title"])

    def test_renders_a_run_whose_stories_and_milestones_depend_on_each_other_in_a_cycle(self):
        scan = self.rendered(CYCLIC_RUN, [], PROGRESS, ("S1", "S2", "S3"))
        text = "".join(scan.text)
        self.assertIn("W1", text)
        self.assertNotIn("elsewhere-only", text)
        self.assertNotIn("Dispatcher", text)

    def test_renders_a_run_whose_ids_types_and_states_are_object_prototype_keys(self):
        scan = self.rendered(PROTO_RUN, PROTO_EVENTS, PROTO_PROGRESS, (*KEYS, "S1"), **{"podium/handoffs.json": "null"})
        text = "".join(scan.text)
        for kind in KEYS:
            self.assertIn(kind, text)
        self.assertNotIn("[native code]", text + "".join(v for _, _, v in scan.attrs))


    def test_share_says_what_it_will_do_while_the_run_does_not_sync(self):
        label, tip = self.share_button({**CYCLIC_RUN, "sync": {"enabled": False, "ref": "refs/heads/podium-run/acme"}})
        self.assertEqual(label, "Share")
        self.assertEqual(tip, "Shares this run so a colleague can plan and build milestones beside you. "
                              "Your orchestrator session picks it up and prints the steps.")

    def test_shared_lists_the_colleagues_steps_with_the_runs_ref(self):
        label, tip = self.share_button({**CYCLIC_RUN, "sync": {"enabled": True, "ref": "refs/heads/podium-run/acme"}})
        self.assertEqual(label, "Shared")
        self.assertEqual(tip.splitlines(), [
            "A colleague joins this run in four steps:",
            "1. Install the tool: pip install --user git+https://github.com/warriv93/podium-dashboard",
            "2. Install the o skill",
            "3. In a new empty folder, run /o join refs/heads/podium-run/acme",
            "4. Claim a milestone with podium claim <id>",
            "Click to print them in your orchestrator's chat again."])

    def test_shared_shows_the_extensions_hint_and_a_hostile_ref_as_text(self):
        run = {**CYCLIC_RUN, "orchestrator": {"name": "o", "command": "/o", "shareHint": X}, "sync": {"enabled": True, "ref": X}}
        tip = self.share_button(run)[1].splitlines()
        self.assertEqual((tip[2], tip[3]), (f"2. {X}", f"3. In a new empty folder, run /o join {X}"))

    def test_the_header_shows_everyone_in_people_or_events_with_a_dot_for_recent_activity(self):
        events = [{"type": "note", "text": "t", "by": "bob", "at": ago(hours=3)}, {"type": "note", "text": "t", "by": "bob", "at": "later"},
                  {"type": "note", "text": "t", "by": "ann", "at": ago(minutes=4)}, {"type": "note", "text": "t", "by": "", "at": ago(minutes=1)}]
        found = self.crew({"ann": {"active": {"epic": "e1", "milestone": "M1"}}, "dee": {}}, events, owners=("ann", "bob"))
        self.assertEqual([(a["text"], a["dot"], "me" in a["cls"]) for a in found], [("AN", True, True), ("BO", False, False), ("DE", False, False)])
        self.assertEqual([a["title"].splitlines() for a in found], [
            ["ann (you) · last active 4m ago", "On M1 · Build", "Owns M1"],
            ["bob · last active 3h ago", "Not on a milestone", "Owns M2"],
            ["dee · no activity yet", "Not on a milestone", "Owns no milestone"]])

    def test_the_header_shows_no_avatars_for_a_run_of_one(self):
        self.assertEqual(self.crew({"ann": {"active": {"milestone": "M1"}}}, [{"type": "note", "by": "ann", "at": ago(minutes=1)}]), [])
        self.assertEqual(self.crew({}, []), [])

    def test_the_header_shows_hostile_and_prototype_key_names_as_text(self):
        events = [{"type": "note", "by": name, "at": X} for name in [X, *KEYS]]
        found = self.crew({X: {"active": X}, "ann": {}}, events, owners=(X,))
        self.assertEqual(sorted(a["title"].splitlines()[0] for a in found),
                         sorted([f"{X} · no activity yet", "ann (you) · no activity yet", *(f"{k} · no activity yet" for k in KEYS)]))
        hostile = next(a for a in found if a["title"].startswith(X))
        self.assertEqual(hostile["title"].splitlines()[1:], [f"On {X}", "Owns M1"])

    def test_more_than_five_people_show_four_and_a_chip_naming_the_rest(self):
        people = {name: {} for name in ("ann", "p1", "p2", "p3", "p4", "p5", "p6")}
        found = self.crew(people, [])
        self.assertEqual([a["text"] for a in found], ["AN", "P1", "P2", "P3", "+3"])
        self.assertEqual((found[-1]["cls"], found[-1]["title"]), (["av", "more"], "p4\np5\np6"))
        self.assertEqual([a["text"] for a in self.crew({name: {} for name in list(people)[:5]}, [])], ["AN", "P1", "P2", "P3", "P4"])


if __name__ == "__main__":
    unittest.main()
