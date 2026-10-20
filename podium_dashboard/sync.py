"""Opt-in git sync of the run state, podium.json's `sync` block: {enabled, remote, ref, include, exclude}.

The state is committed onto `ref` (default refs/heads/podium-run/<run slug>) through a throwaway index, never touching a working
tree, index or HEAD, and pushed to `remote`: a remote name of the run's own repo (default origin), or a URL, whose
commits live in a private bare cache per run under ~/.podium/sync, so a run outside any repo syncs too. `include`
globs (relative to the run dir) pick the files, and `exclude` ones drop some: each list the run's own, else this
machine's default (sync.json beside human.json), else the state files plus the planning docs (Markdown files anywhere in
the run dir, spec/, mock/, domain-stories/) and no exclude; this machine's own files never go: the request queue and its cursor,
the watcher's heartbeat, the server log; nor does Python code or a native module. The whole `sync` block, `include` and `exclude` too,
is this machine's and stays out of the synced podium.json: a remote's save never widens what lands here. The
orchestrator's `extension` is this machine's too: the run carries the value its first save seeded, and only a first
pull or merge here sets it, on a machine that has none.
Two machines that both moved merge per file against their common save: podium.json as concurrent commands do
(rebase), except that a milestone both gave an owner keeps the remote's, the claim that reached it first;
events.jsonl and *.progress as the union of their lines in time order (a progress file of a milestone this person
owns stays as it is here), any other text through `git merge-file`; a conflict keeps this machine's file, writes the other beside
it as `<file>.remote`, and adds to this person's needsYou; so does a file the run dir holds that the remote's save
brings with other content. A pull or merge writes only files this machine's include and exclude lists carry, and
deletes only a file that common save had, unchanged here, that those lists still carry; a save carries the files
those lists leave out as the last save had them, so a machine that shares fewer files never drops another's.
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
from datetime import datetime, timezone

from podium_dashboard import extension, human
from podium_dashboard.files import MACHINE_FILES, SHARED_FILES, git_argv, write_atomic
from podium_dashboard.merge import rebase
from podium_dashboard.state import person_of, watcher_running

MAJOR = {"status", "grilled", "failed", "landed", "settled", "owner"}
MAJOR_PHASES = {"spec", "architecture", "build"}
REMOTE = "origin"
MACHINE = ("enabled", "remote", "ref", "include", "exclude")
LOCAL = [*MACHINE_FILES, "*.tmp", "*.remote", "*.py", "*.pyc", "*.pth", "*.so", "*.dylib", "*.pyd", "repos/**", "worktrees/**", "**/*.logs/**", "*.logs/**",
         "**/__pycache__/**", "__pycache__/**"]
IGNORABLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
APPEND_ONLY = ["events.jsonl", "*.progress"]
PLANNING_DOCS = ["*.md", "**/*.md", "spec/**", "mock/**", "domain-stories/**"]
LISTS = ("include", "exclude")
CACHE = "~/.podium/sync"
USAGE = ("sync on [--remote <name or URL>] [--ref <ref>] | off | save [<message>] | pull | status"
         " | defaults [include=<JSON list>] [exclude=<JSON list>]")


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

    def update_ref(self, sha, old):
        """Move the ref to `sha` only while it is still at `old` (None: absent)."""
        self.out("update-ref", self.ref, sha, old or "")

    def blob(self, data):
        return self.out("hash-object", "-w", "--stdin", input=data, text=False).decode().strip()

    def cat(self, sha):
        return self.out("cat-file", "blob", sha, text=False)

    def files(self, p, commit):
        """{path: blob sha} of the commit's files that may land in the run dir."""
        found = {}
        for entry in self.out("ls-tree", "-r", "-z", "--full-tree", commit).split("\0"):
            meta, _, rel = entry.partition("\t")
            if meta.split()[:2] in (["100644", "blob"], ["100755", "blob"]) and restorable(p, rel, {}):
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


def default_ref(p):
    """refs/heads/podium-run/<the run dir's name, or its repo's for a hidden run dir like .deep-plan, in kebab case>."""
    name = os.path.basename(p.root)
    if name.startswith("."):
        name = os.path.basename(os.path.dirname(p.root))
    return "refs/heads/podium-run/" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "run")


def is_url(remote):
    return "://" in remote or remote.startswith(("/", "~", ".")) or bool(re.match(r"[^/:]+@[^/:]+:", remote))


def open_git(p, remote=None, ref=None):
    """(Git, None) where the run's sync plumbing runs, or (None, why it can't)."""
    s = settings(p)
    remote, ref = remote or s.get("remote") or REMOTE, ref or s.get("ref") or default_ref(p)
    if subprocess.run(git_argv("check-ref-format", ref), capture_output=True).returncode or not ref.startswith("refs/"):
        return None, f"not a full ref name: {ref}"
    if is_url(remote):
        url = os.path.expanduser(remote) if remote.startswith("~") else remote
        url = os.path.normpath(os.path.join(p.root, url)) if url.startswith(".") else url
        key = hashlib.sha1(f"{url}\n{ref}\n{os.path.realpath(p.root)}".encode()).hexdigest()[:16]
        cache = os.path.join(os.path.expanduser(CACHE), key)
        if not os.path.isdir(cache):
            r = subprocess.run(git_argv("init", "--bare", "-q", cache), capture_output=True, text=True)
            if r.returncode:
                return None, (r.stderr.strip().splitlines() or ["git init failed"])[0]
        return Git(git_argv("--git-dir", cache), url, ref), None
    top = subprocess.run(git_argv("-C", p.root, "rev-parse", "--show-toplevel"), capture_output=True, text=True)
    if top.returncode:
        return None, "not in a git repo"
    return Git(git_argv("-C", top.stdout.strip()), remote, ref), None


def podium_json(p):
    return os.path.relpath(p.path, p.root).replace(os.sep, "/")


def defaults_path():
    return os.path.join(os.path.dirname(human.HUMAN_FILE), "sync.json")


def machine_defaults():
    """This machine's default include and exclude lists, sync.json beside human.json; a key only when set."""
    try:
        with open(defaults_path()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    data = data if isinstance(data, dict) else {}
    return {key: [str(g) for g in data[key]] for key in LISTS if isinstance(data.get(key), list)}


def built_in(p, key):
    if key == "exclude":
        return []
    prefix = os.path.relpath(p.dir, p.root).replace(os.sep, "/")
    return [g if prefix == "." else f"{prefix}/{g}" for g in SHARED_FILES] + PLANNING_DOCS


def resolved(p):
    """{include|exclude: (globs, run|default|built-in)}: each the run's own list, else this machine's default, else
    the built-in one."""
    own, default, out = settings(p), machine_defaults(), {}
    for key in LISTS:
        if isinstance(own.get(key), list):
            out[key] = ([str(g) for g in own[key]], "run")
        elif key in default:
            out[key] = (default[key], "default")
        else:
            out[key] = (built_in(p, key), "built-in")
    return out


def includes(p, block=None):
    if block is None:
        return lists(p)["include"]
    found = block.get("include")
    return [str(g) for g in found] if isinstance(found, list) else built_in(p, "include")


def glob_pattern(pattern):
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    return re.compile("".join({"**": ".*", "*": "[^/]*", "?": "[^/]"}.get(x, re.escape(x)) for x in parts))


def folded(name):
    """`name` as a case-insensitive or Unicode-folding file system compares it."""
    return IGNORABLE.sub("", name).casefold()


def local_only(p, rel, block=None):
    """Whether the run dir's `rel` is this machine's alone: LOCAL or the block's exclude, in any case. A pattern with a
    `/` matches the path from the run dir, one without it the file name."""
    patterns = LOCAL + (lists(p)["exclude"] if block is None else [str(g) for g in block.get("exclude") or []])
    rel = folded(rel)
    return any(glob_pattern(folded(pattern)).fullmatch(rel) if "/" in pattern
               else fnmatch.fnmatchcase(posixpath.basename(rel), folded(pattern)) for pattern in patterns)


def git_dir_name(part):
    """Whether a path component names a .git folder on a case-insensitive or Unicode-folding file system."""
    return folded(part).rstrip(". ") == ".git"


def restorable(p, rel, block=None):
    parts = rel.split("/")
    return (bool(rel) and not rel.startswith("/") and not {"", ".", ".."} & set(parts)
            and not any(git_dir_name(x) for x in parts) and not local_only(p, rel, block))


def inside_run(p, rel):
    """Whether the run dir's `rel` lands inside the run dir without passing through a symlink."""
    path = p.root
    for part in rel.split("/"):
        path = os.path.join(path, part)
        if os.path.islink(path):
            return False
    return os.path.realpath(path).startswith(os.path.realpath(p.root) + os.sep)


def covered(p, rel, block=None):
    """Whether the `sync` block's include and exclude lists, by default the run's resolved ones, carry the run dir's
    `rel`."""
    return any(glob_pattern(g).fullmatch(rel) for g in includes(p, block)) and restorable(p, rel, block)


def lists(p):
    return {key: globs for key, (globs, _) in resolved(p).items()}


def widen(p, g):
    """Write the files of this machine's last save or pull that its lists cover now but did not then, and that the
    run dir lacks, then record the lists in synced.json: a file the lists start to cover is the run's, not one
    deleted here."""
    path = os.path.join(p.dir, "synced.json")
    try:
        with open(path) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = None
    now, seed = lists(p), g.rev(g.ref + "^{commit}")
    if now == last:
        return
    if isinstance(last, dict) and seed:
        apply(p, {rel: g.cat(sha) for rel, sha in g.files(p, seed).items() if rel != podium_json(p) and covered(p, rel)
                  and not covered(p, rel, last) and on_disk(p, rel) is None}, set())
    write_atomic(path, json.dumps(now))


def synced_files(p):
    """The run dir's files the sync carries, relative to the run dir, sorted."""
    found = set()
    for pattern in includes(p):
        for path in glob.glob(os.path.join(glob.escape(p.root), pattern), recursive=True):
            rel = os.path.relpath(path, p.root).replace(os.sep, "/")
            if os.path.isfile(path) and inside_run(p, rel) and restorable(p, rel):
                found.add(rel)
    return sorted(found)


def dump(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def shared(raw, extension=None):
    """podium.json as it syncs: without this machine's own `sync` keys, with `extension`, when given, as the
    orchestrator's; None when nothing else is in it."""
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
    if not set(data) - {"updatedAt"}:
        return None
    if extension:
        block = data.get("orchestrator")
        data["orchestrator"] = {**(block if isinstance(block, dict) else {}), "extension": extension}
    return dump(data)


def with_machine_keys(p, content, joining=False):
    """A synced podium.json with this machine's own `sync` keys, and only those, and `orchestrator.extension` put
    back; None when the save has none. Only a machine `joining` (never saved or pulled here) without an extension
    takes the one the save carries: a later pull or merge never changes the code a machine runs."""
    here = p.read()
    block, orchestrator = here.get("sync"), here.get("orchestrator")
    machine = {k: v for k, v in block.items() if k in MACHINE} if isinstance(block, dict) else {}
    extension = orchestrator.get("extension") if isinstance(orchestrator, dict) else None
    try:
        data = json.loads(content) if content is not None else None
    except ValueError:
        return content
    if not isinstance(data, dict):
        return content
    common = data.get("sync")
    common = {k: v for k, v in common.items() if k not in MACHINE} if isinstance(common, dict) else {}
    incoming = data.get("orchestrator")
    refused = not (extension or joining) and isinstance(incoming, dict) and "extension" in incoming
    if not (machine or extension or refused or common != data.get("sync", {})):
        return content
    if machine or common:
        data["sync"] = {**common, **machine}
    else:
        data.pop("sync", None)
    if extension:
        data["orchestrator"] = {**(incoming if isinstance(incoming, dict) else {}), "extension": extension}
    elif refused:
        incoming.pop("extension")
    return dump(data)


def seeded_extension(p, g, commit):
    """The `orchestrator.extension` the podium.json of `commit` carries, None when it carries none."""
    sha = commit and g.rev(f"{commit}:{podium_json(p)}")
    try:
        data = json.loads(g.cat(sha)) if sha else None
    except ValueError:
        return None
    block = data.get("orchestrator") if isinstance(data, dict) else None
    found = block.get("extension") if isinstance(block, dict) else None
    return found if isinstance(found, str) and found else None


def state_tree(p, g, seed=None):
    """The tree of this machine's run state, built in a throwaway index; None when there is none. `seed` (default this
    machine's last save) gives the files this machine's lists leave out, as it has them, and the extension its
    podium.json carries: this machine's own only when that has none, so the first save seeds it, and no machine
    changes it after."""
    seed = seed or g.rev(g.ref + "^{commit}")
    carried = {rel: sha for rel, sha in (g.files(p, seed) if seed else {}).items()
               if rel != podium_json(p) and not covered(p, rel)}
    rels, blobs, paths = list(carried), list(carried.values()), []
    for rel in synced_files(p):
        if rel != podium_json(p):
            paths.append(rel)
            continue
        with open(p.path, "rb") as f:
            content = shared(f.read(), seeded_extension(p, g, seed))
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


def on_disk(p, rel):
    """The run dir's `rel` as it would sync, None when absent."""
    try:
        with open(os.path.join(p.root, *rel.split("/")), "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return shared(raw) if rel == podium_json(p) else raw


def apply(p, files, gone, joining=False):
    """Write each of `files` ({path relative to the run dir: content}) that differs, with this machine's own keys kept
    in podium.json and the lines an append-only file gained meanwhile kept in it, and delete the files in `gone`;
    never a progress file of this person's milestones. podium.json is written only when `files` has it."""
    files, pj = dict(files), podium_json(p)
    if pj in files:
        files[pj] = with_machine_keys(p, files[pj], joining)
    with p.locked():
        kept = own_progress(p)
        files = {rel: content for rel, content in files.items() if not kept(rel)}
        for rel in sorted(set(gone) - set(files) - {pj}):
            if inside_run(p, rel) and not kept(rel):
                try:
                    os.remove(os.path.join(p.root, *rel.split("/")))
                except FileNotFoundError:
                    pass
        for rel, content in files.items():
            if not inside_run(p, rel):
                continue
            path = os.path.join(p.root, *rel.split("/"))
            try:
                with open(path, "rb") as f:
                    here = f.read()
            except OSError:
                here = None
            if here is not None and appended(rel):
                content = union(here, content, appended(rel))
            if here == content:
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write_atomic(path, content)
            p.rewritten[rel] = (here, content)


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


def appended(rel):
    """The line timer of an append-only file, None for any other."""
    name = posixpath.basename(rel)
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in APPEND_ONLY):
        return event_time if name.endswith(".jsonl") else lambda line: instant(line.split(" ", 1)[0])
    return None


def owners(data):
    """{milestone id: owner} of a podium.json's data."""
    epics = data.get("epics") if isinstance(data, dict) else None
    return {m.get("id"): m.get("owner") for e in epics or [] if isinstance(e, dict)
            for m in e.get("milestones") or [] if isinstance(m, dict)}


def own_progress(p):
    """Whether a run dir path is a progress file of a story of a milestone this person owns, as this machine's
    podium.json has it: the agent building it here is that file's only writer."""
    try:
        here = p.read()
    except ValueError:
        here = {}
    epics = here.get("epics") if isinstance(here, dict) and isinstance(here.get("epics"), list) else []
    milestones = [m for e in epics if isinstance(e, dict) and isinstance(e.get("milestones"), list) for m in e["milestones"]]
    prefix = posixpath.dirname(podium_json(p))
    folders = {folded(posixpath.join(prefix, "stories", m["id"])) for m in milestones
               if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"] and p.me and m.get("owner") == p.me}
    return lambda rel: folded(rel).endswith(".progress") and posixpath.dirname(folded(rel)) in folders


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
    if rel == podium_json(p):
        try:
            b, m, t = json.loads(base) if base else {}, json.loads(mine), json.loads(theirs)
            return dump(first_claim(b, m, t, rebase(b, m, t))), True
        except ValueError:
            pass
    if appended(rel):
        return union(mine, theirs, appended(rel)), True
    with tempfile.TemporaryDirectory() as tmp:
        paths = [os.path.join(tmp, n) for n in ("mine", "base", "theirs")]
        for path, content in zip(paths, (mine, base or b"", theirs)):
            with open(path, "wb") as f:
                f.write(content)
        r = subprocess.run(git_argv("merge-file", "-p", *paths), capture_output=True)
    return (r.stdout, True) if r.returncode == 0 else (mine, False)


def flag(p, data, conflicts):
    """Add the conflicts to this person's needsYou in podium.json's `data`, after any reason already pending."""
    person = person_of(data, p.me)
    pending = person["needsYou"] if "needsYou" in person else data.get("needsYou")
    reason = f"sync conflict in {', '.join(conflicts)}"
    if reason in str(pending.get("reason") if isinstance(pending, dict) else pending):
        return
    if isinstance(pending, dict):
        person["needsYou"] = {**pending, "reason": "; ".join(str(x) for x in (pending.get("reason"), reason) if x)}
    else:
        person["needsYou"] = {"reason": f"{pending}; {reason}" if pending else reason}


def blank(value):
    return not value or isinstance(value, dict) and all(blank(v) for v in value.values())


def skeleton(p):
    """Whether this machine's run state is no more than the podium.json `podium init` writes: a project title, the
    orchestrator, and empty epics, people and assumptions."""
    if set(synced_files(p)) - {podium_json(p)}:
        return False
    content = on_disk(p, podium_json(p))
    try:
        data = json.loads(content) if content is not None else {}
    except ValueError:
        return False
    if not isinstance(data, dict) or set(data) - {"project", "orchestrator", "active", "needsYou", "assumptions",
                                                    "epics", "people", "updatedAt"}:
        return False
    project = data.get("project")
    return (isinstance(project, dict) and set(project) <= {"title"} or project is None) and all(
        blank(data.get(k)) for k in ("active", "needsYou", "assumptions", "epics", "people"))


def merged(p, g, base, mine, theirs):
    """(the files of commits `mine` and `theirs` merged against `base` (None: no common save), only those this
    machine's include and exclude lists carry, with a `<file>.remote` beside each conflict; the files to delete). A file the run
    dir holds with content neither `mine` nor the merge has is a conflict too: it stays as it is. So does a progress
    file of this person's milestones, whatever either side has."""
    b, m, t = (g.files(p, c) if c else {} for c in (base, mine, theirs))
    pj, out, conflicts, kept = podium_json(p), {}, [], own_progress(p)
    for rel in sorted(set(m) | set(t), key=lambda x: x != pj):
        if rel != pj and not covered(p, rel) or kept(rel):
            continue
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
    for rel in [r for r in out if r != pj and not r.endswith(".remote")]:
        here = on_disk(p, rel)
        if here is not None and here != out[rel] and (rel not in m or here != g.cat(m[rel])):
            out[rel + ".remote"] = out.pop(rel)
            conflicts.append(rel)
    if conflicts:
        data = json.loads(out[pj]) if pj in out else json.loads(on_disk(p, pj) or b"{}")
        flag(p, data, conflicts)
        out[pj] = dump(data)
    gone = {rel for rel in set(b) - set(out) - set(conflicts) if covered(p, rel) and not kept(rel)
            and on_disk(p, rel) in (None, g.cat(b[rel]), g.cat(m[rel]) if rel in m else None)}
    return out, gone


def merge_into(p, g, head, remote, message, mine=None):
    """Merge the remote's commit into this machine's, `mine` (default `head`) the tree that stands for this machine's
    files: the run dir gets the merged files, the ref a commit with both parents. Returns that commit."""
    joining = not g.rev(g.ref + "^{commit}")
    apply(p, *merged(p, g, g.merge_base(head, remote), mine or head, remote), joining)
    tree = state_tree(p, g, remote) or g.out("mktree", input="").strip()
    return g.commit(tree, [head, remote], message)


def is_major(p, event):
    """Whether an event changes what the run is, so sync saves after it: the extension's SYNC_MAJOR(event) when it
    defines one."""
    module, _ = extension.load(p)
    override = extension.sync_major(module)
    if override:
        return bool(override(event))
    kind = event.get("type")
    return kind in MAJOR or (kind == "phase" and event.get("phase") in MAJOR_PHASES) or (kind == "merged" and bool(event.get("wave")))


def autosave(p):
    if not enabled(p):
        return
    major = [e for e in p.new_events if is_major(p, e)]
    if major:
        print(save(p, "; ".join(describe(e) for e in major)))


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
            widen(p, g)
            local, tree = g.rev(g.ref + "^{commit}"), state_tree(p, g)
            if not tree:
                return "UNCHANGED"
            if remote and tree == g.tree_of(remote) and (not local or g.ancestor(local, remote)):
                if remote != local:
                    g.update_ref(remote, local)
                return "UNCHANGED"
            head = local if tree == g.tree_of(local) else g.commit(tree, [local] if local else [], f"podium: {message}")
            if remote and not g.ancestor(remote, head):
                if g.ancestor(head, remote):
                    return "BEHIND"
                head, merged_here = merge_into(p, g, head, remote, f"podium: {message}"), True
            if head != local:
                g.update_ref(head, local)
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


def pull(p, from_watcher=False):
    """Bring this machine's run state up to the remote's saves, merging them with changes made here since the last
    save, which stay unsaved until the next save unless the two sides had diverged (then the merge commit holds
    them; a pull never pushes). One line: PULLED <sha>, UP-TO-DATE, KEPT <why> (a live watcher, or the remote out of
    reach), FAILED <why>, or OFF. The watcher itself pulls `from_watcher`, past its own heartbeat. A run never saved or pulled here whose state is only the
    skeleton `podium init` writes takes the remote's state whole, keeping this machine's `sync` keys. `p.rewritten`
    then holds {path relative to the run dir: (content before, content written)} for each file the pull rewrote."""
    p.rewritten = {}
    if not enabled(p):
        return "OFF"
    g, why = open_git(p)
    if not g:
        return f"OFF ({why})"
    try:
        out = _pull(p, g, from_watcher)
    except SyncError as e:
        return f"FAILED {e}"
    if out.startswith("PULLED"):
        p.refresh()
    return out


def _pull(p, g, from_watcher):
    remote, err = g.remote_tip()
    if err:
        return f"KEPT {err}"
    if not remote:
        return "UP-TO-DATE"
    with p.locked():
        widen(p, g)
        local, tree = g.rev(g.ref + "^{commit}"), state_tree(p, g)
        if not local and skeleton(p):
            tree = None
        if local and g.ancestor(remote, local):
            return "UP-TO-DATE"
        if tree == g.tree_of(remote):
            if not local or g.ancestor(local, remote):
                g.update_ref(remote, local)
            return "UP-TO-DATE"
        if not from_watcher and watcher_running(p.dir):
            return "KEPT the watcher is running"
        if tree and not local:
            head = merge_into(p, g, g.commit(tree, [], "podium: save"), remote, "podium: merge")
        elif local and not g.ancestor(local, remote):
            head = merge_into(p, g, local, remote, "podium: merge", tree)
        else:
            apply(p, *merged(p, g, local, tree or local, remote), not local)
            head = remote
        g.update_ref(head, local)
    return f"PULLED {head[:7]}"


def status(p):
    """`ref <ref>` first, so another machine can pass it to `sync on --ref`, then OFF or ON and the last save here."""
    ref = settings(p).get("ref") or default_ref(p)
    if not enabled(p):
        return f"ref {ref} OFF"
    g, why = open_git(p)
    if not g:
        return f"ref {ref} OFF ({why})"
    local = g.rev(g.ref + "^{commit}")
    if not local:
        return f"ref {ref} ON {g.remote}, never saved here"
    try:
        changed = state_tree(p, g) != g.tree_of(local)
    except SyncError as e:
        return f"ref {ref} ON {g.remote}, last save {local[:7]}; FAILED {e}"
    return f"ref {ref} ON {g.remote}, last save {local[:7]}" + ("; changed since" if changed else "")


def sources(p):
    """`include <JSON> (<source>) exclude <JSON> (<source>)`: each list as the run resolves it, and where from."""
    return " ".join(f"{key} {json.dumps(globs)} ({source})" for key, (globs, source) in resolved(p).items())


def defaults_line():
    found = machine_defaults()
    return "DEFAULTS " + " ".join(f"{key} {json.dumps(found[key]) if key in found else 'none'}" for key in LISTS)


def cmd_defaults(args):
    """Print this machine's default lists, or set them: `include=<JSON list of globs>`, an empty value clears one."""
    changes = {}
    for arg in args:
        key, eq, value = arg.partition("=")
        if not eq or key not in LISTS or key in changes:
            sys.exit(USAGE)
        try:
            globs = json.loads(value) if value else None
        except ValueError:
            globs = value
        if value and not (isinstance(globs, list) and all(isinstance(g, str) for g in globs)):
            sys.exit(f"podium: sync defaults {key} must be a JSON list of strings, got {value}")
        changes[key] = globs
    if changes:
        found = machine_defaults()
        found.update(changes)
        os.makedirs(os.path.dirname(defaults_path()), exist_ok=True)
        write_atomic(defaults_path(), json.dumps({key: found[key] for key in LISTS if found.get(key) is not None}))
    print(defaults_line())


def cmd_sync(p, args):
    verb, rest = (args[0], args[1:]) if args else ("status", [])
    if verb == "defaults":
        cmd_defaults(rest)
    elif verb == "on":
        opts = dict(zip(rest[::2], rest[1::2]))
        if len(rest) % 2 or set(opts) - {"--remote", "--ref"}:
            sys.exit(USAGE)
        s = settings(p)
        remote, ref = opts.get("--remote") or s.get("remote") or REMOTE, opts.get("--ref") or s.get("ref") or default_ref(p)
        g, why = open_git(p, remote, ref)
        if not g:
            sys.exit(f"podium: sync on refused: {why}")
        p.data["sync"] = {**s, "enabled": True, "remote": remote, "ref": ref}
        p.save()
        print(f"ON {remote} ref {ref}")
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
        print(sources(p))
    else:
        sys.exit(USAGE)
