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
| planning docs (`*.md`, `domain-stories/**`, ...) | orchestrator | only to and from a machine whose own `sync.include` lists them |
| `requests.jsonl` | the server | never |
| `cursor.json` | `podium requests` | never |
| `watcher.json` | `podium watch` | never |
| `server.log` | `podium server --detach` | never |
| `synced.json` | `podium sync` | never |
| `~/.podium/human.json` | `podium hours`, `whoami`, the Podium toggle | outside any run; one per machine |

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
  "dispatcher": "paseo",
  "repoUrl": "https://github.com/example/acme",
  "updatedAt": "2026-10-08T15:14:32+00:00"
}
```

### Top level

| Key | Meaning |
|---|---|
| `project` | `title`, `summary`; `asana` when linked; `quest` when an orchestrator shows a research quest |
| `epics` | list of epics, see below |
| `active` | `{epic, milestone}`: the milestone `milestone:` and a bare story id refer to |
| `needsYou` | `{reason, story?}` or null: what is waiting for the user |
| `assumptions` | answers an agent assumed while the user was away, see below |
| `people` | per-person state, see Collaboration |
| `orchestrator` | the extension block, see below |
| `sync` | git sync, see below |
| `dispatcher` | free text shown in the header (`paseo`, `claude`, ...) |
| `repoUrl` | the project's repository URL, for links in a single-repo run |
| `updatedAt` | stamped on every write |

### Epics

`id`, `title`, `summary`, `spec` (path to its brief), `milestones[]`, and optionally `asana` and `branch`.

### Milestones

| Key | Meaning |
|---|---|
| `id`, `title`, `summary` | |
| `status` | `draft`, `later`, `parked`, `todo`, `working`, `done`, `dropped` |
| `phase` | the stepper position, one of `orchestrator.phases` (default `recon spec mock architecture stories build gate verify land`) |
| `deps` | milestone ids that must be done first |
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
| `artifacts` | `[{name, path, phase}]` documents shown in the drill-down |
| `domainStories` | `{status, at, stories: [{title, path, spec}]}` |
| `asana` | see Asana |

### Stories

| Key | Meaning |
|---|---|
| `id`, `title`, `summary` | |
| `status` | `todo`, `working`, `approval`, `done`, `failed`, `blocked` |
| `deps` | story ids that must be done first |
| `overlapAfter` | story ids to wait for because they touch the same files |
| `files` | files it is expected to touch |
| `repos` | list of repo names it touches |
| `model`, `attempts`, `startedAt`, `finishedAt` | |
| `branch`, `brief` | its branch and its brief (`podium/stories/<milestone>/<id>.md`) |
| `agent` | `{backend, id}` of the agent building it |
| `commits` | `[{sha, subject, plus, minus}]` |
| `failure` | why it failed |

Setting a story to `failed` sets every story that depends on it, directly or through others, to `blocked`. `podium ready` lists `todo` stories whose `deps` and `overlapAfter` are all `done`, leaving out stories handed off to a session of the user's own (`handoffs.json`).

### Assumptions

`{at, milestone, story?, question, choice, why, short?, status}` with `status` `open`, `confirmed` or `reversed`. `podium assume` appends, `podium settle <n> <confirmed|reversed>` settles. Numbers are list indexes: `<n>` for your own, `t<n>` for the top-level ones of a run from before `people`.

### orchestrator

```json
{"name": "my-skill", "command": "/my-skill", "extension": "~/skills/my-skill/podium_ext.py",
 "phases": ["recon", "spec", "build", "land"],
 "stages": {"REVIEW": {"doing": "reviewing", "step": 2, "time": "review"}}}
```

`extension` is a `.py` file, this machine's own once set (a pull never changes it; see `PROTOCOL.md`, Sync): `~` expands, a relative path is relative to `podium/` (`podium init` rewrites one typed relative to the cwd). `phases` replaces the default stepper: names, or `[name, label]` pairs. `maxAttempts` is the attempts a story gets, shown as `attempts of max` on a failed story (default 2). `stages` adds progress stages to the defaults, see Progress files. `podium init` writes this block. A run without it supports the core commands only. See `PROTOCOL.md` for what the extension does.

### sync

`{enabled, remote, ref, include, exclude}`, all this machine's own: never pushed, never taken from a pull. `include` and `exclude` are globs relative to the run dir; `include` defaults to `podium.json`, `events.jsonl`, `handoffs.json`, `stories/**`. To share planning docs, every machine adds the same globs. See `PROTOCOL.md`.

### Collaboration

`people.<me>` holds `active`, `needsYou` and `assumptions` for one person; each person writes only their own key. A run has per-person state when sync is on or `people` exists; otherwise those three keys sit at the top level. Reads prefer `people.<me>` and fall back to the top level.

`me` is `$PODIUM_ME`, else the name set by `podium whoami <name>`, else the local part of `git config user.email`, else `$USER`.

`milestones[].owner` is a person's `me`. `podium claim` and `podium release` change it; `require_owner` enforces it.

### Asana

`asana` on a project, epic or milestone: `{kind: "project"|"task", gid, url, assignee, fields, completed, syncedAt}`. Written by `podium asana link` and `podium asana refresh`. Every link stores its `gid`, 1 to 32 ASCII digits (refresh skips any other as `ASANA-ERROR <target>: not an Asana id`), which refresh reads (a link from before `gid` is read from its `url`). `link` writes only `{kind, gid, url}`; the first refresh fills in the rest, and `assignee` is a project's owner. Keys a run added to the object, such as `keep`, survive a refresh and a relink to the same `gid`; a relink to another `gid` starts over.

## events.jsonl

One JSON object per line, appended in time order: `{"at": "<ISO time>", "type": "<type>", "milestone": "M2", "story": "S4", ...}`. `milestone` and `story` are present when the event concerns one. `by` holds `me` and is added in runs with per-person state.

`podium set <target> ... --event TYPE key=value` appends one, filling `at`, `milestone` and `story` from the target. Core commands write `assumed`, `settled`, `owner` (`owner` is null on release), `handover` (`from`, `to`) and `asana` (`text`, the line the command printed: written on `asana link` and for each change an `asana refresh` reports). The rest are the orchestrator's vocabulary; the Podium draws a timeline from these:

`planned`, `grilled`, `phase` (`phase`), `status` (`text`), `dispatched` (`backend`, `model`), `commit` (`sha`, `subject`), `merged` (`into`, `wave`), `conflict`, `retry` (`attempt`, `reason`), `failed` (`reason`), `approval` (`tool`), `landed` (`sha`, `repo`, `subject`).

An event is major, and saves the run when sync is on, if its type is `status`, `grilled`, `failed`, `landed`, `settled` or `owner`, a `phase` of `spec`, `architecture` or `build`, or a `merged` with `wave: true`. An extension can replace this rule with `SYNC_MAJOR`.

## Progress files

`stories/<milestone>/<story>.progress`, one line per step, appended by `podium log`, which refuses a milestone or story id that isn't 1 to 32 letters, digits, `_` or `-` (`state.valid_id`):

```
2026-10-08T13:47:32+00:00 RED 8 failing tests in roles/can.spec.ts
```

The line is `<ISO time> <STAGE> <note>`. Default stages: `STARTED RED GREEN REFACTOR FIX CONTRACT COMMITTED FAILED`. `orchestrator.stages` adds more, or changes how a default shows: `{STAGE: {doing, step, time}}` where `doing` is the label while the story is in that stage, `step` (0 to 3) its position in the story's progress bar, and `time` the row it counts toward in the timing view.

The watcher prints only `COMMITTED` and `FAILED` lines. A story's brief sits beside its progress file as `<story>.md`.

## requests.jsonl

The server appends one line per button press: `{"action": "assign", "story": "M2/S6", "at": "<ISO time>"}`, plus `"note"` for `confirm` and `reverse` answers and for Asana links. `story` is the target id whatever the action: a milestone, a story, an epic, assumption numbers (`0,2`), or null. `podium requests` and the watcher read it; neither edits it.

## handoffs.json

`{"M2/S6": {"at": "<ISO time>"}}`: stories the user took to a session of their own. The server is its only writer. `podium ready` skips these stories.

## cursor.json

`{"requestsSeen": <byte offset>}`: how far into `requests.jsonl` this machine has read. An older run kept it in `podium.json` as `requestsSeen`; it moves here on first read.

## synced.json

`{include, exclude}`: the lists this machine's last save or pull used. When the lists widen, the next save or pull first writes the files they now cover from the last synced tree, so a file this machine never had is not taken for one it deleted.

## watcher.json

The watcher's heartbeat, rewritten every few seconds: `{pid, at, offsets, seen, mode, since, waiting, idle}`; `seen` holds each progress file's inode and digests of the lines the watcher handled. The server accepts orchestrator requests only while `at` is under 30 seconds old.

## human.json

`~/.podium/human.json` (or `$PODIUM_HUMAN`): `{hours: {days, from, to}, mode, until, at, me}`. The user's working hours (default `Mon-Fri 07:00-17:00`), the toggle's override (`mode` available, mobile or unavailable until `until`), and `me`. One per machine, shared by every run, never synced.
