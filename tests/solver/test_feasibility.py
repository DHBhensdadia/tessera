"""That what the solver produces is what the validator accepts.

**The solver claiming success proves nothing.** Phase 0.1 reported FEASIBLE on all 21
instances, and a checker that always returned "no violations" would have looked identical —
so the claim is checked by something that shares none of its logic. 4.1 spent a phase becoming
that something: seven invariants and sixteen rules, each watched to fail, agreeing with an
independently written second reading over thousands of generated timetables.

The two share the `Snapshot` (D1) and nothing else. Sharing the *state* is what stops them
disagreeing about what is in the term; the *reading of the rules* stays separate, which is
where the evidence comes from.
"""

from __future__ import annotations

import pytest

from tessera.domain.entities import Unavailability
from tessera.domain.ids import AssignmentId, RoomId, SessionId
from tessera.domain.time_grid import TimeGrid
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Report, Snapshot, validate
from tessera.solver import Budget, Outcome, Placed, Solution, solve
from tests.domain.validation.institution import LAB, Institution


def judge(institution: Institution, found: Solution) -> Report:
    """Ask the 4.1 validator what it makes of the solver's answer."""
    return validate(
        Snapshot.of(
            grid=institution.grid,
            sessions=institution.sessions,
            rooms=institution.rooms,
            groups=institution.groups,
            unavailability=institution.unavailability,
            assignments=[
                Assignment(
                    id=AssignmentId(i),
                    session_id=p.session,
                    start_slot=p.start_slot,
                    room_id=p.room,
                )
                for i, p in enumerate(found.placements, start=1)
            ],
        )
    )


@pytest.fixture
def empty() -> Institution:
    return Institution(assignments=())


class TestTheValidatorAgrees:
    def test_a_solved_timetable_is_feasible_and_complete(self, empty: Institution) -> None:
        """Both halves. 4.1's D6 makes completeness a separate question precisely so a solver
        cannot pass by leaving sessions out — an absent session breaks no rule."""
        found = solve(empty.snapshot())
        verdict = judge(empty, found)

        assert found.outcome is Outcome.SOLVED
        assert verdict.is_feasible
        assert verdict.is_complete
        assert verdict.violations == ()

    def test_every_session_is_placed_exactly_once(self, empty: Institution) -> None:
        found = solve(empty.snapshot())

        assert len(found.placements) == len(empty.sessions)
        assert len({p.session for p in found.placements}) == len(empty.sessions)

    def test_it_works_around_a_closed_room(self, empty: Institution) -> None:
        """The lab is the only room with workstations, so closing it for a morning forces
        both labs into the afternoon rather than making the term impossible."""
        closed = empty.closed(*(Unavailability(room_id=LAB, slot=s) for s in range(4)))
        found = solve(closed.snapshot())
        verdict = judge(closed, found)

        assert found.solved
        assert verdict.is_feasible
        assert all(p.start_slot >= 4 for p in found.placements if p.room == LAB)


class TestWhenThereIsNoAnswer:
    def test_an_impossible_term_is_reported_impossible(self) -> None:
        """A solver that never says "no" is as useless as a validator that never says "yes".

        Both labs need the one room with workstations, and the day is narrowed until there is
        one hour for them. One room, one hour, two sessions.
        """
        cramped = Institution(
            assignments=(),
            grid=TimeGrid(days=1, slots_per_day=1, slot_minutes=60, day_start_minute=9 * 60),
        ).rooms_of_only(LAB)

        assert solve(cramped.snapshot()).outcome is Outcome.IMPOSSIBLE

    def test_impossible_carries_no_placements(self) -> None:
        """There is deliberately no partial answer. A solver returning the sessions it managed
        to place would produce something the validator calls feasible, because the ones it
        could not place are simply absent."""
        cramped = Institution(
            assignments=(),
            grid=TimeGrid(days=1, slots_per_day=1, slot_minutes=60, day_start_minute=9 * 60),
        ).rooms_of_only(LAB)
        found = solve(cramped.snapshot())

        assert found.placements == ()
        assert not found.solved

    def test_out_of_time_is_not_impossible(self) -> None:
        """Two different sentences, and only one of them is a reason to change the data.

        Given no time at all, the solver must say it ran out rather than that no timetable
        exists — reporting the second would send somebody to delete a course that was fine.
        """
        found = solve(Institution(assignments=()).snapshot(), Budget(seconds=0.0))

        assert found.outcome is not Outcome.IMPOSSIBLE


class TestDeterminism:
    def test_the_same_term_gives_the_same_timetable(self, empty: Institution) -> None:
        """Pinned seed, one worker. P5 warns at 4.5 that parallel CP-SAT is
        non-deterministic and that 0.1 saw an instance score *worse* with five times the
        budget — settling it here means every number this phase produces is reproducible."""
        first = solve(empty.snapshot(), Budget(seconds=10, workers=1, seed=7))
        again = solve(empty.snapshot(), Budget(seconds=10, workers=1, seed=7))

        assert first.placements == again.placements


class TestTheResultCannotLie:
    def test_a_solved_result_must_carry_placements(self) -> None:
        """The guard behind D4. "Solved" with nothing in it would pass every caller's check
        and mean nothing — and it is exactly what an early return would produce."""
        with pytest.raises(ValueError, match="no placements is not one"):
            Solution(outcome=Outcome.SOLVED)

    def test_a_failed_result_must_not(self) -> None:
        """The other direction, and the more dangerous one: placements alongside "impossible"
        are a partial timetable, which the validator would call feasible because the sessions
        that could not be placed are simply absent."""
        with pytest.raises(ValueError, match="cannot be trusted"):
            Solution(outcome=Outcome.OUT_OF_TIME, placements=(Placed(SessionId(1), 0, RoomId(1)),))
