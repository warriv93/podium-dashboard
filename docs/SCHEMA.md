# Run files

A run is a directory (the run dir) with a `podium/` folder in it. Everything below lives in `podium/` unless noted. A run is plain JSON and text; `sample/` is a complete one.

Unknown keys in `podium.json` pass through every command untouched, so an orchestrator can keep its own fields.

## Shared and machine-local

| File | Written by | Shared by `podium sync` |
|---|---|---|
| `podium.json` | `podium` commands, orchestrator | yes (the `sync` block stays local; `orchestrator.extension` keeps the value the run's first save seeded) |
| `events.jsonl` | `podium set --event`, core commands | yes, merged as a union of lines |
| `stories/<milestone>/<story>.md`, `.progress` | orchestrator, `podium log` | yes (`.progress` merged as a union, except that the owner's machine keeps its own milestone's as it is) |
| `handoffs.json` | the server | yes |
| planning docs (`*.md` and `**/*.md` anywhere in the run dir, `spec/**`, `mock/**`, `domain-stories/**`) | orchestrator | yes, unless this machine's lists leave them out |
| documents `podium.json` references inside the run dir: the references of your own milestones, plus the epics' specs and artifacts and the quest doc (every reference in a run without owners or `people`) | orchestrator | yes, even when no include covers them; never a Python file, a native module or an excluded one. A pull writes the ones any reference names |
| `requests.jsonl` | the server | never |
| `cursor.json` | `podium requests` | never |
| `watcher.json` | `podium watch` | never |
| `server.log` | `podium server --detach` | never |
| `<name>.logs/**/gates.jsonl`, in the run dir | `gates.sh --logs` | never |
| `synced.json` | `podium sync` | never |
| `~/.podium/human.json` | `podium hours`, `whoami`, the Podium toggle | outside any run; one per machine |
| `~/.podium/sync.json` | `podium sync defaults` | outside any run; one per machine, beside `human.json` |

Never synced either: `repos/**`, `worktrees/**`, `*.logs/**`, `*.tmp`, `*.remote`, Python code: `*.py`, `*.pyc`, `*.pth`, `__pycache__/` folders, and native modules: `*.so`, `*.dylib`, `*.pyd`. These names, and `sync.exclude`, match in any case: a Mac's file system ignores it.

## podium.json

```json
{
  "project": {"title": "Acme", "summary": "..."},
  "epics": [{"id": "team-workspace", "milestones": [{"id": "M2", "stories": []}]}],
  "active": {"epic": "team-workspace", "milestone": "M2"},
  "needsYou": {"reason": "...", "story": "S8"},
  "assumptions": [],
  "people": {"ann": {"active": {}, "needsYou": null, "assumptions": []}},
  "orchestrator": {"name": "minimal", "command": "/minimal", "extension": "../../examples/minimal_extension.py"},
  "sync": {"enabled": true, "remote": "git@example.com:acme/podium-runs.git", "ref": "refs/heads/podium-run/acme"},
  "repoUrl": "https://github.com/example/acme",
  "updatedAt": "2026-10-08T15:14:32+00:00"
}
```

### Top level

| Key | Meaning |
|---|---|
| `project` | `title`, `summary`; `asana` when linked; `quest` when an orchestrator shows a research quest, with its cycle in `start` (`YYYY-MM-DD`, the Monday of week 1), `weeks` (6 when absent) and `openWeeks` (2 when absent), and its status report in `report`, `reports` and `reportComments` (README, Quest report) |
| `epics` | list of epics, see below |
| `active` | `{epic, milestone}`: the milestone `milestone:` and a bare story id refer to |
| `needsYou` | `{reason, story?}` or null: what is waiting for the user |
| `assumptions` | answers an agent assumed while the user was away, see below |
| `decisions` | epic-wide questions settled before an epic's milestone cut, see below |
| `people` | per-person state, see Collaboration |
| `orchestrator` | the extension block, see below |
| `sync` | git sync, see below |
| `repoUrl` | the project's repository URL, for links in a single-repo run |
| `updatedAt` | stamped on every write |

### Epics

`id`, `title`, `summary`, `spec` (path to its brief), `milestones[]`, and optionally `asana` and `branch`.

### Milestones

| Key | Meaning |
|---|---|
| `id`, `title`, `summary` | `summary` is what the milestone changes, shown as What in its sheet's About section |
| `goal` | optional: what we gain from it and for whom, shown as Why in the About section |
| `value` | optional: `{"level": "high"\|"medium"\|"low", "why": "<short reason>"}`, what the milestone is worth, shown as the Value box under What and Why |
| `effort` | optional: `{"level": "small"\|"medium"\|"large", "why": "<short reason>"}`, what it costs to build, shown as the Effort box beside Value |
| `verdict` | optional: one line weighing value against effort ("Quick win: cheap, and it unblocks M4"), shown under the two boxes when either is set |
| `status` | `draft`, `later`, `parked`, `todo`, `working`, `done`, `dropped`, `moved` (folded into another milestone by `podium move`) |
| `resumeTo` | `draft` or `todo`: the status a milestone paused or closed from the Podium left, which reopening it restores |
| `movedTo` | a moved milestone's target. The Podium greys its card with a "Moved to <id>" pill that opens the target, and unticking Finished in the State menu hides it like a landed one; it counts as neither landed nor open |
| `includes` | ids of the milestones moved into this one, in the order they were moved; the card says "includes <ids>" |
| `cut` | `{pattern, valuable, kept}`: the splitting pattern that cut it (a slug), whether a user notices it, and why it stays when not (`podium set milestone:<id> cut=<json>`). `valuable: false` with `kept` shows a small "infra" tag whose tooltip is `kept` |
| `phase` | the stepper position, one of `orchestrator.phases` (default `recon spec mock architecture stories build gate verify land`) |
| `deps` | milestone ids that must be done first |
| `waitsFor` | `[{milestone, reason}]`: milestones this one is better done after, a soft relation unlike `deps`: building on (with mocks) is always allowed. A wait on a moved milestone follows `movedTo`, through chains, to where it ends (a cycle stops at the last milestone before it repeats), and reads "Waiting for M11 (was M10)". An awaited milestone that is done or dropped counts as met and is left out everywhere. The Podium marks the card "Waiting for <id>" in amber, gives the awaited milestone an "<id> is waiting" chip and prefers it as up next, and shows a banner with Plan and Go ahead until `waitsForAck` |
| `waitsForAck` | true once the user chose to go ahead without the `waitsFor` milestones (a `proceed` request); cleared when `waitsFor` changes. The card then shows a muted "Going ahead without <id>" |
| `owner` | the `me` of the person who may change it, see Collaboration |
| `buildAll` | true while the orchestrator should keep launching ready stories |
| `grilled` | the spec was settled with the user |
| `brief`, `spec`, `archive` | paths to documents |
| `branch` | the integration branch (single-repo) |
| `repos` | `{<repo>: {path, branch, base, pr: {number, state, url}}}` (`state` draft, open, merged or closed) for a multi-repo milestone; `path` is relative to the run dir or `~`-based, and inside the run dir only under `repos/` or `worktrees/` (`state.checkout_path` refuses any other) |
| `landedSha` | the landing commit: a string, or `{<repo>: <sha>}` for several repos |
| `shippedAt` | date it landed |
| `covers` | the requirements it covers |
| `open` | open questions while it is a draft |
| `note` | free text, shown on the card |
| `stories` | list of stories |
| `quality` | `{contract: [{cmd, ok, at}], gate: {findings, fixed, skipped, note, file} or null, criteria: [{text, pass}]}` |
| `artifacts` | `[{name, path, phase}]` documents shown when the milestone opens on the map |
| `domainStories` | `{status, at, stories: [{title, path, spec}]}` |
| `asana` | see Asana |

### Stories

| Key | Meaning |
|---|---|
| `id`, `title`, `summary` | |
| `status` | `todo`, `working`, `approval`, `done`, `failed`, `blocked` |
| `deps` | story ids that must be done first |
| `overlapAfter` | story ids to wait for because they touch the same files |
| `files` | files it is expected to touch: repo-prefixed paths or globs (`{a,b}` alternatives, `*` within a segment, `**` across segments). The Podium compares them for its conflict radar, see below |
| `repos` | list of repo names it touches |
| `model`, `attempts`, `startedAt`, `finishedAt` | `startedAt` restarts with each attempt; the Podium adds the stories' durations up as a milestone's agent time, from the first start to the last finish as its wall-clock time |
| `worktrees` | `{<repo>: <path>}`, the story's checkouts, relative to the run dir, `~`-based or absolute. `GET /cost` counts the tokens of this machine's Claude Code sessions whose cwd is in one |
| `branch`, `brief` | its branch and its brief (`podium/stories/<milestone>/<id>.md`) |
| `agent` | `{backend, id}` of the agent building it; with `backend` `agent`, an Agent-tool subagent, `GET /cost` also counts its log `~/.claude/projects/*/<session>/subagents/agent-<id>.jsonl` |
| `commits` | `[{sha, subject, plus, minus}]` |
| `failure` | why it failed |

The conflict radar compares the `files` of unfinished stories (not `done` or `dropped`). Across milestones it takes those that are active, `working` or a `todo`/`draft` milestone with stories, and skips a pair where one milestone lists the other in `deps` or `waitsFor`; within a milestone it takes stories in the same wave, so a story never clashes with one it waits for through `deps` or `overlapAfter`. Two patterns clash when some path could match both; other glob syntax (`?`, `[id]`) is read literally.

Setting a story to `failed` sets every story that depends on it, directly or through others, to `blocked`. `podium ready` lists `todo` stories whose `deps` and `overlapAfter` are all `done`, leaving out stories handed off to a session of the user's own (`handoffs.json`).

### Assumptions

`{at, milestone, story?, question, choice, why, short?, status}` with `status` `open`, `confirmed` or `reversed`. `podium assume` appends, `podium settle <n> <confirmed|reversed>` settles. Numbers are list indexes: `<n>` for your own, `t<n>` for the top-level ones of a run from before `people`.

### Decisions

`{id, epic, question, type, affects, blockedBy, status, owner?, outcome?, missing?, at}`: a question touching two or more milestones of an epic, settled with the user before the epic's milestone cut; a milestone's brief names the ones it rests on as `D<n>`. `id` is `D<n>`, numbered across the run; `type` is `discussion` (a grill with the user), `research`, `prototype` or `unblock` (access, setup or evidence, never product code); `affects` lists free-text areas or milestone ids; `blockedBy` lists decision ids. `status` is `open`, `resolved`, `out-of-scope` or `invalidated`; `outcome` is the resolution, or why it was ruled out or invalidated. `owner` is the claim, a person's `me` as on a milestone (`podium decision claim`, refused while someone else holds it unless `--force`). `missing` is what `podium decision unresolved` found lacking: the decision stays open and keeps its owner; closing it clears `missing`. `podium decision add` refuses a 7th open decision on one epic unless `--force`.

The frontier is the open decisions nobody claimed whose `blockedBy` are all closed (an unknown id counts as closed). An epic's state is `ACTIVE` with a frontier, else `WAITING` while one is claimed, else `BLOCKED` while one is open, else `CLEAR`. The Podium shows a strip above each epic's milestones with its open decisions, frontier first, each with its type, owner, "blocked by" its open blockers, `missing` and the milestones it affects, and the count of closed ones; an epic with none has no strip.

### orchestrator

```json
{"name": "my-skill", "command": "/my-skill", "extension": "~/skills/my-skill/podium_ext.py",
 "phases": ["recon", "spec", "build", "land"],
 "stages": {"REVIEW": {"doing": "reviewing", "step": 2, "time": "review"}}}
```

`extension` is a `.py` file, this machine's own once set (a pull never changes it; see `PROTOCOL.md`, Sync): `~` expands, a relative path is relative to `podium/` (`podium init` rewrites one typed relative to the cwd). `phases` replaces the default stepper: names, or `[name, label]` pairs. `maxAttempts` is the attempts a story gets, shown as `attempts of max` on a failed story (default 2). `stages` adds progress stages to the defaults, see Progress files. `podium init` writes this block. A run without it supports the core commands only. See `PROTOCOL.md` for what the extension does.

### sync

`{enabled, remote, ref, include, exclude}`, all this machine's own: never pushed, never taken from a pull. `include` and `exclude` are globs relative to the run dir; each one unset falls back to this machine's `sync.json`, else to the built-in lists: the state files plus `*.md`, `**/*.md`, `spec/**`, `mock/**`, `domain-stories/**`, and no exclude. See `PROTOCOL.md`.

### Collaboration

`people.<me>` holds `active`, `needsYou` and `assumptions` for one person; each person writes only their own key. A run has per-person state when sync is on or `people` exists; otherwise those three keys sit at the top level. Reads prefer `people.<me>` and fall back to the top level.

`me` is `$PODIUM_ME`, else the name set by `podium whoami <name>`, else the local part of `git config user.email`, else `$USER`.

`milestones[].owner` is a person's `me`. `podium claim` and `podium release` change it; `require_owner` enforces it.

### Asana

`asana` on a project, epic or milestone: `{kind: "project"|"task", gid, url, assignee, fields, completed, syncedAt}`. Written by `podium asana link` and `podium asana refresh`. Every link stores its `gid`, 1 to 32 ASCII digits (refresh skips any other as `ASANA-ERROR <target>: not an Asana id`), which refresh reads (a link from before `gid` is read from its `url`). `link` writes only `{kind, gid, url}`; the first refresh fills in the rest, and `assignee` is a project's owner. Keys a run added to the object, such as `keep`, survive a refresh and a relink to the same `gid`; a relink to another `gid` starts over.

## events.jsonl

One JSON object per line, appended in time order: `{"at": "<ISO time>", "type": "<type>", "milestone": "M2", "story": "S4", ...}`. `milestone` and `story` are present when the event concerns one. `by` holds `me` and is added in runs with per-person state.

`podium set <target> ... --event TYPE key=value` appends one, filling `at`, `milestone` and `story` from the target. Core commands write `assumed`, `settled`, `owner` (`owner` is null on release), `handover` (`from`, `to`), `moved` (`to`, `pattern`), `decision` (`decision`, `epic`, `kind`, `question`), `decision-claimed` (`decision`, `owner`, `from` on a takeover), `decision-closed` (`decision`, `status`, `outcome`), `decision-unresolved` (`decision`, `missing`), `reviewed` (`number`, `repo`, `state`, `owner`: the server writes it when someone ticks Looked at it on a colleague's draft PR) and `asana` (`text`, the line the command printed: written on `asana link` and for each change an `asana refresh` reports). The rest are the orchestrator's vocabulary; the Podium draws a timeline from these:

`planned`, `grilled`, `phase` (`phase`), `status` (`text`), `dispatched` (`backend`, `model`), `commit` (`sha`, `subject`), `merged` (`into`, `wave`), `conflict`, `retry` (`attempt`, `reason`), `failed` (`reason`), `approval` (`tool`), `landed` (`sha`, `repo`, `subject`).

An event is major, and saves the run when sync is on, if its type is `status`, `grilled`, `failed`, `landed`, `settled`, `owner`, `moved`, `decision` or `decision-closed`, a `phase` of `spec`, `architecture` or `build`, or a `merged` with `wave: true`. An extension can replace this rule with `SYNC_MAJOR`, except for `finding`, `finding-resolved` and `reviewed`, which always save. A run also saves when a command changes which documents it uploads: the references of your own milestones, plus the epics' specs and artifacts and the quest doc (a milestone's or story's `brief`, `spec`, `archive` or `artifacts`; an epic's `spec` or `artifacts`; the quest's `doc`), with no event needed, and the watcher saves when one of those documents changed on disk since the last save here.

## Progress files

`stories/<milestone>/<story>.progress`, one line per step, appended by `podium log`, which refuses a milestone or story id that isn't 1 to 32 letters, digits, `_` or `-` (`state.valid_id`):

```
2026-10-08T13:47:32+00:00 RED 8 failing tests in roles/can.spec.ts
```

The line is `<ISO time> <STAGE> <note>`. Default stages: `STARTED RED GREEN REFACTOR FIX CONTRACT COMMITTED FAILED`. `orchestrator.stages` adds more, or changes how a default shows: `{STAGE: {doing, step, time}}` where `doing` is the label while the story is in that stage, `step` (0 to 3) its position in the story's progress bar, and `time` the row it counts toward in the timing view.

The watcher prints only `COMMITTED` and `FAILED` lines. A story's brief sits beside its progress file as `<story>.md`.

## gates.jsonl

A contract run's history: `gates.sh <dir> --logs <logs dir>` appends one line per gate it runs to `<logs dir>/gates.jsonl`, beside the per-gate logs it overwrites, and never rewrites or clears it:

```
{"at": "2026-11-17T09:12:03Z", "gate": "test", "ok": false, "secs": 41, "sha": "4f1c2e9…"}
```

`at` is when the gate finished, in UTC; `gate` its name as `PASS`/`FAIL` prints it; `ok` whether it passed; `secs` how long it took in whole seconds; `sha` the checkout's `git rev-parse HEAD`, or null outside a commit. A failed write is skipped and changes neither the gate's result nor the exit code.

The server's `GET /gates` reads every `gates.jsonl` up to three folders below the run dir, none in `worktrees/`, `repos/`, `node_modules/`, `.git/` or `podium/`, so a feature-plan run's `contract-<repo>.logs/<label>/` and a deep-plan run's `contract.logs/` both count. A gate is flaky in a logs folder when a run of it failed and a later run there passed on the same sha; a run without a sha never counts. It answers `{"gates": [{"name", "logs", "flips", "last", "runs", "fails"}]}`, latest flip first: `logs` the folder relative to the run dir, `flips` how many failures were followed by a pass on their sha, `last` the `at` of the latest such pass, `runs` and `fails` every run of the gate in that folder. Each file is read again only once its mtime or size changes.

## requests.jsonl

The server appends one line per button press: `{"action": "assign", "story": "M2/S6", "at": "<ISO time>"}`, plus `"note"` for `confirm` and `reverse` answers and for Asana links. `story` is the target id whatever the action: a milestone, a story, an epic, assumption numbers (`0,2`), or null. `podium requests` and the watcher read it; neither edits it.

## handoffs.json

`{"M2/S6": {"at": "<ISO time>"}}`: stories the user took to a session of their own. The server is its only writer. `podium ready` skips these stories.

## cursor.json

`{"requestsSeen": <byte offset>}`: how far into `requests.jsonl` this machine has read. An older run kept it in `podium.json` as `requestsSeen`; it moves here on first read.

## synced.json

`{include, exclude}`: the lists this machine's last save or pull used. When the lists widen, the next save or pull first writes the files they now cover from the last synced tree, so a file this machine never had is not taken for one it deleted.

## watcher.json

The watcher's heartbeat, rewritten every few seconds: `{pid, at, offsets, seen, mode, since, waiting, idle, warned}`; `seen` holds each progress file's inode and digests of the lines the watcher handled, `warned` the document paths it printed `UNSYNCED` for. The server accepts orchestrator requests only while `at` is under 30 seconds old.

## sync.json

`~/.podium/sync.json`, beside `human.json`: `{include, exclude}`, this machine's default for each list a run's `sync` block leaves unset. Written by `podium sync defaults`; never in a run dir, never synced.

## human.json

`~/.podium/human.json` (or `$PODIUM_HUMAN`): `{hours: {days, from, to}, mode, until, at, me}`. The user's working hours (default `Mon-Fri 07:00-17:00`), the toggle's override (`mode` available, mobile or unavailable until `until`), and `me`. One per machine, shared by every run, never synced.
