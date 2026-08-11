# ADR-0004: One constraint validator, shared by the solver and the UI

**Status:** Accepted · **Date:** 2026-08-07

## Context

Two components need to know whether a placement is legal: the solver, scoring
candidates, and the drag-and-drop editor, deciding whether to highlight a cell red
before the user releases.

The tempting implementation is a fast local check in Swift for the UI and the real
logic in Python for the solver.

## Decision

There is exactly one validator, in `tessera/domain/`. The Swift client never decides
legality; it asks the engine.

## Consequences

- The UI cannot approve a placement the solver rejects, because it is not making the
  decision.
- Every drag interaction depends on round-trip latency. Phase 0.2 measured p99 at
  0.68 ms at department scale and 0.51 ms at ten times that, against a 16 ms budget.
- The validator must be index-backed rather than scanning sessions, or it becomes O(n)
  and fails the budget for reasons unrelated to transport.
- Two implementations would drift, and the resulting bugs — the UI permitting what the
  solver forbids — would be close to unreproducible.
