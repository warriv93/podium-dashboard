# 3. Identity comes from the run's folder

Date: 2026-11-26

## Status

Accepted

## Context

In a shared run each person's claims, needsYou and events are keyed by `me`. Without `$PODIUM_ME` or `podium whoami`, `me` was the local part of `git config user.email` read in the process's working directory. The server is usually started from the podium-dashboard checkout, whose repo-local email can differ from the one used for the run's work, so a work run showed the user under a personal identity.

## Decision

`me` resolves in this order: `$PODIUM_ME`, then the name `podium whoami` stores in `~/.podium/human.json`, then the local part of `git config user.email` read from the run's folder (the parent of its `podium/` directory), then `$USER`.

`podium whoami` stays global and is the override for a machine where git config does not tell identities apart.

## Consequences

- Per-folder git identities (repo-local config or `includeIf`) decide who you are in each run, with no Podium setting.
- Starting the server from any directory gives the same identity for a run.
- A run folder outside any repo falls back to the global git email.
