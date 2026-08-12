"""Instructors, and the slots they cannot teach in.

The availability tests carry most of the weight. Instructors are the pattern from 2.1
again; availability has its own rules, and its edge cases are the ones a grid editor
actually produces — overlapping drags, re-blocking, and releasing part of a range.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.repository import models as m
from tessera.repository import people as repo
from tessera.repository.errors import ConflictError, InvalidReferenceError, NotFoundError


def ident(entity: object) -> int:
    value = getattr(entity, "id", None)
    assert value is not None
    return int(value)


@pytest.fixture
def sharma(db: DbSession) -> int:
    return ident(repo.create_instructor(db, name="Prof. Sharma", email="sharma@example.edu"))


class TestInstructors:
    def test_load_limits_round_trip(self, db: DbSession) -> None:
        created = repo.create_instructor(
            db, name="Prof. Mehta", max_slots_per_day=8, max_slots_per_week=30
        )
        fetched = repo.get_instructor(db, ident(created))

        assert fetched.max_slots_per_day == 8
        assert fetched.max_slots_per_week == 30
        assert fetched.max_consecutive_slots is None  # unset means unlimited

    def test_two_departments_may_each_employ_an_a_sharma(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        """Names are scoped to the department, not the institution.

        Refusing the second would be wrong, and real universities do this constantly.
        """
        cse = m.Department(institution_id=institution.id, name="CSE")
        ece = m.Department(institution_id=institution.id, name="ECE")
        db.add_all([cse, ece])
        db.flush()

        repo.create_instructor(db, name="A. Sharma", department_id=cse.id)
        repo.create_instructor(db, name="A. Sharma", department_id=ece.id)

        assert len(repo.list_instructors(db)) == 2

    def test_the_same_department_may_not(self, db: DbSession, institution: m.Institution) -> None:
        dept = m.Department(institution_id=institution.id, name="CSE")
        db.add(dept)
        db.flush()
        repo.create_instructor(db, name="A. Sharma", department_id=dept.id)

        with pytest.raises(ConflictError):
            repo.create_instructor(db, name="A. Sharma", department_id=dept.id)

    def test_an_unknown_instructor_is_reported(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.get_instructor(db, 999_999)


class TestAvailability:
    def test_a_dragged_range_becomes_rows(self, db: DbSession, term: m.Term, sharma: int) -> None:
        rows = repo.block_slots(
            db, term.id, kind="instructor", subject_id=sharma, slots=range(5, 10)
        )
        assert [r.slot for r in rows] == [5, 6, 7, 8, 9]
        assert all(r.kind == "instructor" for r in rows)
        assert all(r.subject_id == sharma for r in rows)

    def test_reblocking_is_a_no_op(self, db: DbSession, term: m.Term, sharma: int) -> None:
        """Dragging across a partly-blocked range is ordinary use.

        Failing halfway through a gesture would be worse than useless, so the second
        call adds only what is missing rather than raising on the overlap.
        """
        repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[5, 6, 7])
        rows = repo.block_slots(
            db, term.id, kind="instructor", subject_id=sharma, slots=[6, 7, 8, 9]
        )
        assert [r.slot for r in rows] == [5, 6, 7, 8, 9]

    def test_a_repeated_slot_in_one_request_is_stored_once(
        self, db: DbSession, term: m.Term, sharma: int
    ) -> None:
        rows = repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[3, 3, 3])
        assert [r.slot for r in rows] == [3]

    def test_a_slot_beyond_the_grid_is_refused(
        self, db: DbSession, term: m.Term, sharma: int
    ) -> None:
        """Otherwise it is stored, ignored by the solver, and shown nowhere — a silent
        no-op with nothing for the user to debug."""
        with pytest.raises(ConflictError, match="between 0 and"):
            repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[9999])

    def test_a_negative_slot_is_refused(self, db: DbSession, term: m.Term, sharma: int) -> None:
        with pytest.raises(ConflictError):
            repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[-1])

    def test_releasing_part_of_a_range(self, db: DbSession, term: m.Term, sharma: int) -> None:
        """The operation the availability grid actually needs.

        Dragging over blocked cells to release them removes a range, not the lot.
        """
        repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=range(5, 10))

        removed = repo.unblock_slots(
            db, term.id, kind="instructor", subject_id=sharma, slots=[6, 7]
        )

        assert removed == 2
        remaining = repo.list_unavailability(db, term.id, subject_id=sharma)
        assert [r.slot for r in remaining] == [5, 8, 9]

    def test_releasing_everything(self, db: DbSession, term: m.Term, sharma: int) -> None:
        """No slots named keeps the endpoint's original meaning."""
        repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=range(5, 10))

        assert repo.unblock_slots(db, term.id, kind="instructor", subject_id=sharma) == 5
        assert repo.list_unavailability(db, term.id, subject_id=sharma) == []

    def test_releasing_a_slot_that_was_never_blocked(
        self, db: DbSession, term: m.Term, sharma: int
    ) -> None:
        assert (
            repo.unblock_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[42]) == 0
        )

    def test_rooms_and_instructors_do_not_collide(
        self, db: DbSession, term: m.Term, sharma: int
    ) -> None:
        """Both live in one table under an exclusive arc, so a room and an instructor
        sharing an id must not shadow each other."""
        room = m.Room(name="LH-201", capacity=100)
        db.add(room)
        db.flush()

        repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[3])
        repo.block_slots(db, term.id, kind="room", subject_id=room.id, slots=[7])

        instructors = repo.list_unavailability(db, term.id, kind="instructor")
        rooms = repo.list_unavailability(db, term.id, kind="room")

        assert [r.slot for r in instructors] == [3]
        assert [r.slot for r in rooms] == [7]

    def test_an_unknown_subject_is_refused(self, db: DbSession, term: m.Term) -> None:
        with pytest.raises(NotFoundError):
            repo.block_slots(db, term.id, kind="instructor", subject_id=999_999, slots=[1])

    def test_an_unknown_kind_is_refused(self, db: DbSession, term: m.Term, sharma: int) -> None:
        with pytest.raises(InvalidReferenceError):
            repo.block_slots(db, term.id, kind="banana", subject_id=sharma, slots=[1])

    def test_deleting_an_instructor_takes_their_availability(
        self, db: DbSession, term: m.Term, sharma: int
    ) -> None:
        """Those rows describe the instructor and mean nothing without them."""
        repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[1, 2, 3])

        repo.delete_instructor(db, sharma)

        assert repo.list_unavailability(db, term.id) == []

    def test_the_solver_view_is_a_set(self, db: DbSession, term: m.Term, sharma: int) -> None:
        """The solver wants membership, not rows. Kept in the same module so the
        interface and the solver read the same data the same way."""
        repo.block_slots(db, term.id, kind="instructor", subject_id=sharma, slots=[4, 9, 14])

        assert repo.blocked_slots(db, term.id, instructor_id=sharma) == frozenset({4, 9, 14})
