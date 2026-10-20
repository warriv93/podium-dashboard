"""Opt-in git sync of the run state, podium.json's `sync` block: {enabled, remote, ref, include, exclude}.

The state is committed onto `ref` (default refs/heads/podium) through a throwaway index, never touching a working
tree, index or HEAD, and pushed to `remote`: a remote name of the run's own repo (default origin), or a URL, whose
commits live in a private bare cache per run under ~/.podium/sync, so a run outside any repo syncs too. `include`
globs (relative to the run dir) pick the files; this machine's own files never go: the request queue and its cursor,
the watcher's heartbeat, the server log. `enabled`, `remote` and `ref` are this machine's and stay out of the synced
podium.json; `include` and `exclude` sync with the run. Two machines that both moved merge per file against their
common save: podium.json as concurrent commands do (rebase), except that a milestone both gave an owner keeps the
remote's, the claim that reached it first; events.jsonl and *.progress as the union of their lines
in time order, any other text through `git merge-file`; a conflict keeps this machine's file, writes the other beside
it as `<file>.remote`, and sets this person's needsYou. A pull or merge deletes only a file that common save had.
"""
import fnmatch
import glob
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

from podium_dashboard import extension
from podium_dashboard.state import person_of, rebase

MAJOR = {"status", "grilled", "failed", "landed", "settled", "owner"}
MAJOR_PHASES = {"spec", "architecture", "build"}
REMOTE, REF = "origin", "refs/heads/podium"
STATE = ["podium.json", "events.jsonl", "handoffs.json", "stories/**"]
MACHINE = ("enabled", "remote", "ref")
LOCAL = ["cursor.json", "requests.jsonl", "watcher.json", "server.log", "*.tmp", "*.remote"]
APPEND_ONLY = ["events.jsonl", "*.progress"]
CACHE = "~/.podium/sync"
WATCHER_LIVE = 30
USAGE = "sync on [--remote <name or URL>] [--ref <ref>] | off | save [<message>] | pull | status"


class SyncError(Exception):
    pass


class Git:
    def __init__(self, base, remote, ref):
        self.base, self.remote, self.ref = base, remote, ref

    def run(self, *args, input=None, env=None, text=True):
        return subprocess.run([*self.base, *args], input=input, env=env, capture_output=True, text=text)

    def out(self, *args, **kwargs):
        r = self.run(*args, **kwargs)
        if r.returncode:
            err = r.stderr if isinstance(r.stderr, str) else r.stderr.decode(errors="replace")
            raise SyncError((err.strip().splitlines() or [f"git {args[0]} failed"])[0])
        return r.stdout

    def rev(self, name):
        return self.run("rev-parse", "--verify", "-q", name).stdout.strip() or None

    def tree_of(self, commit):
        return commit and self.rev(commit + "^{tree}")

    def ancestor(self, a, b):
        return self.run("merge-base", "--is-ancestor", a, b).returncode == 0

    def merge_base(self, a, b):
        return self.run("merge-base", a, b).stdout.strip() or None

    def commit(self, tree, parents, message):
        return self.out("commit-tree", tree, *[a for c in parents for a in ("-p", c)], "-m", message).strip()

    def update_ref(self, sha):
        self.out("update-ref", self.ref, sha)

    def blob(self, data):
        return self.out("hash-object", "-w", "--stdin", input=data, text=False).decode().strip()

    def cat(self, sha):
        return self.out("cat-file", "blob", sha, text=False)

    def files(self, p, commit):
        """{path: blob sha} of the commit's files that may land in the run dir."""
        found = {}
        for entry in self.out("ls-tree", "-r", "-z", "--full-tree", commit).split("\0"):
            meta, _, rel = entry.partition("\t")
            if meta.split()[:2] in (["100644", "blob"], ["100755", "blob"]) and restorable(p, rel):
                found[rel] = meta.split()[2]
        return found

    def remote_tip(self):
        """(the remote's commit on the ref, fetched, or None; why the remote can't be reached, or None)."""
        r = self.run("ls-remote", self.remote, self.ref)
        if r.returncode:
            return None, (r.stderr.strip().splitlines() or [f"{self.remote} unreachable"])[0]
        tip = next((line.split()[0] for line in r.stdout.splitlines() if line.split()[1:] == [self.ref]), None)
        if tip and self.run("cat-file", "-e", tip + "^{commit}").returncode:
            f = self.run("fetch", "--quiet", "--no-write-fetch-head", self.remote, self.ref)
            if f.returncode:
                return None, (f.stderr.strip().splitlines() or ["fetch failed"])[0]
        return tip, None

    def push(self, sha):
        return self.run("push", "--quiet", self.remote, f"{sha}:{self.ref}").returncode == 0


def settings(p):
    s = p.data.get("sync")
    return s if isinstance(s, dict) else {}


def enabled(p):
    return p.synced()


def is_url(remote):
    return "://" in remote or remote.startswith(("/", "~", ".")) or bool(re.match(r"[^/:]+@[^/:]+:", remote))


def open_git(p, remote=None, ref=None):
    """(Git, None) where the run's sync plumbing runs, or (None, why it can't)."""
    s = settings(p)
    remote, ref = remote or s.get("remote") or REMOTE, ref or s.get("ref") or REF
    if subprocess.run(["git", "check-ref-format", ref], capture_output=True).returncode or not ref.startswith("refs/"):
        return None, f"not a full ref name: {ref}"
    if is_url(remote):
        url = os.path.expanduser(remote) if remote.startswith("~") else remote
        url = os.path.normpath(os.path.join(p.root, url)) if url.startswith(".") else url
        key = hashlib.sha1(f"{url}\n{ref}\n{os.path.realpath(p.root)}".encode()).hexdigest()[:16]
        cache = os.path.join(os.path.expanduser(CACHE), key)
        if not os.path.isdir(cache):
            r = subprocess.run(["git", "init", "--bare", "-q", cache], capture_output=True, text=True)
            if r.returncode:
                return None, (r.stderr.strip().splitlines() or ["git init failed"])[0]
        return Git(["git", "--git-dir", cache], url, ref), None
    top = subprocess.run(["git", "-C", p.root, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode:
        return None, "not in a git repo"
    return Git(["git", "-C", top.stdout.strip()], remote, ref), None


# --- the synced files ------------------------------------------------------------
def podium_json(p):
    return os.path.relpath(p.path, p.root).replace(os.sep, "/")


def includes(p, block=None):
    found = (settings(p) if block is None else block).get("include")
    if isinstance(found, list):
        return [str(g) for g in found]
    prefix = os.path.relpath(p.dir, p.root).replace(os.sep, "/")
    return [g if prefix == "." else f"{prefix}/{g}" for g in STATE]


def local_only(p, rel, block=None):
    """Whether the run dir's `rel` is this machine's alone; a pattern without `/` matches the file name."""
    patterns = LOCAL + [str(g) for g in (settings(p) if block is None else block).get("exclude") or []]
    return ".git" in rel.split("/") or any(
        fnmatch.fnmatchcase(rel if "/" in pattern else posixpath.basename(rel), pattern) for pattern in patterns)


def restorable(p, rel):
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and not {"", ".", ".."} & set(parts) and not local_only(p, rel)


def glob_pattern(pattern):
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    return re.compile("".join({"**": ".*", "*": "[^/]*", "?": "[^/]"}.get(x, re.escape(x)) for x in parts))


def covered(p, rel, block):
    """Whether the `sync` block's include and exclude lists carry the run dir's `rel`."""
    return any(glob_pattern(g).fullmatch(rel) for g in includes(p, block)) and not local_only(p, rel, block)


def synced_files(p):
    """The run dir's files the sync carries, relative to the run dir, sorted."""
    found = set()
    for pattern in includes(p):
        for path in glob.glob(os.path.join(glob.escape(p.root), pattern), recursive=True):
            rel = os.path.relpath(path, p.root).replace(os.sep, "/")
            if os.path.isfile(path) and not os.path.islink(path) and restorable(p, rel):
                found.add(rel)
    return sorted(found)


def dump(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def shared(raw):
    """podium.json as it syncs: without this machine's own `sync` keys; None when nothing else is in it."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(data, dict):
        return raw
    block = data.get("sync")
    kept = {k: v for k, v in block.items() if k not in MACHINE} if isinstance(block, dict) else {}
    if kept:
        data["sync"] = kept
    else:
        data.pop("sync", None)
    return dump(data) if set(data) - {"updatedAt"} else None


def with_machine_keys(p, content):
    """A synced podium.json, None when the save has none, with this machine's own `sync` keys put back."""
    block = p.read().get("sync")
    machine = {k: v for k, v in block.items() if k in MACHINE} if isinstance(block, dict) else {}
    try:
        data = json.loads(content) if content is not None else {}
    except ValueError:
        return content
    if not machine or not isinstance(data, dict):
        return content
    common = data.get("sync")
    data["sync"] = {**(common if isinstance(common, dict) else {}), **machine}
    return dump(data)


def state_tree(p, g):
    """The tree of this machine's run state, built in a throwaway index; None when there is none."""
    rels, blobs, paths = [], [], []
    for rel in synced_files(p):
        if rel != podium_json(p):
            paths.append(rel)
            continue
        with open(p.path, "rb") as f:
            content = shared(f.read())
        if content is not None:
            rels.append(rel)
            blobs.append(g.blob(content))
    if paths:
        rels += paths
        blobs += g.out("hash-object", "-w", "--no-filters", "--stdin-paths",
                       input="".join(os.path.join(p.root, r) + "\n" for r in paths)).split()
    if not rels:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        g.out("update-index", "--index-info", env=env, input="".join(f"100644 {b}\t{r}\n" for b, r in zip(blobs, rels)))
        return g.out("write-tree", env=env).strip()


def apply(p, files, gone):
    """Write each of `files` ({path relative to the run dir: content}) that differs, with this machine's own `sync`
    keys kept in podium.json, and delete the files in `gone` (synced before, and dropped since) that the incoming
    include and exclude lists still carry: a file they no longer carry stops syncing and stays."""
    files, pj = dict(files), podium_json(p)
    try:
        incoming = json.loads(files[pj]).get("sync") if pj in files else None
    except (ValueError, AttributeError):
        incoming = None
    block = incoming if isinstance(incoming, dict) else {}
    gone = {rel for rel in gone if covered(p, rel, block)}
    content = with_machine_keys(p, files.get(pj))
    if content is not None:
        files[pj] = content
    with p.locked():
        for rel in sorted(set(gone) - set(files)):
            try:
                os.remove(os.path.join(p.root, *rel.split("/")))
            except FileNotFoundError:
                pass
        for rel, content in files.items():
            path = os.path.join(p.root, *rel.split("/"))
            try:
                with open(path, "rb") as f:
                    if f.read() == content:
                        continue
            except OSError:
                pass
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "wb") as f:
                f.write(content)
            os.replace(tmp, path)


# --- merging two machines' saves ---------------------------------------------------
def instant(text):
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def event_time(line):
    try:
        return instant(json.loads(line).get("at"))
    except (ValueError, AttributeError):
        return None


def union(mine, theirs, when):
    """Both sides' lines once each, in time order; a line without a time keeps to the line before it."""
    lines, seen = [], set()
    for line in theirs.decode(errors="surrogateescape").splitlines() + mine.decode(errors="surrogateescape").splitlines():
        if line.strip() and line not in seen:
            seen.add(line)
            lines.append(line)
    keyed, last = [], float("-inf")
    for line in lines:
        t = when(line)
        last = last if t is None else t
        keyed.append((last, line))
    keyed.sort(key=lambda x: x[0])
    return "".join(line + "\n" for _, line in keyed).encode(errors="surrogateescape")


def owners(data):
    """{milestone id: owner} of a podium.json's data."""
    epics = data.get("epics") if isinstance(data, dict) else None
    return {m.get("id"): m.get("owner") for e in epics or [] if isinstance(e, dict)
            for m in e.get("milestones") or [] if isinstance(m, dict)}


def first_claim(base, mine, theirs, out):
    """`out`, the rebase of `mine` onto `theirs`, with the remote's owner kept for each milestone both gave a new one."""
    b, m, t = owners(base), owners(mine), owners(theirs)
    for e in (out.get("epics") if isinstance(out, dict) else None) or []:
        for ms in (e.get("milestones") if isinstance(e, dict) else None) or []:
            mid = ms.get("id") if isinstance(ms, dict) else None
            if t.get(mid) and t[mid] != b.get(mid) and m.get(mid) != b.get(mid):
                ms["owner"] = t[mid]
    return out


def merge_file(p, rel, base, mine, theirs):
    """(merged content, whether it merged cleanly) of a file both sides changed."""
    name = posixpath.basename(rel)
    if rel == podium_json(p):
        try:
            b, m, t = json.loads(base) if base else {}, json.loads(mine), json.loads(theirs)
            return dump(first_claim(b, m, t, rebase(b, m, t))), True
        except ValueError:
            pass
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in APPEND_ONLY):
        return union(mine, theirs, event_time if name.endswith(".jsonl") else lambda l: instant(l.split(" ", 1)[0])), True
    with tempfile.TemporaryDirectory() as tmp:
        paths = [os.path.join(tmp, n) for n in ("mine", "base", "theirs")]
        for path, content in zip(paths, (mine, base or b"", theirs)):
            with open(path, "wb") as f:
                f.write(content)
        r = subprocess.run(["git", "merge-file", "-p", *paths], capture_output=True)
    return (r.stdout, True) if r.returncode == 0 else (mine, False)


def merged(p, g, base, mine, theirs):
    """(the files of commits `mine` and `theirs` merged against `base`, with a `<file>.remote` beside each conflict;
    the files of `base` the merge drops)."""
    b, m, t = (g.files(p, c) if c else {} for c in (base, mine, theirs))
    out, conflicts = {}, []
    for rel in sorted(set(m) | set(t)):
        bs, ms, ts = b.get(rel), m.get(rel), t.get(rel)
        if ms == ts or ts == bs:
            chosen = ms
        elif ms == bs or not ms:
            chosen = ts
        elif not ts:
            chosen = ms
        else:
            out[rel], clean = merge_file(p, rel, *(g.cat(x) if x else None for x in (bs, ms, ts)))
            if not clean:
                out[rel + ".remote"] = g.cat(ts)
                conflicts.append(rel)
            continue
        if chosen:
            out[rel] = g.cat(chosen)
    if conflicts:
        pj = podium_json(p)
        data = json.loads(out[pj]) if pj in out else {}
        person_of(data, p.me)["needsYou"] = {"reason": f"sync conflict in {', '.join(conflicts)}"}
        out[pj] = dump(data)
    return out, set(b) - set(out)


def merge_into(p, g, head, remote, message):
    """Merge the remote's commit into this machine's: the run dir gets the merged files, the ref a commit with both
    parents. Returns that commit."""
    apply(p, *merged(p, g, g.merge_base(head, remote), head, remote))
    tree = state_tree(p, g) or g.out("mktree", input="").strip()
    return g.commit(tree, [head, remote], message)


# --- the API -------------------------------------------------------------------
def is_major(p, event):
    """Whether an event changes what the run is, so sync saves after it: the extension's SYNC_MAJOR(event) when it
    defines one."""
    module, _ = extension.load(p)
    override = extension.sync_major(module)
    if override:
        return bool(override(event))
    kind = event.get("type")
    return kind in MAJOR or (kind == "phase" and event.get("phase") in MAJOR_PHASES) or (kind == "merged" and bool(event.get("wave")))


def describe(event):
    where = "/".join(str(x) for x in (event.get("milestone"), event.get("story")) if x)
    what = event.get("phase") or event.get("status") or ("wave" if event.get("wave") else "")
    return " ".join(str(x) for x in (where, event.get("type"), what) if x)


def save(p, message="save"):
    """Commit the run state onto the sync ref and push it. One line: SAVED <sha> <message>[ (not pushed: <why>)],
    UNCHANGED, BEHIND (the remote has newer saves and this machine nothing new: pull), FAILED <why>, or OFF."""
    if not enabled(p):
        return "OFF"
    g, why = open_git(p)
    if not g:
        return f"OFF ({why})"
    try:
        return _save(p, g, message or "save")
    except SyncError as e:
        return f"FAILED {e}"


def _save(p, g, message):
    err, head, merged_here = None, None, False
    for _ in range(3):
        remote, err = g.remote_tip()
        with p.locked():
            local, tree = g.rev(g.ref + "^{commit}"), state_tree(p, g)
            if not tree:
                return "UNCHANGED"
            if remote and tree == g.tree_of(remote) and (not local or g.ancestor(local, remote)):
                g.update_ref(remote)
                return "UNCHANGED"
            if remote and not local:
                return "BEHIND"
            head = local if tree == g.tree_of(local) else g.commit(tree, [local] if local else [], f"podium: {message}")
            if remote and not g.ancestor(remote, head):
                if g.ancestor(head, remote):
                    return "BEHIND"
                head, merged_here = merge_into(p, g, head, remote, f"podium: {message}"), True
            if head != local:
                g.update_ref(head)
        if merged_here:
            p.refresh()
        if err:
            return f"SAVED {head[:7]} {message} (not pushed: {err})" if head != local else "UNCHANGED"
        if head == remote:
            return "UNCHANGED"
        if g.push(head):
            return f"SAVED {head[:7]} {message}"
        err = "push rejected three times"
    return f"SAVED {head[:7]} {message} (not pushed: {err})"


def watcher_running(p):
    try:
        with open(os.path.join(p.dir, "watcher.json")) as f:
            return time.time() - json.load(f)["at"] < WATCHER_LIVE
    except (OSError, ValueError, KeyError, TypeError):
        return False


def pull(p):
    """Bring this machine's run state up to the remote's saves. One line: PULLED <sha>, UP-TO-DATE, KEPT <why>
    (changes since the last save, a live watcher, or the remote out of reach), FAILED <why>, or OFF."""
    if not enabled(p):
        return "OFF"
    g, why = open_git(p)
    if not g:
        return f"OFF ({why})"
    try:
        out = _pull(p, g)
    except SyncError as e:
        return f"FAILED {e}"
    if out.startswith("PULLED"):
        p.refresh()
    return out


def _pull(p, g):
    remote, err = g.remote_tip()
    if err:
        return f"KEPT {err}"
    if not remote:
        return "UP-TO-DATE"
    with p.locked():
        local, tree = g.rev(g.ref + "^{commit}"), state_tree(p, g)
        if local and g.ancestor(remote, local):
            return "UP-TO-DATE"
        if tree == g.tree_of(remote):
            if not local or g.ancestor(local, remote):
                g.update_ref(remote)
            return "UP-TO-DATE"
        if tree and not local:
            return "KEPT this machine has run state it never saved"
        if tree and tree != g.tree_of(local):
            return "KEPT this machine has changes since its last save"
        if watcher_running(p):
            return "KEPT the watcher is running"
        if local and not g.ancestor(local, remote):
            head = merge_into(p, g, local, remote, "podium: merge")
        else:
            theirs = g.files(p, remote)
            gone = set(g.files(p, local)) - set(theirs) if local else set()
            apply(p, {rel: g.cat(sha) for rel, sha in theirs.items()}, gone)
            head = remote
        g.update_ref(head)
    return f"PULLED {head[:7]}"


def status(p):
    if not enabled(p):
        return "OFF"
    g, why = open_git(p)
    if not g:
        return f"OFF ({why})"
    local = g.rev(g.ref + "^{commit}")
    if not local:
        return f"ON {g.remote} {g.ref}, never saved here"
    try:
        changed = state_tree(p, g) != g.tree_of(local)
    except SyncError as e:
        return f"ON {g.remote} {g.ref}, last save {local[:7]}; FAILED {e}"
    return f"ON {g.remote} {g.ref}, last save {local[:7]}" + ("; changed since" if changed else "")


def cmd_sync(p, args):
    verb, rest = (args[0], args[1:]) if args else ("status", [])
    if verb == "on":
        opts = dict(zip(rest[::2], rest[1::2]))
        if len(rest) % 2 or set(opts) - {"--remote", "--ref"}:
            sys.exit(USAGE)
        s = settings(p)
        remote, ref = opts.get("--remote") or s.get("remote") or REMOTE, opts.get("--ref") or s.get("ref") or REF
        g, why = open_git(p, remote, ref)
        if not g:
            sys.exit(f"podium: sync on refused: {why}")
        p.data["sync"] = {**s, "enabled": True, "remote": remote, "ref": ref}
        p.save()
        print(f"ON {remote} {ref}")
    elif verb == "off" and not rest:
        p.data["sync"] = {**settings(p), "enabled": False}
        p.save()
        print("OFF")
    elif verb == "save":
        print(save(p, " ".join(rest) or "save"))
    elif verb == "pull" and not rest:
        print(pull(p))
    elif verb == "status" and not rest:
        print(status(p))
    else:
        sys.exit(USAGE)
