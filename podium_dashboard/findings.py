"""`podium finding` and `podium findings`: what went wrong or cost too much in a run, keyed so a recurrence is seen.

`finding add` appends a `finding` event to the run and a record to findings.jsonl on refs/heads/findings/<run slug> of
the extension's FINDINGS_REMOTE; `finding resolve` and `finding wontfix` append a resolution record and a
`finding-resolved` event the same way. The ref's commits are made in a private bare cache per remote under
~/.podium/findings-cache, never in a working tree; a push that loses a race takes the remote's lines with its own, as
their union, and tries again. `findings` groups the records by key: the run's own events, or with --all every run's
ref on the remotes.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from podium_dashboard import extension, human, sync, update
from podium_dashboard.commands import split_flags
from podium_dashboard.files import NOW, write_atomic

KINDS = ("retro", "tokens")
FIXES = ("check", "pointer", "standard", "delete", "access", "script", "flag", "brief", "model", "tool")
SEVERITIES = ("high", "normal")
KEY = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
CACHE = "~/.podium/findings-cache"
FILE = "findings.jsonl"
PREFIX = "refs/heads/findings/"
FETCHED = "refs/fetched/findings/"
RECUR_EVERY = timedelta(hours=24)
ADD_FLAGS = ("--key", "--kind", "--target", "--title", "--moment", "--fix", "--severity", "--saving", "--milestone")
ADD_USAGE = ("finding add --key <kebab-slug> --kind retro|tokens --target <skill|podium|repo:<name>> --title <title>"
             " --moment <evidence> --fix " + "|".join(FIXES) + " --severity high|normal [--saving <tokens/week>]"
             " [--milestone <id>]")
USAGE = (f"{ADD_USAGE}\n  | finding resolve <key> --sha <sha> --repo <repo> [--remote <url>]...\n"
         "  | finding wontfix <key> --why <why> [--remote <url>]...")
RESOLUTIONS = "resolutions"
LIST_USAGE = "findings [--all] [--remote <url>]... [--open] [--json] [--recur]"


def run_slug(p):
    """The last part of the sync ref when the run syncs, else of the ref it would sync to, in kebab case."""
    name = (sync.enabled(p) and sync.settings(p).get("ref")) or sync.default_ref(p)
    return re.sub(r"[^a-z0-9]+", "-", name.rsplit("/", 1)[-1].lower()).strip("-") or "run"


def run_remote(p):
    if p is None:
        return None
    module, _ = extension.load(p)
    return extension.findings_remote(module)


def remote_url(remote, base):
    url = os.path.expanduser(remote)
    return os.path.normpath(os.path.join(base, url)) if url.startswith(".") else url


def cache_of(url):
    return os.path.join(os.path.expanduser(CACHE), hashlib.sha1(url.encode()).hexdigest()[:16])


@contextlib.contextmanager
def locked(cache):
    fd = os.open(cache, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def content(g, commit):
    if not commit:
        return b""
    r = g.run("cat-file", "blob", f"{commit}:{FILE}", text=False)
    return b"" if r.returncode else r.stdout


def records(data):
    found = []
    for line in data.decode(errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            found.append(r)
    return found


def push(url, slug, record):
    """Add `record` to findings.jsonl on the remote's refs/heads/findings/<slug>: `pushed` or `not pushed: <why>`. A
    record that is not pushed stays on the cache's ref, and the next push to that ref carries it."""
    cache = cache_of(url)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    g, why = sync.bare_cache(cache, url, PREFIX + slug)
    if not g:
        return f"not pushed: {why}"
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    try:
        with locked(cache):
            return _push(g, line)
    except sync.SyncError as e:
        return f"not pushed: {e}"


def _push(g, line):
    err = None
    for _ in range(3):
        remote, err = g.remote_tip()
        theirs = content(g, remote)
        merged = sync.union(sync.union(line, content(g, g.rev(g.ref + "^{commit}")), sync.event_time), theirs, sync.event_time)
        if remote and set(merged.splitlines()) == set(theirs.splitlines()):
            g.out("update-ref", g.ref, remote)
            return "pushed"
        tree = g.out("mktree", input=f"100644 blob {g.blob(merged)}\t{FILE}\n").strip()
        head = g.commit(tree, [remote] if remote else [], "podium: findings")
        g.out("update-ref", g.ref, head)
        if err:
            return f"not pushed: {err}"
        if g.push(head):
            return "pushed"
        err = "push rejected three times"
    return f"not pushed: {err}"


def publish(p, record):
    remote = run_remote(p)
    if not remote:
        return "not pushed: no FINDINGS_REMOTE"
    return push(remote_url(remote, p.root), run_slug(p), record)


def fetched(url):
    """(every run's records on the remote, None), or (what the cache last fetched, why the fetch failed)."""
    cache = cache_of(url)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    g, why = sync.bare_cache(cache, url, None)
    if not g:
        return [], why
    with locked(cache):
        r = g.run("fetch", "--quiet", "--prune", "--no-write-fetch-head", url, f"+{PREFIX}*:{FETCHED}*")
        why = None if r.returncode == 0 else (r.stderr.strip().splitlines() or ["fetch failed"])[0]
        refs = g.run("for-each-ref", "--format=%(refname)", FETCHED).stdout.split()
        return [rec for ref in refs for rec in records(content(g, ref))], why


def from_events(p):
    try:
        with open(os.path.join(p.dir, "events.jsonl"), "rb") as f:
            events = records(f.read())
    except FileNotFoundError:
        return []
    found = []
    for e in events:
        if e.get("type") == "finding":
            found.append({k: v for k, v in e.items() if k != "type"})
        elif e.get("type") == "finding-resolved":
            r = {k: v for k, v in e.items() if k not in ("type", "resolution")}
            found.append({"type": e.get("resolution"), **r})
    return found


def when(record):
    return sync.instant(record.get("at")) or 0.0


def grouped(found):
    """One summary per key with a finding, most runs first, then most saving."""
    occurrences, resolutions = {}, {}
    for r in found:
        key = r.get("key")
        if not isinstance(key, str) or not key:
            continue
        if r.get("type") in ("resolved", "wontfix"):
            if key not in resolutions or when(r) >= when(resolutions[key]):
                resolutions[key] = r
        elif "type" not in r:
            occurrences.setdefault(key, []).append(r)
    out = []
    for key, seen in occurrences.items():
        seen.sort(key=when)
        latest, resolution = seen[-1], resolutions.get(key)
        closed = resolution is not None and when(latest) <= when(resolution)
        out.append({
            "key": key,
            "runs": sorted({str(r.get("run") or "") for r in seen}),
            "people": sorted({str(r["by"]) for r in seen if r.get("by")}),
            "kinds": sorted({str(r["kind"]) for r in seen if r.get("kind")}),
            "target": latest.get("target"),
            "severity": "high" if any(r.get("severity") == "high" for r in seen) else "normal",
            "title": latest.get("title"),
            "moment": latest.get("moment"),
            "at": latest.get("at"),
            "saving": sum(r["saving"] for r in seen if isinstance(r.get("saving"), int) and not isinstance(r["saving"], bool)),
            "status": resolution["type"] if closed else "open",
            **({"sha": resolution.get("sha")} if closed and resolution["type"] == "resolved" else {}),
        })
    out.sort(key=lambda g: (-len(g["runs"]), -g["saving"], g["key"]))
    return out


def line(g):
    status = f"resolved {str(g['sha'])[:7]}" if g["status"] == "resolved" and g.get("sha") else g["status"]
    saving = f" ~{g['saving']}/wk" if g["saving"] else ""
    return (f"FINDING {g['key']} ×{len(g['runs'])} {status} {','.join(g['kinds']) or '-'} {g['target']} {g['severity']}"
            f"{saving} — {g['title']}")


def recurring(groups):
    return [g for g in groups if g["status"] == "open" and (len(g["runs"]) >= 2 or g["severity"] == "high")]


def from_remotes(p, remotes):
    """(records, WARN lines) from every remote's findings refs."""
    base = p.root if p else os.getcwd()
    found, warnings = [], []
    for remote in remotes:
        recs, why = fetched(remote_url(remote, base))
        found += recs
        if why:
            warnings.append(f"WARN findings {remote} {why}")
    return found, warnings


def recur_due(now):
    try:
        at = datetime.fromisoformat(update.stamps()["recur"]["at"])
        return not timedelta(0) <= now - at < RECUR_EVERY
    except (KeyError, TypeError, ValueError):
        return True


def stamp_recur():
    try:
        os.makedirs(os.path.dirname(update.stamp_file()), exist_ok=True)
        write_atomic(update.stamp_file(), json.dumps({**update.stamps(), "recur": {"at": NOW()}}))
    except OSError:
        pass


def recur(p, remotes, now=None):
    """The RECUR lines: open keys seen in two runs or more, or high; nothing when they were listed within 24 hours."""
    if not recur_due(now or datetime.now(timezone.utc)):
        return []
    stamp_recur()
    remotes = remotes or [r for r in (run_remote(p),) if r]
    if remotes:
        found, warnings = from_remotes(p, remotes)
    else:
        found, warnings = (from_events(p) if p else []), []
    return warnings + [f"RECUR {g['key']} ×{len(g['runs'])} — {g['title']}" for g in recurring(grouped(found))]


def cmd_findings(p, args):
    remotes, flags, i = [], set(), 0
    while i < len(args):
        if args[i] == "--remote" and i + 1 < len(args):
            remotes.append(args[i + 1])
            i += 2
        elif args[i] in ("--all", "--open", "--json", "--recur"):
            flags.add(args[i])
            i += 1
        else:
            sys.exit(LIST_USAGE)
    if remotes and not flags & {"--all", "--recur"}:
        sys.exit(f"--remote needs --all or --recur: {LIST_USAGE}")
    if "--recur" in flags:
        for text in recur(p, remotes):
            print(text)
        return
    warnings = []
    if "--all" in flags:
        remotes = remotes or [r for r in (run_remote(p),) if r]
        if not remotes:
            sys.exit("findings --all: no FINDINGS_REMOTE here; pass --remote <url>")
        found, warnings = from_remotes(p, remotes)
    elif p is None:
        sys.exit("findings: no run dir at or above here; pass --dir <run dir>, or --all --remote <url>")
    else:
        found = from_events(p)
    groups = [g for g in grouped(found) if "--open" not in flags or g["status"] == "open"]
    for w in warnings:
        print(w, file=sys.stderr if "--json" in flags else sys.stdout)
    if "--json" in flags:
        print(json.dumps(groups, ensure_ascii=False))
        return
    for g in groups:
        print(line(g))


def cmd_finding(p, args):
    verb, rest = (args[0], args[1:]) if args else (None, [])
    if verb == "add" and p is not None:
        add(p, rest)
    elif verb in ("resolve", "wontfix"):
        remotes = [rest[i + 1] for i in range(len(rest) - 1) if rest[i] == "--remote"]
        rest = [a for i, a in enumerate(rest) if a != "--remote" and (i == 0 or rest[i - 1] != "--remote")]
        if p is None and not remotes:
            sys.exit(f"finding {verb} needs a run dir or --remote <url>")
        needed = ("--sha", "--repo") if verb == "resolve" else ("--why",)
        values, keys = split_flags(rest, needed, USAGE)
        if len(keys) != 1 or any(not values.get(f) for f in needed):
            sys.exit(USAGE)
        fields = {f[2:]: values[f] for f in needed}
        resolve(p, valid_key(keys[0]), "resolved" if verb == "resolve" else "wontfix", remotes, **fields)
    elif verb == "add":
        sys.exit("finding add needs a run dir: pass --dir <run dir>, or set PODIUM_DIR")
    else:
        sys.exit(USAGE)


def valid_key(key):
    if not KEY.fullmatch(key):
        sys.exit(f"finding: key {key!r} is not a kebab-case slug")
    return key


def one_of(values, flag, allowed):
    if values.get(flag) not in allowed:
        sys.exit(f"finding add: {flag} is one of {' '.join(allowed)}")
    return values[flag]


def add(p, args):
    values, rest = split_flags(args, ADD_FLAGS, ADD_USAGE)
    if rest or any(not values.get(f) for f in ("--key", "--target", "--title", "--moment")):
        sys.exit(ADD_USAGE)
    kind = one_of(values, "--kind", KINDS)
    record = {"key": valid_key(values["--key"]), "kind": kind, "target": values["--target"], "title": values["--title"],
              "moment": values["--moment"], "fix": one_of(values, "--fix", FIXES),
              "severity": one_of(values, "--severity", SEVERITIES)}
    if "--saving" in values:
        if kind != "tokens":
            sys.exit("finding add: --saving is for --kind tokens")
        if not re.fullmatch(r"\d+", values["--saving"]):
            sys.exit("finding add: --saving is a whole number of tokens per week")
        record["saving"] = int(values["--saving"])
    milestone = values.get("--milestone") or p.active().get("milestone")
    record.update({"by": p.me, "at": NOW(), "run": run_slug(p), **({"milestone": milestone} if milestone else {})})
    p.event("finding", milestone, **{k: v for k, v in record.items() if k not in ("at", "milestone")})
    print(f"FINDING {record['key']} recorded ({publish(p, record)})")


def resolve(p, key, kind, remotes, **fields):
    """Record a resolution: in the run's events and on its findings ref, or, given remotes, on the run's ref (outside a
    run refs/heads/findings/resolutions) of each; one FINDING line per remote."""
    by = p.me if p else human.me()
    record = {"type": kind, "key": key, **fields, "by": by, "at": NOW()}
    if p is not None:
        p.event("finding-resolved", resolution=kind, key=key, by=by, **fields)
    if remotes:
        slug = run_slug(p) if p else RESOLUTIONS
        results = [push(remote_url(r, p.root if p else os.getcwd()), slug, record) for r in remotes]
    else:
        results = [publish(p, record)]
    what = f"resolved {fields['sha'][:7]}" if kind == "resolved" else "wontfix"
    for result in results:
        print(f"FINDING {key} {what} ({result})")
