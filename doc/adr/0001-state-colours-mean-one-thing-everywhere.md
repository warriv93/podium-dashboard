# 1. State colours mean one thing everywhere

Date: 2026-11-26

## Status

Accepted

## Context

The page coloured a finished story purple in a card's progress dots and in the merged-wave chips, while a landed milestone, a done badge and a merged event were green. Purple also marked "Writing tests" in the time breakdown. A reader had to learn which surface used which colour for "finished", and a glance at a card's dots said less than it should.

## Decision

A state has one colour on every surface that shows the state of a story or milestone:

- green: finished (a story done or merged, a milestone landed or merged to its branch)
- blue (the accent): working on
- red: failed or blocked
- amber: waiting on approval or on the user
- grey: not started

Pull request pills and PR events keep GitHub's colours, purple for merged and green for open, because they show a PR's state as GitHub reports it, and a reader recognises them from GitHub.

New states pick from this set before adding a colour. Purple stays free for PR merges and for categories that are not states, such as the "Writing tests" slice of the time breakdown.

## Consequences

- A card's dots read at a glance: green done, blue in progress, red failed.
- An open PR and a finished story are both green. They sit in different elements (a PR pill and a story dot or chip), so the clash is small, but a PR pill should never be used to show a story's state.
- The `--fold-ink` variable is gone; merged-wave chips use `--green` and `--green-soft`.
