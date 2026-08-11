# ADR-0002: CP-SAT driven by Fix-and-Optimize, not a pure metaheuristic

**Status:** Accepted · **Date:** 2026-08-07

## Context

University course timetabling is NP-hard. The obvious approach is a metaheuristic —
simulated annealing or tabu search — which is what most hobbyist implementations use and
what won the 2007 competition.

The 2019 competition, on a far more realistic formulation, was won by a **Fix-and-Optimize
matheuristic**. Second place was pure MIP. Simulated annealing came third. Across the
literature the pattern holds: richer, more realistic formulations are won by exact
methods wrapped in a heuristic outer loop.

## Decision

Use OR-Tools CP-SAT as the engine, driven by a Fix-and-Optimize / Large Neighbourhood
Search loop: freeze most of the timetable, re-solve a window to optimality, keep
improvements, repeat.

## Consequences

- Hard constraints become real constraints. Violating one is impossible by
  construction rather than merely penalised.
- Pinning is free — a pinned assignment is a fixed variable — which makes
  "re-optimise around my manual edits" nearly no work.
- Solution callbacks give anytime behaviour natively, so the UI can stream improving
  solutions and let the user stop when satisfied.
- Apache 2.0 and free, unlike Gurobi or CPLEX.
- **The outer loop is load-bearing, not an optimisation.** Phase 0.1 measured raw
  CP-SAT at a median +144 % gap to best-known results, and five times the time budget
  did not close it.
