# Protocol

How an orchestrator plugs into Podium, what the HTTP server and the watcher say, and how sync merges. `SCHEMA.md` lists the files.

## Extension

An orchestrator is a Python file named by `podium.json`'s `orchestrator.extension`. Register it with:

```
podium init --name my-skill --command /my-skill --extension ~/skills/my-skill/ext.py [--phases a,b,c]
```

`init` creates `podium/podium.json` when the run has none, and otherwise updates only the `orchestrator` block. `examples/minimal_extension.py` is a complete small one.

The tool loads the file with `importlib.util.spec_from_file_location`, registered as `sys.modules["podium_extension"]`. Only a `.py` file loads; it may live anywhere, the run dir included, since sync never writes one. When the file is missing, is not a `.py` file, or raises on import, core commands keep working and an extension verb prints `podium: extension <path> not loadable: <why>` and exits 2. A core verb always wins over an extension verb of the same name.

The module may define any of these:

| Name | Meaning |
|---|---|
| `COMMANDS` | `{verb: fn(p, args)}`: `podium <verb> ...` calls `fn` with a `Podium` and the remaining arguments. The first line of the docstring appears in `podium --help`. |
| `ACTIONS` | A set of extra request actions the server accepts. The core's are `assign plan build-all stop confirm reverse domain-story claim proceed share`. |
| `prompt(p, kind, target_id)` | Returns the text for the server's prompt endpoints, or None. |
| `on_asana_refresh(p, task_json)` | Called for each linked Asana task a refresh re-reads, before it writes the generic fields; never for a project. Runs from `podium asana refresh` and when an extension calls `asana.refresh(p)`, for example in `turn`. `task_json["subtasks"]` holds the subtasks of a task read on its own and is absent for an epic's subtask taken from its parent's list. |
| `SYNC_MAJOR(event)` | Returns whether an event saves the run when sync is on. Replaces the default rule. |
| `SHARE_STEPS` | A list of non-empty strings: the steps a colleague takes to join the run, listed by the Share button's tooltip, with `{ref}` and `{remote}` replaced by the run's `sync.ref` and `sync.remote` (`<ref>` and `<remote>` while unset). Without it the tooltip lists the generic steps: install this tool, install the `<orchestrator.name>` skill, run `<orchestrator.command> join <ref>` in a new empty folder, claim a milestone. |

### prompt kinds

| `kind` | `target_id` | Used by | Without the hook |
|---|---|---|---|
| `plan` | milestone id | `GET /prompt/plan/<id>` | `<orchestrator.command> <id>` |
| `assign` | `<milestone>/<story>` | `GET /prompt/assign/<id>` | 501 |
| `handoff` | `<milestone>/<story>` | `POST /handoff/<id>` | 501 |

`handoff` is the story prompt plus whatever set-up a person's own session needs, such as a worktree. Returning None for `plan` falls back to the command; for the others it answers 404.

### Importing the tool

```python
from podium_dashboard.commands import require_owner
from podium_dashboard.state import Podium, rebase, parse_value, assign, pairs, NOW
```

`podium_dashboard.state` exports: `ACT_ON DAYS HOURS HUMAN_FILE NOW Podium STAGES WATCHER_LIVE assign availability building day_set find_run http human_hours human_line human_state in_hours local me next_change pairs parse_value person_of podium_dir podium_url queued_requests rebase requests_seen set_requests_seen watcher_running watcher_span write_human`. `podium_dashboard.commands` holds the core verbs (`cmd_*`), `require_owner` and `claim_milestone`.

`Podium(run_dir)` reads `podium.json`. The methods an extension needs:

| | |
|---|---|
| `p.data`, `p.dir`, `p.root`, `p.repo` | the parsed file, the `podium/` folder, the run dir, the folder holding the run dir |
| `p.save()`, `p.refresh()` | write this command's changes onto the file as it is now; catch up with other commands' writes |
| `p.locked()` | the run's re-entrant lock, held for a read-modify-write of run files |
| `p.event(type, milestone, story, **fields)` | append to `events.jsonl`; adds `by` in a per-person run |
| `p.milestones()`, `p.milestone(id)`, `p.story(id, milestone)` | lookups; they exit on an unknown id |
| `p.ready(m)` | ready story ids of milestone `m` |
| `p.me`, `p.active()`, `p.needs_you()`, `p.assumptions_list()` | this person's state; read the active milestone through `p.active()`, not `p.data["active"]` |
| `p.synced()` | whether sync is enabled |

Write personal keys with `podium set me ...` or `podium set . ...`, which write to `people.<me>` in a per-person run. Helpers that need git (checkouts, landed commits) belong to the extension.

Read several stories or milestones with one `podium ls stories|milestones [--milestone M] [--fields a,b]` instead of a `get` each: one line per item, `<id> <status> [key=value ...]`, read-only.

### require_owner

`require_owner(p, milestone_id, force=False, claim=True)` exits 1 with `milestone <id> is owned by <who>` when someone else owns the milestone. In a synced run, a milestone nobody owns is claimed for you (pull, set owner, `owner` event, save and push) and the call goes on; if the push loses a race to another claim, it exits 1. In a run that does not sync it passes when nobody owns the milestone. `force=True` skips the check. `claim=False` lets an unowned milestone pass without claiming it, for bookkeeping that records what already happened.

Every verb that changes a milestone should call it and accept `--force`.

## HTTP API

`podium server [--dir D] [--port 8765] [--idle 60] [--detach] [--git-every 5]` serves the page and the run on `127.0.0.1`, on the first free port from `--port`. It stops after `--idle` minutes without use (0 never).

Every request must carry a `Host` of `127.0.0.1:<port>` or `localhost:<port>`; any other answers 403 (DNS rebinding). Any request but a GET or HEAD with an `Origin` header must have `http://127.0.0.1:<port>` or `http://localhost:<port>`; any other answers 403 (cross-site forms), `null` included. Without an `Origin` (curl) it passes. Only a POST, a DELETE, or a GET from the page's visible tab with no foreign `Origin` counts as use; a HEAD or an OPTIONS never does.

Everything but the page itself (`/`, `/index.html`, `/podium.html`) carries `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups`: a synced HTML file opened from `/podium/...` or `/repo/...` runs in an origin of its own, and its POSTs, `Origin: null`, are refused. The page carries `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`: it loads and fetches only from this server, and links only `http:` and `https:` URLs from the run's state.

| Request | Answer |
|---|---|
| `GET /` | the page |
| `GET /info` | `{runDir, repoDir, watching, orchestrator: {name, command, shareSteps}, me, people, paseoServer, lastUse, stale}`; `shareSteps` is the extension's `SHARE_STEPS` with its placeholders, else null; `people` is `{<name>: {active}}` from podium.json, and the header's avatars add everyone named in an event's `by` from `events.jsonl` |
| `GET /git` | per repo of the run, how far its branch and default branch are behind origin, refreshed every `--git-every` minutes; a checkout path inside the run dir but outside `repos/` and `worktrees/` is skipped |
| `GET /human` | the user's availability |
| `GET /prompt/plan/<milestone>`, `GET /prompt/assign/<milestone>/<story>` | `text/plain` from the extension's `prompt` |
| `GET /repo/<path>` | a file under the run's repo: the git toplevel of the run dir, else the run dir itself; the path is resolved and anything outside answers 404 |
| `GET /podium/...`, any other path | a file of the run dir, by its real path: a folder, or a file a symlink leads outside the run dir, answers 404 |
| `POST /<action>/<id>` | queue a request line, 202 `{"queued": {...}}`; `<action>` is a core action or one of `ACTIONS`; `confirm` and `reverse` take an assumption number or `all`, and `?note=` |
| `POST /build-all/<milestone>`, `POST /stop/<milestone>` | the same, per milestone |
| `POST /proceed/<milestone>` | the same: the banner's Go ahead asks to go ahead without the milestones `waitsFor` names; the watcher prints `REQUEST proceed <milestone>`, `podium requests` `LIST proceed <milestone>`, and the orchestrator sets `waitsForAck=true` and carries on, mocking what is missing; an unknown milestone answers 404 |
| `POST /share` | queue `share`, which takes no id: the page's Share button asks the orchestrator to share the run, or to print the colleague's steps again once it syncs; any id answers 404 |
| `POST /asana[/<epic>]?url=<Asana link>` | queue a link, 202; it takes any `https://app.asana.com/...` link, 400 for any other and 404 for an unknown epic. `podium asana link` later refuses a link that is not a project or task |
| `POST /asana-done/<milestone>?choice=<drop\|keep>` | queue the answer, 202 |
| `POST /handoff/<story>` | record the story in `handoffs.json` and return the `handoff` prompt; `DELETE /handoff/<story>` takes it back |
| `POST /human/<available\|mobile\|unavailable\|auto>[?until=HH:MM]` | set the availability toggle; `podium human set <mode> [--until HH:MM]` does the same from a shell, with no server, and prints the new `podium human` line |
| `POST /restart` | 202; the server starts a fresh process on the same port |

Status codes: 202 queued; 400 a malformed value; 403 Host or Origin refused; 404 an unknown action, id or file; 409 no watcher is running, for every POST except `confirm`, `reverse`, the Asana ones and `/human/`; 500 a `prompt` hook raised; 501 no extension `prompt` for `assign` or `handoff`.

A watcher counts as running while `watcher.json`'s `at` is under 30 seconds old.

## Watcher

`podium watch [--dir D] [--paseo <paseo binary>] [--once]` prints one line per thing the orchestrator must act on, and exits with a `LAPSE` line when nothing needs watching: the user is away and no story is working. It keeps `watcher.json` fresh, and a watcher started within 10 minutes of the last one carries on from where it stopped. `--once` exits after the first lines.

| Line | Meaning |
|---|---|
| `REQUEST <action> [<id>] [note=...]` | a button press from `requests.jsonl` |
| `PROGRESS <story> <progress line>` | a story's `COMMITTED` or `FAILED` line |
| `PERMISSION <story> <tool>` | a Paseo agent waits for approval (`--paseo`) |
| `PERMISSION-CLEARED <story>` | that approval was answered (`--paseo`) |
| `IDLE <story>` | a working story's Paseo agent went idle (`--paseo`) |
| `HUMAN <available\|mobile\|unavailable>` | the user's availability changed |
| `SYNCED <sha> <summary>` | a pull brought someone else's changes: their new event types by `by`, as in `ann: status×2, owner`, else the commit subject |
| `LAPSE <mode>, nothing building` | the last line |

When sync is on, the watcher pulls every 60 seconds, skipping a round while another podium command holds the lock. It pulls during a build too: the pull merges the remote's saves with the unsaved changes here (see Merge), so another person's claim arrives within a minute. Progress lines that arrive with a pull belong to the other person's stories and are not printed; a line logged here while the pull ran is. A progress file a save's merge rewrote behind the watcher is read again whole: it prints the lines it never handled, for a story of a milestone the run has, with no owner or this person, and nothing twice. A progress file that appeared since the watcher started is printed under the same rule.

`podium requests` prints the requests nobody has passed on yet, as `ACT <confirm|reverse|asana|asana-done> <id> [note=...]` (the user's answers, to act on at once) and `LIST <action> [<id>] [note=...]` (the rest; `share` has no id). It moves the cursor in `cursor.json`; lines the running watcher already printed are skipped.

## Asana

`podium asana link <url> [. | epic:<id> | milestone:<id>]` links the project (`.`, the default), an epic or a milestone to an Asana project or task. It exits 1 for anything else than a project or task link, and when another object already holds that `gid`. It prints `LINKED <target> to Asana <kind> <gid>`.

`podium asana refresh` re-reads every link over the Asana REST API with a personal access token: `$ASANA_TOKEN`, else the macOS keychain item `podium-asana`. A linked task is an epic and its subtasks are that epic's milestones. Each line below is also an `asana` event, except `ASK`.

| Line | Meaning |
|---|---|
| `NO_TOKEN` | no token; the command exits 3, even when nothing is linked |
| `ASANA nothing linked` | no object has an `asana` link |
| `ASANA <n> tasks read, no changes` | |
| `ASANA <label> <key> <value>, ...` (label `epic <id>`, `project` or a milestone id) | `url`, `assignee`, `completed` or `fields` changed since the last refresh |
| `LINKED <milestone> to subtask "<name>"` | a new subtask matched one unlinked milestone of the epic, by title or id |
| `NEW <milestone> <draft\|done> "<title>" in <epic>` | a new subtask with no unlinked milestone to take it became one |
| `ASK <subtask gid> "<name>" → <milestone ids> new` | only the user can place the subtask: one of the candidates, or a new milestone |
| `COMPLETED <milestone> in Asana, not landed: the Podium asks Done?` | the subtask was completed and its milestone is not `done` or `dropped` |
| `ASANA-ERROR <gid>: <why>` | a read failed; the command exits 1. `ASANA-ERROR <target>: not an Asana id` is a link whose gid is not 1 to 32 ASCII digits, skipped unread (`<target>` is `project`, `epic <id>` or the milestone id). `ASANA-ERROR <why>` is the extension failing to load |

An extension calling `asana.refresh(p)` gets the same lines as a list, `[]` when nothing is linked and `["ASANA NO_TOKEN"]` without a token, and prints and saves them itself.

## Sync

`podium sync on [--remote <name or URL>] [--ref <ref>]`, `off`, `save [message]`, `pull`, `status`, `defaults [include=<JSON list>] [exclude=<JSON list>]`. Sync is off by default.

The run state is committed with git plumbing onto a ref (default `refs/heads/podium-run/<run dir name in kebab case>`) and pushed to the remote, without touching any working tree, index or HEAD. A remote name refers to a remote of the repo the run dir sits in. A URL needs no repo: the commits live in a bare cache under `~/.podium/sync/`, one per URL, ref and run dir. Every machine must use the same ref; `podium sync status` prints it first.

Files: an include list of globs (relative to the run dir) picks them, and files an exclude list names, or the machine-local list in `SCHEMA.md` holds, never sync. Each list is, on its own, the run's `sync.include` or `sync.exclude` when set, else this machine's default in `~/.podium/sync.json` (beside `human.json`, so `$PODIUM_HUMAN` moves it), else built in: include `podium/podium.json`, `podium/events.jsonl`, `podium/handoffs.json`, `podium/stories/**` and the planning docs `*.md` and `**/*.md` (Markdown files anywhere in the run dir; `repos/**` and `worktrees/**` stay machine-local), `spec/**`, `mock/**`, `domain-stories/**`; exclude nothing. `podium sync defaults` prints this machine's default (`DEFAULTS include <JSON>|none exclude <JSON>|none`); `podium sync defaults include=<JSON list> [exclude=<JSON list>]` sets it in one write, and `include=` alone clears that list. `podium sync status` prints, after its first line, `include <JSON> (run|default|built-in) exclude <JSON> (...)`. The whole `sync` block and `sync.json` stay on their machine: a save never pushes them and a pull never takes them, so a remote that lists more files changes nothing here. A save carries the files its lists leave out as the last synced tree had them, so a machine that shares fewer files drops none of the others'; a machine whose lists widen, its own or through a new default, gets the files they now cover from that tree on its next save or pull, and narrowing them deletes nothing. `orchestrator.extension` is each machine's own too: the run carries the value its first save seeded, no save changes it after, and only the first pull or merge on a machine that has none sets it, so a joiner runs the run's extension until `podium init` registers its own. A machine that synced before the run had an extension never takes one: it runs `podium init` itself. The rest of the `orchestrator` block syncs.

Results, one line each:

- `save`: `SAVED <sha> <message>`, `SAVED <sha> <message> (not pushed: <why>)`, `UNCHANGED`, `BEHIND` (the remote has newer saves: pull), `FAILED <why>`, or `OFF`.
- `pull`: `PULLED <sha>`, `UP-TO-DATE`, `KEPT <why>` (a live watcher, or the remote out of reach), `FAILED <why>`, or `OFF`. A pull merges the remote's saves with this machine's files as they are, changes since the last save included, and never pushes: those changes stay unsaved until the next save, or, when this machine also has saves the remote lacks, go into the local merge commit the next save pushes.

With sync on, every command, core or extension, that appended a major event (see `SCHEMA.md`) saves afterwards.

### Merge

When both machines changed the run since their common save (saved or not), files merge one by one against it, and nothing is overwritten:

- `podium.json`: a three-way merge as concurrent commands do. Items with an `id` (epics, milestones, stories) pair up by id; where both sides changed one value, the local one wins. A milestone both sides gave a new owner keeps the remote's: the first claim to reach the remote wins.
- `events.jsonl` and `*.progress`: the union of their lines, ordered by `at`. A progress file of a milestone you own is yours alone: a merge or pull keeps it exactly as it is here and never takes the other side's lines, nor deletes it.
- Any other text: `git merge-file`. On a conflict the local file stays, the other side is written beside it as `<file>.remote`, or the first free `<file>.<n>.remote` (n = 2, 3, ...) when that holds an earlier conflict's other side, and a line naming both files is added to your `needsYou`. When one of those copies already holds the other side, nothing new is written. A file that exists locally but not at the common save, and arrives with other content, is handled the same way.

### Deletion

A pull deletes a local file only when it was in the last synced tree, is unchanged here, this machine's lists cover it, and the remote dropped it. Files that never synced are never deleted.

### Refs and joining

A second machine starts with an empty run dir:

```
podium --dir acme sync on --remote git@example.com:acme/podium-runs.git --ref refs/heads/podium-run/acme
podium --dir acme sync pull
```

`sync on` creates `podium/` holding only this machine's sync block. A `podium.json` that holds only an `init` skeleton (a title and an orchestrator block, no epics) counts as no local state: the pull takes the remote's run wholesale and keeps this machine's sync block.

Claim a milestone before planning it with `podium claim <milestone>`; `podium release` gives it up, `--force` takes one over and records a `handover` event. Extension verbs that change a milestone call `require_owner`, which claims an unowned one in a synced run.

### Status line

`podium sync status` prints `ref <ref> OFF`, or `ref <ref> ON <remote>, never saved here`, or `ref <ref> ON <remote>, last save <sha>` with `; changed since` when the run has changed since that save.
