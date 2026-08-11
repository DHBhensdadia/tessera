# ADR-0012: Validation endpoints take an explicit viewport

**Status:** Accepted · **Date:** 2026-08-09

## Context

Live conflict highlighting can be built two ways: ask per cell as the cursor moves, or
ask once at drag start for every cell in the grid.

Phase 0.2 measured both. The whole-grid call was 6.1 ms p99 at department scale — and
**43 ms p99 with a 214 KB payload** at the NFR-9 ceiling, missing the frame budget by
2.7×. At that size the validation compute itself dominates: 25,000 cells at ~0.9 µs each.

An unscoped endpoint would therefore pass every test on ordinary data and fail only for
the institutions with the most of it, only in production.

## Decision

Every validation endpoint takes an explicit viewport — a room set and a period range.
**No unscoped whole-grid variant exists**, not as a convenience and not as a default.

## Consequences

- The visible grid stays small however large the institution, because a timetable view
  shows one pivot: one group, one instructor, or one room. Measured at 7.4 ms p99 over
  ceiling-scale data.
- Clients must state what they are looking at, which they know anyway.
- The recommended drag implementation is one viewport call on mouse-down, no calls
  during the drag, and one confirming `validate-move` on drop — roughly 600× less
  transport than validating per frame.
