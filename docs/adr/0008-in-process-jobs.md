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

## Revisited, 2026-09-04 (Phase 4.7)

The decision holds. Nothing extra ships inside the `.dmg`, and solving as an in-process job is
still the right shape for one engine serving one file. Two sentences in it were written before
there was a solver, and both turned out to be half the story.

### *"Cancellation is a flag the solver checks"*

A flag is read at loop boundaries. On a term whose model fits under `Budget.whole_model_ceiling`
the one unrestricted attempt takes the whole clock, so there is no boundary to read it at — on
`comp02` under the default preferences, a thirty-second solve reaches **no round at all**. A
cancel would have been answered thirty seconds after it was asked for.

`CpSolver.stop_search()` is thread-safe and ends a running search in 0.206 to 0.267 s. It also
does nothing at all between two solves, because the wrapper it reaches is created inside
`solve()` and cleared when that returns — so a request landing while a model is being built in
Python, which at department scale is two seconds of the ordinary case, reaches nothing.

So cancellation is both, and `Stop.running()` keeps them in step by telling the caller when a
request has already arrived, so it can decline to start a search it has been asked to abandon.
A window of a few microseconds remains between that check and CP-SAT creating its wrapper; the
cost is one slice, bounded by `round_seconds` or `whole_seconds`.

### *"An in-process async task registry"*

Accurate, but the load-bearing part is that the solve runs on a **thread** and the progress
stream **polls** rather than being pushed to.

OR-Tools releases the GIL, so an asyncio loop beside a running solve ticks at 1.046 ms against
1.023 ms idle, and even at five hundred sessions the loop's worst stall is 27.5 ms of Python
building a model. The job holds one status object which the worker replaces wholesale, and every
connected stream reads that attribute on its own schedule — so there is no queue, no lock, and
nothing marshalling between threads.

### One thing this ADR did not anticipate

A library that dies on a model it has itself validated. OR-Tools 9.15.6755 raises `IndexError`
from its own presolve on a term Tessera can construct, so `solve` catches what the library
raises and reports it rather than dying with it — by exception type, so a failure we could fix
stays loud. `docs/internals/solving.md` §8 carries the detail.
