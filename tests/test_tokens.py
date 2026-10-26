"""Tests for `podium tokens`: totals and patterns read from synthetic Claude Code session logs in a temp HOME."""
import contextlib
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from podium_dashboard import tokens  # noqa: E402

CWD = "/work/repo"
ids = itertools.count()


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def assistant(session, *calls, usage=100, model="opus", cwd=CWD, at=None, mid=None, agent=None):
    content = [{"type": "tool_use", "id": call_id, "name": name, "input": args} for call_id, name, args, _ in calls]
    line = {"type": "assistant", "timestamp": at or ago(hours=1), "cwd": cwd, "sessionId": session,
            "message": {"id": mid or f"msg{next(ids)}", "model": model, "content": content,
                        "usage": {"input_tokens": usage, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                                  "output_tokens": 0}}}
    if agent:
        line["agentId"] = agent
    results = {"type": "user", "timestamp": at or ago(hours=1), "cwd": cwd, "sessionId": session,
               "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call_id, "content": output}
                                                       for call_id, _, _, output in calls]}}
    return [line, results] if calls else [line]


def call(name, output="ok", **args):
    return (f"toolu{next(ids)}", name, args, output)


def bash(command, output="ok"):
    return call("Bash", output, command=command)


def read(path, output="x" * 400):
    return call("Read", output, file_path=path)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.projects = os.path.join(self.tmp, ".claude", "projects")

    def log(self, lines, session="s1", project="-work-repo", agent=None, age=None):
        folder = os.path.join(self.projects, project, *((session, "subagents") if agent else ()))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"agent-{agent}.jsonl" if agent else f"{session}.jsonl")
        with open(path, "a") as f:
            for line in lines:
                f.write((line if isinstance(line, str) else json.dumps(line, separators=(",", ":"))) + "\n")
        if age:
            stamp = time.time() - age.total_seconds()
            os.utime(path, (stamp, stamp))
        return path

    def tokens(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tokens.cmd_tokens(None, ["--projects", self.projects, *args])
        return out.getvalue().splitlines()

    def report(self, *args):
        return json.loads("\n".join(self.tokens("--json", *args)))

    def patterns(self, kind, *args):
        return [p for p in self.report(*args)["patterns"] if p["kind"] == kind]


class Totals(Case):
    def test_sums_the_four_usage_counts_per_model_once_per_message_id_across_sessions_and_subagents(self):
        line = assistant("s1", mid="m1", usage=10)[0]
        line["message"]["usage"].update(cache_creation_input_tokens=200, cache_read_input_tokens=3000, output_tokens=40000)
        self.log([line, line])
        self.log(assistant("s1", usage=7, model="haiku", agent="a1"), session="s1", agent="a1")
        self.log(assistant("s2", usage=5), session="s2")
        self.assertEqual(self.tokens()[:3], ["TOTAL 43.2k sessions 2", "MODEL opus 43.2k", "MODEL haiku 7"])

    def test_counts_only_lines_whose_cwd_is_under_a_cwd_given(self):
        self.log(assistant("s1", usage=1, cwd="/work/repo/sub"))
        self.log(assistant("s2", usage=20, cwd="/work/repo-other"), session="s2")
        self.log(assistant("s3", usage=300, cwd="/elsewhere"), session="s3")
        self.assertEqual(self.tokens("--cwd", "/work/repo")[0], "TOTAL 1 sessions 1")
        self.assertEqual(self.tokens("--cwd", "/work/repo", "--cwd", "/elsewhere")[0], "TOTAL 301 sessions 2")
        self.assertEqual(self.tokens()[0], "TOTAL 321 sessions 3")

    def test_skips_lines_before_since_and_files_last_written_before_it(self):
        self.log(assistant("s1", usage=1, at=ago(days=10)) + assistant("s1", usage=20, at=ago(days=2)))
        self.log(assistant("s2", usage=300, at=ago(hours=1)), session="s2", age=timedelta(days=9))
        self.assertEqual(self.tokens("--since", "7d")[0], "TOTAL 20 sessions 1")
        self.assertEqual(self.tokens("--since", "30d")[0], "TOTAL 321 sessions 2")
        self.assertEqual(self.tokens("--since", ago(days=3))[0], "TOTAL 20 sessions 1")

    def test_skips_malformed_lines_and_reads_the_rest(self):
        self.log(["not json", '{"type":"assistant","usage"', '[1, "usage"]', '{"type":"assistant","message":"usage"}',
                  '{"type":"assistant","timestamp":7,"message":{"usage":{}}}',
                  {"type": "assistant", "timestamp": ago(hours=1), "cwd": CWD, "message": {"usage": {"input_tokens": "x"}}},
                  {"type": "user", "timestamp": ago(hours=1), "cwd": CWD, "message": {"content": "tool_result"}},
                  {"type": "user", "timestamp": ago(hours=1), "cwd": CWD, "message": {"content": [{"type": "tool_result"}]}},
                  ""] + assistant("s1", usage=9))
        self.assertEqual(self.tokens()[0], "TOTAL 9 sessions 1")

    def test_refuses_a_since_it_cannot_read(self):
        with self.assertRaises(SystemExit):
            self.tokens("--since", "last tuesday")


class Patterns(Case):
    def test_big_output_counts_results_of_4000_chars_or_more_by_call(self):
        self.log(assistant("s1", bash("git diff", "x" * 4000), bash("git diff", "x" * 8000), bash("git log", "x" * 3999)))
        self.assertEqual(self.patterns("big-output"), [{"kind": "big-output", "count": 2, "perWeek": 3000, "key": "Bash git diff"}])

    def test_big_output_counts_only_the_text_of_a_result_list(self):
        output = [{"type": "text", "text": "x" * 4000}, {"type": "image", "source": {"data": "y" * 90000}}]
        self.log(assistant("s1", call("Read", output, file_path="/a/shot.png")))
        self.assertEqual(self.patterns("big-output")[0]["perWeek"], 1000)

    def test_repeat_command_normalizes_paths_shas_numbers_and_quoted_strings_across_sessions(self):
        self.log(assistant("s1", bash('git show 1a2b3c4d:/repo/a.py | head -40 && grep "x y" ~/b'), bash("ls")))
        self.log(assistant("s2", bash("git show 9f8e7d6:/other/b.py | head -3 && grep 'z' ~/c/d")), session="s2")
        found = self.patterns("repeat-command")
        self.assertEqual([(p["key"], p["count"]) for p in found], [("Bash git show <sha>:<path> | head -<n> && grep <str> <path>", 2)])

    def test_repeat_command_in_one_session_only_is_no_pattern(self):
        self.log(assistant("s1", bash("make test"), bash("make test")))
        self.assertEqual(self.patterns("repeat-command"), [])

    def test_reread_is_one_file_read_in_two_sessions_or_more(self):
        self.log(assistant("s1", read("/repo/big.py"), read("/repo/big.py"), read("/repo/once.py")))
        self.log(assistant("s2", read("/repo/big.py")), session="s2")
        self.assertEqual(self.patterns("reread"), [{"kind": "reread", "count": 3, "perWeek": 300, "key": "Read /repo/big.py"}])

    def test_sequence_is_the_same_three_calls_in_two_sessions_or_a_subagent(self):
        steps = lambda n: [bash(f"cd /w/{n} && git status"), read(f"/w/{n}/x.py", "x" * 40), call("Edit", file_path=f"/w/{n}/x.py")]
        self.log(assistant("s1", *steps(1)))
        self.log(assistant("s1", *steps(2), agent="a1"), agent="a1")
        self.log(assistant("s2", bash("ls"), *steps(3)[:2]), session="s2")
        self.assertEqual([(p["key"], p["count"]) for p in self.patterns("sequence")],
                         [("Bash cd <path> && git status → Read <path> → Edit <path>", 2)])

    def test_a_call_logged_in_two_files_counts_once(self):
        calls = [bash("make lint"), bash("make lint")]
        self.log(assistant("s1", *calls))
        self.log(assistant("s2", *calls), session="s2")
        self.assertEqual(self.patterns("repeat-command"), [])

    def test_ranks_every_kind_by_tokens_per_week_and_keeps_the_top_n_of_each(self):
        for session in ("s1", "s2"):
            self.log(assistant(session, bash("cat /a", "x" * 400), bash("cat /a", "x" * 400), bash("ls", "x" * 4),
                               read("/r.py", "x" * 4000), bash("pwd", "x" * 40)), session=session)
        lines = [line for line in self.tokens("--top", "2") if line.startswith("PATTERN")]
        self.assertEqual(lines, ["PATTERN sequence ×2 ~2.2k/wk Bash cat <path> → Bash ls → Read <path>",
                                 "PATTERN sequence ×2 ~2.0k/wk Bash ls → Read <path> → Bash pwd",
                                 "PATTERN big-output ×2 ~2.0k/wk Read <path>",
                                 "PATTERN reread ×2 ~2.0k/wk Read /r.py",
                                 "PATTERN repeat-command ×4 ~406/wk Bash cat <path>",
                                 "PATTERN repeat-command ×2 ~22/wk Bash pwd"])

    def test_scales_the_window_to_a_week(self):
        self.log(assistant("s1", read("/r.py", "x" * 4000)))
        self.log(assistant("s2", read("/r.py", "x" * 4000)), session="s2")
        self.assertEqual(self.patterns("reread", "--since", "14d")[0]["perWeek"], 1000)
        self.assertEqual(self.patterns("reread", "--since", "1d")[0]["perWeek"], 14000)


class Format(unittest.TestCase):
    def test_counts_read_as_plain_k_or_m(self):
        self.assertEqual([tokens.human(n) for n in (0, 850, 999.4, 999.6, 12_345, 999_949, 999_950, 1_234_567)],
                         ["0", "850", "999", "1.0k", "12.3k", "999.9k", "1.0M", "1.2M"])

    def test_normalize_keeps_the_command_words(self):
        self.assertEqual(tokens.normalize("python3 -m unittest tests.test_cli -q > /tmp/t2.log 2>&1; tail -3 /tmp/t2.log"),
                         "python3 -m unittest tests.test_cli -q > <path> <n>>&<n>; tail -<n> <path>")


class Cli(Case):
    def test_runs_with_no_run_dir(self):
        self.log(assistant("s1", usage=12))
        r = subprocess.run([sys.executable, "-m", "podium_dashboard", "tokens"], capture_output=True, text=True, cwd=self.tmp,
                           env={**os.environ, "HOME": self.tmp, "PYTHONPATH": ROOT, "PODIUM_DIR": ""})
        self.assertEqual((r.returncode, r.stdout), (0, "TOTAL 12 sessions 1\nMODEL opus 12\n"), r.stderr)


if __name__ == "__main__":
    unittest.main()
