"""Tests for podium.html against a run whose state a hostile collaborator wrote: the page's own script, run in Node
with a stand-in DOM, renders every view and sheet, and what it would put into the document is parsed for markup or
links the run's strings smuggled in. Skipped where Node isn't installed."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
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
        for html in json.loads(r.stdout):
            scan.feed(html)
            scan.close()
            scan.reset()
        return scan

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


if __name__ == "__main__":
    unittest.main()
