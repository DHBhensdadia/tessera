"""What the model is built from, before anything is searched.

Most of the correctness of this phase is in the *shape* of the model rather than in the
search: a start whose domain contains an illegal hour, or a room that should never have been a
candidate, is a wrong answer CP-SAT will find efficiently. So these tests are about what got
written down.

The other half — that a solved timetable actually satisfies the rules — is
`test_feasibility.py`, and it asks the 4.1 validator rather than asking the solver again.
"""

from __future__ import annotations

import pytest

from tessera.domain.entities import Unavailability, WeekPattern
from tessera.domain.ids import AssignmentId, InstructorId
from tessera.domain.timetable import Assignment
from tessera.solver import Outcome, solve
from tessera.solver.model import UnsatisfiableError, build, size
from tests.domain.validation.institution import (
    CUPBOARD,
    HALL,
    LAB,
    LAB_A,
    LAB_B,
    LECTURE,
    LUNCH,
    STUDIO,
    TUTORIAL,
    Institution,
)


@pytest.fixture
def empty() -> Institution:
    """The known-good institution with nothing placed — the solver's job rather than a fact."""
    return Institution(assignments=())


class TestWhichRoomsAreEvenConsidered:
    def test_a_session_only_gets_rooms_that_could_hold_it(self, empty: Institution) -> None:
        """#35's pruning, and the reason the model does not explode.

        The lab needs thirty workstations and there is one room with them; the lecture needs
        sixty seats and there are two rooms that big. Forty rooms would become three, which is
        the difference between a model that fits in memory and one that does not.
        """
        model = build(empty.snapshot())

        assert [c.room for c in model.candidates[LAB_A]] == [LAB]
        assert [c.room for c in model.candidates[LECTURE]] == [HALL]

    def test_it_uses_the_same_test_the_validator_uses(self, empty: Institution) -> None:
        """`Room.can_host`, so the solver cannot consider a room the validator would reject.

        Two answers to "may this session go here" is the drift Decision #5 is about, and it
        would show up as a timetable the solver was proud of and the interface painted red.
        """
        model = build(empty.snapshot())
        rooms = empty.snapshot().rooms

        for session_id, candidates in model.candidates.items():
            session = empty.snapshot().sessions[session_id]
            headcount = empty.snapshot().headcount(session)
            for candidate in candidates:
                assert rooms[candidate.room].can_host(
                    headcount, session.required_features, session.required_counts
                )

    def test_a_session_nothing_can_hold_is_refused_while_building(self) -> None:
        """Arithmetic already knows. CP-SAT would report INFEASIBLE after searching, which is
        a slower way to learn it and a worse one — this message names the session."""
        crowded = Institution(assignments=()).rooms_of_only(CUPBOARD)

        with pytest.raises(UnsatisfiableError, match="no room that can hold it"):
            build(crowded.snapshot())


class TestWhenASessionMayStart:
    def test_the_domain_is_the_legal_hours_not_a_range(self, empty: Institution) -> None:
        """D2. The grid already refuses a session that runs past the end of a day, crosses
        midnight or runs through a break, so the domain is those hours and the solver never
        explores an impossible one."""
        model = build(empty.snapshot())
        grid = empty.grid
        lecture = model.starts[LECTURE]  # two hours long

        allowed = {v for v in range(grid.slot_count) if lecture.proto.domain and _in(lecture, v)}

        assert all(grid.can_hold(v, 2) for v in allowed)
        assert LUNCH not in allowed  # would run through lunch
        assert grid.slots_per_day - 1 not in allowed  # would run past the end of the day

    def test_an_instructor_being_away_removes_hours(self, empty: Institution) -> None:
        """Not a constraint: it does not depend on which room is chosen, so it belongs in the
        domain where the solver never has to consider it."""
        away = empty.closed(
            *(Unavailability(instructor_id=InstructorId(1), slot=s) for s in range(4))
        )
        model = build(away.snapshot())

        assert not any(_in(model.starts[LECTURE], v) for v in range(4))

    def test_a_session_with_nowhere_to_start_is_refused(self, empty: Institution) -> None:
        never = empty.closed(
            *(
                Unavailability(instructor_id=InstructorId(1), slot=s)
                for s in range(empty.grid.slot_count)
            )
        )

        with pytest.raises(UnsatisfiableError, match="no hour it could start in"):
            build(never.snapshot())


class TestPins:
    def test_a_pinned_session_does_not_move(self, empty: Institution) -> None:
        """Decision #10 put `is_pinned` in the schema on day one *because retrofitting
        reworks the solver interface*. This is where that either pays off or is ignored."""
        pinned = Institution(
            assignments=(
                Assignment(
                    id=AssignmentId(1),
                    session_id=TUTORIAL,
                    start_slot=6,
                    room_id=STUDIO,
                    is_pinned=True,
                ),
            )
        )
        found = solve(pinned.snapshot())
        where = {p.session: (p.start_slot, p.room) for p in found.placements}

        assert found.solved
        assert where[TUTORIAL] == (6, STUDIO)

    def test_an_unpinned_placement_is_free_to_move(self, empty: Institution) -> None:
        """The other half. A stored assignment that is *not* pinned is a starting point, not
        a constraint — otherwise re-solving would only ever return what it was given."""
        loose = Institution(
            assignments=(
                Assignment(id=AssignmentId(1), session_id=LECTURE, start_slot=0, room_id=HALL),
                # Deliberately illegal: two labs in one room at one hour.
                Assignment(id=AssignmentId(2), session_id=LAB_A, start_slot=2, room_id=LAB),
                Assignment(id=AssignmentId(3), session_id=LAB_B, start_slot=2, room_id=LAB),
                Assignment(id=AssignmentId(4), session_id=TUTORIAL, start_slot=6, room_id=STUDIO),
            )
        )
        found = solve(loose.snapshot())
        where = {p.session: p.start_slot for p in found.placements}

        assert found.solved
        assert where[LAB_A] != where[LAB_B]

    def test_pins_that_contradict_each_other_are_impossible(self) -> None:
        """Two sessions pinned into one room at one hour. The solver must say so rather than
        quietly unpinning one."""
        contradictory = Institution(
            assignments=(
                Assignment(
                    id=AssignmentId(1), session_id=LAB_A, start_slot=2, room_id=LAB, is_pinned=True
                ),
                Assignment(
                    id=AssignmentId(2), session_id=LAB_B, start_slot=2, room_id=LAB, is_pinned=True
                ),
            )
        )

        assert solve(contradictory.snapshot()).outcome is Outcome.IMPOSSIBLE


class TestTheThingsThatShareTime:
    def test_a_rooms_turnaround_is_part_of_its_time(self, empty: Institution) -> None:
        """The lab needs an hour to clear, so two labs cannot sit an hour apart in it.

        Expressed as the interval's length rather than as a rule of its own — a room being
        cleared *is in use*, and two rules about when a room is free could disagree.
        """
        model = build(empty.snapshot())
        in_lab = [c for c in model.candidates[LAB_A] if c.room == LAB]

        assert in_lab
        assert in_lab[0].interval.size_expr() == 2  # one hour taught, one to clear

    def test_people_are_only_busy_while_teaching(self, empty: Institution) -> None:
        """The mirror of the above, and #190: the students have left and the instructor has
        stopped teaching while the room is being cleared."""
        model = build(empty.snapshot())

        assert model.teaching[LAB_A].size_expr() == 1

    def test_alternating_weeks_may_share_a_room_and_an_hour(self) -> None:
        """Two labs in one room at one hour, one in odd weeks and one in even.

        Universities run fortnightly labs, and a solver that forbade this would refuse a
        timetable that works. `AddNoOverlap` cannot say "except these pairs", so the sessions
        are split by pattern instead.
        """
        alternating = (
            Institution(assignments=())
            .patterned(LAB_A, WeekPattern.ODD_WEEKS)
            .patterned(LAB_B, WeekPattern.EVEN_WEEKS)
            .pinned_to(LAB_A, at=2, room=LAB)
            .pinned_to(LAB_B, at=2, room=LAB)
        )

        assert solve(alternating.snapshot()).solved

    def test_every_week_still_collides(self) -> None:
        """The half that keeps the above meaningful."""
        both = (
            Institution(assignments=())
            .pinned_to(LAB_A, at=2, room=LAB)
            .pinned_to(LAB_B, at=2, room=LAB)
        )

        assert solve(both.snapshot()).outcome is Outcome.IMPOSSIBLE


class TestTheModelIsSmall:
    def test_it_is_not_a_boolean_cube(self, empty: Institution) -> None:
        """#35, made checkable.

        The forbidden formulation is one boolean per (session, period, room) — at department
        scale, 1.6 M of them at 30-minute slots and 2.8 s merely to construct. Here the period
        dimension is an integer, so the count is (session, room) pairs *after* pruning, which
        for this institution is six rather than sixteen.
        """
        sessions, candidates = size(build(empty.snapshot()))

        assert sessions == 4
        assert candidates == 6
        assert candidates < sessions * len(empty.rooms) * empty.grid.slot_count


def _in(var: object, value: int) -> bool:
    """Whether a value is in an IntVar's domain, read off the proto."""
    flat = var.proto.domain  # type: ignore[attr-defined]
    return any(flat[i] <= value <= flat[i + 1] for i in range(0, len(flat), 2))


class TestARoomThatIsShut:
    def test_a_room_closed_all_week_is_not_a_candidate(self, empty: Institution) -> None:
        """Dropped while building, not constrained away.

        A room shut for the whole term is not a room this session could be in, and carrying
        a presence literal for it means the solver explores a branch that can never be true.
        """
        shut = empty.closed(
            *(Unavailability(room_id=LAB, slot=s) for s in range(empty.grid.slot_count))
        )

        with pytest.raises(UnsatisfiableError, match="no room that can hold it"):
            build(shut.snapshot())

    def test_a_room_closed_for_part_of_the_week_keeps_its_other_hours(
        self, empty: Institution
    ) -> None:
        """The branch between the two: the room stays a candidate and the hours it is shut
        are refused *only when this session is in it*."""
        morning = empty.closed(*(Unavailability(room_id=LAB, slot=s) for s in range(4)))
        found = solve(morning.snapshot())

        assert found.solved
        assert all(p.start_slot >= 4 for p in found.placements if p.room == LAB)
