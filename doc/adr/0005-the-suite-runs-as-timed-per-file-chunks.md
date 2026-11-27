# 5. The suite runs as timed per-file chunks

Date: 2026-11-27

## Status

Accepted

## Context

The whole suite takes about 16 minutes run file after file. Running one process per test file, six at a time, still takes about 10.5 minutes: test_sync, test_server, test_collab and test_page each take 5 to 8 minutes on their own when the machine is busy. The tests are CPU-bound on the git, python and node processes they start, so more workers than cores buys nothing. There is no CI; checks run locally before each merge.

The page tests skip themselves when Node is missing and still report OK.

## Decision

`python3 -m tests.check` runs the suite. Its `unit` step lists each test file's tests, cuts every file into chunks of about 30 seconds from the last run's timings (by test count when there are none yet), and runs the chunks on one worker per core, heaviest first. A process only ever runs tests of one file, so tests keep the isolation they have when run file by file.

The `unit` step fails when Node isn't installed rather than let the page tests skip.

The command is a list of named steps run one after another; each step is a command and, optionally, an update command that `--update` runs instead. The browser steps join the list as their own entries.

## Consequences

- The suite takes about 4 minutes on a 10-core machine, so running it before every merge is practical.
- A new test file is picked up by its name, `tests/test_*.py`, with no change to the runner.
- Timings and logs live in `.check/`, ignored by git; the first run on a fresh clone balances by test count and is slower.
- Two files never share a process, so a file whose tests leak environment changes can't break another file's tests; such a leak inside one file still can, as before.
