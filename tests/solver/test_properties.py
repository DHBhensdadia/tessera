"""What the solver claims, checked by something that shares none of its reasoning.

Phase 0.1 reported FEASIBLE on all 21 instances, and a checker that always returned "no
violations" would have produced identical output. The same is true one level up: a solver that
returned any old arrangement and called it solved would pass every test that only asks the
solver. So the positive half is judged by the 4.1 validator, and the negative half — the
refusals — by brute force, which owes nothing to CP-SAT at all.

Both halves matter. A solver that never says "no" is as useless as a validator that never says
"yes", and it is the easier of the two mistakes to ship: nothing in a green suite notices a
solver that quietly declares hard instances impossible.
"""

from __future__ import annotations

from dataclasses import replace

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from tessera.domain.entities import Session
from tessera.domain.time_grid import TimeGrid
from tessera.solver import Budget, Outcome, solve
from tests.domain.validation.generated import Instance
from tests.solver.generated import any_valid_timetable, judge, snapshot_of, to_solve

THOROUGH = settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

#: Small enough that trying every arrangement is cheap. Used only for the refusal half.
TINY = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.filter_too_much,
    ],
)


def _tiny() -> st.SearchStrategy[Instance]:
    """Instances small enough to brute-force: a couple of sessions, a couple of rooms, and a
    week of a few hours. Derived from the same generator so the *shapes* stay the ones that
    cause trouble — nested groups, week patterns, turnaround — only smaller."""
    return to_solve().map(_shrink).filter(lambda i: len(i.sessions) <= 3)


def _shrink(instance: Instance) -> Instance:
    grid = TimeGrid(
        days=1,
        slots_per_day=3,
        slot_minutes=60,
        day_start_minute=9 * 60,
        break_slots=frozenset(),
    )
    return replace(
        instance,
        grid=grid,
        sessions=[_short(s) for s in instance.sessions[:3]],
        rooms=instance.rooms[:2],
        unavailability=[u for u in instance.unavailability if u.slot < grid.slot_count],
    )


def _short(session: Session) -> Session:
    return session.model_copy(update={"duration_slots": 1})


@given(to_solve())
@THOROUGH
def test_anything_it_solves_the_validator_accepts(instance: Instance) -> None:
    """The whole of correctness for this phase, in one assertion.

    Feasible *and* complete: 4.1's D6 keeps them apart precisely so a solver cannot pass by
    leaving sessions out, since an absent session breaks no rule.
    """
    found = solve(snapshot_of(instance), Budget(seconds=10))
    assume(found.outcome is Outcome.SOLVED)

    report = judge(instance, found.placements)

    assert report.is_feasible
    assert report.is_complete
    assert report.violations == ()


@given(to_solve())
@THOROUGH
def test_it_places_every_session_exactly_once(instance: Instance) -> None:
    found = solve(snapshot_of(instance), Budget(seconds=10))
    assume(found.solved)

    placed = [p.session for p in found.placements]

    assert sorted(placed) == sorted(s.id for s in instance.sessions if s.id is not None)
    assert len(set(placed)) == len(placed)


@given(_tiny())
@TINY
def test_anything_it_refuses_really_has_no_answer(instance: Instance) -> None:
    """The half a green suite would not miss.

    Brute force over every (slot, room) for every session. Exponential, which is why the
    instances are kept to a few sessions in a couple of rooms — small enough that "try
    everything" is an answer rather than an aspiration.
    """
    found = solve(snapshot_of(instance), Budget(seconds=10))
    assume(found.outcome is Outcome.IMPOSSIBLE)

    assert not any_valid_timetable(instance)


@given(_tiny())
@TINY
def test_anything_with_an_answer_it_finds(instance: Instance) -> None:
    """The mirror, and the stronger of the two: brute force says a timetable exists, so the
    solver must not report the term impossible.

    Given the whole search space and no time pressure, "I could not find one" is not available
    either — on instances this small CP-SAT is exhaustive.
    """
    assume(any_valid_timetable(instance))

    found = solve(snapshot_of(instance), Budget(seconds=10))

    assert found.outcome is Outcome.SOLVED
