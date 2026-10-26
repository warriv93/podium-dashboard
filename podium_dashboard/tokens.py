"""`podium tokens`: where Claude Code's tokens went, read from its session logs, with the patterns worth fixing.

Reads ~/.claude/projects/*/*.jsonl and */<session>/subagents/*.jsonl line by line, skipping files last written before
--since. An assistant message's tokens are its usage's input, cache creation, cache read and output tokens; a tool
result's are its text's characters / 4. Messages and tool calls count once per id: the log repeats a message's usage on
each of its content blocks, and the same call can appear in more than one file. Patterns are scaled to tokens per week
of the window.
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

USAGE = "tokens [--since 7d|<ISO>] [--cwd <path>]... [--projects <dir>] [--top N] [--json]"
KINDS = ("big-output", "repeat-command", "reread", "sequence")
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
KEY_ARGS = ("command", "file_path", "notebook_path", "pattern", "url", "query", "skill", "subagent_type", "description")
BIG_OUTPUT = 4000
SEQUENCE = 3
KEY_WIDTH = 100
SPAN = re.compile(r"^(\d+)([hdw])$")
QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
PATH = re.compile(r"(?<![\w.~-])~?/[^\s'\"|;&<>()$`]*")
SHA = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,}\b")
NUMBER = re.compile(r"\b\d+\b")


def normalize(text):
    text = QUOTED.sub("<str>", text)
    text = PATH.sub("<path>", text)
    text = SHA.sub("<sha>", text)
    text = NUMBER.sub("<n>", text)
    text = " ".join(text.split())
    return text if len(text) <= KEY_WIDTH else text[:KEY_WIDTH - 1] + "…"


def human(n):
    if n < 999.5:
        return str(int(round(n)))
    if n < 999_950:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"


def parse_since(value, now):
    m = SPAN.match(value)
    if m:
        return now - timedelta(**{{"h": "hours", "d": "days", "w": "weeks"}[m[2]]: int(m[1])})
    try:
        at = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        sys.exit(f"tokens: --since takes 7d, 24h, 2w or an ISO time, not {value!r}\n{USAGE}")
    return at.astimezone(timezone.utc) if at.tzinfo else at.astimezone().astimezone(timezone.utc)


def stamp(at):
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def under(cwd, prefixes):
    return not prefixes or any(cwd == p or cwd.startswith(p.rstrip("/") + "/") for p in prefixes)


def log_files(projects):
    return glob.glob(os.path.join(projects, "*", "*.jsonl")) + glob.glob(os.path.join(projects, "*", "*", "subagents", "*.jsonl"))


def call_key(name, args):
    value = next((args[k] for k in KEY_ARGS if isinstance(args, dict) and isinstance(args.get(k), str)), "")
    return f"{name} {normalize(value)}".rstrip()


def result_chars(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return 0


class Tally:
    def __init__(self):
        self.messages = set()
        self.calls = set()
        self.sessions = set()
        self.models = Counter()
        self.patterns = {kind: defaultdict(lambda: {"count": 0, "tokens": 0, "streams": set()}) for kind in KINDS}

    def add(self, kind, key, tokens, stream):
        entry = self.patterns[kind][key]
        entry["count"] += 1
        entry["tokens"] += tokens
        entry["streams"].add(stream)


def read_file(path, since, prefixes, tally):
    calls, sequence = {}, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "usage" not in line and "tool_result" not in line:
                continue
            try:
                d = json.loads(line)
                message = d.get("message")
                if not isinstance(message, dict) or not isinstance(d.get("timestamp"), str) or d["timestamp"] < since:
                    continue
                if not under(d.get("cwd") or "", prefixes):
                    continue
                stream = (d.get("sessionId"), d.get("agentId"))
                if d.get("type") == "assistant":
                    read_assistant(d, message, stream, calls, sequence, tally)
                elif d.get("type") == "user":
                    read_results(message, calls, tally)
            except (ValueError, TypeError, AttributeError):
                continue
    for i in range(len(sequence) - SEQUENCE + 1):
        window = sequence[i:i + SEQUENCE]
        tally.add("sequence", " → ".join(c["key"] for c in window), sum(c["tokens"] for c in window), window[0]["stream"])


def read_assistant(d, message, stream, calls, sequence, tally):
    usage = message.get("usage")
    mid = message.get("id") or d.get("uuid")
    if isinstance(usage, dict) and mid not in tally.messages:
        used = sum(int(usage.get(k) or 0) for k in USAGE_KEYS)
        tally.messages.add(mid)
        tally.sessions.add(d.get("sessionId"))
        tally.models[message.get("model") or "unknown"] += used
    for item in message.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("id") not in tally.calls:
            tally.calls.add(item.get("id"))
            args = item.get("input") or {}
            call = {"name": item.get("name") or "?", "args": args, "key": call_key(item.get("name") or "?", args),
                    "stream": stream, "tokens": 0}
            calls[item.get("id")] = call
            sequence.append(call)


def read_results(message, calls, tally):
    for item in message.get("content") if isinstance(message.get("content"), list) else []:
        if not isinstance(item, dict) or item.get("type") != "tool_result":
            continue
        call = calls.pop(item.get("tool_use_id"), None)
        if call is None:
            continue
        chars = result_chars(item.get("content"))
        call["tokens"] = chars / 4
        if chars >= BIG_OUTPUT:
            tally.add("big-output", call["key"], call["tokens"], call["stream"])
        if call["name"] == "Bash" and isinstance(call["args"].get("command"), str):
            tally.add("repeat-command", call["key"], call["tokens"] + len(call["args"]["command"]) / 4, call["stream"])
        if call["name"] == "Read" and isinstance(call["args"].get("file_path"), str):
            tally.add("reread", f"Read {call['args']['file_path']}", call["tokens"], call["stream"])


def report(projects, since, now, prefixes, top):
    tally = Tally()
    floor = since.timestamp()
    for path in log_files(projects):
        try:
            if os.path.getmtime(path) < floor:
                continue
            read_file(path, stamp(since), prefixes, tally)
        except OSError:
            continue
    per_week = timedelta(weeks=1) / max(now - since, timedelta(hours=1))
    patterns = []
    for kind in KINDS:
        found = [{"kind": kind, "count": e["count"], "perWeek": round(e["tokens"] * per_week), "key": key}
                 for key, e in tally.patterns[kind].items() if kind == "big-output" or len(e["streams"]) >= 2]
        patterns += sorted(found, key=lambda p: (-p["perWeek"], -p["count"], p["key"]))[:top]
    patterns.sort(key=lambda p: (-p["perWeek"], -p["count"], KINDS.index(p["kind"]), p["key"]))
    return {"since": since.isoformat(), "total": sum(tally.models.values()), "sessions": len(tally.sessions),
            "models": dict(tally.models.most_common()), "patterns": patterns}


def lines(r):
    yield f"TOTAL {human(r['total'])} sessions {r['sessions']}"
    for model, n in r["models"].items():
        yield f"MODEL {model} {human(n)}"
    for p in r["patterns"]:
        yield f"PATTERN {p['kind']} ×{p['count']} ~{human(p['perWeek'])}/wk {p['key']}"


def cmd_tokens(p, args):
    since, prefixes, projects, top, as_json, i = "7d", [], "~/.claude/projects", 10, False, 0
    while i < len(args):
        if args[i] in ("--since", "--cwd", "--projects", "--top") and i + 1 < len(args):
            flag, value = args[i], args[i + 1]
            i += 2
            if flag == "--since":
                since = value
            elif flag == "--cwd":
                prefixes.append(os.path.abspath(os.path.expanduser(value)))
            elif flag == "--projects":
                projects = value
            elif not value.isdigit():
                sys.exit(f"tokens: --top takes a number\n{USAGE}")
            else:
                top = int(value)
        elif args[i] == "--json":
            as_json = True
            i += 1
        else:
            sys.exit(USAGE)
    now = datetime.now(timezone.utc)
    r = report(os.path.expanduser(projects), parse_since(since, now), now, prefixes, top)
    if as_json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return
    for text in lines(r):
        print(text)
