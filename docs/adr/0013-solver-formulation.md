# ADR-0013: Model sessions as intervals, not a boolean placement cube

**Status:** Accepted · **Date:** 2026-08-09

## Context

The Phase 0.1 spike modelled CB-CTT with one boolean per `(course, period, room)`. That
works well there: comp01 is 5,400 booleans and solves to proven optimality in seconds.

Phase 0.4 measured the same formulation at Tessera's target scale — 500 sessions, 40
rooms, an eight-hour day across five days:

| slot length | booleans | time to construct |
|---|---|---|
| 60 min | 800,000 | 1.31 s |
| 30 min | 1,600,000 | 2.77 s |
| 15 min | 3,200,000 | 5.80 s |

Seconds merely to *build* the model, before any search. CB-CTT instances are roughly
300× smaller than the real target.

## Decision

Do not carry the spike's formulation into production. Instead:

1. **Interval variables with `NoOverlap2D`.** Tessera's sessions have durations;
   CB-CTT lectures did not, which is why the spike never needed this.
2. **Integer `start[s]` and `room[s]`** rather than a boolean cube — O(sessions)
   variables instead of O(sessions × periods × rooms).
3. **Create variables only for feasible pairs.** Capacity and feature requirements rule
   out most (session, room) combinations before search begins.

## Consequences

- The model stays tractable at institutional scale.
- Some constraints are more awkward to express over intervals than over a cube, and
  the spike's encodings do not transfer directly.
- Reinforces ADR-0002's lesson from another angle: in Phase 0.1 the *phrasing* of a
  penalty decided what the solver could prove; here the phrasing of the model decides
  whether it can be built at all. The encoding is the design, not a detail of it.
