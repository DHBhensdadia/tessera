# ADR-0015: Direct commits to main; protection limited to force-push and deletion

**Status:** Accepted · **Date:** 2026-08-09

## Context

The obvious workflow — branch, pull request, required status checks, merge — is correct
for a team and largely ceremonial for one person.

Of the things a pull request provides, review is the main one, and it is worth nothing
when the author and the reviewer are the same person. A record of intent is already
carried by commit messages. The one thing a PR genuinely buys is **CI green before
`main` moves**.

That can be had more cheaply. The full gate set runs locally in about three seconds and
pre-commit runs most of it automatically, so the practice that actually keeps `main`
green is running the checks before pushing. CI is the backstop, not the gate.

Requiring status checks would not have helped either: GitHub applies them only to pull
requests, so enabling them forces a PR for every change, including a typo fix.

## Decision

- **Commit directly to `main`** for ordinary work.
- **Use a branch** when work is large, risky, or leaves the tree broken partway. Merge
  it when green. A pull request is available when a diff view or a written record is
  actually wanted, and is not required.
- **Protect `main` against force-pushes and deletion only.** No required reviews, no
  required status checks.
- CI runs on every push to every branch, so a branch can be seen to be green without
  opening a pull request against it.

## Consequences

- No ceremony for small changes; no waiting on CI to continue working.
- `main` can go red. On a project with no dependants that costs little, provided it is
  fixed forward promptly. The CI badge is in the README, so a habitually red `main`
  looks bad regardless of whether it matters technically — which is an argument for
  running the gates locally, not for reinstating ceremony.
- The one irreversible git accident — a mistyped `git push --force` rewriting history —
  remains blocked. That protection costs nothing day to day.
- Revisit if the project gains contributors. Pull requests become genuinely valuable
  the moment someone else's code needs reading before it lands.
