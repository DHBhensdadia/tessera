"""Domain rules that had never been provoked by anything.

Found by an audit after 2.4: three `ValueError`s written in 1.3 that no test had ever
reached. The project's standard is that a guard nobody has watched fail is not known to
work, and these had been quietly assumed to work for four phases.

Not a new feature — the rules already existed and already fired. What was missing was
any evidence of it.
"""

from __future__ import annotations

import pytest

from tessera.domain.entities import Unavailability, UnavailabilityKind
from tessera.domain.groups import GroupKind, StudentGroup
from tessera.domain.ids import InstructorId, RoomId, StudentGroupId
from tessera.domain.time_grid import TimeGrid


class TestAGroupsKindMustMatchItsLinks:
    """`member_ids` is how a cohort names the groups it draws students from.

    A structural group is a node in the tree and takes its students through `parent_id`.
    Giving one `member_ids` is a category error that would make leaf resolution count the
    same students twice — reachable today through `POST /student-groups`.
    """

    def test_a_structural_group_may_not_have_members(self) -> None:
        with pytest.raises(ValueError, match="takes members through the tree"):
            StudentGroup(
                id=StudentGroupId(1),
                name="2024 Intake",
                kind=GroupKind.STRUCTURAL,
                size=120,
                member_ids=frozenset({StudentGroupId(2)}),
            )

    def test_a_structural_group_with_a_parent_is_fine(self) -> None:
        group = StudentGroup(
            id=StudentGroupId(2),
            name="A1",
            kind=GroupKind.STRUCTURAL,
            size=40,
            parent_id=StudentGroupId(1),
        )

        assert group.parent_id == 1

    def test_a_cohort_draws_through_members(self) -> None:
        cohort = StudentGroup(
            id=StudentGroupId(9),
            name="Elective: Robotics",
            kind=GroupKind.COHORT,
            size=0,  # a cohort's headcount is derived from its members, never typed in
            member_ids=frozenset({StudentGroupId(1), StudentGroupId(2)}),
        )

        assert len(cohort.member_ids) == 2


class TestUnavailabilityNamesExactlyOneSubject:
    """A blocked slot belongs to an instructor or to a room, never both and never
    neither. Both would make "who is unavailable" ambiguous at solve time; neither
    would block a slot for nobody."""

    def test_an_instructor_block_is_valid(self) -> None:
        blocked = Unavailability(instructor_id=InstructorId(1), slot=10)

        assert blocked.instructor_id == 1
        assert blocked.kind is UnavailabilityKind.INSTRUCTOR

    def test_a_room_block_is_valid(self) -> None:
        blocked = Unavailability(room_id=RoomId(2), slot=10)

        assert blocked.kind is UnavailabilityKind.ROOM

    def test_naming_both_is_refused(self) -> None:
        with pytest.raises(ValueError, match="exactly one instructor or one room"):
            Unavailability(instructor_id=InstructorId(1), room_id=RoomId(2), slot=10)

    def test_naming_neither_is_refused(self) -> None:
        with pytest.raises(ValueError, match="exactly one instructor or one room"):
            Unavailability(slot=10)


class TestASessionMustHaveDuration:
    """`span` is what the solver and the UI both ask "can this sit here?".

    A zero-length session would produce an empty span, which reads as "fits anywhere" —
    the worst possible answer, since it fits nowhere and blocks nothing.
    """

    @pytest.fixture
    def week(self) -> TimeGrid:
        return TimeGrid(days=5, slots_per_day=16, slot_minutes=30, day_start_minute=540)

    def test_zero_duration_is_refused(self, week: TimeGrid) -> None:
        with pytest.raises(ValueError, match="at least one slot"):
            week.span(0, 0)

    def test_negative_duration_is_refused(self, week: TimeGrid) -> None:
        with pytest.raises(ValueError, match="at least one slot"):
            week.span(0, -2)

    def test_one_slot_is_the_smallest_that_works(self, week: TimeGrid) -> None:
        assert week.span(0, 1) == (0,)
