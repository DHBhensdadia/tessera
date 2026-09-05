"""The pivot: whose week a placed session appears in, and how it is drawn.

Built on the same small institution the validator's mutation tests use, because it already has
the two things this projection is hard about: a two-hour lecture, which must be drawn once
across two rows rather than twice, and a parent group with two batches under it, which decides
whose timetable that lecture is on.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot
from tessera.export import grid
from tests.domain.validation.institution import (
    BATCH_A,
    BATCH_B,
    COMPUTING,
    CUPBOARD,
    HALL,
    LAB,
    LAB_A,
    LAB_B,
    LECTURE,
    LUNCH,
    MATHS,
    STUDIO,
    YEAR_1,
    Institution,
)

NAMES = grid.Labels(
    rooms={
        int(HALL): "Main Hall",
        int(LAB): "Computer Lab",
        int(CUPBOARD): "Seminar Room",
        int(STUDIO): "Studio",
    },
    instructors={1: "Prof. Sharma", 2: "Dr Iyer", 3: "Prof. Rao"},
    groups={int(YEAR_1): "Year 1", int(BATCH_A): "Batch A", int(BATCH_B): "Batch B"},
    courses={int(MATHS): "MA101 Calculus", int(COMPUTING): "CS201 Systems"},
)


@pytest.fixture
def term() -> Snapshot:
    return Institution().snapshot()


def week_of(term: Snapshot, by: grid.Pivot, name: str) -> grid.Week:
    for subject in grid.subjects(term, NAMES, by):
        if subject.name == name:
            return grid.week(term, NAMES, subject)
    raise AssertionError(f"no {by.value} called {name!r}")


def blocks(week: grid.Week) -> list[grid.Block]:
    return [cell.block for row in week.rows for cell in row.cells if cell.block is not None]


class TestWhoseWeekItIs:
    def test_a_lecture_to_the_parent_appears_in_every_batch(self, term: Snapshot) -> None:
        """A leaf is the set of students who share a week, which is the same reading the
        clash rule uses. Pivoting on the parent would produce a document no student is
        handed."""
        for batch in ("Batch A", "Batch B"):
            drawn = {block.session_id for block in blocks(week_of(term, grid.Pivot.GROUP, batch))}

            assert int(LECTURE) in drawn, batch

    def test_a_batchs_own_lab_is_not_on_the_other_batchs_week(self, term: Snapshot) -> None:
        drawn = {block.session_id for block in blocks(week_of(term, grid.Pivot.GROUP, "Batch A"))}

        assert int(LAB_A) in drawn
        assert int(LAB_B) not in drawn

    def test_an_instructor_sees_what_they_teach(self, term: Snapshot) -> None:
        drawn = {
            block.session_id for block in blocks(week_of(term, grid.Pivot.INSTRUCTOR, "Dr Iyer"))
        }

        assert drawn == {int(LAB_A), 4}

    def test_a_room_sees_what_is_booked_into_it(self, term: Snapshot) -> None:
        drawn = {
            block.session_id for block in blocks(week_of(term, grid.Pivot.ROOM, "Computer Lab"))
        }

        assert drawn == {int(LAB_A), int(LAB_B)}


class TestWhoIsOffered:
    def test_every_room_is_a_subject_even_an_empty_one(self, term: Snapshot) -> None:
        """An empty week answers *is this lab free?*, which is worth being able to ask."""
        offered = {s.name for s in grid.subjects(term, NAMES, grid.Pivot.ROOM)}

        assert "Seminar Room" in offered
        assert week_of(term, grid.Pivot.ROOM, "Seminar Room").is_empty

    def test_only_the_leaves_are_group_subjects(self, term: Snapshot) -> None:
        """`Year 1` is a parent: it has no students of its own, so it has no week of its
        own either."""
        offered = {s.name for s in grid.subjects(term, NAMES, grid.Pivot.GROUP)}

        assert offered == {"Batch A", "Batch B"}

    def test_an_instructor_who_teaches_nothing_is_not_offered(self, term: Snapshot) -> None:
        offered = {s.name for s in grid.subjects(term, NAMES, grid.Pivot.INSTRUCTOR)}

        assert offered == {"Prof. Sharma", "Dr Iyer", "Prof. Rao"}

    def test_occupied_agrees_with_what_is_drawn(self, term: Snapshot) -> None:
        """The page opens on a subject with teaching in it, and this is what decides which."""
        for by in grid.Pivot:
            busy = grid.occupied(term, by)

            for subject in grid.subjects(term, NAMES, by):
                drawn = not grid.week(term, NAMES, subject).is_empty

                assert drawn is (subject.id in busy), f"{by.value} {subject.name}"


class TestHowItIsDrawn:
    def test_a_two_hour_lecture_is_one_block_over_two_rows(self, term: Snapshot) -> None:
        week = week_of(term, grid.Pivot.ROOM, "Main Hall")
        drawn = blocks(week)

        assert len(drawn) == 1
        assert drawn[0].duration_slots == 2

    def test_the_slot_underneath_it_is_not_drawn_again(self, term: Snapshot) -> None:
        """Omitting the skip draws the lecture twice, in the row below its own."""
        week = week_of(term, grid.Pivot.ROOM, "Main Hall")
        covered = [cell for row in week.rows for cell in row.cells if cell.covered]

        assert len(covered) == 1
        assert covered[0].slot == 1

    def test_lunch_is_drawn_as_structure(self, term: Snapshot) -> None:
        week = week_of(term, grid.Pivot.ROOM, "Main Hall")

        assert week.rows[LUNCH].is_break
        assert all(cell.is_break for cell in week.rows[LUNCH].cells)

    def test_a_block_carries_what_a_reader_needs(self, term: Snapshot) -> None:
        drawn = blocks(week_of(term, grid.Pivot.ROOM, "Main Hall"))[0]

        assert drawn.course == "MA101 Calculus"
        assert drawn.room == "Main Hall"
        assert drawn.instructors == ("Prof. Sharma",)
        # The group the *session* names, not the leaf whose week this is: a block on Batch
        # A's timetable saying "Year 1" is what tells a reader it is a shared lecture.
        assert set(drawn.attendees) == {"Year 1"}

    def test_an_unresolved_id_reads_as_an_id_rather_than_raising(self, term: Snapshot) -> None:
        """6.2 will render fixtures with no project behind them, and a KeyError is not a
        timetable."""
        week = grid.week(
            term,
            grid.Labels.unresolved(),
            grid.Subject(kind=grid.Pivot.ROOM, id=int(HALL), name="room 1"),
        )

        assert blocks(week)[0].course == "course 1"

    def test_the_week_is_as_wide_as_the_teaching_week(self, term: Snapshot) -> None:
        week = week_of(term, grid.Pivot.ROOM, "Main Hall")

        assert week.days == ("Mon", "Tue", "Wed", "Thu", "Fri")
        assert len(week.rows) == 8


class TestWhatIsWrongWithIt:
    def test_a_valid_timetable_marks_nothing(self, term: Snapshot) -> None:
        assert grid.broken_by_session(term) == {}

    def test_a_clash_marks_both_sides(self) -> None:
        """Two labs in one room at one time. Different instructors and different batches, so
        it is a room clash and nothing else."""
        clashing = Institution(
            assignments=(
                *(a for a in Institution().assignments if a.session_id != LAB_B),
                Assignment(session_id=LAB_B, start_slot=2, room_id=LAB),
            )
        ).snapshot()

        broken = grid.broken_by_session(clashing)

        assert set(broken) == {LAB_A, LAB_B}
        assert all("room" in rule for rules in broken.values() for rule in rules)

    def test_a_marked_block_says_which_rule(self) -> None:
        clashing = Institution(
            assignments=(
                *(a for a in Institution().assignments if a.session_id != LAB_B),
                Assignment(session_id=LAB_B, start_slot=2, room_id=LAB),
            )
        ).snapshot()

        week = grid.week(
            clashing,
            NAMES,
            grid.Subject(kind=grid.Pivot.ROOM, id=int(LAB), name="Computer Lab"),
            grid.broken_by_session(clashing),
        )

        assert all(block.is_broken for block in blocks(week))


class TestAPlacementTheGridRefuses:
    def test_it_draws_one_row_rather_than_raising(self) -> None:
        """`Assignment` accepts any non-negative slot and 5.4 will let one be dragged there. A
        renderer that raises shows nothing at all, which is worse than showing the fault."""
        straddling = Institution(
            assignments=(
                *(a for a in Institution().assignments if a.session_id != LECTURE),
                # Two hours starting in the last slot of Monday: past the end of the day.
                Assignment(session_id=LECTURE, start_slot=7, room_id=HALL),
            )
        ).snapshot()

        week = grid.week(
            straddling,
            NAMES,
            grid.Subject(kind=grid.Pivot.ROOM, id=int(HALL), name="Main Hall"),
        )

        assert blocks(week)[0].duration_slots == 1


class TestEveryWeekAtOnce:
    def test_it_is_one_per_subject(self, term: Snapshot) -> None:
        """What 6.2 writes to a file, and what the agreement test compares."""
        for by in grid.Pivot:
            everything = grid.weeks(term, NAMES, by)

            assert len(everything) == len(grid.subjects(term, NAMES, by))


class TestASessionWithNoCourse:
    def test_it_is_named_by_its_own_id(self, term: Snapshot) -> None:
        """`course_of` is supplied rather than derived, so a caller can leave a session out
        of it — 6.2 renders fixtures, and a `KeyError` is not a timetable."""
        anonymous = Institution().snapshot()
        stripped = replace(anonymous, course_of={})

        drawn = blocks(
            grid.week(
                stripped,
                NAMES,
                grid.Subject(kind=grid.Pivot.ROOM, id=int(HALL), name="Main Hall"),
            )
        )

        assert drawn[0].course == f"session {int(LECTURE)}"
