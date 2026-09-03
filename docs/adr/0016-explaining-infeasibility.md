# ADR-0016: Explain an impossible term with two engines, and count before you search

**Status:** Accepted · **Date:** 2026-09-04

## Context

Every comparable tool answers an impossible term with *"no solution found"*. Saying which
requirements cannot hold together instead is the first of the four features this project
exists for, and the planned mechanism was one: attach an assumption literal to each hard
rule, and on `INFEASIBLE` read back CP-SAT's
`SufficientAssumptionsForInfeasibility()` — a minimal set of rules that cannot all hold.

Measured against real instances, that mechanism does not run on the cases that occur.

`comp01` is a published ITC-2007 instance and, under Tessera's hard room capacity, it has
no timetable: 64 lectures need a room seating 31 or more, two rooms qualify, and the week
gives them 60 room-periods. Short by four — arithmetic, not a solver giving up.

| | at 30 s |
|---|---|
| `comp01`, default formulation | **`out_of_time`** |
| `comp01`, with a redundant cumulative | **`out_of_time`** |
| the same fact, counted in Python | **1.0 ms** |

Generated terms behave the same way: 120 sessions into two rooms needs 240 room-periods
and has 200, and CP-SAT returns nothing in fifteen seconds. **There is no `INFEASIBLE` to
read a core out of.**

Two further measurements shaped the answer:

- **A constraint that can be blamed cannot propagate.** The redundant cumulative refutes
  that pigeonhole in **0.001 s** stated unconditionally, and does not refute it at all in
  **ten seconds** from behind an assumption literal. CP-SAT keeps the semantics of an
  enforced global constraint and loses the propagator.
- **Most of Tessera's hard rules are not constraints.** Four of the seven invariants —
  capacity, features, availability, breaks — are expressed by leaving values out of a
  domain, which is what ADR-0013 requires to keep the model small. A value that is absent
  cannot be blamed, because there is no constraint to attach a literal to.

## Decision

**Two engines, and the arithmetic answers first.**

1. **A counting pre-flight** (`solver/preflight.py`). Hall's condition asked three times —
   sessions against room-periods, an instructor's teaching against the hours they are
   free, a group's classes against the week — returning the *violating set* rather than a
   verdict. A nested sweep where eligibility is a capacity threshold, a transportation
   problem over room classes where required features break the nesting. It runs before any
   model is built, on every solve.

2. **A conflict set** (`solver/explain.py`). `build(relaxable=True)` widens every domain
   and writes the filtering back as constraints, each behind one assumption literal per
   (rule, subject). It runs *after* something has already proved the term impossible,
   never as the way of finding out, on its own small budget.

Three rules govern what they may say:

- **Neither may prove a term possible.** Both relax where a session goes, so failing to
  find a shortage is not evidence of a timetable. Silence is silence.
- **An explanation attaches only to `IMPOSSIBLE`.** Rules to blame on a solve that ran out
  of time would read as a reason to change the data.
- **The conflict set is minimal, not unique.** Every member is necessary — proven by
  re-solving without each — and where several independent contradictions exist CP-SAT
  names one. No wording claims that relaxing a member is sufficient.

The sentences are looked up, not written: `INVARIANTS` carries a statement for each of the
seven and `ConstraintSpec` a summary per kind. Only the *quantity* — "64 against 60" — is
new prose, because it exists nowhere else.

## Consequences

- **The differentiator works on the instance that matters.** `comp01` is refused in about a
  millisecond with the numbers an independent reading recorded four phases earlier, and the
  twenty solvable instances are untouched.
- **A false positive is the failure mode to fear**, so every count under-states demand and
  over-states supply. One shipped for a single run — `bisect_left` where the count was
  `bisect_right` — and was caught by sweeping all twenty-one instances rather than by
  reading. A hand-built fixture would not have found it.
- **Two independent readings of one rulebook can disagree, and the disagreement is a
  defect.** The count reported a room that was big enough and shut all week as too small;
  the conflict set read the same term and named availability. ADR-0004's argument, arriving
  a layer further out than it was written for.
- **A planned lever was built, measured and removed.** Capacity-threshold cumulatives turn
  thirty seconds of nothing into a proof in milliseconds — against a baseline that no longer
  exists. Once the count runs first, no term was found across eleven impossible terms of
  four shapes where the cumulative is the thing that works.
- **Some impossible terms are still proved by nobody here.** Sessions too long to tile a day
  waste the end of every day: 26 three-hour sessions into 5 rooms across four-hour days
  needs 78 slot-units against a nominal 100 and can only ever place 25. The count relaxes
  *where*, so it sees 78 against 100 and stays quiet; CP-SAT returns nothing. Recorded in
  the backlog rather than engineered around.
- **The explaining model is bigger than the one that solves** — +56 % variables on `comp01`,
  +98 % constraints on `comp20` — which is affordable only because it is built once, after a
  failure, and never inside the search loop.
