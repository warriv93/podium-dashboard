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
COST_RUN = {
    "project": {"title": "T"}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M2"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "first", "status": "done", "shippedAt": "2026-10-21", "stories": [
            {"id": "S1", "title": "a", "status": "done", "attempts": 2, "startedAt": "2026-10-20T08:00:00+00:00", "finishedAt": "2026-10-20T09:00:00+00:00"},
            {"id": "S2", "title": "b", "status": "done", "attempts": 1, "startedAt": "2026-10-20T08:30:00+00:00", "finishedAt": "2026-10-20T10:00:00+00:00"},
            {"id": "S3", "title": "c", "status": "done"}]},
        {"id": "M2", "title": "second", "status": "done", "stories": [
            {"id": "S4", "title": "d", "status": "done", "startedAt": "2026-10-22T08:00:00+00:00", "finishedAt": "2026-10-22T08:20:00+00:00"}]},
        {"id": "M3", "title": "third", "status": "todo", "stories": [{"id": "S5", "title": "e", "status": "todo"}]}]}]}
HIDE_FINISHED = "podium-hide-finished:api"
COST = {"ready": True, "milestones": {"M1": {"input": 1000, "cacheWrite": 100000, "cacheRead": 3000000, "output": 99000, "stories": {}},
                                      "__proto__": {"input": 5, "cacheWrite": 5, "cacheRead": 5, "output": 5}}}
PROTO_PROGRESS = "".join(f"2026-10-20T0{i + 6}:00:00+00:00 {kind} note\n" for i, kind in enumerate(reversed(KEYS)))

CONSENT = "core-events/src/main/java/se/parkster/events/domain/parking/consent"
RADAR_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M1"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "building", "status": "working", "phase": "build", "stories": [
            {"id": "S1", "title": "a", "status": "todo", "files": [f"{CONSENT}/{{Email,Sms}}MarketingConsentGivenEvent.java"]},
            {"id": "S2", "title": "b", "status": "working", "files": ["web-applications/M/messages/{en,sv}.json", "web-applications/A/lib/client.ts"]},
            {"id": "S3", "title": "c", "status": "todo", "deps": ["S2"], "files": ["web-applications/A/lib/client.ts"]},
            {"id": "S4", "title": "d", "status": "todo", "files": ["web-applications/M/messages/sv.json"]},
            {"id": "S5", "title": "e", "status": "done", "files": ["app-messaging-service/controller/dto/AudienceDTO.kt"]}]},
        {"id": "M2", "title": "up next", "status": "todo", "stories": [
            {"id": "T1", "title": "f", "status": "todo", "files": [f"{CONSENT}/*.java"]},
            {"id": "T2", "title": "g", "status": "todo", "files": ["app-messaging-service/controller/dto/AudienceDTO.kt"]}]},
        {"id": "M3", "title": "parked", "status": "parked", "stories": [{"id": "P1", "title": "h", "status": "todo", "files": ["web-applications/A/lib/client.ts"]}]},
        {"id": "M4", "title": "after", "status": "todo", "deps": ["M1"], "stories": [{"id": "Q1", "title": "i", "status": "todo", "files": ["web-applications/A/lib/client.ts"]}]},
        {"id": "M5", "title": "dropped story", "status": "draft", "stories": [{"id": "R1", "title": "j", "status": "dropped", "files": ["web-applications/A/lib/client.ts"]}]},
        {"id": "M6", "title": "landed", "status": "done", "stories": [{"id": "D1", "title": "k", "status": "todo", "files": ["web-applications/A/lib/client.ts"]}]}]}]}

HARNESS = r"""
const OUT = [];
const LISTENERS = {};
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
    setAttribute() {}, removeAttribute() {}, addEventListener() {}, focus() {}, blur() {}, select() {}, querySelector() { return null; }, querySelectorAll() { return []; },
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
              addEventListener: (type, f) => (LISTENERS[type] ||= []).push(f), visibilityState: "visible", hidden: false, title: "", createElement: element },
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


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


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
        files = {**files, "localStorage": {HIDE_FINISHED: "0", **files.get("localStorage", {})}, "podium/podium.json": json.dumps(run), "podium/events.jsonl": "".join(json.dumps(e) + "\n" for e in events),
                 "/info": json.dumps({"runDir": "/run", "repoDir": "/repo", "run": "api", "watching": True, "me": "ann", "people": {},
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

    def state_labels(self, run, stored=None):
        """The label of every Filter button the page rendered, in render order."""
        self.rendered(run, [], PROGRESS, (), localStorage=stored or {})
        return [re.search(r"data-state-menu [^>]*>(.*?)</button>", html).group(1) for html in self.html if "data-state-menu" in html]

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

    def test_a_list_field_stored_as_text_drops_that_field_and_keeps_the_map(self):
        run = json.loads(json.dumps(CYCLIC_RUN))
        landed = {"id": "M3", "title": "landed-with-text-artifacts", "status": "done", "deps": "[M1]",
                  "artifacts": "[{name:mock,path:mock/index.html,phase:mock}]"}
        run["epics"][0]["milestones"].append(landed)
        scan = self.rendered(run, [], PROGRESS, ("S1", "S2", "S3"))
        self.assertIn("landed-with-text-artifacts", "".join(scan.text))

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

    def test_the_map_header_has_no_hide_finished_button_and_shows_everything_by_default(self):
        labels = self.state_labels(FINISHED_RUN)
        self.assertTrue(labels)
        self.assertEqual(set(labels), {"Filter"})
        self.assertNotIn('id="hide-finished"', open(PAGE).read())

    def test_a_stored_unticked_finished_reads_as_the_default(self):
        self.assertIn('"podium-hide-finished"', open(PAGE).read())
        self.assertEqual(set(self.state_labels(FINISHED_RUN, {"podium-hide-finished:api": "1"})), {"Filter"})

    def collapse_button(self, html):
        return re.search(r'<button class="share ?(on)?" data-collapse-map aria-pressed="(\w+)"[^>]*>Collapsed</button>', html)

    def test_a_collapsed_button_opens_the_map_header_filters_and_is_off_by_default(self):
        self.assertIn('<span id="collapse-map"></span><span id="map-sort"></span><span id="state-filter"></span>', open(PAGE).read())
        maps, _ = self.maps()
        self.assertEqual(self.collapse_button("".join(self.html)).group(2), "false")
        self.assertNotIn("data-collapsed", maps[-1])

    def test_collapsed_is_kept_in_podium_collapsed_and_marks_the_map(self):
        maps, _ = self.maps(localStorage={"podium-collapsed:api": "1"})
        self.assertEqual(self.collapse_button("".join(self.html)).groups(), ("on", "true"))
        self.assertIn('<div class="full" data-collapsed style=', maps[0])

    def test_pressing_collapsed_flips_it_and_an_open_milestone_stays_in_full(self):
        maps, _ = self.maps(probe='(setCollapsed(true), render(), expand("M2"), S.collapsed)')
        self.assertTrue(self.probe())
        self.assertIn("data-collapsed", maps[-1])
        self.assertIn('<div class="ohead">', self.open_card(maps[-1]))
        css = open(PAGE).read()
        for hidden in (".ftools", ".ms-repos", ".foot", ".fdots"):
            self.assertRegex(css, r"\.full\[data-collapsed\] \.fms:not\(\.open\) " + re.escape(hidden) + r"\b[^{]*\{ display: none")

    def prio_filter(self):
        """The Filter pull-down's priority half as the last render put it: its label, aria-expanded, and each box as (tier, label, checked, disabled)."""
        label, expanded, boxes = self.state_filter()
        return label, expanded, [b for b in boxes if b[0] in ("must", "should", "nice")]

    def state_filter(self):
        """The Filter pull-down as the last render put it: its label, aria-expanded, and each box as (key, label, checked, disabled)."""
        html = [h for h in self.html if "data-state-menu" in h][-1]
        button = re.search(r'<button class="share ?(?:on)?" data-state-menu aria-expanded="(\w+)"[^>]*>(.*?)</button>', html)
        boxes = re.findall(r'<label><input type="checkbox" data-state-show="(\w+)"( checked)?( disabled)?>(.*?)(?:<small>.*?</small>)?</label>', html)
        return button.group(2), button.group(1), [(key, re.sub(r"<[^>]+>", "", label), bool(on), bool(off)) for key, on, off, label in boxes]

    @staticmethod
    def shown(full):
        return re.findall(r'<div class="fms [^"]*" [^>]*?data-id="([^"]*)"', full)

    def test_a_state_pull_down_sits_after_collapsed_and_sort_closed_and_showing_every_tier(self):
        self.assertIn('<span id="collapse-map"></span><span id="map-sort"></span><span id="state-filter"></span>', open(PAGE).read())
        maps, _ = self.maps(self.priority_run())
        self.assertEqual(self.prio_filter(), ("Filter", "false", []))
        self.assertEqual(sorted(self.shown(maps[0])), ["M1", "M2", "M3", "R1"])

    def test_opening_the_state_menu_lists_the_tiers_then_paused_closed_and_finished(self):
        self.maps(self.priority_run(), probe="(setStateMenu(true), S.stateMenu)")
        self.assertTrue(self.probe())
        self.assertEqual(self.state_filter(), ("Filter", "true", [("must", "★Must", True, False), ("should", "★Should", True, False),
                                                                 ("nice", "Nice to have", True, False), ("paused", "Paused", True, False),
                                                                 ("closed", "Closed", False, False), ("finished", "Finished", True, False)]))
        menu = [h for h in self.html if "data-state-menu" in h][-1]
        self.assertIn('data-state-show="must" checked><span class="prio must" title="Must have"><b>★</b>Must</span>', menu)
        for key, badge in (("paused", "parked"), ("closed", "dropped"), ("finished", "done")):
            self.assertRegex(menu, f'data-state-show="{key}"[^>]*><span class="badge {badge}">')

    def test_unticking_a_tier_hides_its_milestones_says_how_many_tiers_show_and_keeps_the_choice(self):
        maps, _ = self.maps(self.priority_run(), probe='(() => { const put = {}; localStorage.setItem = (k, v) => { put[k] = v; };'
                                                       ' closeSheet(); togglePrioTier("nice"); render(); return put["podium-priority-filter:api"]; })()')
        self.assertEqual(json.loads(self.probe()), ["must", "should"])
        self.assertEqual(self.shown(maps[-1]), ["M2", "M3"])
        self.assertEqual(self.prio_filter()[0], "Filter · 2 hidden")

    def test_the_priority_filter_is_read_from_podium_priority_filter(self):
        maps, _ = self.maps(self.priority_run(), localStorage={"podium-priority-filter:api": '["should"]'})
        self.assertEqual(self.shown(maps[0]), ["M3"])
        self.assertEqual(self.prio_filter()[0], "Filter · 3 hidden")

    def test_a_missing_broken_or_hostile_priority_filter_shows_every_tier(self):
        for stored in ("", "{", '"must"', '{"0": "must", "length": 1}', "[]", "null", "[1, 2]", json.dumps(["__proto__", X]), json.dumps(X)):
            with self.subTest(stored=stored):
                maps, _ = self.maps(self.priority_run(), localStorage={"podium-priority-filter:api": stored})
                self.assertEqual(sorted(self.shown(maps[0])), ["M1", "M2", "M3", "R1"])
                self.assertEqual(self.prio_filter()[0], "Filter")
                self.assertNotIn("pwn", "".join(h for h in self.html if "data-state-menu" in h))

    def test_the_last_ticked_tier_cannot_be_unticked(self):
        self.maps(self.priority_run(), localStorage={"podium-priority-filter:api": '["must"]'},
                  probe='(togglePrioTier("must"), setStateMenu(true), S.prioShown)')
        self.assertEqual(self.probe(), ["must"])
        self.assertEqual(self.prio_filter(), ("Filter · 2 hidden", "true", [("must", "★Must", True, True), ("should", "★Should", False, False),
                                                                            ("nice", "Nice to have", False, False)]))

    def test_the_open_milestone_stays_on_the_map_when_its_tier_is_unticked(self):
        maps, _ = self.maps(self.priority_run(), localStorage={"podium-priority-filter:api": '["must"]'}, probe='(closeSheet(), expand("M3"))')
        self.assertEqual(self.shown(maps[-1]), ["M2", "M3"])
        self.assertEqual(self.open_cards(maps[-1]), ["M3"])

    def test_epic_tiles_are_not_filtered_by_priority(self):
        maps, _ = self.maps(self.priority_run(), localStorage={"podium-priority-filter:api": '["nice"]'})
        self.assertEqual(re.findall(r'<div class="fepic" data-epic-sheet="(\w+)"', maps[0]), ["e1", "e2"])
        self.assertEqual(sorted(self.shown(maps[0])), ["M1", "R1"])

    def test_the_state_count_leaves_out_the_finished_milestones_a_tier_also_hides(self):
        run = json.loads(json.dumps(HIDE_RUN))
        run["epics"][0]["milestones"][2]["priority"] = "must"
        shown, _, label = self.hidden_map({"podium-hide-finished:api": "1", "podium-priority-filter:api": '["must"]'}, run=run,
                                          probe='(closeSheet(), expand("M3"), 0)')
        self.assertEqual(shown, ["M3"])
        self.assertEqual(label, "Filter · 1 hidden")

    @staticmethod
    def paused_run():
        run = json.loads(json.dumps(HIDE_RUN))
        run["epics"][0]["milestones"] += [{"id": "M5", "title": "parked", "status": "parked"}, {"id": "M6", "title": "later", "status": "later"},
                                          {"id": "M7", "title": "dropped", "status": "dropped"}]
        return run

    def test_paused_and_finished_milestones_show_and_closed_ones_stay_off_by_default(self):
        shown, _, label = self.hidden_map({}, run=self.paused_run())
        self.assertEqual(shown, ["M1", "M2", "M3", "M4", "M5", "M6"])
        self.assertEqual(label, "Filter")

    def test_finished_milestones_and_stories_are_hidden_until_the_user_ticks_finished(self):
        shown, stories, label = self.hidden_map({HIDE_FINISHED: None}, run=self.paused_run())
        self.assertEqual(shown, ["M3", "M4", "M5", "M6"])
        self.assertEqual(stories, ["S4", "S5"])
        self.assertEqual(label, "Filter")
        self.assertEqual(self.state_filter()[0], "Filter")
        self.assertNotIn('class="share on" data-state-menu', [h for h in self.html if "data-state-menu" in h][-1])

    def test_ticking_finished_shows_them_and_marks_the_menu_as_changed(self):
        shown, _, label = self.hidden_map({HIDE_FINISHED: "0"}, run=self.paused_run())
        self.assertEqual(shown, ["M1", "M2", "M3", "M4", "M5", "M6"])
        self.assertIn('class="share on" data-state-menu', [h for h in self.html if "data-state-menu" in h][-1])

    def test_the_count_leaves_out_the_finished_milestones_hidden_by_default(self):
        _, _, label = self.hidden_map({HIDE_FINISHED: None, "podium-hide-paused:api": "1"}, run=self.paused_run())
        self.assertEqual(label, "Filter · 2 hidden")

    def test_unticking_paused_hides_parked_and_later_milestones_and_keeps_the_choice(self):
        maps, _ = self.maps(self.paused_run(), probe=self.PUT % 'closeSheet(); toggleState("paused"); render()')
        self.assertEqual(self.probe(), ["podium-hide-paused:api"])
        self.assertEqual(self.shown(maps[-1]), ["M1", "M2", "M3", "M4"])
        self.assertEqual(self.state_filter()[0], "Filter · 2 hidden")

    def test_ticking_closed_shows_dropped_milestones_with_a_dropped_badge(self):
        maps, _ = self.maps(self.paused_run(), localStorage={"podium-show-closed:api": "1"}, probe="(closeSheet(), render(), 0)")
        self.assertEqual(self.shown(maps[-1]), ["M1", "M2", "M3", "M4", "M5", "M6", "M7"])
        cards = {re.search(r'data-id="([^"]*)"', c).group(1): c for c in re.split(r'(?=<div class="fms )', maps[-1])[1:]}
        self.assertTrue(cards["M7"].startswith('<div class="fms dropped'))
        self.assertIn('<span class="badge dropped">Dropped</span>', cards["M7"])
        self.assertEqual(self.state_filter()[0], "Filter")

    def test_a_dropped_milestone_is_never_up_next(self):
        run = self.paused_run()
        run["epics"][0]["milestones"] = [m for m in run["epics"][0]["milestones"] if m["id"] != "M4"]
        maps, _ = self.maps(run, localStorage={"podium-show-closed:api": "1"}, probe="(closeSheet(), render(), 0)")
        self.assertNotRegex(maps[-1], r'<div class="fnext">Up next</div><div class="fms dropped')

    def test_unticking_finished_from_the_menu_hides_landed_milestones(self):
        maps, _ = self.maps(self.paused_run(), probe='(closeSheet(), toggleState("finished"), render(), S.hideFinished)')
        self.assertTrue(self.probe())
        self.assertEqual(self.shown(maps[-1]), ["M3", "M4", "M5", "M6"])

    def test_escape_closes_the_state_menu_before_the_open_milestone(self):
        self.maps(self.priority_run(), probe='(() => { closeSheet(); expand("M2"); setStateMenu(true); onEscape(); return [S.stateMenu, S.open]; })()')
        self.assertEqual(self.probe(), [False, "M2"])
        self.assertEqual(self.prio_filter()[1], "false")

    def test_the_state_menu_stays_open_while_ticking_and_a_click_outside_closes_it(self):
        self.maps(self.priority_run(), probe='(() => { const click = (...hits) => { const target = { dataset: { stateShow: "should" }, closest: (s) => (hits.includes(s) ? target : null) };'
                                             ' LISTENERS.click.forEach((f) => f({ target, stopPropagation() {} })); return S.stateMenu; };'
                                             ' closeSheet(); const opened = click("#state-filter", "[data-state-menu]"); const ticked = click("#state-filter", "[data-state-show]");'
                                             ' const shown = [...S.prioShown]; return [opened, ticked, shown, click()]; })()')
        self.assertEqual(self.probe(), [True, True, ["must", "nice"], False])

    @staticmethod
    def sort_run():
        run = json.loads(json.dumps(OPEN_RUN))
        run["needsYou"] = {"story": "A4/S1"}
        run["epics"][0]["milestones"] = [
            {"id": "A1", "title": "landed", "status": "done", "owner": "bob"},
            {"id": "A2", "title": "building", "status": "working", "phase": "build", "owner": "ann", "priority": "should"},
            {"id": "A3", "title": "ready", "status": "todo", "owner": "cy", "priority": "must"},
            {"id": "A4", "title": "draft", "status": "draft", "priority": "must"},
            {"id": "A5", "title": "parked", "status": "parked", "owner": "bob", "priority": "should"},
            {"id": "A6", "title": "waiting", "status": "todo", "deps": ["A3"], "owner": "ann"}]
        return run

    def sorted_lanes(self, sort, probe="(closeSheet(), render(), 0)"):
        maps, _ = self.maps(self.sort_run(), localStorage={"podium-sort:api": sort}, probe=probe)
        cols = re.findall(r'<div class="fcol" data-lane="(\d)">(.*?)</div><!--fcol-->', maps[-1], re.S)
        return maps[-1], [re.findall(r'<div class="fms [^"]*"[^>]* data-id="(\w+)"', html) for _, html in cols]

    def sort_menu(self):
        """The Sort pull-down as the last render put it: its label, aria-expanded, and each row as (key, label, checked)."""
        html = [h for h in self.html if "data-sort-menu" in h][-1]
        button = re.search(r'<button class="share ?(?:on)?" data-sort-menu aria-expanded="(\w+)"[^>]*>(.*?)</button>', html)
        rows = re.findall(r'<label><input type="radio" name="podium-sort" data-sort="(\w+)"( checked)?><b class="tick">(?:✓)?</b>(.*?)<small>', html)
        return button.group(2), button.group(1), [(key, label, bool(on)) for key, on, label in rows]

    def test_a_sort_pull_down_sits_before_state_and_keeps_run_order_by_default(self):
        self.assertIn('<span id="collapse-map"></span><span id="map-sort"></span><span id="state-filter"></span>', open(PAGE).read())
        _, lanes = self.sorted_lanes("run")
        self.assertEqual(lanes, [["A1", "A2", "A3", "A4", "A5", "A6"], ["M2", "M3"]])
        self.assertEqual(self.sort_menu(), ("Sort", "false", []))
        self.assertNotIn('class="share on" data-sort-menu', [h for h in self.html if "data-sort-menu" in h][-1])

    def test_opening_the_sort_menu_lists_run_order_mine_priority_status_and_owner_with_a_tick_on_the_choice(self):
        self.maps(self.sort_run(), probe="(setSortMenu(true), S.sortMenu)")
        self.assertTrue(self.probe())
        self.assertEqual(self.sort_menu(), ("Sort", "true", [("run", "Run order", True), ("mine", "Mine first", False), ("priority", "Priority", False),
                                                             ("status", "Status", False), ("owner", "Owner", False)]))
        menu = [h for h in self.html if "data-sort-menu" in h][-1]
        self.assertIn('role="radiogroup"', menu)
        self.assertIn('data-sort="run" checked><b class="tick">✓</b>', menu)
        self.assertIn('data-sort="priority"><b class="tick"></b>Priority<small><span class="prio must"', menu)

    def test_sorting_reorders_cards_within_each_epic_and_keeps_run_order_inside_a_group(self):
        for sort, first in (("mine", ["A2", "A6", "A4", "A1", "A3", "A5"]), ("priority", ["A3", "A4", "A2", "A5", "A1", "A6"]),
                            ("status", ["A2", "A3", "A6", "A4", "A5", "A1"]), ("owner", ["A2", "A6", "A1", "A5", "A3", "A4"])):
            with self.subTest(sort=sort):
                _, lanes = self.sorted_lanes(sort)
                self.assertEqual(lanes, [first, ["M2", "M3"]])

    def test_a_sort_shows_on_its_button_and_up_next_stays_on_the_milestone_really_next(self):
        full, _ = self.sorted_lanes("status")
        self.assertEqual(self.sort_menu()[0], "Sort · Status")
        self.assertIn('class="share on" data-sort-menu', [h for h in self.html if "data-sort-menu" in h][-1])
        self.assertRegex(full, r'<div class="fnext">Up next</div><div class="fms [^"]*"[^>]* data-id="A3"')
        self.assertEqual(full.count('<div class="fnext">'), 1)

    def test_a_sort_drops_the_queue_lines_and_keeps_the_cross_epic_deps(self):
        cards = '[{ id: "A", lane: "0", deps: [] }, { id: "B", lane: "0", deps: ["A"] }, { id: "U1", lane: "1", deps: ["B"] }]'
        self.maps(probe=f'(() => {{ const before = queuePairs({cards}); setSort("priority"); return [before, queuePairs({cards})]; }})()')
        self.assertEqual(self.probe(), [[["A", "B", "queue"], ["B", "U1", "dep"]], [["B", "U1", "dep"]]])

    def test_picking_a_sort_keeps_it_under_podium_sort_and_the_menu_stays_open_until_a_click_outside(self):
        self.maps(self.sort_run(), probe='(() => { const put = {}; localStorage.setItem = (k, v) => { put[k] = v; };'
                                         ' const click = (...hits) => { const target = { dataset: { sort: "owner" }, closest: (s) => (hits.includes(s) ? target : null) };'
                                         ' LISTENERS.click.forEach((f) => f({ target, stopPropagation() {} })); return S.sortMenu; };'
                                         ' closeSheet(); const opened = click("#map-sort", "[data-sort-menu]"); const picked = click("#map-sort", "[data-sort]");'
                                         ' return [opened, picked, put["podium-sort:api"], click()]; })()')
        self.assertEqual(self.probe(), [True, True, "owner", False])

    def test_a_missing_broken_or_hostile_stored_sort_reads_as_run_order(self):
        for stored in ("", "{", "null", "Priority", "__proto__", "constructor", "toString", X):
            with self.subTest(stored=stored):
                _, lanes = self.sorted_lanes(stored, probe="S.sort")
                self.assertEqual(self.probe(), "run")
                self.assertEqual(lanes[0], ["A1", "A2", "A3", "A4", "A5", "A6"])
                self.assertEqual(self.sort_menu()[0], "Sort")

    def test_escape_closes_the_sort_menu_before_the_open_milestone(self):
        self.maps(self.sort_run(), probe='(() => { closeSheet(); expand("M2"); setSortMenu(true); onEscape(); return [S.sortMenu, S.open]; })()')
        self.assertEqual(self.probe(), [False, "M2"])
        self.assertEqual(self.sort_menu()[1], "false")

    def test_a_stored_podium_hide_finished_stories_changes_nothing_and_the_page_no_longer_names_it(self):
        labels = self.state_labels(FINISHED_RUN, {"podium-hide-finished-stories": "1"})
        self.assertEqual(set(labels), {"Filter"})
        self.assertNotIn("podium-hide-finished-stories", open(PAGE).read())

    def hidden_map(self, stored=None, run=HIDE_RUN, probe='(expand("M3"), 0)'):
        """The last full map's milestone ids, the story ids inside the open milestone, and the Filter label."""
        stored = {"podium-hide-finished:api": "1"} if stored is None else stored
        maps, _ = self.maps(run, localStorage=stored, probe=probe)
        full = maps[-1]
        open_card = self.open_card(full)
        shown = re.findall(r'<div class="fms [^"]*" [^>]*?data-id="([^"]*)"', full)
        stories = re.findall(r'<div class="node compact [^"]*" data-open="[^"]*" data-story="([^"]*)"', open_card)
        label = re.search(r"data-state-menu [^>]*>(.*?)</button>", next(h for h in reversed(self.html) if "data-state-menu" in h)).group(1)
        return shown, stories, label

    def test_hide_finished_hides_landed_and_moved_milestones_and_finished_stories_of_the_open_one(self):
        shown, stories, _ = self.hidden_map()
        self.assertEqual(shown, ["M3", "M4"])
        self.assertEqual(stories, ["S4", "S5"])

    def test_hide_finished_shows_every_milestone_and_story_while_off(self):
        shown, stories, label = self.hidden_map({})
        self.assertEqual(shown, ["M1", "M2", "M3", "M4"])
        self.assertEqual(sorted(stories), ["S1", "S2", "S3", "S4", "S5"])
        self.assertEqual(label, "Filter")

    def test_hiding_finished_work_is_the_default_so_it_counts_nothing(self):
        self.assertEqual(self.hidden_map()[2], "Filter")

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
        self.assertEqual(set(self.state_labels(FINISHED_RUN, {"podium-hide-finished:api": "0"})), {"Filter"})

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

    def test_collapse_has_its_own_corner_of_the_open_cards_head_so_no_button_lands_on_it(self):
        maps, _ = self.maps(probe='expand("M2")')
        self.assertIn('<div class="ohead"><button class="ocollapse" data-collapse aria-expanded="true">▾ Collapse</button><span class="fid">', self.open_card(maps[-1]))
        css = open(PAGE).read()
        self.assertIn(".ohead { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-rows: auto 1fr; gap: 6px 14px; align-items: start; container-type: inline-size; }", css)
        self.assertIn(".ohead > .ocollapse { grid-column: 2; grid-row: 1; justify-self: end; }", css)
        self.assertIn(".ohead > .oside { grid-column: 2; grid-row: 2; }", css)
        self.assertIn("@container (max-width: 560px) { .ohead > .fid { grid-row: 1; } .ohead > .oside { grid-column: 1 / -1; } }", css)
        self.assertNotIn("position: absolute; top: 0; right: 0", css)

    def test_the_open_card_has_a_collapse_button_and_a_title_that_opens_the_milestone_sheet(self):
        maps, _ = self.maps(probe='expand("M2")')
        card = self.open_card(maps[-1])
        self.assertIn('<button class="ocollapse" data-collapse aria-expanded="true">', card)
        self.assertRegex(card, r'<span class="title otitle" data-open="M2"[^>]*>second</span>')
        self.assertLess(card.index("data-collapse"), card.index('class="title otitle"'), "Collapse sits in the top row, before the title")
        self.assertNotIn("data-collapse", card[card.index('class="oside"'):])
        self.assertNotIn("data-expand-ms", card.split(">")[0])

    @staticmethod
    def priority_run():
        run = json.loads(json.dumps(OPEN_RUN))
        m2, m3 = run["epics"][1]["milestones"][:2]
        m2["priority"], m3["priority"] = "must", "should"
        run["epics"][0].update(quest="US1", priority="must")
        run["epics"][1].update(quest="US2", priority="should")
        return run

    def test_must_and_should_have_milestones_show_their_pill_after_the_id_and_the_rest_none(self):
        maps, _ = self.maps(self.priority_run())
        cards = {re.search(r'data-id="([^"]*)"', c).group(1): c for c in re.split(r'(?=<div class="fms )', maps[0])[1:]}
        self.assertIn('<span class="sid">M2</span><span class="prio must" title="Must have"><b>★</b>Must</span>', cards["M2"])
        self.assertIn('<span class="sid">M3</span><span class="prio should" title="Should have"><b>★</b>Should</span>', cards["M3"])
        self.assertNotIn('class="prio', cards["M1"])
        self.assertNotIn("data-prio", maps[0])

    QUEST_MS = ('[..."must must must must should should should nice nice nice".split(" ").map((t, i) => ({ id: `M${i}`, priority: t === "nice" ? undefined : t,'
                ' status: [0, 4, 5, 7].includes(i) ? "done" : "todo" }))]')

    def timeline(self, quest, y, m, d):
        self.maps(probe=f"questTimeline({json.dumps(quest)}, {self.QUEST_MS}, new Date({y}, {m - 1}, {d}, 12))")
        return self.probe()

    def test_the_quest_timeline_shows_the_week_today_and_the_open_weeks_after(self):
        t = self.timeline({"start": "2026-10-12"}, 2026, 11, 5)
        self.assertIn('<span><b>Week 4 of 6</b> · 17 days left', t)
        self.assertIn('<span>Open weeks 23 Nov – 6 Dec</span>', t)
        self.assertIn('style="grid-template-columns:repeat(6, 1fr) repeat(2, .7fr)"', t)
        self.assertEqual(re.findall(r'<span class="qcell( [a-z ]+)?"', t), [" past", " past", " past", " now", "", "", " open", " open"])
        self.assertIn('<span class="qcell now" style="--fill:57%"><i class="qneedle"></i></span>', t)
        self.assertEqual(re.findall(r'<span( class="now")?>((?:W|Open )\d)</span>', t),
                         [("", "W1"), ("", "W2"), ("", "W3"), (' class="now"', "W4"), ("", "W5"), ("", "W6"), ("", "Open 1"), ("", "Open 2")])

    def test_the_pills_count_what_is_left_to_reach_the_goal_overall_and_per_priority_never_behind(self):
        t = self.timeline({"start": "2026-10-12"}, 2026, 11, 5)
        self.assertIn('<span class="pace">4 of 10 landed · 6 to go, ≈ 3 a week</span>', t)
        self.assertIn('<span class="pace">★ Must 1 of 4 · 3 to go</span>', t)
        self.assertIn('<span class="pace">★ Should 2 of 3 · 1 to go</span>', t)
        self.assertNotIn("Nice", t)
        self.assertNotIn("behind", t)

    def test_before_the_quest_starts_the_timeline_counts_down_without_pace(self):
        t = self.timeline({"start": "2026-10-12"}, 2026, 10, 5)
        self.assertIn('<span><b>Quest starts 12 Oct</b> · in 7 days', t)
        self.assertNotIn("pace", t)
        self.assertNotIn("qneedle", t)

    def test_in_the_open_weeks_and_after_them_the_pills_count_what_is_left_without_a_weekly_rate(self):
        t = self.timeline({"start": "2026-10-12"}, 2026, 11, 25)
        self.assertIn('<span><b>Open week 1 of 2</b> · 11 days left', t)
        self.assertEqual(re.findall(r'<span class="qcell( [a-z ]+)?"', t)[5:], [" past", " open now", " open"])
        self.assertIn('<span class="pace">4 of 10 landed · 6 to go</span>', t)
        t = self.timeline({"start": "2026-10-12"}, 2026, 12, 10)
        self.assertIn('<span><b>Quest ended 22 Nov</b>', t)
        self.assertNotIn("qneedle", t)

    def test_the_quest_length_and_open_weeks_can_be_set_and_bad_values_fall_back(self):
        t = self.timeline({"start": "2026-10-12", "weeks": 4, "openWeeks": 0}, 2026, 10, 20)
        self.assertIn('<span><b>Week 2 of 4</b>', t)
        self.assertIn('<span>Ends 8 Nov</span>', t)
        self.assertIn("repeat(4, 1fr)", t)
        t = self.timeline({"start": "2026-10-12", "weeks": "<b>", "openWeeks": -3}, 2026, 11, 5)
        self.assertIn("repeat(6, 1fr) repeat(2, .7fr)", t)
        for quest in ({}, {"start": "<script>"}, {"start": "2026-13-45"}, {"start": 20261012}, None):
            self.assertEqual(self.timeline(quest, 2026, 11, 5), "", quest)

    def test_the_quest_tile_carries_the_timeline_when_the_quest_has_a_start(self):
        page = open(PAGE).read()
        self.assertRegex(page, r"\$\{questTimeline\(q, ms, new Date\(\)\)\}")

    WRAP_MS = ('[{ id: "M1", title: "Login", priority: "must", status: "done", owner: "ann" }, { id: "M2", title: "Pay", priority: "must", status: "done", owner: "bo" },'
               ' { id: "M3", title: "Receipt", priority: "must", status: "working", owner: "bo" }, { id: "M4", title: "Badge", priority: "should", status: "done", owner: "ann" },'
               ' { id: "M5", title: "Theme", priority: "should", status: "todo" }, { id: "M6", title: "Old flow", status: "moved", owner: "cy" },'
               ' { id: "M7", title: "Confetti", status: "done" }]')

    def wrap(self, y, m, d, quest=None, landed_open=True):
        self.maps(probe=f"(S.wrapLanded = {json.dumps(landed_open)}, questWrap({json.dumps({'start': '2026-10-12'} if quest is None else quest)}, {self.WRAP_MS}, new Date({y}, {m - 1}, {d}, 12)))")
        return self.probe()

    def test_the_quest_wrap_up_shows_from_the_last_quest_week_until_the_open_weeks_end(self):
        self.assertEqual(self.wrap(2026, 11, 15), "")
        self.assertIn("Quest wrap-up", self.wrap(2026, 11, 16))
        self.assertIn("Quest wrap-up", self.wrap(2026, 12, 6))
        self.assertEqual(self.wrap(2026, 12, 7), "")
        self.assertIn("Quest wrap-up", self.wrap(2026, 11, 2, {"start": "2026-10-12", "weeks": 4, "openWeeks": 0}))
        self.assertEqual(self.wrap(2026, 11, 9, {"start": "2026-10-12", "weeks": 4, "openWeeks": 0}), "")
        self.assertEqual(self.wrap(2026, 11, 20, {}), "")

    def test_the_quest_wrap_up_tallies_what_landed_moved_is_still_open_and_who_landed_it(self):
        w = self.wrap(2026, 11, 18)
        self.assertIn('<b>Quest wrap-up</b> · last week, 4 days left', w)
        rows = dict(re.findall(r'<div class="qw-row"><span class="qw-k">(?:<button[^>]*>)?([^<]*)(?:</button>)?</span><span class="qw-v">(.*?)</span></div>', w))
        chips = lambda k: re.findall(r'<span class="wchip [a-z]*" data-reveal="(M\d)"><b>M\d</b> ([^<]*)</span>', rows[k])
        self.assertEqual(chips("Landed"), [("M1", "Login"), ("M2", "Pay"), ("M4", "Badge"), ("M7", "Confetti")])
        self.assertEqual(chips("Still open"), [("M3", "Receipt"), ("M5", "Theme")])
        self.assertEqual(chips("Moved"), [("M6", "Old flow")])
        self.assertEqual(rows["Landed by"], "you 2 · bo 1 · no owner 1")
        self.assertIn("★ Must 2 of 3", rows["Tally"])
        self.assertIn("★ Should 1 of 2", rows["Tally"])
        self.assertIn("4 of 6 landed", rows["Tally"])
        self.assertIn("data-quest-copy", w)

    def test_in_the_open_weeks_the_wrap_up_says_so_and_copies_as_text(self):
        self.assertIn('<b>Quest wrap-up</b> · open weeks, 11 days left', self.wrap(2026, 11, 25))
        self.maps(probe=f"wrapText({self.WRAP_MS})")
        self.assertEqual(self.probe().splitlines(), [
            "4 of 6 landed · ★ Must 2 of 3 · ★ Should 1 of 2",
            "Landed: M1 Login, M2 Pay, M4 Badge, M7 Confetti",
            "Still open: M3 Receipt, M5 Theme",
            "Moved: M6 Old flow",
            "Landed by: ann 2 · bo 1 · no owner 1"])

    def test_the_landed_row_starts_folded_to_its_count_behind_an_arrow(self):
        folded = self.wrap(2026, 11, 18, landed_open=False)
        self.assertIn('<button class="qw-fold" data-wrap-landed aria-expanded="false">Landed</button>', folded)
        self.assertIn('<span class="qw-folded">4 milestones</span>', folded)
        self.assertNotIn('data-reveal="M1"', folded)
        self.assertIn('data-reveal="M3"', folded)
        self.assertIn('aria-expanded="true">Landed</button>', self.wrap(2026, 11, 18))
        self.maps(probe="S.wrapLanded")
        self.assertFalse(self.probe())

    def test_the_wrap_up_chips_carry_the_milestone_status_like_the_map(self):
        w = self.wrap(2026, 11, 18)
        self.assertIn('<span class="wchip done" data-reveal="M1">', w)
        self.assertIn('<span class="wchip working" data-reveal="M3">', w)
        self.assertIn('<span class="wchip todo" data-reveal="M5">', w)
        self.assertIn('<span class="wchip moved" data-reveal="M6">', w)

    def test_opening_the_landed_row_is_kept_for_the_run(self):
        page = open(PAGE).read()
        self.assertIn('S.wrapLanded = readRun("podium-wrap-landed") === "1"', page)
        self.assertIn('writeRun("podium-wrap-landed", S.wrapLanded ? "1" : "0")', page)

    def test_the_activity_button_carries_an_arrow_that_turns_when_open(self):
        page = open(PAGE).read()
        self.assertRegex(page, r'<button class="icon-btn" id="feed-toggle"><svg class="chev"')
        self.assertIn('#feed-toggle[aria-pressed="true"] .chev { transform: rotate(180deg); }', page)

    HOSTILE_ITEM = {"id": X, "bucket": X, "role": X, "head": X, "why": X, "isNew": True, "risk": {"level": X, "text": X}}
    HOSTILE_DRAFT = {
        "name": X, "kind": X, "writtenAt": X, "cover": {"from": X, "label": X}, "sections": X,
        "banner": {"title": X, "lede": X, "image": JS, "testUrl": JS, "testLabel": X},
        "stats": [{"n": X, "label": X}, X],
        "tiers": {"must": [HOSTILE_ITEM, {**HOSTILE_ITEM, "bucket": "open", "risk": {"level": "blocks", "text": X}}, X, None],
                  "should": [{**HOSTILE_ITEM, "internal": True}], "nice": X, X: [HOSTILE_ITEM]},
        "earlier": {"must": X, "should": 2}, "moved": [HOSTILE_ITEM], "asks": [{"question": X, "owner": X, "with": X, "by": X}],
        "next": [X, 3, None], "answers": [{"commentId": X, "who": X, "role": X, "question": X, "answer": X}],
        "apps": {"lede": X, "groundwork": X, "links": [{"label": X, "url": JS}, {"label": X, "url": "https://github.com/o/r/milestone/1"}],
                 "items": [{**HOSTILE_ITEM, "platforms": {X: {"state": X, "url": JS}, "iOS": {"state": "done", "url": " JaVaScRiPt:alert(1)"},
                                                          "Android": {"state": "flag", "url": "https://github.com/o/a/pull/1"}}}],
                 "open": [HOSTILE_ITEM]},
        "footer": {"owner": X, "source": X}}

    def report_run(self, report=None, comments=None, reports=None, start="2026-10-12"):
        run = json.loads(json.dumps(OPEN_RUN))
        run["project"]["quest"].update(start=start, report=report or {"draft": "reports/sync.json", "status": "ready", "name": X},
                                       reportComments=comments or [], reports=reports or [])
        return run

    def report_modal(self, draft, report=None):
        """Every report modal the page rendered while opening the quest report's draft, and the scan of all it rendered."""
        run = self.report_run(report)
        scan = self.rendered(run, [], PROGRESS, (), **{"/reports/sync.json": json.dumps(draft)},
                             probe='(async () => { openReport(); await loadReport("reports/sync.json"); return true; })()')
        return [h for h in self.html if h.startswith('<div class="rmodal"')][-1], scan

    def test_the_report_modal_renders_a_hostile_draft_as_text_links_only_http_and_images_only_from_the_run_or_https(self):
        modal, scan = self.report_modal(self.HOSTILE_DRAFT)
        self.assertIn('class="rmodal"', modal)
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])
        self.assertEqual({"script", "iframe", "object", "embed"} & set(scan.tags), set())
        for v in (v.strip() for _, k, v in scan.attrs if k in ("href", "src")):
            same_site = v.startswith("/") and not v.startswith(("//", "/\\"))
            self.assertTrue(same_site or v.startswith(("http://", "https://", "vscode://file/", "paseo://h/")), v)
        self.assertIn("https://github.com/o/r/milestone/1", modal)
        self.assertIn('<a class="rp-plat flag" href="https://github.com/o/a/pull/1"', modal)
        self.assertIn('<span class="rp-plat done">✓ iOS</span>', modal)
        self.assertNotIn("<img", modal)
        self.assertGreater(modal.count(esc(X)), 25)
        for level in re.findall(r'class="rp-risk ([^"]*)"', modal):
            self.assertIn(level, ("blocks", "waits", "later"))
        self.assertEqual(set(re.findall(r'<li class="([^"]*)"', modal)), {"open", "moved", "working", "done"})

    def test_a_banner_image_shows_from_a_run_path_or_https_and_never_from_elsewhere(self):
        for image, src in (("reports/img/admin.png", "/reports/img/admin.png"), ("https://cdn.example/a.png", "https://cdn.example/a.png"),
                           ("http://cdn.example/a.png", None), ("//evil.example/a.png", None), ("../secret.png", None),
                           ("/etc/a.png", None), ("data:image/png;base64,AA", None)):
            modal, _ = self.report_modal({"name": "n", "kind": "sync", "tiers": {}, "banner": {"title": "t", "image": image}})
            self.assertEqual((re.search(r'<img class="rp-shot" src="([^"]*)"', modal) or [None, None])[1], src, image)

    def tier(self, items, show_internal=False):
        draft = {"name": "n", "kind": "sync", "tiers": {"must": items}, "showInternal": show_internal}
        self.maps(probe=f'reportTier({json.dumps(draft)}, "must", "★ Must have")')
        return self.probe()

    def test_each_tier_names_the_unfinished_items_that_block_a_launch_step_with_their_risk_only_when_it_has_unfinished_ones(self):
        blocks = {"bucket": "open", "head": "Should be able to pause and relaunch a message in the new admin", "risk": {"level": "blocks", "text": "Blocks switching off the old admin"}}
        other = {"bucket": "working", "head": X, "risk": {"level": "blocks", "text": X}}
        self.assertIn('<div class="rp-riskline"><b class="blocks">Blocks a launch step:</b> Should be able to pause and relaunch a message in the new admin'
                      ' — Blocks switching off the old admin.</div>', self.tier([blocks, {"bucket": "open", "head": "o"}]))
        self.assertIn('<b class="blocks">2 unfinished items block a launch step:</b><ul class="rp-blockers">'
                      '<li>Should be able to pause and relaunch a message in the new admin — Blocks switching off the old admin.</li>'
                      f'<li>{esc(X)} — {esc(X)}.</li></ul>', self.tier([blocks, other, {"bucket": "done", "head": "d"}]))
        self.assertIn('<b class="blocks">Blocks a launch step:</b> Should be able', self.tier([blocks, {**other, "hidden": True}]))
        self.assertIn('<b class="ok">Nothing unfinished here blocks launch.</b>', self.tier([{"bucket": "open", "head": "o", "risk": {"level": "waits"}}]))
        self.assertIn('<b class="ok">Nothing unfinished here blocks launch.</b>', self.tier([{**blocks, "hidden": True}, {"bucket": "open", "head": "o"}]))
        self.assertNotIn("rp-riskline", self.tier([{"bucket": "done", "head": "d", "risk": {"level": "blocks"}}]))
        self.assertNotIn("rp-riskline", self.tier([]))
        self.assertIn('<span class="tally">1 of 3 delivered</span>', self.tier([blocks, other, {"bucket": "done", "head": "d"}]))

    def details(self, setup):
        draft = {"name": "n", "kind": "sync", "tiers": {"must": [{"bucket": "done", "head": "h", "why": X}, {"bucket": "done", "head": "bare"}]}}
        self.maps(probe=f'(() => {{ {setup}; return reportTier({json.dumps(draft)}, "must", "★ Must have"); }})()')
        return self.probe()

    def test_a_rows_details_sit_folded_under_an_arrow_and_open_alone_or_all_together_as_text(self):
        folded = self.details("")
        self.assertNotIn("rp-desc", folded)
        self.assertIn('<button class="rp-fold" data-report-fold="tiers/must/0" aria-expanded="false"', folded)
        self.assertIn('<span class="rp-fold none"></span>', folded)
        one = self.details('S.reportOpen.add("tiers/must/0")')
        self.assertIn('<button class="rp-fold on" data-report-fold="tiers/must/0" aria-expanded="true"', one)
        self.assertEqual(one.count('<div class="rp-desc why">'), 1)
        self.assertIn(esc(X), one.split('<div class="rp-desc why">')[1])
        self.assertNotIn("<i id=", one)
        self.assertEqual(self.details("S.reportAllOpen = true").count('<div class="rp-desc why">'), 1)

    def test_rows_go_delivered_then_worked_on_then_unfinished_each_sorted_by_role_driver_first_and_others_last(self):
        t = self.tier([{"bucket": "open", "head": "o1", "role": "Staff"}, {"bucket": "done", "head": "d1", "role": "Tester"},
                       {"bucket": "done", "head": "d2", "role": "Admin"}, {"bucket": "done", "head": "d3", "role": "Driver"},
                       {"bucket": "working", "head": "w1"}, {"bucket": "done", "head": "d4", "role": "Marketing"},
                       {"bucket": "done", "head": "d5", "role": "Driver"}, {"bucket": "open", "head": "o2", "role": "Support"}])
        self.assertEqual(re.findall(r'<div class="rp-bucket ([a-z]+)">([^<]*)</div>', t),
                         [("done", "Delivered · 5"), ("working", "Being worked on · 1"), ("open", "Not finished · 2")])
        self.assertEqual(re.findall(r'data-redit="tiers/must/\d+/head">([^<]*)<', t), ["d3", "d5", "d4", "d2", "d1", "w1", "o2", "o1"])

    def test_left_out_items_are_not_in_the_report_and_internal_ones_fold_to_a_line_until_shown(self):
        items = [{"bucket": "done", "head": "kept"}, {"bucket": "done", "head": "gone", "hidden": True},
                 {"bucket": "done", "head": "inner", "internal": True}, {"bucket": "done", "head": "inner2", "internal": True}]
        t = self.tier(items)
        self.assertIn(">kept<", t)
        self.assertNotIn("gone", t)
        self.assertNotIn(">inner<", t)
        self.assertIn("Plus 2 pieces of internal groundwork", t)
        self.assertIn("Delivered · 3", t)
        shown = self.tier(items, show_internal=True)
        self.assertIn(">inner<", shown)
        self.assertNotIn("Plus 2", shown)
        self.assertNotIn("gone", shown)
        draft = {"name": "n", "kind": "sync", "tiers": {"must": items}, "sections": ["must"], "next": ["hidden by section"]}
        self.maps(probe=f"reportText({json.dumps(draft)})")
        self.assertEqual(self.probe().splitlines(), ["n", "", "★ Must have", "✓ kept"])

    def test_the_tile_button_asks_for_a_status_report_during_the_quest_and_a_quest_report_once_its_last_week_ended(self):
        def label(quest, y, m, d):
            self.maps(probe=f"reportTools({json.dumps(quest)}, new Date({y}, {m - 1}, {d}, 12))")
            return re.search(r"data-report-new>([^<]*)</button>", self.probe()).group(1)
        self.assertEqual(label({"start": "2026-10-12"}, 2026, 11, 22), "📄 New status report")
        self.assertEqual(label({"start": "2026-10-12"}, 2026, 11, 23), "📄 New quest report")
        self.assertEqual(label({"start": "2026-10-12", "weeks": 4}, 2026, 11, 9), "📄 New quest report")
        self.assertEqual(label({}, 2026, 12, 25), "📄 New status report")

    def test_the_tile_links_the_newest_report_and_a_ready_draft(self):
        quest = {"start": "2026-10-12", "report": {"status": "ready", "draft": "reports/b.json"},
                 "reports": [{"name": "Sync 2026-11-13", "url": "https://outline.example/b", "publishedAt": "2026-11-13T10:00:00Z"},
                             {"name": "Sync 2026-11-06", "url": "https://outline.example/a", "publishedAt": "2026-11-06T10:00:00Z"},
                             {"name": X, "url": JS, "publishedAt": X}, None]}
        self.maps(probe=f"reportTools({json.dumps(quest)}, new Date(2026, 10, 20, 12))")
        t = self.probe()
        self.assertIn('<button class="share" data-report-open>Draft ready ↗</button>', t)
        self.assertIn('<a class="rlast" href="https://outline.example/b" target="_blank" rel="noopener">Last report: Sync 2026-11-13 ↗</a>', t)
        quest["reports"][2]["publishedAt"] = "2026-11-20"
        self.maps(probe=f"reportTools({json.dumps(quest)}, new Date(2026, 10, 20, 12))")
        self.assertNotIn("rlast", self.probe())

    def test_the_comments_card_shows_only_the_unhandled_comments_with_their_answer_state(self):
        comments = [{"id": "c1", "author": "Maria Ek", "role": "Product", "quote": "q1", "body": "first", "url": "https://outline.example/c1"},
                    {"id": "c2", "author": "Jonna Lund", "body": "second", "answer": True, "url": JS},
                    {"id": "c3", "author": "Old", "body": "third", "handled": True}, X]
        self.maps(probe=f"reportComments({json.dumps({'reportComments': comments})})")
        card = self.probe()
        self.assertIn("💬 2 questions", card)
        self.assertEqual(re.findall(r"<div>(first|second|third)</div>", card), ["first", "second"])
        self.assertIn('<button data-report-answer="c1">Answer in the next report</button>', card)
        self.assertIn('<button data-report-answer="c2" class="on">✓ Answered in the next report</button>', card)
        self.assertIn('<a href="https://outline.example/c1" target="_blank" rel="noopener" data-report-reply="c1">Reply in Outline ↗</a>', card)
        self.assertIn('<button data-report-reply="c2">Mark handled</button>', card)
        self.maps(probe=f"reportComments({json.dumps({'reportComments': [comments[2]]})})")
        self.assertEqual(self.probe(), "")

    def test_the_tile_and_its_comments_render_hostile_report_data_as_text(self):
        run = self.report_run({"status": "ready", "draft": X, "name": X},
                              [{"id": X, "author": X, "role": X, "quote": X, "body": X, "at": X, "url": JS}],
                              [{"name": X, "url": "https://outline.example/x", "publishedAt": "2026-11-13"}])
        scan = self.rendered(run, [], PROGRESS, (), probe="(openReportStart(), openReport(), true)")
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        self.assertEqual([a for a in scan.attrs if a[1].startswith("on")], [])
        page = "".join(self.html)
        self.assertIn("rcomments", page)
        self.assertIn("rsbox", page)
        self.assertIn("Couldn't read the draft", page)

    def test_the_wrap_up_sits_beside_the_quest_tile_not_inside_it(self):
        self.assertRegex(open(PAGE).read(), r'questTile\(P\) \+ questWrap\(')

    def test_a_landing_is_noticed_between_renders_and_the_last_must_is_called_out(self):
        self.maps(probe='(() => { const seen = new Map(), ms = [{ id: "A", priority: "must", status: "done" }, { id: "B", priority: "must", status: "working" },'
                        ' { id: "C", status: "todo" }, { id: "D", priority: "must", status: "todo" }];'
                        ' const out = [landings(seen, ms)]; ms[1].status = "done"; ms[2].status = "done"; out.push(landings(seen, ms)); out.push(landings(seen, ms));'
                        ' ms[3].status = "moved"; ms.push({ id: "E", priority: "must", status: "done" }); out.push(landings(seen, ms)); return out; })()')
        self.assertEqual(self.probe(), [{"landed": [], "lastMust": False}, {"landed": ["B", "C"], "lastMust": False},
                                        {"landed": [], "lastMust": False}, {"landed": ["E"], "lastMust": True}])

    def test_every_render_looks_for_landings_to_celebrate(self):
        self.assertRegex(open(PAGE).read(), r"celebrate\(landings\(S\.landedSeen, msList\(\)\)\)")

    def mine_run(self):
        run = json.loads(json.dumps(OPEN_RUN))
        run["active"] = {}
        e1, e2 = run["epics"]
        e1["milestones"][0]["owner"] = "ann"
        e2["milestones"][0]["owner"] = e2["milestones"][1]["owner"] = "bo"
        return run

    def people_button(self):
        html = [h for h in self.html if "data-people-menu" in h][-1]
        return re.search(r'<button class="share ?(on)?" data-people-menu aria-expanded="(\w+)"[^>]*>(?:<span class="faces">(?:<span[^>]*>[^<]*</span>)*</span>)?(.*?)</button>', html).groups()

    def people_menu(self):
        html = [h for h in self.html if 'id="people-menu"' in h][-1]
        return re.findall(r'data-people-add="([^"]*)"( checked)?.*?<span>([^<]*)</span>(?:<i class="live"[^>]*></i>)?<span class="n">(\d+)</span>', html)

    def test_a_people_menu_sits_beside_filter_and_starts_on_everyone(self):
        self.assertIn('<span id="state-filter"></span><span id="people-filter"></span>', open(PAGE).read())
        maps, _ = self.maps(self.mine_run(), probe="(closeSheet(), render(), 0)")
        self.assertEqual(self.people_button(), (None, "false", "Everyone"))
        self.assertEqual(sorted(self.shown(maps[-1])), ["M1", "M2", "M3", "R1"])

    def test_the_people_menu_lists_you_then_colleagues_by_milestones_owned_then_no_owner(self):
        self.maps(self.mine_run(), probe="(closeSheet(), setPeopleMenu(true), 0)")
        self.assertEqual(self.people_menu(), [("@me", "", "ann (you)", "1"), ("bo", "", "bo", "2"), ("", "", "No owner", "1")])

    def test_mine_shows_your_milestones_and_what_waits_on_you_and_is_kept(self):
        maps, _ = self.maps(self.mine_run(), probe='(() => { const put = {}; localStorage.setItem = (k, v) => { put[k] = v; }; closeSheet();'
                                                    ' S.project.needsYou = { reason: "look", story: "M3/S6" }; setPeople(["@me"]); render(); return put["podium-people:api"]; })()')
        self.assertEqual(self.probe(), '["@me"]')
        self.assertEqual(self.shown(maps[-1]), ["M1", "M3"])
        self.assertEqual(self.people_button(), ("on", "false", "Mine · 2 hidden"))
        maps, _ = self.maps(self.mine_run(), localStorage={"podium-people:api": '["@me"]'}, probe="(closeSheet(), render(), 0)")
        self.assertEqual(self.shown(maps[-1]), ["M1"])

    def test_mine_kept_from_before_the_people_menu_carries_over(self):
        maps, _ = self.maps(self.mine_run(), localStorage={"podium-mine:api": "1"}, probe="(closeSheet(), render(), S.people)")
        self.assertEqual(self.probe(), ["@me"])
        self.assertEqual(self.shown(maps[-1]), ["M1"])

    def test_picking_colleagues_and_no_owner_shows_only_their_milestones(self):
        maps, _ = self.maps(self.mine_run(), probe="(closeSheet(), setPeople([\"bo\"]), render(), 0)")
        self.assertEqual(sorted(self.shown(maps[-1])), ["M2", "M3"])
        self.assertEqual(self.people_button(), ("on", "false", "bo · 2 hidden"))
        maps, _ = self.maps(self.mine_run(), probe="(closeSheet(), setPeople([\"@me\", \"\"]), render(), 0)")
        self.assertEqual(sorted(self.shown(maps[-1])), ["M1", "R1"])
        self.assertEqual(self.people_button()[2], "2 people · 2 hidden")

    def test_a_name_shows_only_them_and_a_box_adds_them(self):
        page = open(PAGE).read()
        self.assertIn('if (padd) { togglePerson(padd.dataset.peopleAdd); render(); return; }', page)
        self.assertIn('if (ponly) { setPeople([ponly.dataset.peopleOnly]); S.peopleMenu = false; render(); return; }', page)
        self.maps(self.mine_run(), probe='(setPeople(["bo"]), togglePerson("@me"), togglePerson("bo"), S.people)')
        self.assertEqual(self.probe(), ["@me"])

    def test_a_bullet_that_wraps_onto_the_next_line_stays_one_bullet(self):
        self.maps(probe=r'md("- Copy (P1\n  P2; copy and shots) last\n- two\n  - nested\n\nafter")')
        self.assertEqual(self.probe(), "<ul><li>Copy (P1 P2; copy and shots) last</li><li>two</li><li>nested</li></ul><p>after</p>")

    def test_a_mock_that_is_not_built_yet_says_so_instead_of_linking(self):
        self.maps(probe='(S.mockFound["/mock/r6/"] = false, md("See `mock/r6/` and mock/m4/a.html"))')
        self.assertEqual(self.probe(), '<p>See <span class="mocklink missing" title="Not built yet: this run has no such mock"><code>mock/r6/</code></span>'
                                       ' and <a class="mocklink" href="/mock/m4/a.html" target="_blank" rel="noopener" title="Open the mock in a new tab">mock/m4/a.html</a></p>')

    def test_a_mock_a_brief_names_opens_from_this_podium_in_a_new_tab(self):
        refs = ["mock/m10/auth-screens.html#proposed", "mock/m12/", "/Users/someone/plans/run/mock/m2/shots/a.png", "feature-folder/mock/r6/"]
        self.maps(probe="md(%s)" % json.dumps("\n".join(f"- `{r}`" for r in refs)))
        links = re.findall(r'<a class="mocklink" href="([^"]*)" target="_blank" rel="noopener" title="Open the mock in a new tab"><code>([^<]*)</code></a>', self.probe())
        self.assertEqual(links, [("/mock/m10/auth-screens.html#proposed", refs[0]), ("/mock/m12/", refs[1]),
                                 ("/mock/m2/shots/a.png", refs[2]), ("/mock/r6/", refs[3])])

    def test_a_mock_named_in_plain_text_links_too_and_the_sentence_keeps_its_stop(self):
        self.maps(probe=r'md("- feature-folder/mock/r6/\nSee mock/m4/api-map.html. Or (mock/m12/) and /__mock/reset")')
        self.assertEqual(self.probe(),
                         '<ul><li><a class="mocklink" href="/mock/r6/" target="_blank" rel="noopener" title="Open the mock in a new tab">feature-folder/mock/r6/</a></li></ul>'
                         '<p>See <a class="mocklink" href="/mock/m4/api-map.html" target="_blank" rel="noopener" title="Open the mock in a new tab">mock/m4/api-map.html</a>.'
                         ' Or (<a class="mocklink" href="/mock/m12/" target="_blank" rel="noopener" title="Open the mock in a new tab">mock/m12/</a>) and /__mock/reset</p>')

    def test_only_a_page_or_picture_under_mock_becomes_a_mock_link(self):
        refs = ["mock/m26/figma/README.md", "mock/m12", "spec-brief.md", "/__mock/reset", "web-applications/apps/x/mock-ams/a.html",
                "mock/../podium/a.html", 'mock/a".html']
        self.maps(probe="md(%s)" % json.dumps("\n".join(f"- `{r}`" for r in refs)))
        self.assertNotIn("<a", self.probe())

    def test_a_mock_in_files_in_scope_opens_it_and_other_files_open_the_document(self):
        self.maps(probe='[fileLink("feature-folder/mock/r6/", "repoDir"), fileLink("core/src/A.java", "repoDir")]')
        mock, other = self.probe()
        self.assertEqual(mock, '<a class="file mono mocklink" href="/mock/r6/" target="_blank" rel="noopener" title="Open the mock in a new tab">feature-folder/mock/r6/</a>')
        self.assertEqual(other, '<a class="file mono" data-doc="core/src/A.java" data-base="repoDir">core/src/A.java</a>')

    def test_a_mock_link_carries_the_mock_buttons_palette(self):
        self.assertIn('a.mocklink::before { content: "🎨" / "";', open(PAGE).read())

    def test_a_quests_us_tiles_carry_the_same_pills(self):
        maps, _ = self.maps(self.priority_run())
        tiles = re.findall(r'<div class="fepic"[^>]*><span class="eyebrow">(.*?)<span class="ftools">', maps[0])
        self.assertEqual(tiles, ['US1<span class="prio must" title="Must have"><b>★</b>Must</span>',
                                 'US2<span class="prio should" title="Should have"><b>★</b>Should</span>'])

    def test_the_open_card_has_no_priority_slider_and_its_badge_opens_the_choices(self):
        maps, _ = self.maps(self.priority_run(), probe='(expand("M2"), S.prioPick = "M2", render(), $("map").innerHTML)')
        card = self.open_card(self.probe())
        self.assertNotIn("prioseg", card)
        self.assertIn('<span class="sid">M2</span><span class="prio-wrap"><button class="prio-pick" data-prio-pick="M2" aria-haspopup="menu" aria-expanded="true" title="Change the priority or status">'
                      '<span class="prio must" title="Must have"><b>★</b>Must</span></button>', card)
        menu = re.search(r'<div class="prio-pick-menu" role="menu" aria-label="State of M2">(.*?)</div>', card).group(1)
        self.assertEqual(re.findall(r'aria-checked="(\w+)" data-prio="(\w*)" data-prio-of="M2">', menu),
                         [("true", "must"), ("false", "should"), ("false", "")])

    def test_an_open_nice_to_have_milestone_shows_a_nice_to_have_badge_and_a_closed_one_none(self):
        maps, _ = self.maps(self.priority_run(), probe='(delete msOf("M2").priority, expand("M2"), $("map").innerHTML)')
        html = self.probe()
        self.assertIn('<button class="prio-pick" data-prio-pick="M2" aria-haspopup="menu" aria-expanded="false" title="Change the priority or status">'
                      '<span class="prio nice" title="Nice to have">Nice to have</span></button>', self.open_card(html))
        self.assertNotIn("prio nice", html.replace(self.open_card(html), ""))
        self.assertNotIn('class="prio-pick-menu"', html)

    def test_the_epic_sheet_has_the_same_badge_pulldown(self):
        self.maps(self.priority_run(), probe='(openSheet({ epic: "e2" }), S.prioPick = "epic/e2", renderSheet(), document.getElementById("sheet-head").innerHTML)')
        head = self.probe()
        self.assertNotIn("prioseg", head)
        self.assertIn('data-prio-pick="epic/e2" aria-haspopup="menu" aria-expanded="true" title="Change the priority"><span class="prio should" title="Should have"><b>★</b>Should</span>', head)
        self.assertIn('aria-checked="true" data-prio="should" data-prio-of="epic/e2"', head)

    def test_an_undrawn_milestone_offers_a_round_draw_button_whose_hover_says_what_happens(self):
        self.maps(self.priority_run(), probe='(S.project.orchestrator = { command: "/o" }, dsBtn(msOf("M3")))')
        btn = self.probe()
        self.assertIn('<button class="dsbtn draw" data-act="domain-story" data-id="M3" aria-label="Draw domain stories"', btn)
        self.assertIn('data-tip-title="Draw domain stories" data-tip="The orchestrator draws what this milestone changes', btn)
        self.assertIn('<b class="ds-badge">+</b>', btn)

    def test_a_drawn_milestone_opens_its_stories_and_badges_their_count(self):
        self.maps(self.priority_run(), probe='(msOf("M3").domainStories = { stories: [{}, {}] }, dsBtn(msOf("M3")))')
        btn = self.probe()
        self.assertIn('<button class="dsbtn has" data-ds="M3" aria-label="Open 2 domain stories"', btn)
        self.assertIn('<b class="ds-badge">2</b>', btn)

    def test_a_milestone_sheet_has_the_same_badge_pulldown(self):
        self.maps(self.priority_run(), probe='(openSheet({ ms: "M3" }), S.prioPick = "M3", renderSheet(), document.getElementById("sheet-head").innerHTML)')
        head = self.probe()
        self.assertIn('<span class="sid">M3</span><span class="prio-wrap"><button class="prio-pick" data-prio-pick="M3" aria-haspopup="menu" aria-expanded="true" title="Change the priority or status"><span class="prio should" title="Should have"><b>★</b>Should</span>', head)
        self.assertIn('aria-checked="true" data-prio="should" data-prio-of="M3"', head)

    def state_picks(self, probe):
        """The Status items of the last probed sheet head's pulldown, as (state, checked, disabled)."""
        self.maps(self.priority_run(), probe=f'({probe}, renderSheet(), document.getElementById("sheet-head").innerHTML)')
        return [(to, checked == "true", bool(off)) for checked, to, off in
                re.findall(r'aria-checked="(\w+)" data-state-to="(\w+)" data-state-of="\w+"( disabled)?', self.probe())]

    def test_a_milestone_sheets_pulldown_also_opens_pauses_and_closes_it(self):
        head_probe = 'openSheet({ ms: "M3" }), S.prioPick = "M3"'
        self.assertEqual(self.state_picks(head_probe), [("open", True, False), ("paused", False, False), ("closed", False, False)])
        self.assertIn('<span class="mhead">Priority</span>', self.probe())
        self.assertIn('<span class="mhead">Status</span>', self.probe())
        for status, ticked in (("parked", "paused"), ("later", "paused"), ("dropped", "closed")):
            with self.subTest(status=status):
                picks = self.state_picks(f'msOf("M3").status = "{status}", {head_probe}')
                self.assertEqual([to for to, on, _ in picks if on], [ticked])

    def test_a_milestone_in_progress_shows_its_status_choices_disabled(self):
        self.assertEqual(self.state_picks('openSheet({ ms: "M2" }), S.prioPick = "M2"'),
                         [("open", True, True), ("paused", False, True), ("closed", False, True)])
        self.assertIn('title="M2 is in progress: stop it first"', self.probe())

    def test_a_landed_milestone_and_an_epic_offer_priority_only(self):
        self.assertEqual(self.state_picks('openSheet({ ms: "M1" }), S.prioPick = "M1"'), [])
        self.assertIn('aria-label="Priority of M1"', self.probe())
        self.assertEqual(self.state_picks('openSheet({ epic: "e2" }), S.prioPick = "epic/e2"'), [])

    def test_picking_a_status_posts_it_shows_the_new_status_and_closes_the_pulldown(self):
        self.maps(probe='(async () => { const calls = [];'
                        ' globalThis.fetch = async (p, o) => (calls.push([p, o && o.method]), { ok: true, status: 200, json: async () => ({ status: "parked" }) });'
                        ' S.prioPick = "M3"; await setMsState("M3", "paused"); return [calls, msOf("M3").status, S.prioPick]; })()')
        self.assertEqual(self.probe(), [[["/status/M3?to=paused", "POST"]], "parked", None])

    def test_a_refused_status_says_why(self):
        self.maps(probe='(async () => { const said = []; toast = (t) => said.push(t);'
                        ' globalThis.fetch = async () => ({ ok: false, status: 409, json: async () => ({ error: "M3 is in progress: stop it first" }) });'
                        ' await setMsState("M3", "closed"); return [said, msOf("M3").status]; })()')
        self.assertEqual(self.probe(), [["Closing M3…", "Couldn't change M3: M3 is in progress: stop it first"], "todo"])

    def test_a_repos_commits_given_as_one_bare_sha_read_as_that_commit(self):
        self.maps(probe='commitsOf({ commits: { core: 9359861629, web: "7f4b7858", api: [{ sha: "abc" }] } })')
        self.assertEqual(self.probe(), [{"repo": "core", "sha": "9359861629"}, {"repo": "web", "sha": "7f4b7858"}, {"repo": "api", "sha": "abc"}])

    def cost_view(self, **files):
        """The milestone sheets' Timeline headers, the landed cards' cost lines and the epic sheet's Milestones header."""
        self.maps(COST_RUN, probe='(async () => { const sheet = async (sel) => { await openSheet(sel); renderSheet(); return document.getElementById("sheet-body").innerHTML; };'
                                  ' const head = (html, name) => (html.match(new RegExp(`<h3>${name}(.*?)</h3>`)) || [])[1] ?? null;'
                                  ' const out = {}; for (const id of ["M1", "M2", "M3"]) out[id] = head(await sheet({ ms: id }), "Timeline");'
                                  ' out.epic = head(await sheet({ epic: "e1" }), "Milestones"); return out; })()', **files)
        cards = {}
        for card in re.split(r'(?=<div class="fms )', [h for h in self.html if 'class="fms ' in h][-1])[1:]:
            line = re.search(r'<div class="fcost"[^>]*>(.*?)</div>', card)
            cards[re.search(r'data-id="([^"]*)"', card).group(1)] = line and line.group(1)
        return self.probe(), cards

    def test_a_milestone_sheets_timeline_says_its_time_retries_and_this_machines_tokens(self):
        sheets, _ = self.cost_view(**{"/cost": json.dumps(COST)})
        self.assertIn("2 h 0 min start to finish · 2 h 30 min agent time · 1 retry · 200.0k tokens on this machine</span>", sheets["M1"])
        self.assertIn('title="Tokens of this machine&#39;s Claude Code sessions only: input 1.0k · cache writes 100.0k · output 99.0k, and 3.0M more read back from the cache"', sheets["M1"])
        self.assertIn("20 min start to finish · 20 min agent time</span>", sheets["M2"])
        self.assertNotIn("tokens", sheets["M2"])
        self.assertIsNone(sheets["M3"])

    def test_a_landed_milestones_card_carries_a_quiet_cost_line_and_an_open_one_none(self):
        _, cards = self.cost_view(**{"/cost": json.dumps(COST)})
        self.assertEqual(cards, {"M1": "2h 30m agent time · 1 retry · 200.0k tokens", "M2": "20m agent time", "M3": None})

    def test_the_epic_sheet_totals_its_milestones(self):
        sheets, _ = self.cost_view(**{"/cost": json.dumps(COST)})
        self.assertIn(">2 h 50 min agent time · 1 retry · 200.0k tokens on this machine</span>", sheets["epic"])

    def test_a_server_without_cost_leaves_out_the_tokens_and_keeps_the_time(self):
        sheets, cards = self.cost_view()
        self.assertTrue(sheets["M1"].endswith("2 h 0 min start to finish · 2 h 30 min agent time · 1 retry</span>"), sheets["M1"])
        self.assertEqual(cards["M1"], "2h 30m agent time · 1 retry")
        self.assertNotIn("tokens", sheets["epic"])

    ASK_COST = ('(async () => { const asked = []; const real = globalThis.fetch;'
                ' globalThis.fetch = async (p, o) => (String(p) === "/cost" && asked.push(p), real(p, o));'
                ' S.costAt = 0; await loadCost(); await loadCost(); const first = asked.length;'
                ' if (S.costAt) S.costAt = Date.now() - COST_MS; await loadCost(); return [first, asked.length]; })()')

    def test_cost_is_asked_again_only_after_a_minute(self):
        self.maps(COST_RUN, probe=self.ASK_COST, **{"/cost": json.dumps(COST)})
        self.assertEqual(self.probe(), [1, 2])

    def test_cost_is_never_asked_again_of_a_server_without_it(self):
        self.maps(COST_RUN, probe=self.ASK_COST)
        self.assertEqual(self.probe(), [1, 1])

    def test_a_status_change_says_it_started_and_when_it_is_done(self):
        self.maps(probe='(async () => { const said = []; toast = (t) => said.push(t);'
                        ' globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ status: "dropped" }) });'
                        ' await setMsState("M3", "closed"); return said; })()')
        self.assertEqual(self.probe(), ["Closing M3…", "M3 closed"])

    FLAKY = [{"name": "unit", "logs": "contract-core.logs/merge-r6", "flips": 3, "last": "2026-10-20T08:00:00Z", "runs": 4, "fails": 1},
             {"name": "lint", "logs": "contract.logs", "flips": 1, "last": "2026-10-19T08:00:00Z", "runs": 1, "fails": 1}]
    FLAKY_PROBE = ('(async () => { const chip = document.getElementById("flaky-gates").innerHTML;'
                   ' LISTENERS.click.forEach((f) => f({ target: { dataset: {}, closest: (q) => (q === "[data-flaky]" ? { dataset: {} } : null) }, stopPropagation() {} }));'
                   ' await null; return [chip, S.sel, document.getElementById("sheet-head").innerHTML, document.getElementById("sheet-body").innerHTML]; })()')

    def test_flaky_gates_show_as_a_chip_that_opens_a_sheet_listing_each_with_where_how_often_and_when(self):
        self.maps(probe=self.FLAKY_PROBE, **{"/gates": json.dumps({"gates": self.FLAKY})})
        chip, sel, head, body = self.probe()
        self.assertIn(">2 flaky gates</button>", chip)
        self.assertEqual(sel, {"gates": True})
        self.assertIn("<h2>Flaky gates</h2>", head)
        for text in ("<b class=\"mono\">unit</b>", "contract-core.logs/merge-r6", "flipped 3 times", "1 of 4 runs failed",
                     "<b class=\"mono\">lint</b>", "flipped 1 time<", "1 of 1 run failed"):
            self.assertIn(text, body)

    def test_no_flaky_gates_or_a_server_without_them_shows_no_chip(self):
        for gates in (None, {"gates": []}, {"gates": "x"}):
            with self.subTest(gates=gates):
                self.maps(probe='document.getElementById("flaky-gates").innerHTML', **({"/gates": json.dumps(gates)} if gates else {}))
                self.assertEqual(self.probe(), "")

    def test_the_flaky_gates_sheet_shows_hostile_fields_as_text_and_links_to_itself(self):
        self.maps(probe=self.FLAKY_PROBE, **{"/gates": json.dumps({"gates": [{"name": X, "logs": X, "flips": X, "last": X, "runs": X, "fails": X}]})})
        scan = Scan()
        scan.feed(self.probe()[3])
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        self.assertIn(X, "".join(scan.text))
        self.maps(probe='(S.sel = { gates: true }, sheetRoute())', **{"/gates": json.dumps({"gates": self.FLAKY})})
        self.assertEqual(self.probe(), {"hash": "#/gates", "label": "the flaky gates"})

    def test_a_milestone_sheet_without_a_priority_offers_nice_to_have(self):
        self.maps(self.priority_run(), probe='(openSheet({ ms: "M1" }), renderSheet(), document.getElementById("sheet-head").innerHTML)')
        self.assertIn('data-prio-pick="M1" aria-haspopup="menu" aria-expanded="false" title="Change the priority"><span class="prio nice" title="Nice to have">Nice to have</span>', self.probe())

    def test_a_click_outside_either_pulldown_closes_it(self):
        self.maps(probe='(() => { const click = () => { const target = { dataset: {}, closest: () => null }; LISTENERS.click.forEach((f) => f({ target, stopPropagation() {} })); };'
                        ' S.prioPick = "M2"; click(); const prio = S.prioPick; S.ownerMenu = "M3"; click(); return [prio, S.ownerMenu]; })()')
        self.assertEqual(self.probe(), [None, None])

    def test_picking_from_the_pulldown_closes_it(self):
        self.maps(probe='(async () => { globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });'
                        ' S.prioPick = "M2"; await setPriority("M2", "must"); return S.prioPick; })()')
        self.assertIsNone(self.probe())

    def test_picking_a_level_posts_it_and_shows_it_at_once(self):
        self.maps(probe='(async () => { const calls = [];'
                        ' globalThis.fetch = async (p, o) => (calls.push([p, o && o.method]), { ok: true, status: 200, json: async () => ({}) });'
                        ' await setPriority("M2", "must"); const must = msOf("M2").priority; await setPriority("epic/e1", "should");'
                        ' const epic = S.project.epics.find((E) => E.id === "e1").priority; await setPriority("M2", "");'
                        ' return [calls, must, epic, msOf("M2").priority ?? null]; })()')
        self.assertEqual(self.probe(), [[["/priority/M2?level=must", "POST"], ["/priority/epic/e1?level=should", "POST"], ["/priority/M2?level=nice", "POST"]],
                                        "must", "should", None])

    def test_epic_columns_keep_a_width_their_cards_fit_in_and_the_map_scrolls_sideways_past_it(self):
        maps, _ = self.maps()
        self.assertIn('grid-template-columns:minmax(320px, 1fr) minmax(380px, 1.7fr);min-width:752px', maps[0])
        self.assertRegex(open(PAGE).read(), r"\.ms-repos \.repo-line \{[^}]*flex-wrap: wrap")

    def test_the_map_has_no_row_number_gutter(self):
        maps, _ = self.maps()
        self.assertNotIn('class="ford"', maps[0])
        self.assertNotRegex(maps[0], r">#\d+<")
        self.assertIn('<div class="full" style="grid-template-columns:minmax(', maps[0])

    def test_the_open_milestones_epic_column_widens_so_its_story_cards_keep_their_contents(self):
        maps, _ = self.maps(probe='expand("M2")')
        self.assertIn('grid-template-columns:minmax(320px, 1fr) minmax(560px, 2fr);min-width:932px', maps[-1])
        self.assertRegex(open(PAGE).read(), r"\.node\.compact \.badge \{[^}]*white-space: normal")

    def test_a_click_on_the_open_cards_padding_or_the_maps_empty_space_collapses_it(self):
        self.maps(probe='(() => { expand("M2"); onBackdrop({ matches: () => false }); const kept = S.open;'
                        ' onBackdrop({ matches: (s) => s === BACKDROP }); return [kept, S.open]; })()')
        self.assertEqual(self.probe(), ["M2", None])
        backdrop = re.search(r'const BACKDROP = "([^"]*)"', open(PAGE).read()).group(1).split(", ")
        for part in (".fms.open", ".fms.open .mtree", ".full", ".full > div:empty", "#map"):
            self.assertIn(part, backdrop)

    def test_what_can_be_clicked_grows_a_little_on_hover_and_info_badges_stay_still(self):
        css = open(PAGE).read()
        grows = re.search(r":is\(([^)]*(?:\([^)]*\))?[^)]*)\):hover \{ transform: scale\(1\.06\)", css).group(1).split(", ")
        for clickable in ("a.pr", ".dsbtn", ".mockbtn", ".asanabtn", ".fchip", ".wchip:not(.pr-chip)", ".btn", ".share", ".prio-pick"):
            self.assertIn(clickable, grows)
        for still in (".repo", ".badge", ".sid", ".prio", ".owner"):
            self.assertNotIn(still, grows)

    def test_each_milestone_card_shows_its_state_as_a_coloured_rail_and_a_glyph(self):
        css = open(PAGE).read()
        for state, glyph, word, colour in (("done", "✓", "Landed", "var(--green)"), ("working", "●", "In progress", "var(--accent)"),
                                           ("waits", "!", "Waiting on you", "var(--amber)"), ("failed", "✕", "Failed", "var(--red)")):
            self.assertIn(f'.fms.{state} .fidrow::before {{ content: "{glyph}" / "{word}"; color: {colour}; }}', css)
        self.assertIn('.fms .fidrow::before { content: "○" / "Not started";', css)
        self.assertIn(".fms, .fms.working, .fms.waits, .fms.waitfor, .fms.failed { border-left-width: 4px; }", css)
        self.assertIn(".fms.done { border-left-color: var(--green-dot); }", css)

    def test_work_in_progress_is_blue_so_green_only_means_landed(self):
        css = open(PAGE).read()
        self.assertIn(".fms.working { background: linear-gradient(var(--accent-soft), var(--accent-soft)), var(--card); border: 1.5px solid var(--accent);", css)
        self.assertIn(".node.working { background: linear-gradient(var(--accent-soft), var(--accent-soft)), var(--card); border: 1.5px solid var(--accent);", css)
        for rule in (".badge.working { color: var(--accent);", ".fdots i.working { background: var(--accent); }", ".owork { color: var(--accent); }",
                     ".banner.working { background: var(--accent-soft);", ".bar3 i.on { background: var(--accent); }"):
            self.assertIn(rule, css)
        self.assertRegex(css, r"\.pulse \{[^}]*background: var\(--accent\)")

    def test_the_epic_bar_shows_landed_and_in_progress_milestones_apart(self):
        maps, _ = self.maps()
        bars = re.findall(r'<div class="fbar">(.*?)</div>', maps[0])
        self.assertIn('<i class="d" style="width:0%"></i><i class="w" style="width:50%"></i>', bars)
        css = open(PAGE).read()
        self.assertIn(".fbar i.d { background: var(--green-dot); }", css)
        self.assertIn(".fbar i.w { background: var(--accent); }", css)

    def test_links_that_leave_the_podium_carry_an_arrow(self):
        self.assertIn(':is(a.pr, a.mockbtn, a.asanabtn, a.mocklink)::after { content: "↗" / "";', open(PAGE).read())

    def test_info_chips_on_milestone_cards_are_flat_so_they_never_look_like_buttons(self):
        css = open(PAGE).read()
        self.assertIn(".fms :is(.sid, .repo), .fms .foot .badge:not([data-reveal]) { background: none; padding-left: 0; padding-right: 0; }", css)

    def test_what_can_be_clicked_shows_a_focus_ring_when_tabbed_to(self):
        css = open(PAGE).read()
        ringed = re.search(r":is\(([^)]*(?:\([^)]*\))?[^)]*)\):focus-visible \{ outline: 2px solid var\(--accent\)", css).group(1).split(", ")
        for clickable in ("a.pr", ".dsbtn", ".mockbtn", ".asanabtn", ".btn", ".share", ".prio-pick", ".fms", ".fepic"):
            self.assertIn(clickable, ringed)

    def test_a_closed_milestone_shows_its_owner_as_initials_and_the_open_one_by_name(self):
        maps, _ = self.maps(probe='(msOf("M2").owner = msOf("M3").owner = "bo.berg", expand("M2"), render(), 0)')
        cards = dict(re.findall(r'<div class="fms [^"]*" [^>]*?data-id="(M[23])"[^>]*>(.*?)(?=<div class="fms |$)', maps[-1], re.S))
        self.assertIn('👤 <span class="who">bo.berg</span>', cards["M2"])
        self.assertIn('<span class="owner dot" style="background:hsl(', cards["M3"])
        self.assertIn(""" title="bo.berg&#39;s: only they plan and build it">BB</span>""", cards["M3"])
        self.assertNotIn("👤", cards["M3"])
        css = open(PAGE).read()
        self.assertIn(".owner.dot { width: 22px; height: 22px; padding: 0; justify-content: center;", css)
        self.assertIn(".owner.dot.me { box-shadow: 0 0 0 2px var(--accent); }", css)

    OWNED = 'S.project.people = { "ann": {}, "bo.berg": {}, "cy": {} }, msOf("M2").owner = msOf("M3").owner = "bo.berg", render()'

    def owner_menu(self, mid):
        self.maps(probe=f'({self.OWNED}, setOwnerMenu("{mid}"), $("map").innerHTML)')
        html = self.probe()
        card = re.search(r'<div class="fms [^"]*" [^>]*?data-id="%s"[^>]*>(.*?)(?=<div class="fms |$)' % mid, html, re.S).group(1)
        menu = re.search(r'<div class="owner-menu" role="menu" aria-label="Owner of %s">(.*?)</div></span>' % mid, card, re.S)
        return card, menu and menu.group(1)

    def test_the_owner_badge_opens_a_menu_of_the_runs_people_with_the_owner_ticked_and_unassign(self):
        card, menu = self.owner_menu("M3")
        self.assertIn('<button class="ownbtn" data-owner-menu="M3" aria-haspopup="menu" aria-expanded="true" title="Change who owns M3, or unassign it">', card)
        self.assertEqual(re.findall(r'aria-checked="(\w+)" data-give="M3" data-to="([^"]*)">', menu),
                         [("false", "ann"), ("true", "bo.berg"), ("false", "cy"), ("false", "")])
        self.assertIn("<span>ann (you)</span>", menu)
        self.assertIn("<span>Unassign</span>", menu)
        self.assertNotIn("disabled", menu)

    def test_an_owner_missing_from_the_runs_people_is_still_listed_and_ticked(self):
        self.maps(probe=f'({self.OWNED}, msOf("M3").owner = "dee", setOwnerMenu("M3"), $("map").innerHTML)')
        self.assertIn('aria-checked="true" data-give="M3" data-to="dee">', self.probe())

    def test_a_milestone_being_built_cannot_change_hands(self):
        _, menu = self.owner_menu("M2")
        self.assertIn('<div class="owner-note">M2 is building: stop it first</div>', menu)
        self.assertEqual(menu.count(" disabled>"), 4)

    def test_a_closed_menu_shows_only_the_badge_button(self):
        self.maps(probe=f'({self.OWNED}, $("map").innerHTML)')
        self.assertIn('data-owner-menu="M3" aria-haspopup="menu" aria-expanded="false"', self.probe())
        self.assertNotIn('class="owner-menu"', self.probe())

    def test_picking_a_person_posts_the_new_owner_and_unassign_posts_nobody(self):
        self.maps(probe=f'(async () => {{ {self.OWNED}; const calls = []; poll = () => {{}};'
                        ' fetch = async (u, o) => (calls.push([u, o?.method]), { ok: true, json: async () => ({}) });'
                        ' setOwnerMenu("M3"); await giveMs("M3", "cy"); const closed = S.ownerMenu; await giveMs("M3", "");'
                        ' return [calls, closed]; })()')
        self.assertEqual(self.probe(), [[["/owner/M3?to=cy", "POST"], ["/owner/M3?to=", "POST"]], None])

    def test_the_side_panels_owner_opens_its_own_menu_with_unassign_and_the_card_keeps_its_closed(self):
        self.maps(probe=f'({self.OWNED}, openSheet({{ ms: "M3" }}), setOwnerMenu("sheet:M3"), renderSheet(),'
                        ' [document.getElementById("sheet-head").innerHTML, $("map").innerHTML])')
        head, card = self.probe()
        self.assertIn('<button class="ownbtn" data-owner-menu="sheet:M3" aria-haspopup="menu" aria-expanded="true"', head)
        self.assertIn('data-give="M3" data-to=""><span class="owner dot none">–</span><span>Unassign</span>', head)
        self.assertNotIn('class="owner-menu"', card)

    def test_the_side_panels_claim_opens_its_own_menu(self):
        self.maps(probe=f'({self.OWNED}, delete msOf("M3").owner, openSheet({{ ms: "M3" }}), setOwnerMenu("sheet:M3"), renderSheet(),'
                        ' document.getElementById("sheet-head").innerHTML)')
        self.assertIn('<button class="claim" data-owner-menu="sheet:M3" aria-haspopup="menu" aria-expanded="true"', self.probe())
        self.assertIn('<div class="owner-menu" role="menu" aria-label="Owner of M3">', self.probe())

    def test_an_owner_change_says_it_started_before_the_server_answers(self):
        self.maps(probe=f'(async () => {{ {self.OWNED}; const said = []; toast = (t) => said.push(t); poll = () => {{}};'
                        ' fetch = async () => ({ ok: true, json: async () => ({}) });'
                        ' await giveMs("M3", ""); await giveMs("M3", "cy"); return said; })()')
        self.assertEqual(self.probe(), ["Unassigning M3…", "M3 is up for Claim again", "Giving M3 to cy…", "M3 is now cy's"])

    def test_claim_opens_the_owner_menu_without_a_tick_or_unassign(self):
        self.maps(probe=f'({self.OWNED}, delete msOf("M3").owner, setOwnerMenu("M3"), $("map").innerHTML)')
        html = self.probe()
        self.assertIn('<span class="ownwrap"><button class="claim" data-owner-menu="M3" aria-haspopup="menu" aria-expanded="true" title="Claim it, or give it to a colleague">Claim</button>', html)
        menu = re.search(r'<div class="owner-menu" role="menu" aria-label="Owner of M3">(.*?)</div></span>', html, re.S).group(1)
        self.assertEqual(re.findall(r'aria-checked="(\w+)" data-give="M3" data-to="([^"]*)">', menu), [("false", "ann"), ("false", "bo.berg"), ("false", "cy")])

    HANDED = ('S.events = [{ type: "owner", milestone: "M3", owner: "ann", by: "bo.berg", at: "2026-11-06T10:00:00Z" },'
              ' { type: "owner", milestone: "M2", owner: "ann", by: "bo.berg", at: "2026-11-06T09:00:00Z" },'
              ' { type: "owner", milestone: "M1", owner: "ann", by: "ann", at: "2026-11-06T09:30:00Z" },'
              ' { type: "owner", milestone: "M1", owner: "cy", by: "bo.berg", at: "2026-11-06T09:40:00Z" }];'
              ' msOf("M3").owner = "ann"; msOf("M2").owner = "cy"; msOf("M1").owner = "ann"')

    def test_a_milestone_someone_else_gave_you_shows_a_banner_until_you_say_got_it(self):
        self.maps(probe=f'(() => {{ {self.HANDED}; const shown = handedBanner(), keys = attention().map((x) => x[0]).filter((k) => k.startsWith("handed"));'
                        ' seeHanded(); return [shown, keys, handedBanner()]; })()')
        shown, keys, after = self.probe()
        self.assertIn('<div class="banner needs handed"><span class="label"><span class="pulse amber"></span>Given to you</span>', shown)
        self.assertEqual(re.findall(r'<span class="wchip" data-reveal="(M\d)"><b>M\d</b> from ([^<]*)</span>', shown), [("M3", "bo.berg")])
        self.assertIn("data-handed-done", shown)
        self.assertEqual((keys, after), (["handed:M3"], ""))

    def test_the_header_hints_who_runs_an_old_podium_and_only_them(self):
        self.maps(probe='(S.project.people = { "ann": {}, "mo.leon": {}, "cy": {} }, S.info.people = { "ann": { podium: { commit: "aaaaaaa", behind: 2, restart: true } },'
                        ' "mo.leon": { podium: { commit: "e6f6b8c", behind: 4 } }, "cy": { podium: { commit: "bbbbbbb", behind: 0 } } }, renderCrew(), $("crew").innerHTML)')
        hints = re.findall(r'<span class="vhint" title="([^"]*)">([^<]*)</span>', self.probe())
        self.assertEqual([h[1] for h in hints], ["AN · aaaaaaa, 2 behind", "ML · e6f6b8c, 4 behind"])
        self.assertIn("press Restart", hints[0][0])
        self.assertIn("/orchestrate-plan", hints[1][0])

    def test_every_tile_on_the_map_sits_white_on_a_deeper_shadow_landed_ones_too(self):
        css = open(PAGE).read()
        self.assertIn("--shadow-tile: 0 1px 3px rgba(0,0,0,.12), 0 8px 22px rgba(0,0,0,.18);", css)
        self.assertEqual(css.count("--shadow-tile: 0 1px 3px rgba(0,0,0,.5), 0 8px 22px rgba(0,0,0,.6);"), 2)
        self.assertIn(".fepic, .fms { position: relative; z-index: 1; background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px; cursor: pointer; text-align: left; box-shadow: var(--shadow-tile); }", css)
        self.assertNotIn(".fms.done { background: transparent; box-shadow: none; }", css)

    def test_the_page_loads_the_season_layer_deferred_from_the_server(self):
        page = open(PAGE).read()
        self.assertIn('<script src="/podium-season/season.js" defer></script>', page[:page.index("</head>")])

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

    def test_scrolling_to_a_milestone_clears_the_sticky_map_head(self):
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
        for gone in ("data-drill", "Full map", "S.view", 'id="filters"', "data-filter"):
            self.assertNotIn(gone, page)

    def test_a_search_dims_the_stories_dots_and_milestones_that_miss_it_and_removes_none(self):
        maps, _ = self.maps(probe='(() => { const cards = msList().map((m) => Object.assign(element(), { dataset: { id: m.id }, textContent: m.title,'
                                  ' kids: (m.stories || []).map((s) => Object.assign(element(), { dataset: { story: s.id } })) }));'
                                  ' cards.forEach((c) => (c.querySelectorAll = () => c.kids));'
                                  ' const out = []; for (const q of ["six", "second", "one"]) {'
                                  ' S.query = q; render(); document.querySelectorAll = (sel) => (sel === "#map .fms[data-id]" ? cards : []); applyFilter();'
                                  ' document.querySelectorAll = () => [];'
                                  ' out.push([cards.flatMap((c) => c.kids.filter((k) => !k.classes.has("dim")).map((k) => `${c.dataset.id}/${k.dataset.story}`)),'
                                  ' cards.filter((c) => !c.classes.has("dim")).map((c) => c.dataset.id)]); } return out; })()')
        self.assertEqual(self.probe(), [[["M3/S6"], ["M3"]], [[], ["M2"]], [["M1/S1"], ["M1"]]])
        for ms, story in (("M1", "S1"), ("M2", "S2"), ("M2", "S3"), ("M2", "S4"), ("M2", "S5"), ("M3", "S6")):
            self.assertEqual(len(re.findall(f'data-(?:open|ms)="{ms}" data-story="{story}"', maps[-1])), 1, story)
        self.assertEqual(re.findall(r'<div class="fms [^"]*"[^>]* data-id="(\w+)"', maps[-1]), ["R1", "M1", "M2", "M3"])

    def test_the_search_names_the_whole_map_and_the_legend_always_shows(self):
        page = open(PAGE).read()
        self.assertIn('<input id="q" type="search" placeholder="Search milestones, stories, files, ids"', page)
        self.assertNotIn(".placeholder =", page)
        self.maps(probe='(() => { const out = []; for (const go of [() => {}, () => collapse(), () => expand("M3")]) {'
                        ' go(); out.push(document.querySelector(".legend").hidden); } return out; })()')
        self.assertEqual(self.probe(), [False] * 3)

    def test_the_quality_panel_follows_the_open_milestone(self):
        self.maps(probe='(() => { const out = []; for (const go of [() => {}, () => expand("M2"), () => collapse(), () => expand("M3"), () => reveal("R1")]) {'
                        ' go(); out.push($("quality").hidden ? null : $("qsum").innerHTML.match(/class="qms">([^<]*)/)?.[1]); } return out; })()')
        self.assertEqual(self.probe(), [None, "M2", None, "M3", "M3"])

    def test_the_open_card_sits_in_its_epics_column_like_a_closed_card(self):
        maps, _ = self.maps(probe='(expand("M2"), collapse())')
        opened = next(m for m in maps if self.open_cards(m) == ["M2"])
        self.assertRegex(opened, r'<div class="fcol" data-lane="1"><div class="fms open ')
        self.assertNotIn("grid-column", self.open_card(opened))
        self.assertRegex(maps[-1], r'<div class="fcol" data-lane="1"><div class="fms working')

    def test_each_epic_stacks_its_milestones_in_its_own_column_from_the_top(self):
        maps, _ = self.maps(probe="(closeSheet(), render(), 0)")
        cols = re.findall(r'<div class="fcol" data-lane="(\d)">(.*?)</div><!--fcol-->', maps[-1], re.S)
        self.assertEqual([(lane, re.findall(r'<div class="fms [^"]*"[^>]* data-id="(\w+)"', html)) for lane, html in cols],
                         [("0", ["M1"]), ("1", ["M2", "M3"])])
        self.assertNotIn("<div></div>", maps[-1])

    def test_queue_lines_join_cards_within_a_column_and_cross_epic_deps_cross(self):
        self.maps(probe='queuePairs([{ id: "A", lane: "0", deps: [] }, { id: "U1", lane: "1", deps: ["B"] }, { id: "B", lane: "0", deps: ["A"] },'
                        ' { id: "U2", lane: "1", deps: ["U1", "Z"] }, { id: "C", lane: "0", deps: ["U2"] }])')
        self.assertEqual(self.probe(), [["A", "B", "queue"], ["B", "C", "queue"], ["U1", "U2", "queue"], ["B", "U1", "dep"], ["U2", "C", "dep"]])

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
        maps, _ = self.maps(FINISHED_RUN, localStorage={"podium-hide-finished:api": "1"}, probe='expand("M2")')
        self.assertEqual(self.tree_text(self.open_card(maps[-1])), (["Wave 3"], ["S3"], []))
        self.assertNotIn("Fold merged waves", self.open_card(maps[-1]))

    def test_with_hide_finished_on_an_open_milestone_whose_stories_all_finished_says_so_with_a_show_button(self):
        run = json.loads(json.dumps(FINISHED_RUN))
        run["epics"][0]["milestones"][0]["stories"] = [{"id": "S1", "title": "a", "status": "done"}, {"id": "S2", "title": "b", "status": "dropped"}]
        row = '<div class="mfold"><span class="mfl">All 2 stories finished</span><button class="ocollapse" data-hide-finished>Show</button></div>'
        for stored, shown in (({"podium-hide-finished:api": "1"}, True), ({}, False)):
            self.maps(run, localStorage=stored, probe='(reveal("M1"), $("map").innerHTML)')
            card = self.open_card(self.probe())
            self.assertEqual(row in card, shown)
            self.assertEqual("node compact" in card, not shown)

    def test_show_on_an_open_milestone_scrolls_back_to_it_and_the_header_button_does_not(self):
        run = json.loads(json.dumps(FINISHED_RUN))
        run["epics"][0]["milestones"][0]["stories"] = [{"id": "S1", "title": "a", "status": "done"}]
        self.maps(run, localStorage={"podium-hide-finished:api": "1"},
                  probe='(() => { const scrolls = []; scrollTo = (o) => scrolls.push(o.behavior); reveal("M1"); scrolls.length = 0;'
                        ' const click = (...hits) => { const target = { dataset: { ms: "M1" }, closest: (s) => (hits.includes(s) ? target : null) };'
                        ' LISTENERS.click.forEach((f) => f({ target, stopPropagation() {} })); return [S.hideFinished, scrolls.splice(0)]; };'
                        ' return [click("[data-hide-finished]", ".mtree[data-ms]"), click("[data-hide-finished]")]; })()')
        self.assertEqual(self.probe(), [[False, ["smooth"]], [True, []]])

    def test_search_sits_behind_an_icon_beside_the_map_title_and_closing_it_clears_the_query(self):
        page = open(PAGE).read()
        self.assertRegex(page, r'<h2 id="map-title">Topology</h2>\s*<button class="search-btn" id="search-toggle" aria-expanded="false"')
        self.assertRegex(page, r'<div class="map-search" id="map-search" hidden>\s*<label class="search">')
        self.assertNotIn("toolbar", page)
        self.maps(probe='(() => { const out = []; S.query = "six"; $("q").value = "six"; setSearch(false);'
                        ' out.push([$("map-search").hidden, S.query, $("q").value]); setSearch(true); out.push($("map-search").hidden); return out; })()')
        self.assertEqual(self.probe(), [[True, "", ""], False])

    def test_enter_in_search_goes_to_the_one_milestone_left_or_the_one_it_names(self):
        self.maps(probe='(() => { const card = (id, dim) => ({ dataset: { id }, classList: { contains: (c) => c === "dim" && dim } });'
                        ' const at = (q, ...cards) => { S.query = q; document.querySelectorAll = (sel) => (sel === "#map .fms[data-id]" ? cards : []); return searchHit(); };'
                        ' return [at("m11", card("M1", true), card("M11", false)), at(" M1 ", card("M1", false), card("M11", false)),'
                        ' at("m", card("M1", false), card("M11", false)), at(" ", card("M1", false)), at("x", card("M1", true))]; })()')
        self.assertEqual(self.probe(), ["M11", "M1", None, None, None])
        self.assertIn('$("q").addEventListener("keydown", (ev) => { const id = ev.key === "Enter" && searchHit(); if (id) scrollToMs(id); });', open(PAGE).read())

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
        edges = self.tree_edges(TREE_RUN, "M1", {"podium-hide-finished:api": "1"})
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
        cards, _ = self.moved(stored={"podium-hide-finished:api": "1"})
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
        if '<div class="fdrow">' not in full:
            return None
        cells = full.split('<div class="fdrow">')[1:]
        self.assertEqual(len(cells), len(epics))
        return [None if c.startswith("</div>") else c for c in cells]

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
        self.assertIn('<span class="owner dot" style="background:hsl(156 50% 45%)" title="bo is settling it">BO</span>', strip)
        self.assertIn('<span class="dmeta">blocked by D1</span><span class="dmeta">missing: a price list</span>', strip)
        for closed in ("Old", "Gone", "Elsewhere"):
            self.assertNotIn(closed, strip)

    def test_the_strip_marks_your_own_claim_and_reveals_affected_milestones(self):
        [strip, _] = self.strips([{"id": "D1", "epic": "e1", "question": "Q", "type": "discussion", "status": "open",
                                   "owner": "ann", "affects": ["M11", "billing", "M99"]}])
        self.assertIn('<span class="owner dot me" style="background:hsl(354 50% 45%)" title="Yours (ann): you are settling it">AN</span>', strip)
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

    PUT = '(() => { const put = {}; localStorage.setItem = (k, v) => { put[k] = v; }; %s; return Object.keys(put).sort(); })()'

    def test_the_runs_own_choices_carry_its_slug_and_the_theme_stays_global(self):
        self.maps(probe=self.PUT % ('closeSheet(); setTheme("dark"); setHideFinished(true); setCollapsed(true); setPeople(["@me"]);'
                                    ' togglePrioTier("nice"); toggleState("paused"); toggleState("closed"); setSort("owner"); seeHanded(); markSeen()'))
        self.assertEqual(self.probe(), ["podium-collapsed:api", "podium-handed-seen:api", "podium-hide-finished:api", "podium-hide-paused:api",
                                        "podium-people:api", "podium-priority-filter:api", "podium-seen:api", "podium-show-closed:api", "podium-sort:api", "podium-theme"])

    def test_a_value_kept_without_the_slug_or_under_another_run_is_not_read(self):
        for stored in ({"podium-collapsed": "1", "podium-people": '["@me"]'}, {"podium-collapsed:web": "1", "podium-people:web": '["@me"]'}):
            with self.subTest(stored=stored):
                self.maps(localStorage=stored, probe="[S.collapsed, S.people]")
                self.assertEqual(self.probe(), [False, []])
        self.maps(localStorage={"podium-collapsed:web": "1"}, info={"run": "web"}, probe="S.collapsed")
        self.assertTrue(self.probe())

    def test_nothing_is_kept_before_the_page_knows_its_run(self):
        self.maps(info={"run": None}, probe=self.PUT % 'closeSheet(); setCollapsed(true); setTheme("light"); markSeen()')
        self.assertEqual(self.probe(), ["podium-theme"])

    def test_the_season_snooze_stays_global(self):
        with open(os.path.join(ROOT, "podium_dashboard", "season", "season.js")) as f:
            season = f.read()
        self.assertIn('localStorage.getItem("podium-season-off")', season)
        self.assertIn('localStorage.setItem("podium-season-off",', season)

    RUNS = {"runs": [{"slug": "api", "port": 8765, "live": True, "used": DONE, "pinned": False, "title": "Acme", "current": True},
                     {"slug": "web", "port": 8766, "live": True, "used": DONE, "pinned": True, "title": X, "current": False},
                     {"slug": "ops", "port": 8770, "live": False, "used": DONE, "pinned": False, "title": None, "current": False}]}
    CLICK = ('const click = (...hits) => { const target = { dataset: { runGo: "web" }, closest: (s) => (hits.includes(s) ? target : null) };'
             ' LISTENERS.click.forEach((f) => f({ target, stopPropagation() {} })); };')

    def switch(self, probe, **files):
        self.maps(probe=f"(async () => {{ {self.CLICK} closeSheet(); {probe} }})()", **{"/runs": json.dumps(self.RUNS), **files})
        return self.probe()

    def test_the_title_has_a_button_that_opens_the_switcher_closed(self):
        page = open(PAGE).read()
        self.assertIn('<div class="title-row"><h1 id="epic-title">Loading…</h1><span class="ownwrap" id="runs"></span></div>', page)
        html = self.switch('return $("runs").innerHTML;')
        self.assertIn('data-runs-menu aria-haspopup="menu" aria-expanded="false"', html)
        self.assertNotIn("runs-menu", html.replace("data-runs-menu", ""))

    def test_lists_every_run_marking_the_current_one_and_which_are_live(self):
        html = self.switch('await setRunsMenu(true); return $("runs").innerHTML;')
        self.assertIn('aria-expanded="true"', html)
        menu = re.search(r'<div class="owner-menu runs-menu" role="menu" aria-label="Runs on this machine">(.*)</div>$', html, re.S).group(1)
        rows = re.findall(r'aria-checked="(\w+)" data-run-go="(\w+)"[^>]*><span class="run-dot ?(on)? ?"></span><span>([^<]*)</span>'
                          r'<span class="run-port">([^<]*)</span>', menu)
        self.assertEqual([(c, slug, on, port) for c, slug, on, _, port in rows],
                         [("true", "api", "on", "api · 8765"), ("false", "web", "on", "web · 8766"), ("false", "ops", "", "ops · 8770")])
        self.assertEqual(rows[2][3], "ops")
        self.assertEqual(menu.count('class="tick"'), 1)
        scan = Scan()
        scan.feed(html)
        self.assertNotIn(("i", "id", "pwn"), scan.attrs)
        self.assertIn(X, "".join(scan.text))

    def test_a_click_outside_or_escape_closes_it_and_the_button_toggles_it(self):
        self.assertEqual(self.switch('await setRunsMenu(true); const before = S.runsMenu; click(); return [before, S.runsMenu, $("runs").innerHTML.includes("Runs on this machine")];'),
                         [True, False, False])
        self.assertEqual(self.switch('await setRunsMenu(true); onEscape(); return S.runsMenu;'), False)
        self.assertEqual(self.switch('await setRunsMenu(true); click("#runs"); return S.runsMenu;'), True)
        self.assertEqual(self.switch('click("#runs", "[data-runs-menu]"); await new Promise((r) => setImmediate(r)); return S.runsMenu;'), True)

    def test_a_live_run_opens_on_its_port_and_a_stopped_one_is_started_first(self):
        self.assertEqual(self.switch('await setRunsMenu(true); await goRun("web"); return [location.href, S.runsMenu];'),
                         ["http://127.0.0.1:8766/", False])
        started = self.switch('await setRunsMenu(true); await goRun("ops"); return location.href;', **{"/runs/ops/start": '{"url": "http://127.0.0.1:8770/"}'})
        self.assertEqual(started, "http://127.0.0.1:8770/")
        self.assertEqual(self.switch('await setRunsMenu(true); await goRun("api"); return location.href;'), "http://127.0.0.1:8765/")

    def test_a_start_that_fails_or_answers_another_url_stays_put(self):
        for body in (None, json.dumps({"url": JS}), json.dumps({"url": "http://evil.example:8770/"})):
            with self.subTest(body=body):
                files = {"/runs/ops/start": body} if body else {}
                self.assertEqual(self.switch('await setRunsMenu(true); await goRun("ops"); return location.href;', **files),
                                 "http://127.0.0.1:8765/")

    GLOBS = [
        ("web-applications/A/lib/client.ts", "web-applications/A/lib/client.ts", True),
        ("web-applications/A/lib/client.ts", "web-applications/A/lib/schemas.ts", False),
        ("web-applications/M/mock-ams/store.ts", "app-messaging-service/M/mock-ams/store.ts", False),
        ("web-applications/M/messages/{en,sv,de,da}.json", "web-applications/M/messages/da.json", True),
        ("web-applications/M/messages/{en,sv}.json", "web-applications/M/messages/{de,da}.json", False),
        (f"{CONSENT}/{{Email,Sms,Push}}MarketingConsent{{Given,Revoked}}Event.java", f"{CONSENT}/PushMarketingConsentRevokedEvent.java", True),
        (f"{CONSENT}/{{Email,Sms,Push}}MarketingConsent{{Given,Revoked}}Event.java", f"{CONSENT}/PushMarketingConsentWithdrawnEvent.java", False),
        (f"{CONSENT}/{{Email,Sms,Push}}MarketingConsent{{Given,Revoked}}Event.java", f"{CONSENT}/*Revoked*.java", True),
        ("core-events/src/main/java/se/parkster/events/domain/news/*.java", "core-events/src/main/java/se/parkster/events/domain/news/NewsCreatedEvent.java", True),
        ("core-events/src/main/java/se/parkster/events/domain/news/*.java", "core-events/src/main/java/se/parkster/events/domain/news/v2/NewsCreatedEvent.java", False),
        ("app-messaging-service/src/main/kotlin/*.kt", "app-messaging-service/src/main/kotlin/*.kts", False),
        ("app-messaging-service/src/*Links.kt", "app-messaging-service/src/Supported*", True),
        ("core/backend/**/consent/ConsentView.java", "core/backend/web/core/src/main/java/se/parkster/server/service/consent/ConsentView.java", True),
        ("core/backend/**/ConsentView.java", "core/backend/ConsentView.java", True),
        ("core/backend/**/ConsentView.java", "core/frontend/ConsentView.java", False),
        ("web-applications/apps/**", "web-applications/apps/*/messages/{en,sv}.json", True),
        ("web-applications/apps/in-app-messaging/src/app/(protected)/drafts/[id]/page.tsx", "web-applications/apps/in-app-messaging/src/app/(protected)/drafts/d/page.tsx", False),
        ("web-applications/apps/in-app-messaging/src/app/(protected)/drafts/[id]/page.tsx", "web-applications/apps/in-app-messaging/src/app/(protected)/drafts/[id]/page.tsx", True),
        ("web-applications/S/feature/drafts/lib/{load-draft-form,draft-form-{values,problems}}.ts", "web-applications/S/feature/drafts/lib/draft-form-problems.ts", True),
        ("./web-applications/A/lib/client.ts", "web-applications/A/lib/client.ts", True),
    ]

    def test_two_file_patterns_overlap_when_some_path_matches_both(self):
        self.maps(RADAR_RUN, probe=f"{json.dumps([[a, b] for a, b, _ in self.GLOBS])}.map(([a, b]) => [globsOverlap(a, b), globsOverlap(b, a)])")
        for (a, b, want), got in zip(self.GLOBS, self.probe()):
            with self.subTest(a=a, b=b):
                self.assertEqual(got, [want, want])

    def test_a_shared_path_names_the_narrower_pattern_or_both_when_both_are_wildcards(self):
        m = "web-applications/M/messages"
        pairs = [[f"{m}/{{en,sv}}.json", f"{m}/{{sv,de}}.json"], [f"{m}/{{en,sv}}.json", f"{m}/sv.json"], [f"{m}/*.json", f"{m}/{{en,sv}}.json"],
                 [f"{m}/*.json", f"{m}/en.*"], [f"{m}/{{en,sv}}.json", f"{m}/{{en,sv}}.json"]]
        self.maps(RADAR_RUN, probe=f"{json.dumps(pairs)}.map(([a, b]) => sharedFiles({{ files: [a] }}, {{ files: [b] }}))")
        self.assertEqual(self.probe(), [[f"{m}/sv.json"], [f"{m}/sv.json"], [f"{m}/{{en,sv}}.json"], [f"{m}/*.json ∩ {m}/en.*"], [f"{m}/{{en,sv}}.json"]])

    @staticmethod
    def radar_cards(full):
        return {re.search(r'data-id="([^"]*)"', c).group(1): c for c in re.split(r'(?=<div class="fms )', full)[1:]}

    def test_a_milestone_card_shows_an_amber_chip_for_each_active_milestone_its_open_stories_overlap(self):
        maps, _ = self.maps(RADAR_RUN)
        cards = self.radar_cards(maps[-1])
        given = f"{CONSENT}/{{Email,Sms}}MarketingConsentGivenEvent.java"
        self.assertIn(f'<span class="badge overlaps" data-reveal="M2" title="S1 ↔ T1: {given}">Overlaps M2</span>', cards["M1"])
        self.assertIn(f'<span class="badge overlaps" data-reveal="M1" title="T1 ↔ S1: {given}">Overlaps M1</span>', cards["M2"])
        self.assertEqual(re.findall(r">Overlaps (M\d)<", maps[-1]), ["M2", "M1"])

    def test_finished_stories_paused_milestones_and_milestones_that_wait_for_the_other_are_left_off_the_radar(self):
        self.maps(RADAR_RUN, probe="crossOverlaps().map((p) => [p.a.ms, p.a.story, p.b.ms, p.b.story])")
        self.assertEqual(self.probe(), [["M1", "S1", "M2", "T1"]])

    def test_the_milestone_sheet_lists_each_overlapping_pair_with_its_shared_paths_and_a_link_to_the_other_milestone(self):
        self.maps(RADAR_RUN, probe='(openSheet({ ms: "M1" }), renderSheet(), document.getElementById("sheet-body").innerHTML)')
        body = self.probe()
        rows = re.findall(r'<div class="clash">(.*?)</div>', body[body.index("<h3>Overlaps</h3>"):])
        self.assertEqual(rows, [
            '<span><a data-open="M1" data-story="S2">S2</a> ↔ <a data-open="M1" data-story="S4">S4</a></span>'
            '<span class="clash-files mono">web-applications/M/messages/sv.json</span>',
            '<span><a data-open="M1" data-story="S1">S1</a> ↔ <a data-reveal="M2">M2</a> <a data-open="M2" data-story="T1">T1</a></span>'
            f'<span class="clash-files mono">{CONSENT}/{{Email,Sms}}MarketingConsentGivenEvent.java</span>'])

    def test_stories_in_one_milestone_overlap_only_when_they_share_a_wave(self):
        self.maps(RADAR_RUN, probe='waveOverlaps(msOf("M1")).map((p) => [p.a.story, p.b.story, p.paths])')
        self.assertEqual(self.probe(), [["S2", "S4", ["web-applications/M/messages/sv.json"]]])

    def test_a_milestone_without_overlaps_has_no_overlaps_section(self):
        self.maps(RADAR_RUN, probe='(openSheet({ ms: "M3" }), renderSheet(), document.getElementById("sheet-body").innerHTML)')
        self.assertNotIn("Overlaps", self.probe())

    def test_hostile_story_ids_and_paths_on_the_radar_are_escaped(self):
        run = json.loads(json.dumps(RADAR_RUN))
        run["epics"][0]["milestones"][0]["stories"][0].update(id=X, files=[X, f"{CONSENT}/*.java"])
        run["epics"][0]["milestones"][1]["id"] = X
        run["epics"][0]["milestones"][1]["stories"][0]["files"] = [X, f"{CONSENT}/*.java"]
        maps, _ = self.maps(run, probe='(openSheet({ ms: "M1" }), renderSheet(), document.getElementById("sheet-body").innerHTML)')
        self.assertIn('class="badge overlaps"', maps[-1])
        self.assertIn("<h3>Overlaps</h3>", self.probe())
        self.assertNotIn("<i id=pwn", maps[-1] + self.probe())


STICKY_HARNESS = r"""
const src = require("fs").readFileSync(process.argv[2], "utf8");
const fn = src.slice(src.indexOf("function trackStickyBar()"), src.indexOf("trackStickyBar();\n"));
const bar = { offsetHeight: 50, position: "sticky" }, vars = {}, head = { style: {}, classList: { toggle() {} } };
const watchers = [], resizers = [];
globalThis.window = { addEventListener: (_, f) => resizers.push(f) };
globalThis.document = { documentElement: { style: { setProperty: (k, v) => (vars[k] = v) } }, querySelector: (s) => (s === ".topbar" ? bar : head) };
globalThis.$ = () => ({});
globalThis.getComputedStyle = (el) => ({ position: el.position });
globalThis.IntersectionObserver = class { constructor(_, o) { this.margin = o.rootMargin; this.live = true; watchers.push(this); } observe() {} disconnect() { this.live = false; } };
let resized;
const observed = [];
globalThis.ResizeObserver = class { constructor(f) { resized = f; } observe(el) { observed.push(el); } };
eval(fn + "; trackStickyBar();");
const snap = (...extra) => [vars["--bar-h"], watchers.at(-1).margin, ...extra];
const out = [snap(observed.length)];
bar.offsetHeight = 90; resized();
out.push(snap(watchers[0].live, watchers.filter((w) => w.live).length));
bar.position = "static"; resizers[0]();
out.push(snap());
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "needs Node to run the page's script")
class StickyBar(unittest.TestCase):
    def test_the_map_head_offset_follows_the_header_height(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(tmp, "harness.js"), "w") as f:
            f.write(STICKY_HARNESS)
        r = subprocess.run(["node", os.path.join(tmp, "harness.js"), PAGE], capture_output=True, text=True, cwd=tmp, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [
            ["50px", "-50px 0px 0px 0px", 1],
            ["90px", "-90px 0px 0px 0px", False, 1],
            ["0px", "-0px 0px 0px 0px"],
        ])


if __name__ == "__main__":
    unittest.main()
