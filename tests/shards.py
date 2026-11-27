"""Lists the suite's test files, plans them into timed chunks and runs the chunks in parallel, one file per process."""
import glob
import importlib
import json
import os
import re
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_SECONDS = 30.0


@dataclass(frozen=True)
class Chunk:
    file: str
    ids: tuple
    weight: float


@dataclass(frozen=True)
class FailedChunk:
    chunk: Chunk
    log: str


@dataclass(frozen=True)
class Result:
    ok: bool
    ran: int
    failed_chunks: list
    seconds_by_file: dict


def discover(root=ROOT, pattern="tests/test_*.py"):
    files = sorted(os.path.relpath(path, root) for path in glob.glob(os.path.join(root, pattern)))
    return {file: test_ids(_module(file)) for file in files}


def test_ids(module_name):
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return [module_name]
    tests = _flatten(unittest.defaultTestLoader.loadTestsFromModule(module))
    return [test.id() for test in tests if type(test).__module__ == module_name]


def plan(ids_by_file, timings, target=TARGET_SECONDS):
    seconds_per_test = _mean_seconds_per_test(ids_by_file, timings)
    chunks = []
    for file, ids in ids_by_file.items():
        if not ids:
            continue
        weight = timings.get(file, len(ids) * seconds_per_test)
        count = max(1, min(len(ids), round(weight / target)))
        chunks += [Chunk(file, tuple(ids[i::count]), weight / count) for i in range(count)]
    return sorted(chunks, key=lambda c: c.weight, reverse=True)


def run(chunks, workers, logs_dir, python=sys.executable, cwd=ROOT):
    os.makedirs(logs_dir, exist_ok=True)
    for old in glob.glob(os.path.join(logs_dir, "*.log")):
        os.remove(old)
    logs = [os.path.join(logs_dir, f"{i:03d}-{_module(c.file)}.log") for i, c in enumerate(chunks)]

    def run_one(chunk, log):
        started = time.monotonic()
        with open(log, "w") as out:
            code = subprocess.run([python, "-m", "unittest", "-q", *chunk.ids], cwd=cwd, stdout=out,
                                  stderr=subprocess.STDOUT).returncode
        return code, time.monotonic() - started

    with ThreadPoolExecutor(workers) as pool:
        outcomes = list(pool.map(run_one, chunks, logs))

    seconds_by_file = {}
    for chunk, (_, seconds) in zip(chunks, outcomes):
        seconds_by_file[chunk.file] = seconds_by_file.get(chunk.file, 0.0) + seconds
    failed = [FailedChunk(chunk, log) for chunk, log, (code, _) in zip(chunks, logs, outcomes) if code != 0]
    return Result(not failed, sum(_ran(log) for log in logs), failed, seconds_by_file)


def load_timings(path):
    try:
        with open(path) as f:
            timings = json.load(f)
    except (OSError, ValueError):
        return {}
    return timings if isinstance(timings, dict) else {}


def save_timings(path, seconds_by_file):
    merged = {**load_timings(path), **seconds_by_file}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(merged, f, indent=2, sort_keys=True)


def _module(file):
    return os.path.splitext(file)[0].replace(os.sep, ".")


def _flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test


def _ran(log):
    with open(log) as f:
        found = re.search(r"^Ran (\d+) tests?", f.read(), re.MULTILINE)
    return int(found.group(1)) if found else 0


def _mean_seconds_per_test(ids_by_file, timings):
    timed = [file for file, ids in ids_by_file.items() if file in timings and ids]
    tests = sum(len(ids_by_file[file]) for file in timed)
    return sum(timings[file] for file in timed) / tests if tests else 1.0
