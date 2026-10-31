# podium-dashboard

Podium is a live localhost dashboard and a run-state CLI for feature work that agents build in parallel. A run is a folder of JSON and text files (epics, milestones, stories, events, progress lines); `podium` reads and changes it, and the dashboard shows it. Python 3.9 or later, standard library only. It grew out of Claude Code orchestration skills, but nothing in it depends on them.

![The Podium dashboard](docs/podium.png)

[`docs/podium-deck.pptx`](docs/podium-deck.pptx) is a 16-slide talk on Podium and the [deep-skills](https://github.com/warriv93/deep-skills) suite that drives it: many agents building in parallel from one plan, the suite as a layer cake, the ideas it borrows, the loop caps and model routing that keep them cheap, the quality gates, and what it has shipped so far. [`docs/podium-deck.js`](docs/podium-deck.js) builds it with pptxgenjs.

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
| `requests` | the button presses nobody has handled yet |
| `server`, `watch` | the dashboard, and the watcher an orchestrator listens to |
| `init` | name the run's orchestrator and its extension |

A milestone may wait for another without being held back: its `waitsFor` puts a "Waiting for M10" pill and a banner on the dashboard, whose Go ahead queues a `proceed` request, and `status` appends ` · waiting for M10` (see `docs/SCHEMA.md`).

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

Every side sheet has a **Copy link** button left of its close button: the link (`http://127.0.0.1:8765/open?run=<run slug>#/M24`, or `#/M2/S8`, or `#/M24/doc/spec/m24/spec.md`) opens the same sheet in a colleague's own Podium. Port 8765 is where a Podium starts, and any Podium there sends the link on to the server of that run on the colleague's machine, whatever port it took; with no Podium running on 8765-8784 the browser can't connect, and one that doesn't serve the run answers a page with `podium server --detach` to start it in their checkout.

The **Hide finished** button in the map header drops finished milestones from the milestone map and merged or dropped stories from a milestone's story map (a finished item that is open or needs you stays); the choice is kept in the browser under `podium-hide-finished`.

Beside it, a run with two or more people shows one avatar each (everyone in `podium.json`'s `people` or the `by` of an event; yours has a ring; past five people it shows four and a `+N` chip). A green dot means an event of theirs is under 15 minutes old: recent activity, not live presence. The tooltip names the milestones they own, the one they're on with its phase, and when they were last active.

## Security

The server binds to `127.0.0.1` only and refuses any request whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>`. Any request but a GET or HEAD from a page with another `Origin` is refused too. There is no login: anyone with a shell on your machine can reach it, so do not forward the port.

## Trust model

Sharing a run through `podium sync` means trusting everyone who can push to its remote: what they write, such as story briefs and the prompts built from the run's state, becomes instructions for your agents.

What a pull never does: run code. The extension is a `.py` file each machine sets itself (a machine takes the run's only on its first join, and never again); Python files and native modules never sync; the orchestrator skills run a contract command from synced state only after you `podium approve` it. A pull writes only the run's files that this machine's own include and exclude lists carry, inside the run dir and never through a symlink, and never touches the progress of milestones you own.

What it accepts: a repo path in `podium.json` may point at any repo on disk, and git runs there (always with `safe.bareRepository=explicit`). The dashboard sets no frame policy, so another site may frame it, and a click inside that frame is a click on the dashboard.

What `podium server --lan` exposes: the dashboard on your network, for a browser on another machine. Anyone holding its printed `lan` URL can read the run and press every button, as you can at 127.0.0.1. The key is in that URL and, once opened, in the browser's cookie for it; it is new each time the server starts (a restart keeps it). Without the key a LAN request gets 403, and the network sees the key in clear, as it is plain HTTP: use it on a network you trust.

## License

MIT, see [LICENSE](LICENSE).
