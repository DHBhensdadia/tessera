"""The exit test: the objective and the validator produce the same integer.

**Why this and not P5's test.** P5 asked that raising a weight measurably reduce that
violation class. That was written when nothing scored anything — but 4.1 already computes the
score, so this phase is not inventing scoring, it is expressing the same sixteen rules a
second time in CP-SAT's language. And "raising a weight reduces the violations" can pass while
both implementations are wrong in **the same direction**. Agreement to the integer cannot.

The reason to trust the arrangement is measured rather than argued: Phase 0.1 got **zero cost
mismatches across 21 published instances** precisely because its checker and its model were
separate readings of the specification. Two readings that agree are evidence. One reading
agreeing with itself is not — which is why the solver never calls `rules.py`, and why a
disagreement here is a bug found by a test rather than a silent difference between what was
optimised and what gets reported.

**The objective is read away from its optimum on purpose.** The first version of this file
called `solve`, which minimises; on instances this small it reached zero every time, so the
test compared zero with zero across eighty-seven solved terms and would have passed with every
one of the eight rules unwritten. Measured, not suspected. So the model is now pointed at the
*dearest* timetable as often as the cheapest, which is where a miscounted term actually shows.

All sixteen kinds are covered: the eight over named sessions, and the eight scoped to an
instructor, a group or a course. `SCORED` is the registry itself rather than a list, so a
seventeenth kind joins these tests by existing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, assume, find, given, settings
from hypothesis import strategies as st
from hypothesis.errors import UnsatisfiedAssumption
from ortools.sat.python import cp_model

from tessera.domain.constraints import ConstraintKind
from tessera.solver import Budget, Outcome, Placed, solve
from tessera.solver.model import UnsatisfiableError, build
from tessera.solver.objective import TERMS, add
from tests.domain.validation.generated import Instance
from tests.solver.generated import judge, snapshot_of, to_enforce, to_score

#: Every kind there is, taken from the registry so nothing can be left out of these tests
#: by being left out of a list.
SCORED = frozenset(TERMS)

THOROUGH = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.filter_too_much,
    ],
)

#: Where to point the objective. "anywhere" leaves the model a satisfaction problem, so the
#: answer is whatever CP-SAT reaches first — an arbitrary point, which is the case agreement
#: is actually a claim about.
AIMS = st.sampled_from(["cheapest", "dearest", "anywhere"])


@dataclass(frozen=True)
class Scored:
    """A timetable, and what the objective made of it."""

    penalty: int
    breakdown: dict[str, int]
    placements: tuple[Placed, ...]


def score_at(instance: Instance, aim: str) -> Scored:
    """Build the model, aim the objective, and read back what it says.

    Deliberately not `solve`, which always minimises. The claim being tested is that the two
    implementations agree about *any* timetable, and the optimum is the one arrangement where
    a term that always returns zero would look correct.

    A term with no timetable, or with nothing to score, raises `UnsatisfiedAssumption` — the
    exception `assume` itself raises, so Hypothesis discards the example and goes looking for
    a better one rather than counting it as a pass.
    """
    snapshot = snapshot_of(instance)
    try:
        model = build(snapshot)
    except UnsatisfiableError:
        raise UnsatisfiedAssumption("no session can go anywhere") from None

    objective = add(model, snapshot)
    if objective is None:
        raise UnsatisfiedAssumption("nothing in this term is priced")
    if aim == "cheapest":
        model.cp.minimize(objective.total)
    elif aim == "dearest":
        model.cp.maximize(objective.total)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    if solver.solve(model.cp) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise UnsatisfiedAssumption("this term has no timetable")

    return Scored(
        penalty=objective.penalty(solver),
        breakdown=objective.breakdown(solver),
        placements=tuple(
            Placed(
                session=session_id,
                start_slot=solver.value(model.starts[session_id]),
                room=model.room_of(solver, session_id),
            )
            for session_id in sorted(model.starts)
        ),
    )


@given(instance=to_score(SCORED), aim=AIMS)
@THOROUGH
def test_the_objective_is_exactly_the_validators_penalty(instance: Instance, aim: str) -> None:
    """The phase's exit criterion.

    Not "close", not "the same ordering" — the same integer, and the same decomposition kind
    for kind. Anything less would mean the solver optimised one number and the interface
    reported another.
    """
    found = score_at(instance, aim)

    report = judge(instance, found.placements)

    assert found.penalty == report.penalty
    assert found.breakdown == report.penalty_breakdown


@given(instance=to_score(SCORED), aim=AIMS)
@THOROUGH
def test_a_scored_timetable_is_still_a_valid_one(instance: Instance, aim: str) -> None:
    """Optimising must not cost feasibility.

    A solver that shed a hard rule to reach a better score would look like an improvement in
    every number this phase reports. 4.2's property, re-asserted with the objective in place
    and with rules present — which 4.2's own instances deliberately had none of.
    """
    found = score_at(instance, aim)

    report = judge(instance, found.placements)

    assert report.is_feasible
    assert report.is_complete


@given(to_enforce(SCORED))
@THOROUGH
def test_a_hard_rule_is_obeyed_rather_than_paid_for(instance: Instance) -> None:
    """A gap 4.2 left: its model never read `snapshot.constraints` at all, so a hard
    distribution rule was neither enforced nor scored, and the solver could return a
    timetable the validator called invalid. Nothing noticed, because 4.2's generated
    instances carried no rules."""
    found = solve(snapshot_of(instance), Budget(seconds=10))
    assume(found.solved)

    report = judge(instance, found.placements)

    assert report.is_feasible
    assert found.penalty == 0, "a hard rule is refused, not priced"


@given(to_score(SCORED))
@THOROUGH
def test_solving_reports_the_score_it_optimised(instance: Instance) -> None:
    """The same agreement, through the path a caller actually uses.

    `score_at` reads the objective off the model; this checks that `solve` carries the same
    number out to `Solution`, decomposition and all. Two different mistakes, and the second
    one is the kind that only shows in the interface.
    """
    found = solve(snapshot_of(instance), Budget(seconds=10))
    assume(found.solved)

    report = judge(instance, found.placements)

    assert found.penalty == report.penalty
    assert found.penalty_breakdown == report.penalty_breakdown
    assert sum(found.penalty_breakdown.values()) == found.penalty


@given(to_score(SCORED))
@THOROUGH
def test_the_bound_is_sound(instance: Instance) -> None:
    """Never negative, never above the best solution found.

    `Solution` refuses to carry either, so in practice this fails as an exception out of
    `solve` rather than here — which is the point. Phase 0.1 reported cost 5 against a lower
    bound of **-7** for a whole phase, because the only thing reading the number was a person
    skimming a table.
    """
    found = solve(snapshot_of(instance), Budget(seconds=10))
    assume(found.outcome is not Outcome.IMPOSSIBLE)

    assert found.lower_bound >= 0
    if found.solved:
        assert found.lower_bound <= found.penalty


@pytest.mark.parametrize("kind", sorted(SCORED))
def test_this_kind_can_be_seen_to_cost_something(kind: ConstraintKind) -> None:
    """The guard on the guard, and the reason it exists is that this file already failed it.

    The first version of these tests passed on three hundred examples while every solved term
    scored **zero** — `solve` minimises, and on instances this small it reaches an optimum of
    nothing. Eight rules could have been left unwritten and the suite would have been green.

    So each kind must be *shown* to reach a non-zero cost on the strategy the agreement tests
    actually use. `find` searches for such a term and raises when there is none, which turns
    "the tests exercise all eight rules" from something measured once into something the
    suite re-establishes on every run.
    """
    find(
        to_score(frozenset({kind})),
        lambda instance: bool(score_at(instance, "dearest").penalty),
        settings=settings(
            max_examples=400,
            deadline=None,
            database=None,
            # Reproducible on purpose. Some kinds need an uncommon shape to cost anything at
            # all — `RESPECT_INSTRUCTOR_PREFERENCES` wants a *soft* unavailable hour on an
            # instructor who then teaches in it, which a random draw finds a couple of times
            # in a hundred. A search that passes most runs is a test that fails some, and a
            # flaky guard gets ignored, which is the one thing a guard cannot afford.
            derandomize=True,
        ),
    )


@given(instance=to_score(SCORED), aim=AIMS)
@THOROUGH
def test_the_breakdown_names_only_rules_the_term_has(instance: Instance, aim: str) -> None:
    """A kind in the breakdown nobody asked for would mean the objective invented a cost —
    and the penalty would still agree with the validator if the validator invented the same
    one."""
    found = score_at(instance, aim)

    asked = {c.kind.value for c in instance.constraints if not c.is_hard and c.weight}

    assert set(found.breakdown) <= asked
    assert sum(found.breakdown.values()) == found.penalty
