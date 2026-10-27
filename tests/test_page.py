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
FINISHED_RUN = {
    "project": {"title": "T", "quest": {"doc": "q.md"}}, "orchestrator": {"name": "o", "command": "/o"}, "active": {"epic": "e1", "milestone": "M2"},
    "epics": [{"id": "e1", "title": "E", "milestones": [
        {"id": "M1", "title": "first", "status": "done"},
        {"id": "M2", "title": "second", "status": "working", "phase": "build", "deps": ["M1"],
         "stories": [{"id": "S1", "title": "a", "status": "done"}, {"id": "S2", "title": "b", "status": "done", "deps": ["S1"]},
                     {"id": "S3", "title": "c", "status": "todo", "deps": ["S2"]}]}]}]}
PROTO_PROGRESS = "".join(f"2026-10-20T0{i + 6}:00:00+00:00 {kind} note\n" for i, kind in enumerate(reversed(KEYS)))

HARNESS = r"""
const OUT = [];
const els = {};
function element() {
  let html = "";
  const e = {
    get innerHTML() { return html; }, set innerHTML(v) { html = v; OUT.push(v); },
    insertAdjacentHTML(_, v) { OUT.push(v); },
    textContent: "", hidden: false, style: { setProperty() {} }, dataset: {}, title: "", value: "", href: "", placeholder: "", open: false,
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
  localStorage: { getItem: (k) => (FILES.localStorage || {})[k] ?? null, setItem() {}, removeItem() {} },
  addEventListener() {}, getComputedStyle: () => ({ position: "sticky" }), matchMedia: () => ({ matches: false }), scrollTo() {}, requestAnimationFrame: () => 0,
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
  OUT.push(`TITLE ${esc(document.title)}`);
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

    def hide_finished_buttons(self, run, stored=None, scope=None):
        """The label of every Hide finished button the page rendered, in render order, optionally only the map's or the stories'."""
        self.rendered(run, [], PROGRESS, (), localStorage=stored or {})
        labels = []
        for html in self.html:
            if f'data-hide-finished="{scope}"' in html if scope else "data-hide-finished" in html:
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
        self.assertIn("Show all · 1 hidden", labels)

    def test_the_story_map_has_its_own_setting_in_podium_hide_finished_stories(self):
        self.assertIn('"podium-hide-finished-stories"', open(PAGE).read())
        full = {"podium-hide-finished": "1"}
        stories = {"podium-hide-finished-stories": "1"}
        self.assertEqual(set(self.hide_finished_buttons(FINISHED_RUN, full, "stories")), {"Hide finished"})
        self.assertIn("Show all · 1 hidden", self.hide_finished_buttons(FINISHED_RUN, full, "map"))
        self.assertIn("Show all · 2 hidden", self.hide_finished_buttons(FINISHED_RUN, stories, "stories"))
        self.assertEqual(set(self.hide_finished_buttons(FINISHED_RUN, stories, "map")), {"Hide finished"})

    def test_hide_finished_is_off_for_any_other_stored_value(self):
        self.assertEqual(set(self.hide_finished_buttons(FINISHED_RUN, {"podium-hide-finished": "0"})), {"Hide finished"})

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

    def test_milestone_cards_add_the_repos_only_their_stories_name_after_their_own(self):
        cards = self.card_repos([{"id": "M1", "title": "a", "status": "todo", "repos": {"core": {}},
                                  "stories": [{"id": "S1", "title": "s", "status": "todo", "repos": ["web", "core"]},
                                              {"id": "S2", "title": "t", "status": "todo", "repos": ["api"]}]},
                                 {"id": "M2", "title": "b", "status": "todo",
                                  "stories": [{"id": "S3", "title": "s", "status": "todo", "repos": ["web"]}]}])
        self.assertEqual(cards["M1"][0], "coreno PR yetwebno PR yetapino PR yet")
        self.assertEqual(cards["M2"][0], "webno PR yet")

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
        self.assertIn('<span class="badge moved" data-drill="M11">Moved to M11</span>', cards["M10"][1])
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
        self.assertIn('<a data-drill="M10">M10</a> moved to <a data-drill="M11">M11</a> (&lt;b&gt;simple&lt;/b&gt;)', feed)
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

    def test_the_strip_marks_your_own_claim_and_drills_into_affected_milestones(self):
        [strip, _] = self.strips([{"id": "D1", "epic": "e1", "question": "Q", "type": "discussion", "status": "open",
                                   "owner": "ann", "affects": ["M11", "billing", "M99"]}])
        self.assertIn('<span class="owner" style="background:hsl(354 50% 45%)" title="Yours (ann): you are settling it">👤 <span class="who">you</span></span>', strip)
        self.assertIn('<span class="dmeta">affects <a data-drill="M11">M11</a>, billing, M99</span>', strip)

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
