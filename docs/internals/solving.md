# Solving

How a term becomes a timetable, how that timetable becomes a good one, and what is said when
there is no timetable at all. Six modules in `tessera/solver/` and one in
`tessera/domain/validation/`, described here as the one system they are rather than as seven
parts, because their most important properties are relationships between them.

## The shape of it

```
Snapshot ──► preflight.check ──► a shortfall?  ──yes──► IMPOSSIBLE, counted
   │              (arithmetic, no model, ~1 ms)               and explained
   │                     │ no
   ▼                     ▼
   │         model.build ──► objective.enforce ──► CP-SAT ──► a timetable
   │              │                                    │            │
   │              │                              INFEASIBLE   search.improve ◄─┐
   │              ▼                                    │            │          │
   │       explain.conflict ◄──────────────────────────┘   freeze all but a    │
   │       the rules that cannot hold together             window, re-solve,   │
   │                                                       keep what is better─┘
   │                                                              │
   └──────────────► validation.validate ◄────────────────────────┘
                    the second reading, which agrees or the build is red
```

Two phases, deliberately ([ADR-0002](../adr/0002-cpsat-fix-and-optimize.md)). Finding *a*
valid timetable and finding a good one are different problems, and at department scale
they are so different that doing them together does neither.

A third thing runs before both and is not a phase but a refusal: counting what arithmetic
already settles, so a term that cannot work is refused in a millisecond instead of after the
budget (§7, [ADR-0016](../adr/0016-explaining-infeasibility.md)).

## 1. One rulebook, read twice

The single most important rule in this subsystem, and the reason to read this section
before any other:

> **`domain/validation/` is the authority for what a timetable costs. `solver/objective.py`
> is a separate expression of the same rules, and a test asserts the two agree to the
> integer.**

Nothing in the solver calls `rules.py`, and nothing in the validator imports OR-Tools.
They share the `Snapshot` — the *state* — and no logic at all.

This looks like duplicated work and is the opposite. Two independent readings of a
specification that agree are evidence the specification was read correctly; one reading
agreeing with itself is evidence of nothing. Phase 0.1 got zero cost mismatches across
21 published instances precisely because its checker and its model were written
separately, and `tests/solver/test_agreement.py` is what keeps that true here: over
hundreds of generated terms, CP-SAT's objective equals `Report.penalty` and its
decomposition equals `penalty_breakdown`, kind for kind.

The cost of the arrangement is that sixteen rules exist twice. The benefit is that a
misreading of any of them is a red build rather than a timetable that is confidently
wrong, and there is no third place to look when they disagree.

## 2. The model, and the shape it is not

`model.build` turns a term into CP-SAT variables. The shape is constrained by
[ADR-0013](../adr/0013-solver-formulation.md) and it is worth knowing what it refuses.

**Not a boolean cube.** `x[session, period, room]` is the obvious encoding and it is
forbidden: at department scale it is 1.6 million booleans and 2.8 seconds merely to
construct, before any search. It works in the CB-CTT benchmarks because those instances
are roughly three hundred times smaller.

What is built instead:

| | |
|---|---|
| `starts[session]` | an integer whose **domain is the hours it could legally begin at** — not a range with constraints bolted on afterwards |
| `candidates[session]` | one presence boolean per **room that could actually hold it**; capacity and features rule most rooms out before the search sees them |
| `teaching[session]` | the interval the people are busy, which excludes the room's turnaround |
| `Candidate.interval` | the interval the *room* is busy, which includes it |

The two interval kinds are not a duplication. A lab that needs twenty minutes to clear is
in use for those twenty minutes; the students have left. Room clashes use the first,
instructor and group clashes the second.

Impossibility is discovered while building rather than by searching. A session with no
legal hour or no room able to hold it raises `UnsatisfiableError` naming the session,
which is a better answer than `INFEASIBLE` after thirty seconds.

## 3. The objective, and why every term is clamped

`objective.py` expresses the sixteen rules as arithmetic over those variables. Two things
about it are load-bearing.

**Every term is non-negative.** Phase 0.1's first optimising run returned cost 5 with a
lower bound of **−7**, because room stability was written as `sum(uses_room) - 1` and a
course in one room contributed minus nothing. An objective that can go below zero lets
the solver "improve" a constraint into meaninglessness, and the bound it derives is
unsound. `Solution` refuses a negative penalty and a negative bound, and every unit
variable is clamped by construction.

**Weights come from the constraints, never from constants.** The rules screen has sliders;
an objective with hard-coded weights would make them decorative, which is the worst kind
of interface defect because it looks like it works. A hard rule contributes nothing to the
cost and is pinned to zero violations instead — refused, not priced.

`enforce()` writes only that hard half. It exists because the feasibility phase must obey
the hard distribution rules without carrying the cost of the soft ones, and three of the
sixteen soft terms are expensive enough to prevent a first answer existing at all.

## 4. Why feasibility runs alone

Three of the sixteen rules — idle hours for a group, idle hours for an instructor, hours
in a row — are about *hours*, so each needs a boolean per subject per hour. Measured at
500 sessions, 40 rooms and a hundred-hour week:

| | variables | first answer within 30 s |
|---|---|---|
| hard rules only | 20,500 | **yes, proven optimal in 4.6 s** |
| every rule, scored | 182,694 | **no answer at all** |

`default_constraints()` starts every new term with group gaps at weight 8, so that is the
ordinary configuration and not an exotic one. Carrying the objective into the search for a
first answer is what stops there being one.

## 5. Fix-and-Optimize

`search.improve` takes the feasible timetable and makes it better. A round freezes almost
everything, re-solves a window, and keeps the result only if it is strictly better.

**Freezing narrows a domain; it does not add a constraint.** This is the whole reason a
round is affordable. A session pinned by an equality still owns a boolean for every hour it
could have started at and every room it could have been in, and the objective channels all
of them — so the model is built in full and merely told not to use most of it. A session
with one legal start and one candidate room contributes one boolean per channel:

| at 500 sessions | variables | built in |
|---|---|---|
| nothing frozen | 182,694 | 2.15 s |
| **40 of 500 free** | **40,531** | **0.46 s** |

The frozen sessions keep their variables rather than disappearing, because the objective
scores the **whole** timetable and not the window. A round's cost is what the term costs,
which is what makes accepting a round a comparison of like with like.

**A round cannot make things worse.** The incumbent is a feasible point of every
sub-problem — the frozen sessions are already at their values, the free ones may simply
stay — so a round hinted with it returns something at or below what it started with.
Accepting only a strict improvement makes the descent monotone, and `Solution` refuses a
trajectory that rose.

**A round's lower bound is not the term's.** It bounds a restricted problem, which is
easier. Reporting it would make a timetable "proven optimal" because forty of its five
hundred sessions are. Only an unrestricted solve sets `lower_bound`, and
`bound_is_proven` says whether anything did.

### What decides a window

`neighbourhood.py` holds the strategies, each a plain function of the term, the timetable
in hand and a seeded `Random`. The loop rotates through them, because they are blind in
different places: one frees a day, one a subject's whole week, one the sessions carrying
the most cost, and one at random.

The random one is the control and is in the set on purpose. A strategy that cannot beat
it is not a strategy.

Two rules hold for all of them and are tested as properties over the registry, so a fifth
inherits both by being registered: **a window is never empty**, and **a window never
contains a pinned session**. The second is the one that would be a lie rather than an
inefficiency — the timetable would come back better, so nobody would read it closely.

## 6. Budgets, and why there are two kinds

A budget in seconds and a reproducible answer are not compatible: how much a solver gets
done in thirty seconds depends on the machine. CP-SAT counts its own progress in a
machine-independent unit, and `Budget` carries both.

| | for |
|---|---|
| `seconds`, `round_seconds` | a person waiting, and a ceiling that must not be reached |
| `deterministic_seconds`, `round_deterministic_seconds` | benchmarks and tests, which must mean the same thing on any machine |
| `rounds` | the same, for the loop — how many rounds fit in a minute is not reproducible, how many were asked for is |

**A test may not assert a wall-clock outcome.** This is not a style preference: the
department-scale test asked for thirty seconds and asserted that optimisation rounds had
run, and on CI's slower hardware the setup consumed the budget, no round started, and
`main` went red on a branch that had been green. The solver was right — it returned a
valid, complete, correctly scored timetable — and the test was wrong. Wall-clock figures
belong in the phase records, beside the hardware they were measured on.

## 7. Saying why there is no timetable

Two engines answer that, and they fail in opposite places. Everything here is bounded by one
rule: **both can prove a term impossible and neither can prove one possible.** Each relaxes
where a session actually goes, so silence means nothing was proven — not that all is well.

### The count runs first

`preflight.check` asks Hall's condition three times — sessions against room-periods, an
instructor's teaching against the hours they are free, a group's classes against the week —
and returns the *violating set* rather than a verdict.

It exists because the obvious mechanism does not fire. On `comp01`, which has no timetable
under Tessera's hard capacity, CP-SAT returns `out_of_time` at thirty seconds under every
formulation this project has; the same fact counted takes about a millisecond:

> 64 sessions needing a room that seats 31 or more need 64 hours, and the rooms that could
> take them offer 60 — 4 short.

Two algorithms, chosen by the shape of the term. Where a room's eligibility is decided by
capacity alone the eligible sets are **nested** — anything that fits a room seating a hundred
fits every larger one — so Hall's condition needs testing only at each distinct threshold,
which is a sorted sweep. Required features order as a lattice rather than a chain, and those
fall to a transportation problem over room classes. A test asserts the two agree; the flow is
the definition and the sweep is the fast case.

**A false positive is the failure to fear.** Reporting a shortage that is not there refuses a
term somebody could have run, in milliseconds, with an authoritative number attached. So every
count under-states demand and over-states supply: a session demands its duration and not the
room's turnaround, and a room supplies every teaching slot it is not closed in even though a
session could not start in the last of them.

Two things that look like details and are not:

| | |
|---|---|
| **Thresholds are session headcounts, not room capacities** | `comp01`'s binding threshold is 31 and no room seats exactly 31. Keyed on capacities the same argument proves nothing |
| **Sessions in alternating weeks are counted apart** | Sixteen hours for one group in an eight-hour week is feasible when half of them are fortnightly, and counting them together would invent an impossibility |

### The conflict set runs second, and only after a proof

`explain.conflict` builds the same term with every hard rule behind an assumption literal,
asserts them all, and reads back the subset that cannot hold. It answers what no count can
see — two rooms, two hours of teaching, a week of eight, and one instructor pinned into both
at nine o'clock. Nothing is short of anything; the arrangement is simply impossible.

**Why it cannot go first.** A constraint behind a literal keeps its meaning and loses its
propagation. The same redundant cumulative refutes a 120-session pigeonhole in **0.001 s**
stated unconditionally and does not refute it at all in **ten seconds** from behind a literal.
So the relaxing model is strictly worse at refuting than the model that just refuted the term,
and asking it first would trade a proof for a sentence and often get neither.

**Why the model is a mode of `build` and not a second builder.** Four of the seven invariants
are enforced by leaving values out of a domain, and a missing value cannot be blamed — there
is no constraint to attach a literal to. So the relaxable model widens the domains and writes
the rules back as constraints. Doing that in a second builder would be a *third* reading of
the rules, and §1's argument applies: the symptom would be an explanation naming a rule the
solver does not enforce. The break rule is derived from `TimeGrid.can_hold` for the same
reason — the starts that fit the day and that `can_hold` still refuses are exactly the ones a
break blocks.

One literal per **rule per subject**. Per rule alone gives seven and a set that says
"instructors clash" while naming nobody; per session gives thousands. Per subject is the
granularity somebody can act on, and hard distribution rules are per constraint *row* rather
than per kind, because an institution with four `SAME_DAY` rules needs to be told which one.

### What the answer is allowed to claim

`Solution.explanation` is attached to `IMPOSSIBLE` and to nothing else. `OUT_OF_TIME` means
the search ran out, which says nothing about whether a timetable exists, and rules to blame
beside it would read as a reason to change data that may be fine.

The conflict set is **minimal but not unique**. Every member is necessary — `explain`'s own
deletion filter re-solves with each relaxed in turn, and the tests run it on every conflict
they check — but where several independent contradictions exist CP-SAT names one and never
mentions the others. So the report says every requirement listed is needed, and says outright
that relaxing one is not a promise that a timetable appears.

The sentences are looked up rather than written: `INVARIANTS` carries a statement for each of
the seven and `ConstraintSpec` a summary per kind, both already shown on the rules screen. The
only new prose is the quantity, because it exists nowhere else.

### What neither can prove

Sessions too long to tile a day. Twenty-six three-hour sessions into five rooms across
four-hour days needs 78 slot-units against a nominal 100, and can only ever place 25 — one per
room per day. The count relaxes *where*, so it sees 78 against 100 and stays quiet; CP-SAT
returns nothing in fifteen seconds. It is in the backlog, and it is the honest edge of what
this subsystem does.

## 8. Where to look when something is wrong

| Symptom | Look at |
|---|---|
| The score reported differs from the score optimised | `objective.py` and `tests/solver/test_agreement.py`, which exist to make this impossible |
| A negative lower bound, or one above the best solution | `result.py` → `Solution._the_score_makes_sense` |
| `is_optimal` is true and should not be | `result.py` → `bound_is_proven`; a round bounds its own window |
| A timetable comes back worse than the one that went in | `search.py` acceptance, and `Solution._the_descent_makes_sense` |
| A solve burns the whole budget improving nothing | `search.py` → `_keep_going`; a penalty of zero ends the loop |
| Every round reports finding nothing | the window is too large for the round's budget — `Budget.window` |
| A sub-problem is rejected outright | `search.py` → `_run` raises on `MODEL_INVALID`; usually a variable hinted twice |
| A moved session lands somewhere impossible | `model.py` — start domains and candidate rooms |
| `NotScorableError` | a constraint kind with no term in `objective.TERMS` |
| A term is refused that could really be solved | `preflight.py` — every count must under-state demand and over-state supply |
| A solve says "impossible" and explains nothing | `Budget.explain_seconds` ran out, or the relaxable model is weaker than what refuted the term |
| A conflict names rules that are not really in conflict | `explain.py` → `necessary_one_at_a_time`, which the tests run on every conflict |
| A hard rule can never be blamed | it was written without a literal — `build(relaxable=True)` and `objective.enforce(relaxable=True)` |

`MAP.md` in the planning workspace carries the same table for the whole codebase.
