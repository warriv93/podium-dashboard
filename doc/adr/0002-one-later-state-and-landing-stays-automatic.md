# 2. One Later state, and landing stays automatic

Date: 2026-11-26

## Status

Accepted

## Context

A milestone could be `later` or `parked` (shown as Paused). Filters, sort, the unstarted logic and reopening treated them the same; only the icon differed. The states the user could set (Open, Paused, Closed) sat inside the priority menu, and the status pill itself did nothing on click.

## Decision

- `later` is the one stored state for a milestone put off. `parked` becomes `later` on load, refresh and save, and the page converts it too since it reads `podium.json` from disk. The server accepts `POST /status?to=later` and keeps `paused` as an alias.
- The status pill is a pulldown, like the priority pill, on the side panel and on an open card. It lists the lifecycle in order: Ready, Later, Planning, Working on, Landed, Dropped.
- Only Ready (reopen, back to draft or todo from `resumeTo`), Later and Dropped can be set by hand. Planning, Working on and Landed are shown greyed with what sets them, since the run owns them.
- Landed is never set by hand. A milestone lands when all its stories are done and all its PRs are merged, through the server's periodic check.

## Consequences

- Landed stays a promise: every story is done and every PR merged. Work that landed outside Podium cannot be marked landed from the page; it has to reach that state through its stories and PRs.
- `later` was already a value older Podiums render, so shared runs stay readable by them.
- The priority menu shows priority only.
