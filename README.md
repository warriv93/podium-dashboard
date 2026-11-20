# podium-dashboard

Podium is a live localhost dashboard and a run-state CLI for feature work that agents build in parallel. A run is a folder of JSON and text files (epics, milestones, stories, events, progress lines); `podium` reads and changes it, and the dashboard shows it. Python 3.9 or later, standard library only. It grew out of Claude Code orchestration skills, but nothing in it depends on them.

![The Podium dashboard](docs/podium.png)

[`docs/podium-deck.pptx`](docs/podium-deck.pptx) is an 18-slide talk on Podium and the [deep-skills](https://github.com/warriv93/deep-skills) suite that drives it: many agents building in parallel from one plan, the suite as a layer cake, the ideas it borrows, the loop caps and model routing that keep them cheap, the quality gates, and what it has shipped so far. [`docs/podium-deck.js`](docs/podium-deck.js) builds it with pptxgenjs.

## Install

```
pip3 install --user git+https://github.com/warriv93/podium-dashboard
```

Or from a clone, so edits take effect at once:

```
pip3 install --user -e .
```

This puts `podium` on your path. Check with `podium --version`.

`podium self-update` brings the first kind of install up to the repo's HEAD, at most once per 6 hours (`--force` now, `--check` to only report).

## Quick start

`sample/` is a run in progress for a made-up product, Acme.

```
podium --dir sample status
podium --dir sample server --detach
```

`status` prints the active milestone, who owns what and each story's state. `server --detach` prints a `http://127.0.0.1:<port>/` URL; open it. The server stops by itself after an hour without use.

Each run keeps its port from one start to the next, and with it the page's settings in your browser: the first start takes the first free port of 8765-8784 that no other run holds, and records it as the run's lease in `~/.podium/ports.json`. A lease lasts 7 days from the run's last use. Starting a run that is already served prints where and exits 1; a leased port something else holds gives the run another free port for that start. `--port` overrides the lease and becomes it. `podium ports` lists the leases: `release <slug>` drops one, `pin <slug>` keeps one from expiring.

`podium` with no `--dir` finds the run for you: `$PODIUM_DIR`, else the nearest directory at or above the current one that holds `podium/podium.json`.

To start your own run, `podium init --name my-tool --command /my-tool --extension ./ext.py` creates `podium/podium.json`. Then add epics, milestones and stories with `podium set`, see `docs/SCHEMA.md`.

## Commands

| Command | What it does |
|---|---|
| `status [--all] [--milestone ID]` | compact view of the run |
| `get <target>` | a project, epic, milestone or story as JSON |
| `set <target> key=value ... [--event TYPE ...]` | change fields, append an event; `batch` does several in one write |
| `ready [--milestone ID]` | ids of the stories whose dependencies are done |
| `log [<milestone>/<story>] <STAGE> <note>` | append a progress line for a story |
| `assume`, `assumptions`, `settle` | record, list and settle assumptions made while you were away |
| `claim <milestone>`, `release <milestone>`, `whoami [name]` | ownership in a shared run |
| `decision add\|claim\|resolve\|outscope\|invalidate\|unresolved`, `decisions [--epic ID] [--json]` | epic-wide questions settled before the milestone cut, with the frontier to work next |
| `sync on\|off\|save\|pull\|status` | share the run through git |
| `finding add\|resolve\|wontfix`, `findings [--all] [--open] [--recur]` | record what went wrong or cost too much under a key reused when it recurs, and list the keys across runs, see Findings |
| `tokens [--since 7d] [--cwd <path>]... [--top N] [--json]` | where Claude Code's tokens went in the last week, and the recurring tool calls worth fixing, see Findings |
| `asana link\|refresh` | link a run to an Asana project or task and read its progress back, see Linking Asana |
| `ls stories\|milestones [--milestone ID] [--fields a,b]` | one line per story or milestone |
| `hours`, `human [set <mode> [--until HH:MM]]` | your working hours and availability, per machine; `human set` flips the toggle |
| `ports [release\|pin\|unpin <slug>]` | each run's port lease on this machine, whether it is served, when it was last used |
| `requests` | the button presses nobody has handled yet |
| `server`, `watch` | the dashboard, and the watcher an orchestrator listens to |
| `init` | name the run's orchestrator and its extension |

A milestone may wait for another without being held back: its `waitsFor` puts a "Waiting for M10" pill and a banner on the dashboard, whose Go ahead queues a `proceed` request, and `status` appends ` · waiting for M10` (see `docs/SCHEMA.md`).

The dashboard also runs a conflict radar over the stories' `files`. An active milestone whose unfinished stories may touch the same path as another active milestone's gets an amber "Overlaps M49" chip, with the shared paths in its tooltip; the chip opens M49. The milestone sheet's Overlaps section lists each story ↔ story pair with its shared paths, including stories of the same wave that collide, so you can add an `overlapAfter` or a dep before both start (see `docs/SCHEMA.md`).

`podium move M10 --to M11 [--pattern <slug>]` folds a milestone into another: M10 turns `moved`, M11 `includes` it, and a wait on M10 becomes "waiting for M11 (was M10)".

Questions that touch two or more milestones of an epic are settled first, as decisions: `podium decision add "Which auth?" --type discussion --affects "M1,M2"` prints `DECISION D1 open` (at most 6 open per epic without `--force`), `decision claim D1` makes it yours, and `resolve`, `outscope` or `invalidate` close it with the outcome (`unresolved` keeps it open with what is missing); on a decision someone else claimed, these need `--force`. `podium decisions` lists them and ends with `FRONTIER D1,D4` (open, unclaimed, every blocker closed) and `STATE ACTIVE|WAITING|BLOCKED|CLEAR`; cut the epic once it is `CLEAR`.

`podium --help` has the full reference. Targets are `.` (the project), `me`, `epic:<id>`, `milestone:<id>`, `<story>` of the active milestone, or `<milestone>/<story>`.

## Linking Asana

`podium asana link <url> [. | epic:<id> | milestone:<id>]` links the project, an epic or a milestone to an Asana project or task, and `podium asana refresh` reads every link back: assignee, custom fields, completion, and the subtasks of a linked task as milestones. Refresh needs a personal access token, from `$ASANA_TOKEN` or the macOS keychain:

```
security add-generic-password -s podium-asana -a "$USER" -w
```

Without a token `refresh` prints `NO_TOKEN` and exits 3; a failed read prints `ASANA-ERROR` and exits 1. The output lines are in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Findings

A run records a **finding** when something went wrong or cost too much, under a short kebab-case key that a later run reuses for the same problem: `podium finding add --key gate-reran --kind retro --target feature-qa --title "…" --moment "<evidence>" --fix check --severity normal`. It goes into the run's events (the dashboard's feed shows it) and onto the ref `refs/heads/findings/<run slug>` of the git remote the extension names as `FINDINGS_REMOTE`, file `findings.jsonl`, one JSON record per line, without touching any working tree. With no `FINDINGS_REMOTE` the event is still recorded. `podium finding resolve <key> --sha <sha> --repo <repo>` and `podium finding wontfix <key> --why "<why>"` close a key the same way; outside a run they take `--remote <url>` and write to `refs/heads/findings/resolutions`.

`podium findings` lists the run's own findings grouped by key; `--all` reads every run's ref on the remote (outside a run, `--remote <url>`, repeatable): `FINDING <key> ×<runs> <open|resolved <sha>|wontfix> <kind> <target> <severity>[ ~<saving>/wk] — <title>`. A closed key is open again when it recurs later. `podium findings --recur` prints `RECUR <key> ×<runs> — <title>` for open keys seen in two runs or more, or marked high, at most once a day per machine: an orchestrator's turn can pass those lines on.

`podium tokens` is where a `tokens` finding's evidence comes from. It reads Claude Code's session logs under `~/.claude/projects` (subagents included) since `--since` (default `7d`, or an ISO time), for sessions whose cwd is under a `--cwd`, with no model calls, and prints `TOTAL <tokens> sessions <n>`, a `MODEL <model> <tokens>` line per model, and `PATTERN <kind> ×<count> ~<tokens>/wk <normalized>` lines ranked by tokens per week: `big-output` (large tool results), `repeat-command` (the same Bash command, with paths, shas, numbers and quoted strings as placeholders, in several sessions), `reread` (the same file read in several sessions) and `sequence` (the same three tool calls in a row in several sessions). `--top N` keeps N of each kind (default 10), `--json` prints one object.

## Writing an orchestrator extension

The core knows run state, not what your orchestrator does. Your orchestrator adds verbs (`launch`, `merge`, ...), the prompts the dashboard's buttons hand out, and any extra request actions in one Python file, registered with `podium init`. `examples/minimal_extension.py` is a working one:

```
podium --dir sample hello
```

The full contract is in [docs/PROTOCOL.md](docs/PROTOCOL.md), the files in [docs/SCHEMA.md](docs/SCHEMA.md).

## Sharing a run between two machines

Sync commits the run's state onto a git ref and pushes it to a private repo you choose. Nothing in your working trees changes.

```
podium sync on --remote git@example.com:acme/podium-runs.git
podium claim M2
```

`sync on` prints the ref it uses. The second machine joins with the same remote and ref, then pulls:

```
podium --dir acme sync on --remote git@example.com:acme/podium-runs.git --ref refs/heads/podium-run/acme
podium --dir acme sync pull
```

Sync carries the run's state files and its planning docs: Markdown files anywhere in the run dir, `spec/`, `mock/` and `domain-stories/`, plus any document `podium.json` references inside the run dir (an artifact, a brief, a spec, a ledger), unless excluded. Each person claims their milestones, so changes stay apart; `podium.json` merges, `events.jsonl` and progress files union (the progress of your own milestones stays as your machine has it), and a text conflict keeps your file and writes the other as `<file>.remote` (`<file>.2.remote`, `.3.remote`, ... while an earlier conflict's copy is still there). While the watcher runs it pulls every minute and prints `SYNCED <sha> <summary>` when someone else's change arrives. The merge rules are in [docs/PROTOCOL.md](docs/PROTOCOL.md).

The dashboard's **Share** button queues a `share` request for your orchestrator, which switches sync on and prints the colleague's steps in its chat. Once the run syncs, the button reads **Shared** and its tooltip lists those steps with the run's ref and remote filled in: the extension's `SHARE_STEPS` when it has them, else install this tool, install the orchestrator's skill, run `<orchestrator command> join <ref>` in a new empty folder, and `podium claim <milestone>`. In a run that syncs, the Podium server also pulls your colleagues' changes every minute on its own, orchestrator or not, and the **Fetch** button beside **Share** pulls them at once.

Every side sheet has a **Copy link** button left of its close button: the link (`http://127.0.0.1:8765/open?run=<run slug>#/M24`, or `#/M2/S8`, or `#/M24/doc/spec/m24/spec.md`) opens in a colleague's own Podium: `#/M24` opens milestone M24 on the map, `#/M2/S8` opens M2 on the map and story S8's sheet, and a `/doc/` link opens that document's sheet. Port 8765 is where a Podium starts, and any Podium there sends the link on to the server of that run on the colleague's machine, whatever port it took: the run's leased port, else any of 8765-8784. A run with a lease that isn't served is started from the dir the lease names, then opened. With no Podium running on 8765-8784 the browser can't connect, and one that finds neither the run nor a lease for it answers a page with `podium server --detach` to start it in their checkout.

The ▾ beside the run's title lists every run with a lease on this machine, a green dot on those served now, with a tick on this one. Click another to open it, or, when it is stopped, to start it from its own dir and then open it.

A brief or file list that names a mock under the run dir's `mock/` (an HTML page, a picture, or a folder with an `index.html`, such as `mock/m10/auth-screens.html#proposed` or `feature-folder/mock/r6/`) links it with 🎨: it opens in a new tab from this Podium, so a colleague on the shared run opens the same mock, which `podium sync` carries with the run. A mock that isn't in the run yet shows greyed with "not built yet" instead of a link that would 404.

In a shared run, clicking a milestone's owner badge, or **Claim** on one nobody owns, opens a pulldown of the run's people with its owner ticked: pick a colleague to give it to them, or **Unassign** to put it up for Claim again (`POST /owner/<milestone>?to=<person>`, `?to=` for nobody; written at once with `handover` and `owner` events, pushed when the run syncs, no watcher needed). Anyone may move any milestone, except while one of its stories is building or awaiting approval. A click outside a pulldown, or Escape, closes it. A milestone someone else gave you shows a **Given to you** banner (and counts in the tab title and notifications) until you press Got it, kept in the browser under `podium-handed-seen:<run slug>`.

Each Podium server writes the commit it runs to `people.<me>.podium` when it starts, and every 30 minutes (`--version-every`, 0 never) checks it against the repo's HEAD, counting the commits in between through GitHub's compare API. Anyone behind shows as an amber hint beside the avatars, such as `ML · e6f6b8c, 31 behind`; nobody up to date shows one. Your own hint says whether to press Restart (the latest is installed) or run `podium self-update` first.

Choices kept in the browser carry the run's slug, so a port another run takes later doesn't inherit them; the theme and the season's snooze are yours across runs.

**Collapsed**, first in the map header, shows every closed milestone as one line (id, priority, title and owner) to glance over a long run; the milestone you open still shows in full. Closed milestones and decisions show their owner as initials, like the avatars in the header; the open milestone and its sheet show the full name. The choice is kept in the browser under `podium-collapsed:<run slug>`.

**Sort**, after Collapsed, reorders the milestones inside each epic column; epics stay where they are. Run order is the default; Mine first puts the milestones you own first, then those waiting on you; Priority goes Must, Should, Nice; Status goes working and waiting on you, then ready, waiting on a dependency, draft, paused and finished; Owner groups by owner name with unowned milestones last. Run order breaks ties inside each group. While a sort is on, the button names it (**Sort · Priority**), the queue lines between cards in a column are hidden because they would imply run order (lines to dependencies in other epics stay), and **Up next** stays on the milestone that is really next. The choice is kept in the browser under `podium-sort:<run slug>`.

**Filter**, after Sort, opens a menu in two parts. Priority ticks Must have, Should have and Nice to have; unticking one hides those milestones (the last ticked tier can't be unticked). Status ticks Paused (parked or later milestones), Closed (dropped ones) and Finished (landed and moved milestones and, inside the open milestone, merged or dropped stories); Closed and Finished start unticked, so a run opens on the work still to do. Whatever is open or needs you stays, epic tiles are never filtered, and once the menu differs from its defaults the button counts the milestones your choices hide beyond them. The choices are kept in the browser under `podium-priority-filter`, `podium-hide-paused`, `podium-show-closed` and `podium-hide-finished`, each followed by `:<run slug>`.

**People**, after Filter, narrows the map to some people's milestones. It reads **Everyone** until you pick: its menu lists you first, then colleagues by how many milestones on the map they own, then No owner, each with that count and a green dot when they were active in the last 15 minutes. Clicking a name shows only them; its box adds them to who is shown. Picking you (**Mine**) also keeps what waits on you (the one that needs you, a draft PR for you to look at, the one you have open). The button names the choice (**Mine**, a name, **2 people**) with their faces and counts what it hides, and the choice is kept in the browser under `podium-people:<run slug>`; a Mine kept under `podium-mine` from before carries over.

An amber chip after People, such as **2 flaky gates**, shows when a contract gate failed and then passed on the same commit: the flakes that cost a wave a re-run. It comes from the `gates.jsonl` history that `gates.sh --logs` appends to in each contract's logs folder (see [docs/SCHEMA.md](docs/SCHEMA.md#gatesjsonl)), read by the server's `GET /gates`. Clicking it opens a sheet listing each flaky gate with its logs folder, how often it flipped, when it last did and how many of its runs failed. With no flakes, or a server older than `/gates`, there is no chip.

A quest with a start date (`podium set . project.quest.start=2026-10-12`, the Monday of its first week) shows its timeline under the quest tile: its weeks (`weeks`, 6 by default) with today marked, the open weeks after them (`openWeeks`, 2 by default), and what is left to reach the goal, overall and for the Must and Should ones: `4 of 10 landed · 6 to go, ≈ 3 a week`, the weekly rate spread over the quest's remaining weeks (none in its last week, the open weeks or after). From the quest's last week until its open weeks end, a wrap-up card sits under the tile to prepare the presentation and the test rounds: the tally, what landed, the Must and Should ones still open, what moved, and who landed how many. Each milestone chip carries its status like the map's cards (✓ landed in green, ● working in blue, → moved greyed), and the Landed row starts folded to its count: its arrow opens it, kept in the browser under `podium-wrap-landed:<run slug>`. **Copy as text** puts it on the clipboard.

A milestone that lands while you watch bursts from its card all year: quiet ticks and sparkles, or the season's own marks when one is on. When the last Must of the quest lands, confetti falls.

From 1 December to 6 January the page dresses up for the season. Light snow falls, the epic tiles get snow on top, the logo wears a Santa hat and a chip counts down to Christmas Eve. About once a minute a bauble or a star drifts by behind the cards, and about every three minutes a reindeer walks along the bottom (click it). Lucia, 13 December, swaps the hat for a candle crown; New Year, 31 December and 1 January, brings a party hat and fireworks, with a show at midnight. The ❄ beside the chip turns the season off until next year (kept in the browser under `podium-season-off`); with reduced motion on, only the hat, the tiles' snow and the chip stay. Halloween (24 October to 1 November) brings falling leaves, bats, a witch hat and a pumpkin walking by. Easter (Palm Sunday to Easter Monday) brings feathers, grass on the tiles, flying eggs and a witch, bunny ears and the Easter bunny with its chicks. Fettisdagen (the Sunday to the Tuesday it falls on) has light snow, a semla on the logo and a rolling semla. Valborg (28 to 30 April) has bonfire sparks drifting up and a student cap. `?season=xmas`, `lucia`, `newyear`, `halloween`, `easter`, `fettisdagen`, `valborg` or `off` on the page's URL forces one. The layer lives in `podium_dashboard/season/`: `season.js` keeps one entry per season (its dates, chip, particles, cap on the tiles, hat, flyers, walk-by and burst), so a new season is one more entry and its art. The third-party files there and their licences are listed in its `NOTICE.md`.

Each milestone card shows its state on a coloured left edge with a glyph before its id: green ✓ landed, blue ● in progress, amber ! waiting on you, red ✕ failed, grey ○ not started. Blue means in progress everywhere on the page, and green only means landed. Each epic's bar splits the same way: green for landed milestones, blue for those in progress.

What a milestone cost shows in its sheet's Timeline header: from its first story's start to its last story's finish, its agent time (the stories' durations added up, a retried story's last attempt only, as `startedAt` restarts with each attempt), its retries (from the stories' `attempts`, or the `retry` events when they say more) and the tokens this machine's Claude Code sessions spent on it, e.g. `3h 10m start to finish · 12h agent time · 1 retry · 3.1M tokens on this machine`; the count leaves out context read back from the cache, which dwarfs the rest; hover it for input, cache writes, output and those cache reads. A landed milestone's card repeats it as one quiet line, and an epic's sheet totals its milestones. Tokens come from `GET /cost`: the session logs in `~/.claude/projects` whose cwd is one of a story's `worktrees`, plus an Agent-tool subagent's log by its `agent.id`. Logs exist only on the machine that ran the story, so a colleague's milestones show their time alone; a figure the run doesn't have is left out.

A milestone or epic marked must have carries a gold **★ Must** pill on the map, one marked should have a soft gold **★ Should** pill; anything unmarked is nice to have. Click the pill on an open milestone (where a nice to have one shows a grey **Nice to have** pill; closed cards leave it out) or in an epic's sheet (a quest's US tiles) to pick another from a pulldown (`POST /priority/<milestone>?level=must|should|nice`, or `/priority/epic/<epic>?level=...`; written to `podium.json` at once, with no watcher needed), or with `podium set milestone:<id> priority=must` (`priority=should`, `epic:<id>` for an epic, `priority=null` clears it).

A milestone's pulldown also sets its status: **Open**, **Paused** (parked) or **Closed** (dropped), from the open card or its sheet (`POST /status/<milestone>?to=open|paused|closed`, written to `podium.json` at once with a `status` event, and pushed in a shared run). Pausing or closing an open milestone keeps the status it left in `resumeTo`, which Open restores. The choices are greyed out while the milestone is in progress, and a landed or moved one, or an epic, offers priority only.

Beside it, a run with two or more people shows one avatar each (everyone in `podium.json`'s `people` or the `by` of an event; yours has a ring; past five people it shows four and a `+N` chip). A green dot means an event of theirs is under 15 minutes old: recent activity, not live presence. The tooltip names the milestones they own, the one they're on with its phase, and when they were last active.

## Quest report

The quest tile's **📄 New status report** (**📄 New quest report** once the quest's last week has ended) asks the orchestrator for a report on the quest for product, UX and management, to read through in the Podium and publish to Outline. A start dialog picks what it covers: since the last report (the default during the quest, offered once there is one), the whole quest (the default once it ended) or from a date. The tile links the newest published report and, while there is one, the draft.

The page queues these requests; `podium watch` prints them as `REQUEST …` and `podium requests` as `LIST …`, none with an id:

    REQUEST report cover=since           draft a report on what changed since the last one
    REQUEST report cover=all             draft one on the whole quest
    REQUEST report cover=2026-11-06      draft one on what changed from that date
    REQUEST report-publish               publish the ready draft to Outline
    REQUEST report-comments              read the comments on the published reports again

Each needs a running watcher (409 otherwise). The orchestrator answers them through `project.quest` in podium.json:

- `report`: the report being written, `{"draft": "reports/<slug>.json", "status": "drafting" | "ready" | "published", "name": "Sync 2026-11-20", "url": "<Outline URL, once published>"}`. The draft is a file of the run dir's `reports/`; the page shows it while `ready`, and a "being written" state while `drafting`.
- `reports`: the published ones, oldest first, `[{"name", "url", "publishedAt"}]`; the orchestrator appends one on each publish.
- `reportComments`: the Outline comments on them, `[{"id", "author", "role", "quote", "body", "at", "url", "answer"?: true, "handled"?: true}]`. The tile lists those not handled. **Answer in the next report** sets `answer` (the next draft answers it under `answers`); **Reply in Outline ↗** opens `url` and sets `handled`. The page writes both straight to podium.json (`POST /report-comment/<id>?answer=1|0`, `?handled=1|0`), with no watcher.

The draft, `reports/<slug>.json`, is what the page renders and what gets published. Every field is optional but `name`, `kind` and `tiers`:

```
{ "name": "Sync 2026-11-20", "kind": "sync" | "final", "writtenAt": "2026-11-20",
  "cover": {"from": "2026-11-13" | null, "label": "Since last sync (13 Nov)"},
  "sections": ["banner", "stats", "must", "should", "nice", "moved", "ask", "next", "app"],
  "showInternal": false, "groundworkLine": false, "structure": "status" | "priority" | "group",
  "banner": {"title": "...", "lede": "...", "image": "reports/img/admin.png", "testUrl": "https://...", "testLabel": "Try it in test"},
  "stats": [{"n": "10 of 14", "label": "must haves delivered"}],
  "tiers": {"must": [Item], "should": [Item], "nice": [Item]},
  "earlier": {"must": 10, "should": 2, "nice": 0},
  "moved": [Item],
  "asks": [{"question": "...", "owner": "Henrik", "with": "with the app leads", "by": "27 Nov"}],
  "next": ["..."],
  "answers": [{"commentId": "c1", "who": "Maria Ek", "role": "Product", "question": "...", "answer": "..."}],
  "apps": {"lede": "...", "groundwork": "Plus groundwork in both apps: ...", "links": [{"label": "iOS milestone", "url": "https://..."}],
           "items": [{"id", "role", "head", "why", "platforms": {"iOS": {"state": "done" | "flag" | "open" | "none", "url": "https://..."}, "Android": {...}}}],
           "open": [Item]},
  "footer": {"owner": "Henrik Linde", "source": "in-app-message-experience"} }

Item = {"id", "bucket": "done" | "working" | "open", "role": "Driver", "head": "Should be able to …", "why": "...",
        "isNew": true, "internal": true, "hidden": true, "added": true, "keep": true, "risk": {"level": "blocks" | "waits" | "later", "text": "Blocks switching off the old admin"}}
```

Without `sections`, every section shows but `ask` and `next`, which the user ticks on. `structure` picks the order, `status` when absent: **status** lists Delivered, then Being worked on, then Not finished, each split by priority; **priority** lists each tier with its statuses inside; **group** lists each target group (`role`) with its statuses inside. Each tier lists its items under Delivered, Being worked on and Not finished, by role (Driver, Marketing, Support, Admin, Staff, then the rest), and names the unfinished ones that block a launch step (`risk.level` `blocks`), each as its head then its `risk.text`. `earlier` is the count delivered before `cover.from`, shown as one line. `internal` items are left out unless `groundworkLine` (one line counting them) or `showInternal` (every one). An app item is Live, Built behind a switch (a platform `flag`) or Not finished (a platform `open`); `apps.open` are Not finished. `banner.image` is a run-relative path or an https URL; every link is http(s) or left out.

What the user changes in the modal is saved back into the draft with `PUT /report-draft?path=<draft>` (a JSON object under 256 KB, only to `project.quest.report.draft` and only while it is `ready`): edited text in place, **Leave out** as `"hidden": true` on the item, the section checkboxes as `sections`, the Structure pick as `structure`, a ghost row's new item with `"added": true`, a row dragged to another priority, status or target group with `"keep": true`, **Show internal groundwork** as `showInternal`. Publish the draft as it is on disk: it is what the user read through. **Copy for Slack** copies it as plain text; **Rewrite the draft** asks for `report` again with the same cover.

## Security

The server binds to `127.0.0.1` only and refuses any request whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>`. Any request but a GET or HEAD from a page with another `Origin` is refused too. There is no login: anyone with a shell on your machine can reach it, so do not forward the port.

## Trust model

Sharing a run through `podium sync` means trusting everyone who can push to its remote: what they write, such as story briefs and the prompts built from the run's state, becomes instructions for your agents.

What a pull never does: run code. The extension is a `.py` file each machine sets itself (a machine takes the run's only on its first join, and never again); Python files and native modules never sync; the orchestrator skills run a contract command from synced state only after you `podium approve` it. A pull writes only the run's files that this machine's own include and exclude lists carry, inside the run dir and never through a symlink, and never touches the progress of milestones you own.

What it accepts: a repo path in `podium.json` may point at any repo on disk, and git runs there (always with `safe.bareRepository=explicit`). The dashboard sets no frame policy, so another site may frame it, and a click inside that frame is a click on the dashboard.

What `podium server --lan` exposes: the dashboard on your network, for a browser on another machine. Anyone holding its printed `lan` URL can read the run and press every button, as you can at 127.0.0.1. The key is in that URL and, once opened, in the browser's cookie for it; it is new each time the server starts (a restart keeps it). Without the key a LAN request gets 403, and the network sees the key in clear, as it is plain HTTP: use it on a network you trust.

## License

MIT, see [LICENSE](LICENSE).
