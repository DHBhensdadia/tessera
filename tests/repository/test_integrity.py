"""Rules the database enforces, rather than trusting callers to remember.

Each test here corresponds to something the schema accepted before this pass and now
refuses. They exist because all three were *demonstrated* against the previous schema —
none was theoretical.

The general point: an invariant enforced by convention holds until the first caller who
has not read the convention. One enforced by a constraint holds regardless.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from tessera.repository import models as m


@pytest.fixture
def two_terms(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> tuple[m.Term, m.Term]:
    autumn = m.Term(
        institution_id=institution.id, time_grid_id=grid.id, academic_year="2026-27", name="Autumn"
    )
    spring = m.Term(
        institution_id=institution.id, time_grid_id=grid.id, academic_year="2026-27", name="Spring"
    )
    db.add_all([autumn, spring])
    db.commit()
    return autumn, spring


def make_session(db: DbSession, term: m.Term, code: str = "CS301") -> m.Session:
    course = m.Course(code=code, name="Course")
    db.add(course)
    db.commit()
    offering = m.Offering(term_id=term.id, course_id=course.id)
    db.add(offering)
    db.commit()
    row = m.Session(offering_id=offering.id, term_id=term.id, duration_slots=2)
    db.add(row)
    db.commit()
    return row


class TestTermScoping:
    def test_a_timetable_cannot_hold_a_session_from_another_term(
        self, db: DbSession, two_terms: tuple[m.Term, m.Term]
    ) -> None:
        """Previously accepted silently.

        Term duplication is where this would occur for real, and the solver would then
        produce nonsense out of data that looked valid.
        """
        autumn, spring = two_terms
        spring_session = make_session(db, spring)
        room = m.Room(name="LH-201", capacity=100)
        autumn_timetable = m.Timetable(term_id=autumn.id, name="Autumn draft")
        db.add_all([room, autumn_timetable])
        db.commit()

        db.add(
            m.Assignment(
                timetable_id=autumn_timetable.id,
                session_id=spring_session.id,
                term_id=autumn.id,  # matches the timetable, not the session
                start_slot=0,
                room_id=room.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_a_matching_term_is_accepted(
        self, db: DbSession, two_terms: tuple[m.Term, m.Term]
    ) -> None:
        """The constraint must not be so strict that the legitimate case fails."""
        autumn, _ = two_terms
        session_row = make_session(db, autumn)
        room = m.Room(name="LH-201", capacity=100)
        timetable = m.Timetable(term_id=autumn.id, name="Draft")
        db.add_all([room, timetable])
        db.commit()

        db.add(
            m.Assignment(
                timetable_id=timetable.id,
                session_id=session_row.id,
                term_id=autumn.id,
                start_slot=0,
                room_id=room.id,
            )
        )
        db.commit()
        assert db.query(m.Assignment).count() == 1

    def test_a_session_cannot_claim_a_term_its_offering_is_not_in(
        self, db: DbSession, two_terms: tuple[m.Term, m.Term]
    ) -> None:
        """Keeps the denormalised copy honest.

        ``session.term_id`` only makes the assignment constraint meaningful if it cannot
        itself drift from the offering it belongs to.
        """
        autumn, spring = two_terms
        course = m.Course(code="CS999", name="Course")
        db.add(course)
        db.commit()
        offering = m.Offering(term_id=autumn.id, course_id=course.id)
        db.add(offering)
        db.commit()

        db.add(m.Session(offering_id=offering.id, term_id=spring.id, duration_slots=2))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


class TestUnavailabilitySubject:
    def test_it_cannot_reference_an_instructor_that_does_not_exist(
        self, db: DbSession, two_terms: tuple[m.Term, m.Term]
    ) -> None:
        """Previously accepted, because the old column had no foreign key at all."""
        autumn, _ = two_terms
        db.add(m.Unavailability(term_id=autumn.id, instructor_id=999_999, slot=3))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_it_must_name_exactly_one_subject(
        self, db: DbSession, two_terms: tuple[m.Term, m.Term]
    ) -> None:
        autumn, _ = two_terms
        instructor = m.Instructor(name="Prof. Sharma")
        room = m.Room(name="LH-201", capacity=100)
        db.add_all([instructor, room])
        db.commit()

        db.add(m.Unavailability(term_id=autumn.id, slot=3))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(
            m.Unavailability(
                term_id=autumn.id, instructor_id=instructor.id, room_id=room.id, slot=3
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_deleting_an_instructor_takes_their_unavailability_with_it(
        self, db: DbSession, two_terms: tuple[m.Term, m.Term]
    ) -> None:
        """The orphan the old design left behind.

        Worse than clutter: primary keys can be reused, so a later instructor could have
        inherited a predecessor's blocked slots.
        """
        autumn, _ = two_terms
        instructor = m.Instructor(name="Prof. Mehta")
        db.add(instructor)
        db.commit()
        db.add(m.Unavailability(term_id=autumn.id, instructor_id=instructor.id, slot=5))
        db.commit()
        assert db.query(m.Unavailability).count() == 1

        db.delete(instructor)
        db.commit()
        assert db.query(m.Unavailability).count() == 0


class TestCommandPayload:
    def test_a_solve_can_record_every_placement_it_replaced(self) -> None:
        """``CommandKind.SOLVE`` was documented as undoable and was not.

        The payload was typed ``dict[str, int]`` while the column storing it was JSON —
        the domain was narrower than its own storage, which would have surfaced at Phase
        5.6 as "undo does not work after solving".
        """
        from tessera.domain import Command, CommandKind

        previous = [{"session_id": i, "start_slot": i * 2, "room_id": 1} for i in range(200)]
        command = Command(
            sequence=0,
            kind=CommandKind.SOLVE,
            summary="Generated 200 placements",
            before={"assignments": previous},
            after={"assignments": [], "penalty": 1094},
        )
        assert len(command.before["assignments"]) == 200
        assert command.after["penalty"] == 1094
