"""Tests for podium.html against a run whose state a hostile collaborator wrote: the page's own script, run in Node
with a stand-in DOM, renders every view and sheet, and what it would put into the document is parsed for markup or
links the run's strings smuggled in. Skipped where Node isn't installed."""
import json
import os
import re
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
HIDE_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M3"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "first", "status": "done"},
        {"id": "M2", "title": "second", "status": "moved", "movedTo": "M3"},
        {"id": "M3", "title": "third", "status": "working", "phase": "build", "stories": [
            {"id": "S1", "title": "a", "status": "done"}, {"id": "S2", "title": "b", "status": "dropped"},
            {"id": "S3", "title": "c", "status": "done"}, {"id": "S4", "title": "d", "status": "failed", "attempts": 1},
            {"id": "S5", "title": "e", "status": "todo", "deps": ["S4"]}]},
        {"id": "M4", "title": "fourth", "status": "todo"}]}]}
FINISHED_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M2"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "first", "status": "done"},
        {"id": "M2", "title": "second", "status": "working", "phase": "build", "deps": ["M1"],
         "stories": [{"id": "S1", "title": "a", "status": "done"}, {"id": "S2", "title": "b", "status": "done", "deps": ["S1"]},
                     {"id": "S3", "title": "c", "status": "todo", "deps": ["S2"]}]}]}]}
TREE_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M1"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "tree", "status": "working", "phase": "build", "stories": [
            {"id": "S1", "title": "a", "status": "done"}, {"id": "S2", "title": "b", "status": "todo"},
            {"id": "S3", "title": "c", "status": "todo", "deps": ["S2", "S2"]},
            {"id": "S4", "title": "d", "status": "todo", "deps": ["S1"], "overlapAfter": ["S3"]},
            {"id": "S5", "title": "e", "status": "todo", "deps": ["S6", "S9"]}, {"id": "S6", "title": "f", "status": "todo", "deps": ["S5"]},
            {"id": "__proto__", "title": "p", "status": "todo", "deps": ["constructor", "S2", "__proto__"], "overlapAfter": ["S2"]}]},
        {"id": "M2", "title": "order", "status": "todo", "stories": [
            {"id": "A1", "title": "a", "status": "todo"}, {"id": "A2", "title": "b", "status": "todo"}, {"id": "A3", "title": "c", "status": "todo"},
            {"id": "B1", "title": "d", "status": "todo", "deps": ["A3"]}, {"id": "B2", "title": "e", "status": "todo", "deps": ["A1"]},
            {"id": "B3", "title": "f", "status": "todo", "deps": ["A2"]},
            {"id": "C1", "title": "g", "status": "todo", "deps": ["B1"]}, {"id": "C2", "title": "h", "status": "todo", "deps": ["B2"]}]}]}]}
TWIN_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M1"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "first", "status": "working", "phase": "build", "stories": [{"id": "S1", "title": "S1 of M1", "status": "todo"}]},
        {"id": "M2", "title": "second", "status": "todo", "deps": ["M1"], "stories": [{"id": "S1", "title": "S1 of M2", "status": "todo"}]},
        {"id": "M3", "title": "third", "status": "todo", "artifacts": [{"name": "the mock", "path": "mock.md"}]}]}]}
H = "\"'><b onmouseover=alert(1)>h"
EMIT_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M1"},
    "needsYou": {"story": f"M1/{H}", "reason": "r"},
    "assumptions": [{"question": "q", "choice": "c", "why": "w", "status": "open", "story": H, "milestone": "M1"}],
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "M", "status": "working", "phase": "build",
         "stories": [{"id": H, "title": "h", "status": "working", "deps": []}, {"id": "S2", "title": "b", "status": "todo", "deps": [H]}]},
        {"id": "M2", "title": "N", "status": "todo", "deps": ["M1"]}]}]}
OPEN_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e2", "milestone": "M2"},
    "epics": [
        {"id": "e1", "title": "E1", "milestones": [
            {"id": "M1", "title": "first", "status": "done", "stories": [{"id": "S1", "title": "one", "status": "done"}]},
            {"id": "R1", "title": "look", "kind": "research", "status": "todo", "artifacts": [{"name": "notes", "path": "r.md"}]}]},
        {"id": "e2", "title": "E2", "milestones": [
            {"id": "M2", "title": "second", "status": "working", "phase": "build", "deps": ["M1"], "stories": [
                {"id": "S2", "title": "two", "status": "working", "model": "opus-model", "agent": {"backend": "paseo", "id": "ag1"}},
                {"id": "S3", "title": "three", "status": "done"},
                {"id": "S4", "title": "four", "status": "todo", "deps": ["S3"]},
                {"id": "S5", "title": "five", "status": "todo", "deps": ["S2"]}]},
            {"id": "M3", "title": "third", "status": "todo", "deps": ["M2"], "stories": [{"id": "S6", "title": "six", "status": "todo"}]}]}]}
PROTO_PROGRESS = "".join(f"2026-10-20T0{i + 6}:00:00+00:00 {kind} note\n" for i, kind in enumerate(reversed(KEYS)))

HARNESS = r"""
const OUT = [];
const SCROLLS = [];
const els = {};
function element() {
  let html = "";
  const e = {
    get innerHTML() { return html; }, set innerHTML(v) { html = v; OUT.push(v); },
    insertAdjacentHTML(_, v) { OUT.push(v); },
    textContent: "", hidden: false, style: { setProperty() {} }, dataset: {}, title: "", value: "", href: "", placeholder: "", open: false,
    outerHTML: "<svg></svg>", clientWidth: 1200, scrollWidth: 1200, scrollHeight: 800, offsetHeight: 50, offsetLeft: 0,
    classes: new Set(),
    classList: { toggle(c, force) { const on = force ?? !e.classes.has(c); if (on) e.classes.add(c); else e.classes.delete(c); return on; },
                 add(c) { e.classes.add(c); }, remove(c) { e.classes.delete(c); }, contains: (c) => e.classes.has(c) },
    setAttribute() {}, removeAttribute() {}, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
  };
  e.parentElement = e; e.lastElementChild = e;
  return e;
}
const node = (key) => (els[key] ||= element());
const FILES = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
Object.assign(globalThis, {
  window: globalThis, location: { href: "http://127.0.0.1:8765/", hostname: "127.0.0.1", port: "8765", hash: "", ...FILES.location }, innerWidth: 1400, scrollY: 0,
  document: { getElementById: node, querySelector: (s) => node("query " + s), querySelectorAll: () => [], documentElement: element(),
              addEventListener() {}, visibilityState: "visible", hidden: false, title: "", createElement: element },
  localStorage: { getItem: (k) => (FILES.localStorage || {})[k] ?? null, setItem() {}, removeItem() {} },
  addEventListener() {}, getComputedStyle: () => ({ position: "sticky" }), matchMedia: () => ({ matches: false }), scrollTo: (o) => SCROLLS.push(o), requestAnimationFrame: (f) => (f(), 0),
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
  OUT.push("LOADED " + JSON.stringify({ open: S.open ?? null, sel: S.sel }));
  for (const [k, v] of Object.entries(JSON.parse(FILES.progress))) S.progress[k] = v;
  S.digestSince = 0;
  render();
  renderEvents();
  await openSheet({ quest: true });
  for (const E of S.project.epics) {
    await openSheet({ epic: E.id });
    for (const m of E.milestones) {
      await openSheet({ ms: m.id });
      expand(m.id);
      render();
      for (const s of m.stories || []) await openSheet({ ms: m.id, story: s.id });
      for (let i = 0; i < (m.artifacts || []).length; i++) await openSheet({ ms: m.id, story: `A${i + 1}` });
    }
    S.ds = { id: E.id, tab: 0 };
    renderDs();
  }
  collapse();
  if (FILES.doc) await openDoc(...JSON.parse(FILES.doc));
  if (FILES.probe) OUT.push("PROBE " + JSON.stringify(await eval(FILES.probe)));
  const gained = Object.getOwnPropertyNames(Object.prototype).filter((k) => !PROTO.includes(k));
  if (gained.length) throw new Error(`Object.prototype gained ${gained}`);
  OUT.push("SCROLLS " + JSON.stringify(SCROLLS));
  OUT.push("FLASHED " + JSON.stringify(Object.keys(els).filter((k) => els[k].classes.has("flash")).map((k) => /data-id="([^"]*)"/.exec(k)?.[1])));
  OUT.push(`TITLE ${esc(document.title)}`);
  OUT.push(`FEED ${[...node("feed").classes].join(" ")}`);
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


class Opens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-open" in attrs:
            self.found.append(attrs)


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
    def rendered(self, run=RUN, events=EVENTS, progress=PROGRESS, stories=("S1", "S2", "S4"), info=None, **files):
        with open(PAGE) as f:
            page = f.read()
        script = page[page.index("<script>") + len("<script>"):page.rindex("</script>")]
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        files = {**files, "podium/podium.json": json.dumps(run), "podium/events.jsonl": "".join(json.dumps(e) + "\n" for e in events),
                 "/info": json.dumps({"runDir": "/run", "repoDir": "/repo", "watching": True, "me": "ann", "people": {},
                                      "orchestrator": run["orchestrator"], "paseoServer": X, "stale": False, **(info or {})}),
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

    def card_repos(self, milestones):
        """Each milestone card's repo chips in the full map, by id: the chip row's text and PR links, or None for no row."""
        run = {**CYCLIC_RUN, "epics": [{"id": "e1", "title": "E", "milestones": milestones}]}
        self.rendered(run, [], PROGRESS, ())
        cards = {}
        for card in re.split(r'(?=<div class="fms )', [h for h in self.html if 'class="fms ' in h][-1])[1:]:
            row = re.search(r'<div class="ms-repos">(.*?)</div>', card, re.S)
            scan = Scan()
            if row:
                scan.feed(row.group(1))
            cards[re.search(r'data-id="([^"]*)"', card).group(1)] = (
                ("".join(scan.text), [v for tag, k, v in scan.attrs if tag == "a" and k == "href"], scan) if row else None)
        return cards

    def card_dots(self, milestones):
        """Each milestone card's story dots in the full map, by id: the card's expand target and each dot's attributes, or None for no dots."""
        run = {**CYCLIC_RUN, "epics": [{"id": "e1", "title": "E", "milestones": milestones}]}
        self.rendered(run, [], PROGRESS, ())
        page = [h for h in self.html if 'class="fms ' in h][-1]
        cards = {}
        for card in re.split(r'(?=<div class="fms )', page)[1:]:
            row = re.search(r'<span class="fdots"[^>]*>(.*?)</span>', card, re.S)
            dots = [dict(re.findall(r'([\w-]+)="([^"]*)"', tag)) for tag in re.findall(r"<i [^>]*>", row.group(1))] if row else None
            cards[re.search(r'data-id="([^"]*)"', card).group(1)] = (re.search(r'data-expand-ms="([^"]*)"', card.split(">")[0]), dots, card)
        return cards

    def share_button(self, run):
        """The Share button's label and tooltip, as the last render of the header put them."""
        self.rendered(run, [], PROGRESS, ())
        scan = Scan()
        scan.feed([html for html in self.html if 'data-act="share"' in html][-1])
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        return "".join(scan.text), dict((k, v) for tag, k, v in scan.attrs if tag == "button")["title"]

    def fetch_button(self, run, pull=None):
        """The Fetch button's label and tooltip, as the last render of the header put them, or None when it showed none."""
        self.rendered(run, [], PROGRESS, (), info={"pull": pull})
        shown = [html for html in self.html if "data-fetch" in html]
        if not shown:
            return None
        scan = Scan()
        scan.feed(shown[-1])
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        return "".join(scan.text), dict((k, v) for tag, k, v in scan.attrs if tag == "button")["title"]

    def hide_finished_buttons(self, run, stored=None):
        """The label of every Hide finished button the page rendered, in render order."""
        self.rendered(run, [], PROGRESS, (), localStorage=stored or {})
        labels = []
        for html in self.html:
            if "data-hide-finished" in html:
                scan = Scan()
                scan.feed(html)
                labels.append("".join(scan.text))
        return labels

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

    def test_over_the_lan_a_loopback_link_names_the_host_the_page_came_from(self):
        run = json.loads(json.dumps(RUN))
        run["project"]["quest"]["links"] = [{"url": "http://localhost:5173/app", "label": "app"},
                                            {"url": "https://localhost.example/x", "label": "elsewhere"}]
        run["epics"][0]["milestones"][1]["mock"] = {"url": "http://127.0.0.1:8766/mock/"}
        for host, app, mock in (("192.168.1.5", "http://192.168.1.5:5173/app", "http://192.168.1.5:8766/mock/"),
                                ("127.0.0.1", "http://localhost:5173/app", "http://127.0.0.1:8766/mock/")):
            scan = self.rendered(run, location={"href": f"http://{host}:8765/", "hostname": host})
            links = {v for _, k, v in scan.attrs if k == "href"}
            self.assertLessEqual({app, mock, "https://localhost.example/x"}, links, host)
            if host != "127.0.0.1":
                self.assertEqual([v for v in links if re.match(r"https?://(127\.|localhost[:/])", v)], [])

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

    def test_the_feed_renders_findings_and_their_resolutions_and_offers_a_findings_filter(self):
        events = [
            {"type": "finding", "key": "big-<b>read", "kind": "tokens", "target": "feature-qa", "title": "reads <i>whole</i> files", "fix": "pointer",
             "severity": "high", "saving": 40000, "milestone": "M1", "by": "ann", "at": ago(hours=3)},
            {"type": "finding-resolved", "key": "k1", "resolution": "resolved", "sha": "abcdef123456", "repo": "podium", "at": ago(hours=2)},
            {"type": "finding-resolved", "key": "k2", "resolution": "wontfix", "why": "<u>rare</u>", "at": ago(hours=1)},
        ]
        self.rendered(RUN, events, PROGRESS, ())
        feed = [h for h in self.html if 'class="ev"' in h][-1]
        self.assertEqual(feed.count("◎"), 3)
        for found in ("finding <b>big-&lt;b&gt;read</b>", "reads &lt;i&gt;whole&lt;/i&gt; files", "feature-qa · pointer", "~40000/wk", "<b>high</b>",
                      "<b>k1</b> resolved <code>abcdef1</code> in podium", "<b>k2</b> won't fix: &lt;u&gt;rare&lt;/u&gt;"):
            self.assertIn(found, feed)
        self.assertNotIn("<i>whole", feed)
        self.assertTrue(any('data-feed="findings"' in h for h in self.html))

    def test_renders_a_run_whose_stories_and_milestones_depend_on_each_other_in_a_cycle(self):
        scan = self.rendered(CYCLIC_RUN, [], PROGRESS, ("S1", "S2", "S3"))
        text = "".join(scan.text)
        self.assertNotIn("elsewhere-only", text)
        self.assertNotIn("Dispatcher", text)

    def test_renders_a_run_whose_ids_types_and_states_are_object_prototype_keys(self):
        scan = self.rendered(PROTO_RUN, PROTO_EVENTS, PROTO_PROGRESS, (*KEYS, "S1"), **{"podium/handoffs.json": "null"})
        text = "".join(scan.text)
        for kind in KEYS:
            self.assertIn(kind, text)
        self.assertNotIn("[native code]", text + "".join(v for _, _, v in scan.attrs))


    def sheets(self, run, *opens):
        """Opens each selection, or follows each `#/…` link, in turn: the sheet head's title, the link Copy link gives, and the last toast."""
        expr = ("(async () => { const out = []; for (const o of %s) {"
                " if (typeof o === 'string') { location.hash = o; await goTo(parseRoute()); } else await openSheet(o);"
                " out.push([$('sheet-head').innerHTML, sheetRoute()?.hash ?? null, $('toast').textContent]); } return out; })()") % json.dumps(opens)
        self.rendered(run, [], PROGRESS, (), probe=expr)
        shown = json.loads([h for h in self.html if h.startswith("PROBE ")][-1][len("PROBE "):])
        return [((re.search(r"<h2>(.*?)</h2>", head) or [None, None])[1], link, toast) for head, link, toast in shown]

    def opens(self, marker, unit):
        """(data-open, data-story) of every element that opens a sheet inside the pieces of output that start with marker, cut at each unit."""
        found = []
        for html in self.html:
            for piece in re.split(f"(?={re.escape(unit)})", html):
                if piece.startswith(marker):
                    parser = Opens()
                    parser.feed(piece)
                    found += [(o["data-open"], o.get("data-story")) for o in parser.found]
        return found

    def test_a_story_sheet_shows_the_story_of_its_own_milestone_when_two_milestones_share_its_id(self):
        shown = self.sheets(TWIN_RUN, {"ms": "M1", "story": "S1"}, {"ms": "M2", "story": "S1"}, {"ms": "M1", "story": "S1"})
        self.assertEqual([title for title, _, _ in shown], ["S1 of M1", "S1 of M2", "S1 of M1"])

    def test_copy_link_gives_the_milestone_on_a_milestone_sheet_and_the_milestone_and_story_on_a_story_sheet(self):
        shown = self.sheets(TWIN_RUN, {"ms": "M2"}, {"ms": "M2", "story": "S1"}, {"ms": "M1", "story": "S1"}, {"epic": "e1"}, {"quest": True})
        self.assertEqual([link for _, link, _ in shown], ["#/M2", "#/M2/S1", "#/M1/S1", "#/epic/e1", "#/quest"])
        self.assertEqual(shown[0][0], "second")

    def test_a_link_to_a_story_opens_that_milestones_story(self):
        shown = self.sheets(TWIN_RUN, "#/M2/S1", "#/M1/S1")
        self.assertEqual([(title, link) for title, link, _ in shown], [("S1 of M2", "#/M2/S1"), ("S1 of M1", "#/M1/S1")])

    def test_an_artifact_of_a_milestone_without_stories_opens_as_its_story_and_links_to_it(self):
        self.assertEqual(self.sheets(TWIN_RUN, {"ms": "M3", "story": "A1"})[0][:2], ("the mock", "#/M3/A1"))

    def test_a_story_or_milestone_the_run_lacks_says_so_and_keeps_the_open_sheet(self):
        shown = self.sheets(TWIN_RUN, {"ms": "M2", "story": "S1"}, {"ms": "M2", "story": "S9"}, {"ms": "M9"}, {"ms": "M3", "story": "A2"}, "#/M1/A1")
        self.assertEqual(shown[1], ("S1 of M2", "#/M2/S1", "This run has no story M2/S9"))
        self.assertEqual(shown[2], ("S1 of M2", "#/M2/S1", "This run has no milestone M9"))
        self.assertEqual(shown[3][2], "This run has no story M3/A2")
        self.assertEqual(shown[4][2], "This run has no story M1/A1")

    def test_story_links_name_their_milestone_and_story_and_milestone_links_only_the_milestone(self):
        events = [{"type": "merged", "milestone": "M1", "story": H, "at": DONE}]
        scan = self.rendered(EMIT_RUN, events, PROGRESS, (), probe='(S.expanded = new Set(["0"]), render(), null)')
        story = ("M1", H)
        for kind in ("working", "needs", "assumed", "digest"):
            self.assertIn(story, self.opens(f'<div class="banner {kind}"', '<div class="banner '), kind)
        self.assertIn(story, self.opens('<li class="ev"', '<li class="ev"'))
        self.assertIn(story, self.opens('<div class="node compact working', '<div class="node '))
        chips = self.opens('<span class="link-chip', '<span class="link-chip')
        self.assertIn(story, chips)
        self.assertIn(("M1", None), chips)
        self.assertIn(("M2", None), self.opens('<div class="fms ', '<div class="fms '))
        everywhere = Opens()
        for html in self.html:
            everywhere.feed(html)
        self.assertEqual([o for o in everywhere.found if "data-ms" in o or o["data-open"] in (H, "S2")], [])
        self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])

    def test_the_idle_banner_does_not_count_a_story_handed_to_another_session_as_ready(self):
        run = {**TWIN_RUN, "epics": [{"id": "e1", "title": "E", "milestones": [
            {"id": "M1", "title": "first", "status": "working", "phase": "build",
             "stories": [{"id": "S1", "title": "a", "status": "todo"}, {"id": "S2", "title": "b", "status": "todo"}]},
            {"id": "M2", "title": "second", "status": "todo", "deps": ["M1"]}]}]}
        self.rendered(run, [], PROGRESS, (), **{"podium/handoffs.json": json.dumps({"M1/S1": {"at": DONE}})})
        banners = "".join(h for h in self.html if "banner idle" in h)
        self.assertIn("M1: 1 story is ready to assign", banners)
        self.assertNotIn("2 stories are ready", banners)

    def test_the_done_banner_of_an_epic_with_one_milestone_says_the_epic_completed(self):
        run = {**TWIN_RUN, "epics": [{"id": "e1", "title": "E", "milestones": [
            {"id": "M1", "title": "only", "status": "done", "stories": [{"id": "S1", "title": "a", "status": "done"}]}]}]}
        self.rendered(run, [], PROGRESS, ())
        banner = [h for h in self.html if "banner done" in h][-1]
        self.assertIn('<span class="label">✓ Epic completed</span><span class="sub">1 milestone landed</span>', banner)

    def test_share_says_what_it_will_do_while_the_run_does_not_sync(self):
        label, tip = self.share_button({**CYCLIC_RUN, "sync": {"enabled": False, "ref": "refs/heads/podium-run/acme"}})
        self.assertEqual(label, "Share")
        self.assertEqual(tip, "Shares this run so a colleague can plan and build milestones beside you. "
                              "Your orchestrator session picks it up and prints the steps.")

    def test_shared_lists_the_colleagues_steps_with_the_runs_ref(self):
        label, tip = self.share_button({**CYCLIC_RUN, "sync": {"enabled": True, "ref": "refs/heads/podium-run/acme"}})
        self.assertEqual(label, "Shared")
        self.assertEqual(tip.splitlines(), [
            "A colleague joins this run:",
            "1. Install the tool: pip install --user git+https://github.com/warriv93/podium-dashboard",
            "2. Install the o skill",
            "3. In a new empty folder, run /o join refs/heads/podium-run/acme",
            "4. Claim a milestone with podium claim <id>",
            "Click to print them in your orchestrator's chat again."])

    def test_shared_shows_a_hostile_ref_in_the_generic_steps_as_text(self):
        tip = self.share_button({**CYCLIC_RUN, "sync": {"enabled": True, "ref": X}})[1].splitlines()
        self.assertEqual(tip[3], f"3. In a new empty folder, run /o join {X}")

    def test_shared_lists_the_extensions_steps_with_the_runs_ref_and_remote(self):
        steps = ["Clone {remote}", "Run /o join {ref} from {remote}", "Claim a milestone: podium claim <id>"]
        run = {**CYCLIC_RUN, "orchestrator": {"name": "o", "command": "/o", "shareSteps": steps},
               "sync": {"enabled": True, "ref": "refs/heads/podium-run/acme", "remote": "git@example.com:acme/app.git"}}
        self.assertEqual(self.share_button(run)[1].splitlines(), [
            "A colleague joins this run:",
            "1. Clone git@example.com:acme/app.git",
            "2. Run /o join refs/heads/podium-run/acme from git@example.com:acme/app.git",
            "3. Claim a milestone: podium claim <id>",
            "Click to print them in your orchestrator's chat again."])

    def test_shared_fills_missing_placeholders_with_their_names_and_no_replacement_patterns(self):
        run = {**CYCLIC_RUN, "orchestrator": {"name": "o", "command": "/o", "shareSteps": ["{remote} {ref}", "{ref}"]},
               "sync": {"enabled": True, "ref": "$&{remote}$'"}}
        self.assertEqual(self.share_button(run)[1].splitlines()[1:3], ["1. <remote> $&{remote}$'", "2. $&{remote}$'"])

    def test_shared_shows_a_hostile_step_as_text(self):
        run = {**CYCLIC_RUN, "orchestrator": {"name": "o", "command": "/o", "shareSteps": [X, "{ref}"]}, "sync": {"enabled": True, "ref": X}}
        self.assertEqual(self.share_button(run)[1].splitlines()[1:3], [f"1. {X}", f"2. {X}"])

    def test_the_map_header_offers_hide_finished_and_shows_everything_by_default(self):
        labels = self.hide_finished_buttons(FINISHED_RUN)
        self.assertTrue(labels)
        self.assertEqual(set(labels), {"Hide finished"})
        self.assertIn('id="hide-finished"', open(PAGE).read())

    def test_hide_finished_reads_podium_hide_finished_from_local_storage(self):
        self.assertIn('"podium-hide-finished"', open(PAGE).read())
        labels = self.hide_finished_buttons(FINISHED_RUN, {"podium-hide-finished": "1"})
        self.assertIn("Show all · 3 hidden", labels)

    def test_a_stored_podium_hide_finished_stories_changes_nothing_and_the_page_no_longer_names_it(self):
        labels = self.hide_finished_buttons(FINISHED_RUN, {"podium-hide-finished-stories": "1"})
        self.assertEqual(set(labels), {"Hide finished"})
        self.assertNotIn("podium-hide-finished-stories", open(PAGE).read())

    def hidden_map(self, stored=None, run=HIDE_RUN, probe='(expand("M3"), 0)'):
        """The last full map's milestone ids, the story ids inside the open milestone, and the Hide finished label."""
        stored = {"podium-hide-finished": "1"} if stored is None else stored
        maps, _ = self.maps(run, localStorage=stored, probe=probe)
        full = maps[-1]
        open_card = self.open_card(full)
        shown = re.findall(r'<div class="fms [^"]*" [^>]*?data-id="([^"]*)"', full)
        stories = re.findall(r'<div class="node compact [^"]*" data-open="[^"]*" data-story="([^"]*)"', open_card)
        label = next(h for h in reversed(self.html) if "data-hide-finished" in h)
        scan = Scan()
        scan.feed(label)
        return shown, stories, "".join(scan.text)

    def test_hide_finished_hides_landed_and_moved_milestones_and_finished_stories_of_the_open_one(self):
        shown, stories, _ = self.hidden_map()
        self.assertEqual(shown, ["M3", "M4"])
        self.assertEqual(stories, ["S4", "S5"])

    def test_hide_finished_shows_every_milestone_and_story_while_off(self):
        shown, stories, label = self.hidden_map({})
        self.assertEqual(shown, ["M1", "M2", "M3", "M4"])
        self.assertEqual(sorted(stories), ["S1", "S2", "S3", "S4", "S5"])
        self.assertEqual(label, "Hide finished")

    def test_hide_finished_counts_the_milestones_and_stories_it_hides(self):
        self.assertEqual(self.hidden_map()[2], "Show all · 5 hidden")

    def test_hide_finished_keeps_the_story_whose_sheet_is_open(self):
        _, stories, label = self.hidden_map(probe='(openSheet({ ms: "M3", story: "S1" }), 0)')
        self.assertEqual(sorted(stories), ["S1", "S4", "S5"])

    def test_hide_finished_keeps_a_story_that_needs_the_user(self):
        run = {**HIDE_RUN, "needsYou": {"story": "M3/S3", "reason": "r"}}
        _, stories, _ = self.hidden_map(run=run)
        self.assertEqual(sorted(stories), ["S3", "S4", "S5"])

    def feed_classes(self, stored=None):
        self.rendered(localStorage=stored or {})
        return [h for h in self.html if h.startswith("FEED")][-1].split()[1:]

    def test_the_activity_feed_starts_folded(self):
        self.assertIn("folded", self.feed_classes())

    def test_the_activity_feed_opens_when_podium_feed_open_is_stored(self):
        self.assertIn('"podium-feed-open"', open(PAGE).read())
        self.assertNotIn("folded", self.feed_classes({"podium-feed-open": "1"}))

    def test_the_activity_feed_stays_folded_for_any_other_stored_value(self):
        self.assertIn("folded", self.feed_classes({"podium-feed-open": "0"}))

    def test_hide_finished_is_off_for_any_other_stored_value(self):
        self.assertEqual(set(self.hide_finished_buttons(FINISHED_RUN, {"podium-hide-finished": "0"})), {"Hide finished"})

    def test_a_missing_document_of_a_colleagues_milestone_is_not_synced_from_their_machine_yet(self):
        run = {**CYCLIC_RUN, "epics": [{"id": "e1", "title": "E", "milestones": [
            {"id": "M1", "title": "M", "status": "working", "owner": "bob", "brief": "m1.md"},
            {"id": "M2", "title": "N", "status": "todo", "owner": "ann", "brief": "m2.md"}]}]}
        self.rendered(run, [], PROGRESS, ())
        text = "".join(self.html)
        self.assertIn("Not synced from bob's machine yet", text)
        self.assertNotIn("m1.md not readable from the Podium", text)
        self.assertIn("m2.md not readable from the Podium", text)

    def test_a_milestone_spec_missing_from_the_repo_opens_from_the_run_dir(self):
        run = {**CYCLIC_RUN, "epics": [{"id": "e1", "title": "E", "milestones": [
            {"id": "M1", "title": "M", "status": "working", "spec": "spec/m1/spec.md"}]}]}
        self.rendered(run, [], PROGRESS, (), doc=json.dumps(["spec/m1/spec.md", "repoDir"]),
                      **{"spec/m1/spec.md": "The spec of M1"})
        text = "".join(self.html)
        self.assertIn("The spec of M1", text)
        self.assertNotIn("spec/m1/spec.md not readable", text)

    def test_the_away_digest_lists_stories_milestones_and_prs_but_no_other_events(self):
        events = [{"type": "grilled", "text": "R6 grill round 1", "by": "bob", "at": ago(minutes=5)},
                  {"type": "phase", "milestone": "M1", "phase": "verify", "at": ago(minutes=4)}]
        self.rendered(CYCLIC_RUN, events, PROGRESS, ())
        digest = next(h for h in self.html if "While you were away" in h)
        self.assertIn('<span class="k">Milestones</span>', digest)
        self.assertNotIn('<span class="k">Other</span>', digest)
        self.assertNotIn("R6 grill round 1", digest)

    def test_fetch_shows_only_while_the_run_syncs(self):
        self.assertIsNone(self.fetch_button({**CYCLIC_RUN, "sync": {"enabled": False}}))
        self.assertIsNone(self.fetch_button(CYCLIC_RUN))
        self.assertEqual(self.fetch_button({**CYCLIC_RUN, "sync": {"enabled": True}}), (
            "Fetch", "Pull your colleagues' latest changes to this run. The Podium also pulls every minute on its own"))

    def test_fetch_names_the_last_auto_pull_and_shows_a_hostile_result_as_text(self):
        tip = self.fetch_button({**CYCLIC_RUN, "sync": {"enabled": True}}, {"at": X, "result": f"FAILED {X}"})[1]
        self.assertEqual(tip.splitlines()[1], f"Last pull {X}: FAILED {X}")

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

    def test_milestone_cards_show_their_repos_with_the_pr_whatever_the_status(self):
        pr = {"number": 7, "url": "https://github.com/o/core/pull/7", "state": "draft"}
        cards = self.card_repos([
            {"id": "M1", "title": "a", "status": "parked", "repos": {"core": {"pr": pr}, "api": {}}},
            {"id": "M2", "title": "b", "status": "draft", "repos": {"web": {}}}])
        self.assertEqual(cards["M1"][:2], ("core#7 Draftapi" + "no PR yet", ["https://github.com/o/core/pull/7"]))
        self.assertEqual(cards["M2"][0], "webno PR yet")

    def test_the_looked_checkbox_sits_inside_a_colleagues_pr_pill_and_outside_its_link(self):
        pr = {"number": 8, "url": "https://github.com/o/core/pull/8", "state": "draft"}
        run = {**CYCLIC_RUN, "epics": [{"id": "e1", "title": "E", "milestones": [
            {"id": "M1", "title": "a", "status": "working", "owner": "bob", "repos": {"core": {"pr": pr}}}]}]}
        self.rendered(run, [], PROGRESS, ())
        banner = [h for h in self.html if 'class="banner needs"' in h][-1]
        pill = re.search(r'<span class="wchip pr-chip">(.*?</label>)</span>', banner, re.S).group(1)
        link = re.search(r'<a class="pr-link"[^>]*>.*?</a>', pill, re.S).group(0)
        self.assertIn('data-looked="M1:core:8"', pill)
        self.assertNotIn("data-looked", link)
        self.assertNotIn("<label", link)
        self.assertTrue(pill.endswith("</label>"))

    def test_milestone_cards_add_the_repos_only_their_stories_name_after_their_own(self):
        cards = self.card_repos([{"id": "M1", "title": "a", "status": "todo", "repos": {"core": {}},
                                  "stories": [{"id": "S1", "title": "s", "status": "todo", "repos": ["web", "core"]},
                                              {"id": "S2", "title": "t", "status": "todo", "repos": ["api"]}]},
                                 {"id": "M2", "title": "b", "status": "todo",
                                  "stories": [{"id": "S3", "title": "s", "status": "todo", "repos": ["web"]}]}])
        self.assertEqual(cards["M1"][0], "coreno PR yetwebno PR yetapino PR yet")
        self.assertEqual(cards["M2"][0], "webno PR yet")

    def test_milestone_cards_show_one_dot_per_story_in_wave_order_classed_by_the_stories_status(self):
        cards = self.card_dots([{"id": "M1", "title": "a", "status": "working", "stories": [
            {"id": "S1", "title": "first", "status": "done"},
            {"id": "S3", "title": "third", "status": "todo", "deps": ["S2"]},
            {"id": "S2", "title": "second", "status": "working", "deps": ["S1"]},
            {"id": "S4", "title": "fourth", "status": "todo"}]},
            {"id": "M2", "title": "b", "status": "parked", "stories": [{"id": "S1", "title": "only", "status": "approval"}]}])
        _, dots, card = cards["M1"]
        self.assertEqual([(d["class"], d["data-ms"], d["data-story"], d["title"]) for d in dots],
                         [("done", "M1", "S1", "S1 \u00b7 first \u00b7 merged"), ("ready", "M1", "S4", "S4 \u00b7 fourth \u00b7 to do"),
                          ("working", "M1", "S2", "S2 \u00b7 second \u00b7 working"), ("waiting", "M1", "S3", "S3 \u00b7 third \u00b7 to do")])
        self.assertIn('<span class="fdots" role="img" aria-label="1 merged, 2 to do, 1 working">', card)
        self.assertNotIn("fwave", card)
        self.assertNotIn("fsc", card)
        self.assertEqual([d["class"] for d in cards["M2"][1]], ["approval"])

    def test_a_card_with_more_stories_than_its_row_holds_shows_the_first_dots_and_a_count_of_the_rest(self):
        many = [{"id": f"S{i}", "title": f"s{i}", "status": "done" if i <= 30 else "todo"} for i in range(1, 34)]
        cards = self.card_dots([{"id": "M1", "title": "a", "status": "done", "stories": many},
                                {"id": "M2", "title": "b", "status": "done", "stories": many[:16]}])
        _, dots, card = cards["M1"]
        self.assertEqual([d["data-story"] for d in dots], [f"S{i}" for i in range(1, 15)])
        self.assertIn('<b class="fmore" title="19 more: 16 merged, 3 to do">+19</b></span>', card)
        self.assertIn('aria-label="30 merged, 3 to do"', card)
        self.assertEqual(len(cards["M2"][1]), 16)
        self.assertNotIn("fmore", cards["M2"][2])

    def test_a_milestone_card_without_stories_has_no_dots(self):
        cards = self.card_dots([{"id": "M1", "title": "a", "status": "parked"}, {"id": "M2", "title": "b", "status": "working", "stories": []}])
        self.assertEqual([cards["M1"][1], cards["M2"][1]], [None, None])

    def test_clicking_a_story_dot_is_clicking_its_card(self):
        _, dots, card = self.card_dots([{"id": "M1", "title": "a", "status": "working", "stories": [{"id": "S1", "title": "s", "status": "todo"}]}])["M1"]
        self.assertTrue(card.startswith('<div class="fms '))
        self.assertIn('data-expand-ms="M1"', card.split(">")[0])
        self.assertTrue(all("data-expand-ms" not in d and "data-open" not in d for d in dots))

    def test_a_hostile_story_title_on_a_dot_is_text(self):
        _, dots, _ = self.card_dots([{"id": "M1", "title": "a", "status": "parked", "stories": [{"id": X, "title": X, "status": X}]}])["M1"]
        self.assertEqual(len(dots), 1)
        self.assertNotIn("pwn", dots[0])

    def test_a_dot_takes_the_status_its_story_card_shows(self):
        maps, _ = self.maps(**{"podium/handoffs.json": json.dumps({"M3/S6": {"at": DONE}})})
        card = next(c for c in re.split(r'(?=<div class="fms )', maps[-1]) if 'data-id="M3"' in c.split(">")[0])
        self.assertRegex(card, r'<i class="elsewhere" data-ms="M3" data-story="S6"')

    def maps(self, run=OPEN_RUN, **kw):
        """Every full map the page rendered, in order, and the state the first load left: {open, sel}."""
        self.rendered(run, [], PROGRESS, (), **kw)
        loaded = json.loads(next(h for h in self.html if h.startswith("LOADED "))[len("LOADED "):])
        return [h for h in self.html if '<div class="full"' in h], loaded

    def probe(self):
        return json.loads([h for h in self.html if h.startswith("PROBE ")][-1][len("PROBE "):])

    def scrolls(self):
        return json.loads(next(h for h in self.html if h.startswith("SCROLLS "))[len("SCROLLS "):])

    def flashed(self, ms):
        flashed = json.loads(next(h for h in self.html if h.startswith("FLASHED "))[len("FLASHED "):])
        return ["flash"] if ms in flashed else []

    @staticmethod
    def open_cards(html):
        return re.findall(r'<div class="fms open [^"]*" data-id="([^"]*)"', html)

    @staticmethod
    def open_card(html):
        return re.split(r'(?=<div class="fms )', html[html.index('<div class="fms open '):])[1]

    def test_nothing_opens_on_load_not_even_the_milestone_being_built(self):
        maps, loaded = self.maps()
        self.assertEqual(self.open_cards(maps[0]), [])
        self.assertEqual(loaded, {"open": None, "sel": None})

    def test_opening_a_milestone_closes_the_one_that_was_open(self):
        maps, _ = self.maps(probe='(expand("M2"), expand("M3"), S.open)')
        self.assertEqual(self.probe(), "M3")
        self.assertEqual(self.open_cards(maps[-1]), ["M3"])

    def test_escape_closes_the_sheet_first_and_then_the_open_milestone(self):
        maps, _ = self.maps(probe='(() => { S.ds = null; expand("M2"); openSheet({ ms: "M3" }); onEscape(); const first = [S.open, S.sel]; onEscape(); return [first, S.open]; })()')
        self.assertEqual(self.probe(), [["M2", None], None])
        self.assertEqual(self.open_cards(maps[-1]), [])

    def test_the_open_card_has_a_collapse_button_and_a_title_that_opens_the_milestone_sheet(self):
        maps, _ = self.maps(probe='expand("M2")')
        card = self.open_card(maps[-1])
        self.assertIn('<button class="ocollapse" data-collapse aria-expanded="true">', card)
        self.assertRegex(card, r'<span class="title otitle" data-open="M2"[^>]*>second</span>')
        self.assertLess(card.index("data-collapse"), card.index('class="title otitle"'), "Collapse sits in the top row, before the title")
        self.assertNotIn("data-collapse", card[card.index('class="oside"'):])
        self.assertNotIn("data-expand-ms", card.split(">")[0])

    @staticmethod
    def must_run():
        run = json.loads(json.dumps(OPEN_RUN))
        run["epics"][1]["milestones"][0]["priority"] = "must"
        return run

    def test_a_must_have_milestone_shows_a_must_pill_after_its_id_and_others_show_none(self):
        maps, _ = self.maps(self.must_run())
        cards = {re.search(r'data-id="([^"]*)"', c).group(1): c for c in re.split(r'(?=<div class="fms )', maps[0])[1:]}
        self.assertIn('<span class="sid">M2</span><span class="mustpill" title="Must have"><b>★</b>Must</span>', cards["M2"])
        self.assertNotIn("mustpill", cards["M3"])
        self.assertNotIn("data-must", maps[0])

    def test_only_the_open_card_has_the_must_have_switch(self):
        maps, _ = self.maps(self.must_run(), probe='(expand("M2"), expand("M3"))')
        opened = {self.open_cards(m)[0]: self.open_card(m) for m in maps if self.open_cards(m)}
        self.assertIn('<button class="mustsw" role="switch" aria-checked="true" data-must="M2">', opened["M2"])
        self.assertIn('<span class="sid">M2</span><span class="mustpill"', opened["M2"])
        self.assertIn('<button class="mustsw" role="switch" aria-checked="false" data-must="M3">', opened["M3"])

    def test_flipping_the_switch_posts_the_priority_and_shows_it_at_once(self):
        self.maps(probe='(async () => { const calls = [];'
                        ' globalThis.fetch = async (p, o) => (calls.push([p, o && o.method]), { ok: true, status: 200, json: async () => ({}) });'
                        ' await setMust("M2", true); const on = msOf("M2").priority; await setMust("M2", false);'
                        ' return [calls, on, msOf("M2").priority ?? null]; })()')
        self.assertEqual(self.probe(), [[["/priority/M2?must=1", "POST"], ["/priority/M2?must=0", "POST"]], "must", None])

    def test_a_research_card_opens_its_sheet_and_never_expands(self):
        maps, _ = self.maps(probe='(expand("M2"), expand("R1"), reveal("R1"), [S.open, S.sel])')
        self.assertEqual(self.probe(), ["M2", {"ms": "R1"}])
        research = re.search(r'<div class="fms [^"]*research"[^>]*>', maps[0]).group(0)
        self.assertIn('data-open="R1"', research)
        self.assertNotIn("data-expand-ms", research)

    def test_a_later_poll_never_moves_or_reopens_the_open_milestone(self):
        swap = ('{ const run = JSON.parse(FILES["podium/podium.json"]), [m2, m3] = run.epics[1].milestones;'
                ' Object.assign(m2, { status: "done" }); Object.assign(m3, { status: "working", phase: "build", n: (m3.n || 0) + 1 });'
                ' run.active.milestone = "M3"; FILES["podium/podium.json"] = JSON.stringify(run); await poll(); }')
        self.maps(probe=f'(async () => {{ expand("M2"); {swap} const kept = S.open; collapse(); {swap} return [kept, S.open]; }})()')
        self.assertEqual(self.probe(), ["M2", None])

    def test_a_project_with_one_milestone_leaves_it_closed_on_load(self):
        run = {**OPEN_RUN, "active": None, "epics": [
            {"id": "e1", "title": "E1", "milestones": [{"id": "M1", "title": "only", "status": "todo", "stories": [{"id": "S1", "title": "a", "status": "todo"}]}]}]}
        maps, loaded = self.maps(run)
        self.assertEqual(self.open_cards(maps[0]), [])
        self.assertEqual(loaded["open"], None)

    def test_when_the_open_milestone_leaves_the_run_nothing_is_open(self):
        maps, _ = self.maps(probe='(async () => { expand("M3"); const run = JSON.parse(FILES["podium/podium.json"]);'
                                  ' run.epics[1].milestones.pop(); FILES["podium/podium.json"] = JSON.stringify(run); await poll(); return S.open; })()')
        self.assertIsNone(self.probe())
        self.assertEqual(self.open_cards(maps[-1]), [])

    def test_a_poll_that_drops_the_open_milestone_collapses_it(self):
        maps, _ = self.maps(probe='(async () => { expand("M3"); const run = JSON.parse(FILES["podium/podium.json"]);'
                                  ' run.epics[1].milestones[1].status = "dropped"; FILES["podium/podium.json"] = JSON.stringify(run); await poll(); return S.open; })()')
        self.assertIsNone(self.probe())
        self.assertEqual(self.open_cards(maps[-1]), [])

    def test_a_dropped_milestone_revealed_from_the_epic_sheet_opens_its_sheet_and_nothing_on_the_map(self):
        run = json.loads(json.dumps(OPEN_RUN))
        run["epics"][1]["milestones"][1]["status"] = "dropped"
        self.maps(run, probe='(async () => { collapse(); await openSheet({ epic: "e2" }); const sheet = $("sheet-body").innerHTML;'
                             ' await reveal("M3"); const out = [S.open, S.sel]; await openSheet({ ms: "M3", story: "S6" }); expand("M3");'
                             ' return [sheet.includes(\'<a data-reveal="M3">third</a>\'), ...out, S.open, S.sel]; })()')
        self.assertEqual(self.probe(), [True, None, {"ms": "M3"}, None, {"ms": "M3"}])

    def test_a_milestone_with_no_stories_or_artifacts_opens_its_sheet_from_its_card_and_from_reveal(self):
        run = json.loads(json.dumps(OPEN_RUN))
        run["epics"][1]["milestones"].append({"id": "M4", "title": "fourth", "status": "todo"})
        maps, _ = self.maps(run, probe='(async () => { expand("M2"); await reveal("M4"); return [S.open, S.sel]; })()')
        self.assertEqual(self.probe(), ["M2", {"ms": "M4"}])
        card = re.search(r'<div class="fms [^"]*"[^>]*data-id="M4"[^>]*>', maps[0]).group(0)
        self.assertIn('data-open="M4"', card)
        self.assertNotIn("data-expand-ms", card)

    def test_reveal_scrolls_to_the_card_and_flashes_it(self):
        self.maps(probe='(() => { const scrolls = []; requestAnimationFrame = (f) => (f(), 0); scrollTo = (o) => scrolls.push(o.behavior);'
                        ' collapse(); reveal("M3"); return [S.open, scrolls, [...document.querySelector(\'#map .fms[data-id="M3"]\').classes]]; })()')
        self.assertEqual(self.probe(), ["M3", ["smooth"], ["flash"]])

    def test_the_open_card_keeps_what_the_closed_cards_foot_shows(self):
        run = json.loads(json.dumps(OPEN_RUN))
        e2 = run["epics"][1]["milestones"]
        e2[0].update({"pr": {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "draft"}, "includes": ["M0"],
                      "waitsFor": [{"milestone": "M3", "reason": "r"}]})
        run["epics"][0]["milestones"][0].update({"shippedAt": DONE})
        run["epics"][0]["milestones"].append({"id": "M9", "title": "moved", "status": "moved", "movedTo": "M3",
                                              "stories": [{"id": "S9", "title": "nine", "status": "done"}]})
        cards = {}
        for name, before in (("building", ""), ("waiting", 'msOf("M2").stories[0].status = "done";'), ("landed", ""), ("moved", "")):
            ms = {"landed": "M1", "moved": "M9"}.get(name, "M2")
            self.maps(run, probe=f'(() => {{ {before} expand("{ms}"); return $("map").innerHTML; }})()')
            cards[name] = self.open_card(self.probe()).split('<div class="mtree"')[0]
        for card in cards.values():
            self.assertEqual(card.count('<div class="foot">'), 1)
        self.assertIn('href="https://github.com/o/r/pull/7"', cards["building"])
        self.assertIn("#7 Draft", cards["building"])
        self.assertIn('<span class="badge waitfor" title="r">Waiting for M3</span>', cards["building"])
        self.assertIn('<div class="fincl">includes M0</div>', cards["building"])
        self.assertEqual(cards["building"].count("Working on"), 1)
        self.assertIn('<span class="badge needs">Waiting on you</span>', cards["waiting"])
        self.assertIn("#7 Draft", cards["waiting"])
        self.assertIn('<span class="badge done">Landed 2026-10-20</span>', cards["landed"])
        self.assertIn('<span class="badge moved" data-reveal="M3">Moved to M3</span>', cards["moved"])

    def test_a_link_to_a_milestone_opens_it_in_place_without_a_sheet_from_the_first_render(self):
        maps, loaded = self.maps(location={"hash": "#/M3"})
        self.assertEqual(self.open_cards(maps[0]), ["M3"])
        self.assertEqual(loaded, {"open": "M3", "sel": None})

    def test_a_link_to_a_story_opens_its_milestone_and_its_sheet_from_the_first_render(self):
        maps, loaded = self.maps(location={"hash": "#/M3/S6"})
        self.assertEqual(self.open_cards(maps[0]), ["M3"])
        self.assertEqual(loaded, {"open": "M3", "sel": {"ms": "M3", "story": "S6"}})

    def test_a_link_to_a_story_scrolls_to_its_milestone_and_a_load_without_a_link_does_not(self):
        self.maps(location={"hash": "#/M3/S6"})
        self.assertEqual([o["behavior"] for o in self.scrolls()], ["smooth"])
        self.assertEqual(self.flashed("M3"), ["flash"])
        self.maps()
        self.assertEqual(self.scrolls(), [])

    def test_a_later_story_link_scrolls_to_its_milestone_and_keeps_the_sheet_open(self):
        self.maps(probe='(async () => { location.hash = "#/M2/S4"; S.route = parseRoute(); await goTo(S.route); return S.sel; })()')
        self.assertEqual(self.probe(), {"ms": "M2", "story": "S4"})
        self.assertEqual([o["behavior"] for o in self.scrolls()], ["smooth"])
        self.assertEqual(self.flashed("M2"), ["flash"])
        self.assertEqual(self.flashed("M3"), [])

    def test_a_story_link_scrolls_before_the_sheet_has_finished_loading(self):
        self.maps(probe='(async () => { const order = []; scrollTo = () => order.push("scroll"); const open = openSheet;'
                        ' openSheet = async (sel) => { order.push("open"); await open(sel); order.push("opened"); };'
                        ' location.hash = "#/M2/S4"; S.route = parseRoute(); await goTo(S.route); return order; })()')
        self.assertEqual(self.probe(), ["open", "scroll", "opened"])

    def test_scrolling_to_a_milestone_clears_the_sticky_map_head_as_well_as_the_toolbar(self):
        self.maps(probe='(() => { const scrolls = []; scrollTo = (o) => scrolls.push(o.top);'
                        ' document.querySelector(".map-head").getBoundingClientRect = () => ({ top: 0, height: 50 });'
                        ' collapse(); reveal("M3"); return scrolls; })()')
        self.assertEqual(self.probe(), [-62])

    def test_the_needs_banner_story_chip_scrolls_to_its_milestone(self):
        self.maps({**OPEN_RUN, "needsYou": {"story": "M3/S6", "reason": "r"}})
        self.assertIn('<span class="wchip" data-open="M3" data-story="S6" data-scroll>', "".join(self.html))

    def test_a_later_link_opens_the_milestone_in_place_and_a_story_link_also_its_sheet(self):
        maps, _ = self.maps(probe='(() => { const out = []; for (const h of ["#/M3", "#/M2/S4"]) {'
                                  ' location.hash = h; S.route = parseRoute(); followLink(); out.push([S.open, S.sel]); } return out; })()')
        self.assertEqual(self.probe(), [["M3", None], ["M2", {"ms": "M2", "story": "S4"}]])
        self.assertEqual(self.open_cards(maps[-1]), ["M2"])

    def test_controls_that_went_to_a_milestone_reveal_it_on_the_map(self):
        run = {**OPEN_RUN, "needsYou": {"story": "M3/S6", "reason": "r"}}
        events = [{"type": "phase", "milestone": "M3", "phase": "build", "at": ago(minutes=4)}]
        self.rendered(run, events, PROGRESS, (), info={"people": {"ann": {"active": "M3"}, "bob": {}}})
        shown = "".join(self.html)
        self.assertIn('<a data-reveal="M3">M3</a>', [h for h in self.html if 'class="who' in h][-1])
        self.assertIn('<span class="wchip" data-reveal="M3"><b>M3</b> go to milestone in map ›</span>', shown)
        self.assertIn('<span class="wchip" data-reveal="M3"><b>M3</b> → Build</span>', shown)
        self.assertIn('<a data-reveal="M3">M3</a> Phase →', shown)
        self.assertIn('<a data-reveal="M3">third</a>', shown)
        self.assertNotIn("data-drill", shown)
        self.assertNotIn("data-drill", open(PAGE).read())

    def test_the_page_has_no_story_map(self):
        page = open(PAGE).read()
        for gone in ("data-drill", "Full map", "S.view"):
            self.assertNotIn(gone, page)

    def filter_counts(self, html):
        return {k: (label, int(n)) for k, label, n in re.findall(r'data-filter="(\w+)">([^<]*)<span class="n">(\d+)</span>', html)}

    def test_the_filters_count_every_milestones_stories_and_always_say_done(self):
        self.maps()
        shown = [h for h in self.html if 'data-filter="all"' in h]
        self.assertTrue(shown)
        self.assertEqual(self.filter_counts(shown[0]), {"all": ("All", 6), "working": ("Working", 1), "todo": ("To do", 3),
                                                        "done": ("Done", 2), "failed": ("Failed", 0)})
        run = json.loads(json.dumps(OPEN_RUN))
        run["epics"][0]["milestones"].append({"id": "M9", "title": "gone", "status": "dropped", "stories": [{"id": "S9", "title": "x", "status": "failed"}]})
        self.maps(run)
        self.assertEqual(self.filter_counts([h for h in self.html if 'data-filter="all"' in h][-1])["all"], ("All", 6))

    def test_a_filter_dims_the_stories_dots_and_milestones_that_miss_it_and_removes_none(self):
        maps, _ = self.maps(probe='(() => { const cards = msList().map((m) => Object.assign(element(), { dataset: { id: m.id }, textContent: m.title,'
                                  ' kids: (m.stories || []).map((s) => Object.assign(element(), { dataset: { story: s.id } })) }));'
                                  ' cards.forEach((c) => (c.querySelectorAll = () => c.kids));'
                                  ' const out = []; for (const [f, q] of [["working", ""], ["all", "six"], ["all", "second"], ["done", "one"]]) {'
                                  ' S.filter = f; S.query = q; render(); document.querySelectorAll = (sel) => (sel === "#map .fms[data-id]" ? cards : []); applyFilter();'
                                  ' document.querySelectorAll = () => [];'
                                  ' out.push([cards.flatMap((c) => c.kids.filter((k) => !k.classes.has("dim")).map((k) => `${c.dataset.id}/${k.dataset.story}`)),'
                                  ' cards.filter((c) => !c.classes.has("dim")).map((c) => c.dataset.id)]); } return out; })()')
        self.assertEqual(self.probe(), [[["M2/S2"], ["M2"]], [["M3/S6"], ["M3"]], [[], ["M2"]], [["M1/S1"], ["M1"]]])
        for ms, story in (("M1", "S1"), ("M2", "S2"), ("M2", "S3"), ("M2", "S4"), ("M2", "S5"), ("M3", "S6")):
            self.assertEqual(len(re.findall(f'data-(?:open|ms)="{ms}" data-story="{story}"', maps[-1])), 1, story)
        self.assertEqual(re.findall(r'<div class="fms [^"]*"[^>]* data-id="(\w+)"', maps[-1]), ["R1", "M1", "M2", "M3"])

    def test_the_search_names_the_whole_map_and_the_filters_and_legend_always_show(self):
        page = open(PAGE).read()
        self.assertIn('<input id="q" type="search" placeholder="Search milestones, stories, files, ids"', page)
        self.assertNotIn(".placeholder =", page)
        self.maps(probe='(() => { const out = []; for (const go of [() => {}, () => collapse(), () => expand("M3")]) {'
                        ' go(); out.push([$("filters").hidden, document.querySelector(".legend").hidden]); } return out; })()')
        self.assertEqual(self.probe(), [[False, False]] * 3)

    def test_the_quality_panel_follows_the_open_milestone(self):
        self.maps(probe='(() => { const out = []; for (const go of [() => {}, () => expand("M2"), () => collapse(), () => expand("M3"), () => reveal("R1")]) {'
                        ' go(); out.push($("quality").hidden ? null : $("qsum").innerHTML.match(/class="qms">([^<]*)/)?.[1]); } return out; })()')
        self.assertEqual(self.probe(), [None, "M2", None, "M3", "M3"])

    def test_the_open_card_sits_in_its_epics_column_like_a_closed_card(self):
        maps, _ = self.maps(probe='(expand("M2"), collapse())')
        opened = next(m for m in maps if self.open_cards(m) == ["M2"])
        self.assertRegex(opened, r'<div class="ford">#\d+</div><div></div><div class="fms open ')
        self.assertNotIn("grid-column", self.open_card(opened))
        self.assertRegex(maps[-1], r'<div class="ford">#\d+</div><div></div><div class="fms working')

    def test_each_story_shows_once_on_the_map(self):
        maps, _ = self.maps()
        for ms, story in (("M1", "S1"), ("M2", "S2"), ("M2", "S3"), ("M2", "S4"), ("M2", "S5"), ("M3", "S6")):
            self.assertEqual(len(re.findall(f'data-(?:open|ms)="{ms}" data-story="{story}"', maps[0])), 1, story)

    def test_story_cards_show_id_title_status_and_the_agent_link_or_assign_or_take_back_in_rows_of_three(self):
        maps, _ = self.maps(**{"podium/handoffs.json": json.dumps({"M2/S5": {"at": DONE}}),
                               "podium/stories/M2/S2.progress": "2026-10-20T07:00:00+00:00 RED x\n"}, probe='expand("M2")')
        found = re.findall(r'(<div class="node compact[^"]*" data-open="M2" data-story="(S\d)".*?</div></div>)', self.open_card(maps[-1]))
        cards = {sid: card for card, sid in found}
        self.assertEqual(sorted(cards), ["S2", "S3", "S4", "S5"])
        self.assertIn('<span class="sid">S2</span>', cards["S2"])
        self.assertIn('<span class="title">two</span>', cards["S2"])
        self.assertIn('<span class="badge working">Working on</span>', cards["S2"])
        self.assertIn("Paseo ↗", cards["S2"])
        for gone in ("opus-model", "Making them pass", 'class="doing', 'class="model'):
            self.assertNotIn(gone, cards["S2"])
        self.assertIn('data-act="assign" data-id="M2/S4"', cards["S4"])
        self.assertIn('data-release="M2/S5"', cards["S5"])
        self.assertIn('<span class="badge done merged">Merged<span class="more"> to branch</span></span>', cards["S3"])
        self.assertRegex(open(PAGE).read(), r"\.mrow \{[^}]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)")
        sheet = next(h for h in self.html if "<dt>Model</dt>" in h and "opus-model" in h)
        self.assertIn('<dt>Step</dt><dd class="doing">Making them pass', sheet)

    @staticmethod
    def tree_text(card):
        """The open card's wave labels, fold line, chips and fold controls as text, and the story ids shown as cards and as chips."""
        parts = re.findall(r'<span class="(?:mwl|mfl)">(.*?)</span>|<span class="fchip[^"]*"[^>]*>(.*?)</span>|<button class="ocollapse" data-unfold[^>]*>([^<]*)</button>', card)
        lines = [re.sub(r"<[^>]+>", "", "".join(p)) for p in parts]
        cards = re.findall(r'<div class="node compact [^"]*" data-open="M2" data-story="([^"]*)"', card)
        chips = re.findall(r'<span class="fchip[^"]*" data-open="M2" data-story="([^"]*)"', card)
        return lines, cards, chips

    def test_merged_leading_waves_fold_into_one_line_of_chips_and_the_wave_count_goes_on(self):
        maps, _ = self.maps(FINISHED_RUN, probe='expand("M2")')
        lines, cards, chips = self.tree_text(self.open_card(maps[-1]))
        self.assertEqual(lines, ["Waves 1–2 · 2 merged", "Show ▸", "S1 a", "S2 b", "Wave 3"])
        self.assertIn('<div class="mfh"><span class="mfl"><b>Waves 1–2</b> · 2 merged</span><button class="ocollapse" data-unfold="M2"', self.open_card(maps[-1]))
        self.assertEqual(cards, ["S3"])
        self.assertEqual(chips, ["S1", "S2"])
        self.assertIn('<button class="ocollapse" data-unfold="M2" aria-expanded="false">Show ▸</button>', self.open_card(maps[-1]))

    def test_show_unfolds_the_merged_waves_as_cards_in_place_and_fold_merged_waves_folds_them_back(self):
        maps, _ = self.maps(FINISHED_RUN, probe='(() => { expand("M2"); const out = [S.unfold.M2 === true]; toggleFold("M2"); out.push(S.unfold.M2 === true); return out; })()')
        self.assertEqual(self.probe(), [False, True])
        lines, cards, chips = self.tree_text(self.open_card(maps[-1]))
        self.assertEqual(lines, ["Fold merged waves ▴", "Wave 1", "Wave 2", "Wave 3"])
        self.assertEqual((cards, chips), (["S1", "S2", "S3"], []))
        maps, _ = self.maps(FINISHED_RUN, probe='(expand("M2"), toggleFold("M2"), toggleFold("M2"), Object.keys(S.unfold))')
        self.assertEqual(self.probe(), [])
        self.assertEqual(self.tree_text(self.open_card(maps[-1]))[2], ["S1", "S2"])

    def test_the_fold_toggle_says_whether_the_merged_waves_are_folded(self):
        maps, _ = self.maps(FINISHED_RUN, probe='(expand("M2"), toggleFold("M2"), 0)')
        self.assertIn('<button class="ocollapse" data-unfold="M2" aria-expanded="true">Fold merged waves ▴</button>', self.open_card(maps[-1]))

    def test_an_expandable_closed_card_has_a_collapsed_title_button_and_no_role_of_its_own(self):
        maps, _ = self.maps()
        cards = {re.search(r'data-id="([^"]*)"', c).group(1): c for c in re.split(r'(?=<div class="fms )', maps[0])[1:]}
        self.assertIn('<div class="fms ', cards["M3"])
        self.assertIn('data-expand-ms="M3" data-id="M3">', cards["M3"])
        self.assertIn('<button class="title" aria-expanded="false">', cards["M3"])
        self.assertNotIn("role=", cards["M3"].split(">")[0])
        self.assertNotIn("tabindex", cards["M3"].split(">")[0])

    def test_a_card_that_opens_a_sheet_stays_focusable_with_a_plain_title(self):
        maps, _ = self.maps()
        cards = {re.search(r'data-id="([^"]*)"', c).group(1): c for c in re.split(r'(?=<div class="fms )', maps[0])[1:]}
        self.assertIn('data-open="R1" data-id="R1" tabindex="0">', cards["R1"])
        self.assertNotIn("aria-expanded", cards["R1"])
        self.assertIn('<span class="title">', cards["R1"])

    def test_dot_words_read_as_plain_language(self):
        self.maps(probe='["done", "approval", "elsewhere", "failed", "blocked", "working", "todo", "ready", "waiting", "draft", "parked", "later", "<b>"].map(dotWord)')
        self.assertEqual(self.probe(), ["merged", "needs approval", "on another machine", "failed", "blocked", "working", "to do", "to do", "to do",
                                        "not started", "not started", "not started", "<b>"])

    def test_after_an_action_in_the_map_focus_returns_to_the_control_that_replaces_the_one_acted_on(self):
        probe = '''(() => {
          const focused = [], q = document.querySelector;
          document.querySelector = (s) => Object.assign(q(s), { focus: () => focused.push(s) });
          const inMap = (on) => { document.activeElement = { closest: (s) => (on && s === "#map" ? {} : null) }; };
          collapse();
          inMap(true); expand("M2"); collapse(); expand("M2"); toggleFold("M2");
          inMap(false); expand("M2"); toggleFold("M2"); collapse();
          document.querySelector = q;
          return focused;
        })()'''
        self.maps(FINISHED_RUN, probe=probe)
        self.assertEqual(self.probe(), ['#map .fms.open[data-id="M2"] .otitle', '#map .fms[data-id="M2"] button.title',
                                        '#map .fms.open[data-id="M2"] .otitle', '#map .mtree[data-ms="M2"] [data-unfold]'])

    def test_a_fold_chip_opens_its_story_sheet(self):
        maps, _ = self.maps(FINISHED_RUN, probe='(openSheet({ ms: "M2", story: "S1" }), S.sel)')
        self.assertEqual(self.probe(), {"ms": "M2", "story": "S1"})
        self.assertRegex(self.open_card(maps[-1]), r'<span class="fchip sel" data-open="M2" data-story="S1" tabindex="0"><b>S1</b> a</span>')
        self.assertIn(".fchip", re.search(r'ev\.target\.matches\("([^"]*)"\)\) ev\.target\.click', open(PAGE).read()).group(1))

    def test_with_hide_finished_on_merged_waves_are_hidden_with_no_fold_line(self):
        maps, _ = self.maps(FINISHED_RUN, localStorage={"podium-hide-finished": "1"}, probe='expand("M2")')
        self.assertEqual(self.tree_text(self.open_card(maps[-1])), (["Wave 3"], ["S3"], []))
        self.assertNotIn("Fold merged waves", self.open_card(maps[-1]))

    def test_with_hide_finished_on_an_open_milestone_whose_stories_all_finished_says_so_with_a_show_button(self):
        run = json.loads(json.dumps(FINISHED_RUN))
        run["epics"][0]["milestones"][0]["stories"] = [{"id": "S1", "title": "a", "status": "done"}, {"id": "S2", "title": "b", "status": "dropped"}]
        row = '<div class="mfold"><span class="mfl">All 2 stories finished</span><button class="ocollapse" data-hide-finished>Show</button></div>'
        for stored, shown in (({"podium-hide-finished": "1"}, True), ({}, False)):
            self.maps(run, localStorage=stored, probe='(reveal("M1"), $("map").innerHTML)')
            card = self.open_card(self.probe())
            self.assertEqual(row in card, shown)
            self.assertEqual("node compact" in card, not shown)

    def test_cards_in_a_wave_sit_under_the_stories_they_depend_on(self):
        self.maps(TREE_RUN, probe='treeRows(msOf("M2")).map((w) => w.map((s) => s.id))')
        self.assertEqual(self.probe(), [["A1", "A2", "A3"], ["B2", "B3", "B1"], ["C2", "C1"]])

    def tree_edges(self, run, ms, stored=None, before=""):
        self.maps(run, localStorage=stored or {}, probe=f'(() => {{ {before} const m = msOf("{ms}"); return treeEdges(m, treeView(m).foldedIds); }})()')
        return sorted((e["from"], e["to"], e["kind"], e["fromFold"]) for e in self.probe())

    def test_tree_lines_start_at_a_folded_storys_chip_and_skip_edges_between_two_folded_stories(self):
        self.assertEqual(self.tree_edges(FINISHED_RUN, "M2"), [("S2", "S3", "dep", True)])
        self.assertEqual(self.tree_edges(FINISHED_RUN, "M2", before='toggleFold("M2");'), [("S1", "S2", "dep", False), ("S2", "S3", "dep", False)])

    def test_tree_lines_are_solid_for_deps_and_dashed_for_shared_files_and_skip_missing_and_self_edges(self):
        self.assertEqual(self.tree_edges(TREE_RUN, "M1"), [
            ("S1", "S4", "dep", False), ("S2", "S3", "dep", False), ("S2", "__proto__", "dep", False),
            ("S3", "S4", "overlap", False), ("S5", "S6", "dep", False), ("S6", "S5", "dep", False)])

    def test_tree_lines_into_stories_hide_finished_hides_are_dropped(self):
        edges = self.tree_edges(TREE_RUN, "M1", {"podium-hide-finished": "1"})
        self.assertNotIn("S1", [e[0] for e in edges])
        self.assertIn(("S3", "S4", "overlap", False), edges)

    def test_tree_lines_survive_cycles_and_prototype_named_stories(self):
        for run, edges in ((CYCLIC_RUN, 4), (PROTO_RUN, 6)):
            self.maps(run, probe='(() => { const m = msOf("M1"); return [treeRows(m).flat().length, treeEdges(m, treeView(m).foldedIds).length]; })()')
            self.assertEqual(self.probe(), [4, edges])

    def test_stories_whose_deps_are_not_a_list_render_as_stories_without_dependencies(self):
        run = json.loads(json.dumps(TREE_RUN))
        run["epics"][0]["milestones"][0]["stories"] = [{"id": "S1", "title": "a", "status": "todo", "deps": {}, "overlapAfter": 5},
                                                       {"id": "S2", "title": "b", "status": "todo", "deps": 5, "overlapAfter": {}}]
        maps, _ = self.maps(run, probe='(expand("M1"), treeRows(msOf("M1")).map((w) => w.map((s) => s.id)))')
        self.assertEqual(self.probe(), [["S1", "S2"]])
        self.assertEqual(re.findall(r'<div class="node compact ready" data-open="M1" data-story="(S\d)"', self.open_card(maps[-1])), ["S1", "S2"])

    def test_the_tree_draws_its_lines_behind_opaque_cards_without_removing_the_queue_lines(self):
        page = open(PAGE).read()
        self.assertIn('t.insertAdjacentHTML("afterbegin", `<svg class="links"', page)
        self.assertIn('t.querySelector("svg.links")?.remove()', page)
        self.assertRegex(page, r"\.mtree \{[^}]*position: relative")
        self.assertRegex(page, r"\.mtree > svg\.links \{[^}]*z-index: 0")
        self.assertRegex(page, r"\.mtree \.node\.dim[^{]*\{ opacity: 1; \}")
        self.assertIn("function drawLines() { drawQueue(); drawTree(); }", page)
        self.assertIn("requestAnimationFrame(drawLines)", page)
        self.assertIn('window.addEventListener("resize", () => { if (S.project) drawLines(); });', page)

    def test_a_milestone_card_without_known_repos_has_no_chip_row(self):
        cards = self.card_repos([{"id": "M1", "title": "a", "status": "parked"},
                                 {"id": "M2", "title": "b", "status": "todo", "repos": {}, "stories": [{"id": "S1", "title": "s", "status": "todo"}]}])
        self.assertEqual(cards, {"M1": None, "M2": None})

    def test_a_hostile_repo_name_on_a_milestone_card_is_text(self):
        cards = self.card_repos([{"id": "M1", "title": "a", "status": "parked", "repos": {X: {"pr": {"number": X, "url": JS, "state": X}}},
                                  "stories": [{"id": "S1", "title": "s", "status": "todo", "repos": [X + "2"]}]},
                                 {"id": "M2", "title": "b", "status": "todo"}])
        text, hrefs, scan = cards["M1"]
        self.assertIn(X, text)
        self.assertEqual(hrefs, [])
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])

    def waiting(self, m10="draft", **m12):
        """The full map's cards by id, as (class, foot html), and the last render's waiting banners, for a run where M12
        waits for M10 (status `m10`) with `m12`'s fields, M11 lands, and M14 went ahead without a milestone the run lacks."""
        milestones = [{"id": "M14", "title": "Other", "status": "todo", "waitsFor": [{"milestone": "M99", "reason": "r"}], "waitsForAck": True},
                      {"id": "M11", "title": "Auth", "status": "done"},
                      {"id": "M10", "title": "Login", "status": m10},
                      {"id": "M12", "title": "Upload", "status": "working", "phase": "build",
                       "waitsFor": [{"milestone": "M10", "reason": "login is needed"}], **m12}]
        self.rendered({**CYCLIC_RUN, "epics": [{"id": "e1", "title": "E", "milestones": milestones}]}, [], PROGRESS, ())
        cards = {}
        for card in re.split(r'(?=<div class="fms )', [h for h in self.html if 'class="fms ' in h][-1])[1:]:
            cards[re.search(r'data-id="([^"]*)"', card).group(1)] = (re.match(r'<div class="fms ([^"]*)"', card).group(1),
                                                                     re.search(r'<div class="foot">(.*?)</div>', card, re.S).group(1))
        shown = [h for h in self.html if 'class="banner needs waitfor"' in h]
        banners = re.split(r'(?=<div class="banner )', shown[-1]) if shown else []
        return cards, [b for b in banners if b.startswith('<div class="banner needs waitfor"')]

    def test_a_waiting_milestone_card_is_amber_with_a_waiting_for_pill(self):
        cards, _ = self.waiting()
        self.assertIn("waitfor", cards["M12"][0].split())
        self.assertIn('<span class="badge waitfor" title="login is needed">Waiting for M10</span>', cards["M12"][1])
        self.assertNotIn("goahead", cards["M12"][1])

    def test_an_acked_milestone_card_shows_a_muted_going_ahead_pill_and_no_amber(self):
        cards, _ = self.waiting(waitsForAck=True)
        self.assertNotIn("waitfor", cards["M12"][0].split())
        self.assertIn('<span class="badge goahead">Going ahead without M10</span>', cards["M12"][1])
        self.assertNotIn("badge waitfor", cards["M12"][1])
        self.assertNotIn("is waiting", cards["M10"][1])

    def test_the_awaited_milestone_card_says_who_is_waiting_and_is_up_next(self):
        cards, _ = self.waiting()
        self.assertIn('<span class="badge awaited">M12 is waiting</span>', cards["M10"][1])
        full = [h for h in self.html if 'class="fms ' in h][-1]
        self.assertLess(full.index('data-id="M14"'), full.index('<div class="fnext">'))
        self.assertLess(full.index('<div class="fnext">'), full.index('data-id="M10"'))

    def test_an_unknown_awaited_milestone_is_plain_text(self):
        cards, _ = self.waiting()
        self.assertIn('<span class="badge goahead">Going ahead without M99</span>', cards["M14"][1])

    def test_the_banner_recommends_the_awaited_milestone_only_while_not_acked(self):
        _, banners = self.waiting()
        self.assertEqual(len(banners), 1)
        scan = Scan()
        scan.feed(banners[0])
        self.assertEqual("".join(scan.text), "M12's planning recommends doing M10 first:login is neededPlan M10Go ahead")
        self.assertIn(("button", "data-act", "proceed"), scan.attrs)
        self.assertIn(("button", "data-id", "M10"), scan.attrs)
        self.assertEqual(self.waiting(waitsForAck=True)[1], [])

    def test_a_landed_or_dropped_awaited_milestone_counts_as_met_everywhere(self):
        for m10 in ("done", "dropped"):
            cards, banners = self.waiting(m10)
            self.assertNotIn("waitfor", cards["M12"][0].split())
            self.assertNotIn("badge waitfor", cards["M12"][1])
            self.assertNotIn("badge goahead", cards["M12"][1])
            self.assertNotIn("is waiting", cards.get("M10", ("", ""))[1])
            self.assertEqual(banners, [])
            self.assertIn("TITLE Podium · T", self.html)

    def test_only_the_open_awaited_milestones_are_named(self):
        cards, banners = self.waiting(waitsFor=[{"milestone": "M11", "reason": "auth"}, {"milestone": "M10", "reason": "login"}])
        self.assertIn('<span class="badge waitfor" title="login">Waiting for M10</span>', cards["M12"][1])
        self.assertNotIn("is waiting", cards["M11"][1])
        self.assertIn("M12's planning recommends doing M10 first:", banners[0])
        self.assertNotIn("auth", banners[0])
        self.assertIn("TITLE (1) Podium · T", self.html)

    def test_a_hostile_waiting_reason_is_text(self):
        cards, banners = self.waiting(waitsFor=[{"milestone": X, "reason": X}])
        for html in (cards["M12"][1], banners[0]):
            scan = Scan()
            scan.feed(html)
            self.assertNotIn(("i", "id", "pwn"), scan.attrs)
            self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])
            self.assertIn(X, "".join(scan.text) + "".join(v for _, _, v in scan.attrs))


    def moved(self, m10=None, m11=None, events=(), stored=None, extra=()):
        """The full map's cards by id, as (class, html), and the last feed, for a run where M10 moved into M11 (which
        carries an infra cut and includes M10) and M12 waits for M10."""
        milestones = [{"id": "M10", "title": "Login", "status": "moved", "movedTo": "M11", **(m10 or {})},
                      {"id": "M11", "title": "Auth", "status": "todo", "includes": ["M10"],
                       "cut": {"pattern": "simple-complex", "valuable": False, "kept": "the API needs it first"}, **(m11 or {})},
                      {"id": "M12", "title": "Upload", "status": "working", "phase": "build", "waitsFor": [{"milestone": "M10", "reason": "login"}]}, *extra]
        self.rendered({**CYCLIC_RUN, "epics": [{"id": "e1", "title": "E", "milestones": milestones}]}, list(events), PROGRESS, (),
                      localStorage=stored or {})
        cards = {}
        for card in re.split(r'(?=<div class="fms )', [h for h in self.html if 'class="fms ' in h][-1])[1:]:
            cards[re.search(r'data-id="([^"]*)"', card).group(1)] = (re.match(r'<div class="fms ([^"]*)"', card).group(1), card)
        feeds = [h for h in self.html if 'class="ev"' in h]
        return cards, feeds[-1] if feeds else ""

    def test_a_moved_milestone_card_is_greyed_with_a_pill_that_jumps_to_its_target(self):
        cards, _ = self.moved()
        self.assertIn("moved", cards["M10"][0].split())
        self.assertIn('<span class="badge moved" data-reveal="M11">Moved to M11</span>', cards["M10"][1])
        self.assertNotIn("Ready", cards["M10"][1])

    def test_the_target_card_says_what_it_includes(self):
        cards, _ = self.moved()
        self.assertIn('<div class="fincl">includes M10</div>', cards["M11"][1])
        self.assertNotIn("fincl", cards["M12"][1])

    def test_a_kept_milestone_that_is_not_valuable_shows_an_infra_tag_with_the_reason(self):
        cards, _ = self.moved()
        self.assertIn('<span class="infra" title="the API needs it first">infra</span>', cards["M11"][1])
        for cut in ({"valuable": True, "kept": "x"}, {"valuable": False}, "infra"):
            self.assertNotIn('class="infra"', self.moved(m11={"cut": cut})[0]["M11"][1])

    def test_a_wait_on_a_moved_milestone_names_the_target_and_where_it_was(self):
        cards, _ = self.moved()
        self.assertIn('<span class="badge waitfor" title="login">Waiting for M11 (was M10)</span>', cards["M12"][1])
        self.assertIn('<span class="badge awaited">M12 is waiting</span>', cards["M11"][1])
        self.assertNotIn("is waiting", cards["M10"][1])

    def test_a_wait_through_a_move_is_met_once_the_target_lands(self):
        cards, _ = self.moved(m11={"status": "done"})
        self.assertNotIn("badge waitfor", cards["M12"][1])
        self.assertNotIn("waitfor", cards["M12"][0].split())

    def test_a_dependency_on_a_moved_milestone_needs_its_target_until_it_lands(self):
        m13 = {"id": "M13", "title": "Share", "status": "todo", "deps": ["M10"]}
        cards, _ = self.moved(extra=[m13])
        self.assertIn('<span class="badge waiting">Needs M11 (was M10)</span>', cards["M13"][1])
        cards, _ = self.moved(m11={"status": "done"}, extra=[m13])
        self.assertNotIn("Needs", cards["M13"][1])
        self.assertIn("ready", cards["M13"][0].split())

    def test_hide_finished_hides_a_moved_milestone_like_a_landed_one(self):
        cards, _ = self.moved(stored={"podium-hide-finished": "1"})
        self.assertNotIn("M10", cards)
        self.assertIn("M11", cards)

    def test_the_feed_says_a_milestone_moved_and_why_under_phases(self):
        _, feed = self.moved(events=[{"type": "moved", "milestone": "M10", "to": "M11", "pattern": "<b>simple</b>", "at": ago(hours=1)}])
        self.assertIn('<a data-reveal="M10">M10</a> moved to <a data-reveal="M11">M11</a> (&lt;b&gt;simple&lt;/b&gt;)', feed)
        self.assertIn('"moved"', re.search(r"phases: \[[^\]]*\]", open(PAGE).read()).group(0))

    def test_hostile_move_fields_are_text(self):
        cards, _ = self.moved(m10={"movedTo": X}, m11={"includes": [X], "cut": {"valuable": False, "kept": X}})
        for html in (cards["M10"][1], cards["M11"][1]):
            scan = Scan()
            scan.feed(html)
            self.assertNotIn(("i", "id", "pwn"), scan.attrs)
            self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])
            self.assertIn(X, "".join(scan.text) + "".join(v for _, _, v in scan.attrs))

    def strips(self, decisions):
        """The full map's decision strip html per epic column (None for an empty cell), or None when it
        rendered no decision row, for a run of epics e1 (M10, M11) and e2 (M20)."""
        epics = [{"id": "e1", "title": "E", "milestones": [{"id": "M10", "title": "Login", "status": "todo"},
                                                           {"id": "M11", "title": "Auth", "status": "todo"}]},
                 {"id": "e2", "title": "F", "milestones": [{"id": "M20", "title": "Upload", "status": "todo"}]}]
        self.rendered({**CYCLIC_RUN, "epics": epics, "decisions": decisions}, [], PROGRESS, (), info={"me": "ann"})
        full = [h for h in self.html if 'class="full"' in h][-1]
        if '<div class="ford" title="Decisions">D</div>' not in full:
            return None
        row = re.split(r'<div class="(?:ford|fnext)"', full.split('<div class="ford" title="Decisions">D</div>', 1)[1])[0]
        cells = re.findall(r'<div></div>|<div><div class="fdecs">.*?(?=<div></div>|<div><div class="fdecs">|$)', row, re.S)
        self.assertEqual(len(cells), len(epics))
        return [None if c == "<div></div>" else c for c in cells]

    def test_an_epic_without_decisions_has_no_strip_and_a_run_without_any_no_row(self):
        self.assertIsNone(self.strips([]))
        self.assertIsNone(self.strips("D1"))
        cells = self.strips([{"id": "D1", "epic": "e2", "question": "Q", "type": "research", "status": "open"}])
        self.assertIsNone(cells[0])
        self.assertIn("Q", cells[1])

    def test_the_strip_lists_open_decisions_frontier_first_with_type_owner_blockers_and_missing(self):
        [strip, _] = self.strips([
            {"id": "D1", "epic": "e1", "question": "Which auth?", "type": "discussion", "status": "open", "owner": "bo"},
            {"id": "D2", "epic": "e1", "question": "Where do files live?", "type": "research", "status": "open",
             "blockedBy": ["D1", "D4"], "missing": "a price list"},
            {"id": "D3", "epic": "e1", "question": "Get keys", "type": "unblock", "status": "open", "blockedBy": ["D4"]},
            {"id": "D4", "epic": "e1", "question": "Old", "type": "prototype", "status": "resolved", "outcome": "x"},
            {"id": "D5", "epic": "e1", "question": "Gone", "type": "discussion", "status": "invalidated"},
            {"id": "D6", "epic": "e2", "question": "Elsewhere", "type": "discussion", "status": "open"}])
        self.assertIn('<span class="dhead">Decisions · 3 open · 2 closed</span>', strip)
        self.assertEqual(re.findall(r'data-decision="([^"]*)"', strip), ["D3", "D1", "D2"])
        self.assertEqual(re.findall(r'<div class="fdec( frontier)?" data-decision', strip), [" frontier", "", ""])
        self.assertIn('<span class="sid">D3</span><span class="dtype">unblock</span></div><span class="title">Get keys</span>', strip)
        self.assertIn('<span class="owner" style="background:hsl(156 50% 45%)" title="bo is settling it">👤 <span class="who">bo</span></span>', strip)
        self.assertIn('<span class="dmeta">blocked by D1</span><span class="dmeta">missing: a price list</span>', strip)
        for closed in ("Old", "Gone", "Elsewhere"):
            self.assertNotIn(closed, strip)

    def test_the_strip_marks_your_own_claim_and_reveals_affected_milestones(self):
        [strip, _] = self.strips([{"id": "D1", "epic": "e1", "question": "Q", "type": "discussion", "status": "open",
                                   "owner": "ann", "affects": ["M11", "billing", "M99"]}])
        self.assertIn('<span class="owner" style="background:hsl(354 50% 45%)" title="Yours (ann): you are settling it">👤 <span class="who">you</span></span>', strip)
        self.assertIn('<span class="dmeta">affects <a data-reveal="M11">M11</a>, billing, M99</span>', strip)

    def test_a_strip_of_closed_decisions_only_shows_the_count(self):
        [strip, _] = self.strips([{"id": "D1", "epic": "e1", "question": "Q", "type": "discussion", "status": "resolved"}])
        self.assertIn('<span class="dhead">Decisions · 0 open · 1 closed</span>', strip)
        self.assertNotIn('class="fdec', strip.replace('class="fdecs"', ""))

    def test_hostile_decision_fields_are_text(self):
        [strip, _] = self.strips([{"id": X, "epic": "e1", "question": X, "type": X, "status": "open", "owner": X, "missing": X,
                                   "affects": [X, 1, {}], "blockedBy": [X, {}]},
                                  {"id": "__proto__", "epic": "e1", "question": "p", "type": "t", "status": "open", "blockedBy": ["toString"]},
                                  {"epic": "e1", "question": "no id", "status": "open"}, None, "D9"])
        scan = Scan()
        scan.feed(strip)
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])
        self.assertIn(X, "".join(scan.text))
        self.assertNotIn("no id", strip)
        self.assertIn('data-decision="__proto__"', strip)

    def test_an_id_with_dot_segments_never_reaches_another_endpoint(self):
        expr = ("(async () => { const sent = []; const real = fetch;"
                " globalThis.fetch = async (p, o) => (sent.push(String(p)), real(p, o));"
                " for (const id of ['../restart', 'M1/../../pull', './M1', '..']) {"
                "  await act('plan', id); await release(id); await copyPrompt('plan', id); await copyPrompt('assign', id);"
                "  await settle('confirm', id); await asanaDone('skip', id); await markLooked({ ms: id, number: 1 }); await linkAsana(id); }"
                " const bad = sent.slice(); sent.length = 0;"
                " await act('plan', 'M1'); await release('M1/S1');"
                " return { bad, good: sent, toast: $('toast').textContent }; })()")
        self.rendered(TWIN_RUN, [], PROGRESS, (), probe=expr)
        got = self.probe()
        self.assertEqual(got["bad"], [])
        self.assertEqual(got["good"], ["/plan/M1", "/handoff/M1/S1"])

STICKY_HARNESS = r"""
const src = require("fs").readFileSync(process.argv[2], "utf8");
const fn = src.slice(src.indexOf("function trackStickyBar()"), src.indexOf("trackStickyBar();\n"));
const bar = { offsetHeight: 50, position: "sticky" }, toolbar = { offsetHeight: 40 }, vars = {}, head = { style: {}, classList: { toggle() {} } };
const watchers = [], resizers = [];
globalThis.window = { addEventListener: (_, f) => resizers.push(f) };
globalThis.document = { documentElement: { style: { setProperty: (k, v) => (vars[k] = v) } }, querySelector: (s) => (s === ".topbar" ? bar : s === ".toolbar" ? toolbar : head) };
globalThis.$ = () => ({});
globalThis.getComputedStyle = (el) => ({ position: el.position });
globalThis.IntersectionObserver = class { constructor(_, o) { this.margin = o.rootMargin; this.live = true; watchers.push(this); } observe() {} disconnect() { this.live = false; } };
let resized;
const observed = [];
globalThis.ResizeObserver = class { constructor(f) { resized = f; } observe(el) { observed.push(el); } };
eval(fn + "; trackStickyBar();");
const snap = (...extra) => [vars["--bar-h"], vars["--toolbar-h"], watchers.at(-1).margin, ...extra];
const out = [snap(observed.length)];
bar.offsetHeight = 90; resized();
out.push(snap(watchers[0].live, watchers.filter((w) => w.live).length));
toolbar.offsetHeight = 80; resized();
out.push(snap());
bar.position = "static"; resizers[0]();
out.push(snap());
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "needs Node to run the page's script")
class StickyBar(unittest.TestCase):
    def test_the_toolbar_and_map_head_offsets_follow_the_header_and_toolbar_heights(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(tmp, "harness.js"), "w") as f:
            f.write(STICKY_HARNESS)
        r = subprocess.run(["node", os.path.join(tmp, "harness.js"), PAGE], capture_output=True, text=True, cwd=tmp, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [
            ["50px", "40px", "-90px 0px 0px 0px", 2],
            ["90px", "40px", "-130px 0px 0px 0px", False, 1],
            ["90px", "80px", "-170px 0px 0px 0px"],
            ["0px", "80px", "-80px 0px 0px 0px"],
        ])


if __name__ == "__main__":
    unittest.main()
