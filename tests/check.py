"""`python3 -m tests.check [step ...] [--update] [--workers N]`: runs the named check steps, all of them by default."""
import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional, Union

from tests import shards

ROOT = shards.ROOT
CHECK_DIR = os.path.join(ROOT, ".check")
LOG_TAIL = 40

Command = Union[Callable[[int], int], list]


@dataclass(frozen=True)
class Step:
    name: str
    run: Command
    update: Optional[Command] = None


def unit(workers):
    if not shutil.which("node"):
        print("node not found: the page tests need Node, install it and rerun")
        return 1
    timings_path = os.path.join(CHECK_DIR, "timings.json")
    ids_by_file = shards.discover()
    chunks = shards.plan(ids_by_file, shards.load_timings(timings_path))
    started = time.monotonic()
    result = shards.run(chunks, workers, os.path.join(CHECK_DIR, "logs"))
    failed_files = {failed.chunk.file for failed in result.failed_chunks}
    shards.save_timings(timings_path, {file: seconds for file, seconds in result.seconds_by_file.items()
                                       if file not in failed_files})
    print(f"ran {result.ran} tests in {len(ids_by_file)} files, {len(chunks)} chunks, "
          f"{time.monotonic() - started:.0f}s")
    for failed in result.failed_chunks:
        _report(failed)
    return 0 if result.ok else 1


def _report(failed):
    with open(failed.log) as f:
        lines = f.read().splitlines()
    print(f"\n{failed.chunk.file} failed, log {failed.log}")
    for line in lines:
        if line.startswith(("FAIL:", "ERROR:")):
            print(f"  {line}")
    print("\n".join(lines[-LOG_TAIL:]))


STEPS = [Step("unit", run=unit)]


def main(argv):
    parser = argparse.ArgumentParser(prog="python3 -m tests.check")
    parser.add_argument("steps", nargs="*", help="steps to run, all by default")
    parser.add_argument("--update", action="store_true", help="run each step's update command instead")
    parser.add_argument("--workers", type=_positive, default=os.cpu_count())
    args = parser.parse_args(argv)

    by_name = {step.name: step for step in STEPS}
    unknown = [name for name in args.steps if name not in by_name]
    if unknown:
        print(f"unknown step {', '.join(unknown)}; steps: {', '.join(by_name)}")
        return 2

    failed = False
    for step in [by_name[name] for name in args.steps] or STEPS:
        command = step.update if args.update else step.run
        if command is None:
            print(f"{step.name}: nothing to update, skipped")
            continue
        started = time.monotonic()
        code = _execute(command, args.workers)
        print(f"{step.name}  {'PASS' if code == 0 else 'FAIL'}  {time.monotonic() - started:.0f}s")
        failed |= code != 0
    return 1 if failed else 0


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {value}")
    return number


def _execute(command, workers):
    if callable(command):
        return command(workers)
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
