# ADR-0008: Solve jobs run in-process; no Celery, no Redis

**Status:** Accepted · **Date:** 2026-08-07

## Context

Solving takes seconds to minutes, so it cannot block an HTTP request. The reflexive
answer is a task queue with a broker.

## Decision

An in-process async task registry. `POST /solve` returns a job id, progress streams over
Server-Sent Events, and cancellation is a flag the solver checks.

## Consequences

- Nothing extra ships inside the `.dmg`. A Redis binary bundled into a single-user
  desktop application would be a real cost paid for no benefit.
- Jobs do not survive an engine restart. Acceptable: a solve is seconds to minutes, and
  the timetable it started from is already persisted.
- Server mode with many concurrent users would need revisiting. That is out of scope
  for v1 and the decision is cheap to revisit then.
