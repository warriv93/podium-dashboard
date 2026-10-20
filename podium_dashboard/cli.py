"""podium [--dir <run dir>] <command> ...

The run dir is --dir, else $PODIUM_DIR, else the nearest directory at or above the cwd holding
podium/podium.json or .deep-plan/podium/podium.json. hours, human, whoami, init and --version need no run.

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
    human
        Whether the user is available, mobile or unavailable, until when, and why:
        their hours (default Mon-Fri 07:00-17:00 local time) or the Podium's
        toggle (holding until the next change of hours). Both live in
        ~/.podium/human.json ($PODIUM_HUMAN), one per machine: every run shares them.
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
        milestone and this one exits 1.
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
    log [<milestone>/<story>] <STAGE> <note>
        Append `<ISO time> <STAGE> <note>` to the story's progress file. The story
        is the argument, else $PODIUM_MILESTONE/$PODIUM_STORY, else the cwd's
        branch story/<id>.
    requests
        Each request in requests.jsonl that no earlier call or the watcher passed on:
          ACT <confirm|reverse|asana|asana-done> <id> [note=…]   the user's answers
          LIST <action> <id> [note=…]                           the rest
        The cursor lives in podium/cursor.json, local to this machine.
    sync on [--remote <name or URL>] [--ref <ref>] | off | save [<message>] | pull | status
        Opt-in git sync of the run state (podium.json's `sync` block), committed
        onto <ref> (default refs/heads/podium) without touching a working tree,
        index or HEAD, and pushed to <remote>: a remote of the run's repo
        (default origin), or a URL, which needs no repo. sync.include globs
        (relative to the run dir) pick the files; the request queue, its
        cursor, the watcher's heartbeat and the server log never sync.
        sync.include and sync.exclude travel with the run; enabled, remote and
        ref are this machine's. While on, every command that appends a major
        event saves on its own.
          save: SAVED <sha> <message>[ (not pushed: <why>)] | UNCHANGED | BEHIND | FAILED <why>
          pull: PULLED <sha> | UP-TO-DATE | KEPT <why> | FAILED <why>
        Two machines that both saved merge: podium.json as concurrent commands
        do, events and progress lines as their union; a text conflict keeps this
        machine's file, writes the other as <file>.remote, and sets needsYou.
    init --name <name> --command </command> --extension <path to .py> [--phases a,b,c]
        Name the run's orchestrator and its extension module in podium.json's
        `orchestrator` block, creating podium/podium.json when absent.
    server ... | watch ...
        Serve the Podium for the run, or watch it.
"""
import importlib
import os
import sys

from podium_dashboard import __version__, extension, sync
from podium_dashboard.state import (Podium, cmd_assume, cmd_assumptions, cmd_batch, cmd_claim, cmd_get, cmd_hours,
                                    cmd_human, cmd_init, cmd_log, cmd_ready, cmd_release, cmd_requests, cmd_set,
                                    cmd_settle, cmd_status, cmd_whoami)

COMMANDS = {"status": cmd_status, "get": cmd_get, "set": cmd_set, "batch": cmd_batch, "ready": cmd_ready,
            "human": cmd_human, "hours": cmd_hours, "assume": cmd_assume, "assumptions": cmd_assumptions,
            "settle": cmd_settle, "log": cmd_log, "requests": cmd_requests, "init": cmd_init,
            "sync": sync.cmd_sync, "whoami": cmd_whoami, "claim": cmd_claim, "release": cmd_release}
SUBCOMMANDS = ("server", "watch")
NO_PODIUM = {"hours", "human", "whoami"}  # the user's, one per machine


def find_run(d):
    """The nearest run dir at or above d: one holding podium/podium.json, or a repo's .deep-plan run (podium.json
    in .deep-plan/podium/, or at its top in a run from before podium/)."""
    while True:
        for run in (d, os.path.join(d, ".deep-plan")):
            if os.path.isfile(os.path.join(run, "podium", "podium.json")) or (run != d and os.path.isfile(os.path.join(run, "podium.json"))):
                return run
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)


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
    if verb in NO_PODIUM:
        COMMANDS[verb](None, args)
        return
    if not root and verb != "init":
        fail("no run dir at or above here: pass --dir <run dir>, or set PODIUM_DIR")
    p = Podium(root or os.curdir)
    if verb in COMMANDS:
        COMMANDS[verb](p, args)
        autosave(p)
        return
    module, why = extension.load(p)
    if why:
        fail(why)
    command = extension.commands(module).get(verb)
    if not command:
        fail(f"unknown command {verb!r}; `podium` lists them")
    command(p, args)
    autosave(p)


def autosave(p):
    if not sync.enabled(p):
        return
    major = [e for e in p.fresh if sync.is_major(p, e)]
    if major:
        print(sync.save(p, "; ".join(sync.describe(e) for e in major)))
