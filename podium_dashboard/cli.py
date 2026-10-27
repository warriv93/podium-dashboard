"""podium [--dir <run dir>] <command> ...

The run dir is --dir, else $PODIUM_DIR, else the nearest directory at or above the cwd holding
podium/podium.json or .deep-plan/podium/podium.json. hours, human, whoami, self-update, tokens, init, sync defaults,
findings --all --remote, findings --recur, finding resolve|wontfix --remote and --version need no run.

TARGETS
    .                  the project (top level); in a run with one state per person, its
                       active and needsYou are yours (people.<you>)
    me                 your own state, people.<you>, in a run that syncs or has a `people`
                       block; the project in any other run
    epic:<id>          an epic
    milestone:<id>     a milestone; `milestone:` alone is the active one
    <story>            a story of the active milestone
    <milestone>/<story>   a story of any milestone: two can build at once

COMMANDS
    status [--all] [--milestone ID]
        Compact view: your active milestone and needsYou, each person's active
        milestone, each epic's milestone counts and owners, then the stories of
        the named milestone, else of the active one and every other milestone
        building (status working, phase build), each with its buildAll and its
        ready ones. --all lists every milestone.
    get <target>
        The target as compact JSON (a milestone without its stories).
    set <target> [key=value ...] [--event TYPE [key=value ...]]
        value is JSON when it parses, else a string; `now` is the current ISO
        time, `@file` reads JSON from a file. Dotted keys reach into objects
        (agent.id=x, repos.api.pr=@pr.json), and a number into a list
        (assumptions.0.status=x). key+=value appends to a list or adds to a
        number.
        A story set to status=failed blocks every story that depends on it,
        directly or through others. --event appends one events.jsonl line
        with `at`, `milestone` and `story` filled in from the target.
    batch
        Several `set`s in one write: stdin holds one `set` argument line per op
        (`<target> key=value ... [--event TYPE key=value ...]`, shell-quoted, a
        leading `set` allowed). Their events are appended in order after the
        write; an op that fails writes nothing. Prints `<n> sets, <n> events`.
    ready [--milestone ID]
        The active (or named) milestone's ready story ids, space-separated. A story
        the user handed off to a session of their own (handoffs.json) is never ready.
    ls stories|milestones [--milestone ID] [--fields a,b,...]
        One line per story (of the active or named milestone) or per milestone:
        `<id> <status> [deps=S1,S2] [wave=2] [repos=...]` for stories,
        `<id> <status> [phase=build] [owner=simon] [deps=M1]` for milestones; an
        empty key is left out. --fields picks the item's own keys instead, each as
        key=value (missing: `-`; a list of ids comma-joined, other nested values as
        compact JSON). Read-only.
    human [set <available|mobile|unavailable|auto> [--until HH:MM]]
        Whether the user is available, mobile or unavailable, until when, and why:
        their hours (default Mon-Fri 07:00-17:00 local time) or the Podium's
        toggle (holding until the next change of hours). Both live in
        ~/.podium/human.json ($PODIUM_HUMAN), one per machine: every run shares them.
        `human set` writes the toggle as the Podium's buttons do, until HH:MM (the
        next one) or the next change of hours, `auto` clearing it, and prints the
        same line. It needs no run and records no event.
    hours [<days> <HH:MM>-<HH:MM>]
        Print the user's hours, or set them for every run: `hours Mon-Fri 07:00-17:00`
        (days as `Mon-Fri` or `Mon,Wed,Fri-Sun`).
    whoami [<name>]
        Who you are in a shared run: $PODIUM_ME, else the name `whoami <name>` keeps
        in ~/.podium/human.json, else the local part of `git config user.email`,
        else $USER. In a run that syncs or has a `people` block, your active,
        needsYou and assumptions live in podium.json's people.<you>.
    claim <milestone> [--force]
        Make the milestone yours (milestones[].owner) with an `owner` event,
        pulling first when the run syncs, and pushing at once. Refused (exit 1)
        while someone else owns it, unless --force, which records a `handover`
        event. When another claim reached the remote first, it keeps the
        milestone and this one exits 1. In a synced run, an orchestrator verb
        that changes a milestone nobody owns claims it this way first.
    release <milestone>
        Give up your milestone; refused (exit 1) when it is someone else's.
    assume <question> <choice> <why> [--story [<milestone>/]ID] [--short TEXT]
        Record an assumption made while the user is unavailable: appends
        {at, milestone, story, question, choice, why, short, status: open} to the
        project's assumptions and an `assumed` event. The milestone is the
        story's prefix, else the active one.
    assumptions
        The open assumptions, numbered by their index in the list.
    settle <n>[,<n>...] <confirmed|reversed>
        Settle those assumptions with one write and one `settled` event.
    move <milestone> --to <target> [--pattern <slug>]
        Fold a milestone into another: sets its status to moved and movedTo to the
        target, adds it to the target's includes, and appends a `moved` event
        (`to`, `pattern`). Refused (exit 1) for an unknown milestone, the milestone
        itself, or a target already moved into it. A wait on a moved milestone
        follows movedTo to where it ends: ` · waiting for M11 (was M10)`. Prints
        `MOVED <milestone> → <target>`.
    decision add "<question>" --type <type> [--epic <id>] [--affects "a,b"] [--blocked-by D1,D2] [--force]
    decision claim <D<n>> [--force]
    decision resolve|outscope|invalidate <D<n>> "<outcome or why>" [--force]
    decision unresolved <D<n>> "<missing>" [--force]
        An epic decision: a question touching two or more milestones of an epic,
        settled before its milestone cut, in podium.json's top-level decisions.
        type is discussion (a grill with the user), research, prototype or unblock
        (access, setup, evidence; never product code). add numbers it D<n> on the
        active epic (or --epic), open, and prints `DECISION D<n> open`; a 7th open
        decision on one epic is refused (`CAP 6 open decisions on <epic>: ...`)
        unless --force. claim makes it yours as `claim` does a milestone, open ones
        only: `CLAIMED D<n>`. resolve, outscope and invalidate close it with its
        outcome (`RESOLVED`, `OUT-OF-SCOPE`, `INVALIDATED D<n>`); unresolved keeps it
        open and its owner, with what is missing: `OPEN D<n> missing: <missing>`.
        These four are refused (exit 1) on a decision someone else claimed, unless
        --force; an unclaimed one anyone may change.
        Events: decision, decision-claimed, decision-closed, decision-unresolved.
    decisions [--epic <id>] [--json]
        One line per decision, then the frontier (the open ones nobody claimed
        whose blockers are all closed) and the state:
          DECISION <id> <status> <type> <owner|-> blocked=<open blocker ids|-> — <question>
          FRONTIER D1,D4 | FRONTIER none
          STATE ACTIVE (a frontier) | WAITING (one claimed) | BLOCKED (open ones) | CLEAR
        --json prints {decisions, frontier, state}. Read-only.
    log [<milestone>/<story>] <STAGE> <note>
        Append `<ISO time> <STAGE> <note>` to the story's progress file. STAGE is
        one of STARTED RED GREEN REFACTOR FIX CONTRACT COMMITTED FAILED, or a key
        of the orchestrator's `stages` map. The story
        is the argument, else $PODIUM_MILESTONE/$PODIUM_STORY, else the cwd's
        branch story/<id>.
    requests
        Each request in requests.jsonl that no earlier call or the watcher passed on:
          ACT <confirm|reverse|asana|asana-done> <id> [note=…]   the user's answers
          LIST <action> [<id>] [note=…]                         the rest (share has no id)
        The cursor lives in podium/cursor.json, local to this machine.
    sync on [--remote <name or URL>] [--ref <ref>] | off | save [<message>] | pull | status | defaults ...
        Opt-in git sync of the run state (podium.json's `sync` block), committed
        onto <ref> (default refs/heads/podium-run/<run dir name, or the repo's for
        .deep-plan, in kebab case>; each machine must use the same) without touching a working tree,
        index or HEAD, and pushed to <remote>: a remote of the run's repo
        (default origin), or a URL, which needs no repo. By default the state
        files and the planning docs sync: Markdown files anywhere in the
        run dir, spec/, mock/ and domain-stories/. sync.include and sync.exclude globs
        (relative to the run dir) change that for one run, `sync defaults` for
        every run on this machine. The request queue, its cursor, the
        watcher's heartbeat, the server log, Python code, repos/, worktrees/
        and *.logs/ folders never sync. A document podium.json references
        (an artifact, a brief, a spec, a ledger) inside the run dir syncs
        even when no include covers it, unless excluded.
        The sync block, include and exclude too, is this machine's: a save
        never pushes it and a pull never takes it. While on, every command
        that appends a major event or changes which documents the run
        references saves on its own.
          save: SAVED <sha> <message>[ (not pushed: <why>)] | UNCHANGED | BEHIND | FAILED <why>
          pull: PULLED <sha> | UP-TO-DATE | KEPT <why> | FAILED <why>
          status: the ref and ON/OFF, then `include <JSON> (run|default|built-in)
          exclude <JSON> (...)`, each list and where it comes from
        sync defaults [include=<JSON list>] [exclude=<JSON list>]
          Print (`DEFAULTS include <JSON>|none exclude <JSON>|none`) or set this
          machine's default lists, ~/.podium/sync.json beside human.json, for
          every run without its own; `include=` alone clears one. Changing them
          acts like changing a run's lists: the next save or pull restores the
          files they now cover from the last one and deletes nothing.
        Two machines that both saved merge: podium.json as concurrent commands
        do, events and progress lines as their union; a text conflict keeps this
        machine's file, writes the other as <file>.remote, and adds to your
        needsYou. So does a local file the remote's save brings with other content.
        To join a shared run on another machine: `podium --dir <run dir> sync on
        --remote <URL> --ref <ref>` in a dir with no run yet (or only what `init`
        writes), then `sync pull`.
    asana link <url> [. | epic:<id> | milestone:<id>] | asana refresh
        link: link the project (default), an epic or a milestone to the Asana
        project or task the URL names (asana.kind). refresh: re-read every link
        over the Asana REST API with $ASANA_TOKEN, else the keychain item
        podium-asana: a line and an `asana` event per change, LINKED or NEW for
        a linked task's new subtask, `ASK <subtask gid> "<name>" → <candidates>`
        for one only you can place, COMPLETED for a milestone completed in Asana
        but not landed. The orchestrator extension's on_asana_refresh sees each
        task first. Without a token it prints NO_TOKEN and exits 3; an
        ASANA-ERROR line exits 1.
    self-update [--check] [--force]
        Update a pip install from git (direct_url.json) to its remote's HEAD:
        `UPDATED podium <old>→<new>` then `RESTART server` (a running server
        is older than the page), `OK podium <sha>` when up to date, `SKIP
        podium editable|not from git`. At most once per 6 hours per machine
        (~/.podium/update.json beside human.json); --force ignores that,
        --check prints `BEHIND podium <old>→<new>` and installs nothing. A
        network or pip failure prints `WARN podium <why>`; it always exits 0.
    finding add --key <slug> --kind retro|tokens --target <target> --title <title> --moment <evidence>
                --fix <fix> --severity high|normal [--saving <tokens/week>] [--milestone <id>]
        Record a finding: what went wrong or cost too much, under a kebab-case key reused
        when the same problem recurs. target is where its fix lands: a skill's name,
        podium, or repo:<name>. fix is one of check pointer standard delete access
        script flag brief model tool; --saving (tokens/week) only for --kind tokens.
        Appends a `finding` event and pushes the record onto
        refs/heads/findings/<run slug> (the last part of the sync ref, or of the ref the
        run would sync to when it doesn't) of the extension's FINDINGS_REMOTE,
        file findings.jsonl, merging the lines with a concurrent push's.
        Prints `FINDING <key> recorded (pushed | not pushed: <why>)`; a record not
        pushed is carried by the next push to that ref.
    finding resolve <key> --sha <sha> --repo <repo> [--remote <url>]...
    finding wontfix <key> --why <why> [--remote <url>]...
        Record that a key's fix landed, or that it will not be fixed, the same way,
        with a `finding-resolved` event: `FINDING <key> resolved <sha>|wontfix (...)`,
        one line per remote. --remote (repeatable) pushes to those remotes instead;
        outside a run it is required, and the record goes to
        refs/heads/findings/resolutions with no event.
    findings [--all] [--remote <url>]... [--open] [--json] [--recur]
        The run's findings grouped by key, from its events; --all every run's on
        the remotes (default the run's FINDINGS_REMOTE; outside a run --remote is
        required). One line per key, most runs first:
          FINDING <key> ×<runs> <open|resolved <sha>|wontfix> <kinds> <target> <severity>[ ~<saving>/wk] — <title>
        A key resolved or wontfix is open again once it recurs after that. --open
        keeps the open ones, --json prints the groups as a JSON list. --recur prints
        `RECUR <key> ×<runs> — <title>` for each open key seen in two runs or more,
        or high, at most once per 24 hours per machine (~/.podium/update.json).
    tokens [--since 7d|<ISO>] [--cwd <path>]... [--projects <dir>] [--top N] [--json]
        Where Claude Code's tokens went, from its session logs (--projects, default
        ~/.claude/projects): main sessions and their subagents, the lines since --since
        (default 7d; also 24h, 2w or an ISO time) whose cwd is under a --cwd. Prints
        `TOTAL <tokens> sessions <n>`, `MODEL <model> <tokens>`, then
        `PATTERN <kind> ×<count> ~<tokens>/wk <normalized>`, ranked by tokens per week,
        the top N (default 10) of each kind: big-output (tool results of 4000 chars or
        more, by call), repeat-command (a Bash command, its paths, shas, numbers and
        quoted strings as <path> <sha> <n> <str>, in 2 sessions or more), reread (a
        file Read in 2 sessions or more) and sequence (the same 3 consecutive tool
        calls in 2 sessions or more). Tokens are usage tokens; a tool result's are its
        characters / 4. --json prints the same as one object. Reads no run.
    init --name <name> --command </command> --extension <path to .py> [--phases a,b,c]
        Name the run's orchestrator and its extension module in podium.json's
        `orchestrator` block, creating podium/podium.json when absent.
    server ... | watch ...
        Serve the Podium for the run, or watch it.
"""
import importlib
import os
import sys

from podium_dashboard import __version__, decisions, extension, findings, sync, tokens, update
from podium_dashboard.commands import (cmd_assume, cmd_assumptions, cmd_batch, cmd_claim, cmd_get, cmd_hours, cmd_human,
                                       cmd_init, cmd_log, cmd_ls, cmd_move, cmd_ready, cmd_release, cmd_requests, cmd_set,
                                       cmd_settle, cmd_status, cmd_whoami)
from podium_dashboard.plugins import asana
from podium_dashboard.state import Podium, find_run

COMMANDS = {"status": cmd_status, "get": cmd_get, "set": cmd_set, "batch": cmd_batch, "ready": cmd_ready,
            "ls": cmd_ls, "human": cmd_human, "hours": cmd_hours, "assume": cmd_assume, "assumptions": cmd_assumptions,
            "settle": cmd_settle, "move": cmd_move, "log": cmd_log, "requests": cmd_requests, "init": cmd_init,
            "sync": sync.cmd_sync, "whoami": cmd_whoami, "claim": cmd_claim, "release": cmd_release,
            "asana": asana.cmd_asana, "self-update": update.cmd_self_update, "tokens": tokens.cmd_tokens,
            "finding": findings.cmd_finding, "findings": findings.cmd_findings, "decision": decisions.cmd_decision,
            "decisions": decisions.cmd_decisions}
SUBCOMMANDS = ("server", "watch")
NO_PODIUM = {"hours", "human", "whoami", "self-update", "tokens"}


def usage(root):
    text = __doc__
    if not root:
        return text
    p = Podium(root)
    module, why = extension.load(p)
    if why:
        return f"{text}\n{why}\n"
    verbs = extension.commands(module)
    if not verbs:
        return text
    name = (p.data.get("orchestrator") or {}).get("name") or "extension"
    lines = [f"    {verb}" + (f"\n        {fn.__doc__.strip().splitlines()[0]}" if fn.__doc__ and fn.__doc__.strip() else "")
             for verb, fn in sorted(verbs.items())]
    return f"{text}\n{name.upper()} COMMANDS ({extension.path_of(p)})\n" + "\n".join(lines) + "\n"


def subcommand(name):
    try:
        module = importlib.import_module(f"podium_dashboard.{name}")
    except ModuleNotFoundError as e:
        if e.name != f"podium_dashboard.{name}":
            raise
        fail(f"podium {name} is not available in this install")
    return module.main


def fail(message):
    print(f"podium: {message}", file=sys.stderr)
    sys.exit(2)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    root = None
    while argv[:1] in (["--dir"], ["--version"]):
        if argv[0] == "--version":
            print(f"podium {__version__}")
            return
        if len(argv) < 2:
            fail("--dir needs a run dir")
        root, argv = argv[1], argv[2:]
    root = root or os.environ.get("PODIUM_DIR") or find_run(os.getcwd())
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage(root), end="")
        return
    verb, args = argv[0], argv[1:]
    if verb in SUBCOMMANDS:
        return subcommand(verb)((["--dir", root] if root else []) + args)
    if verb in NO_PODIUM or argv[:2] == ["sync", "defaults"] or (verb in ("finding", "findings") and not root):
        COMMANDS[verb](None, args)
        return
    if not root and verb != "init":
        fail("no run dir at or above here: pass --dir <run dir>, or set PODIUM_DIR")
    p = Podium(root or os.curdir)
    if verb in COMMANDS:
        COMMANDS[verb](p, args)
        sync.autosave(p)
        return
    module, why = extension.load(p)
    if why:
        fail(why)
    command = extension.commands(module).get(verb)
    if not command:
        fail(f"unknown command {verb!r}; `podium` lists them")
    command(p, args)
    sync.autosave(p)

