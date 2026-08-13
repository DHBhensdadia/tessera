"""Reconciliation — the phase's real weight, and its exit test.

Expansion is easy to get right once and hard to get right twice. The tests that matter
here are the ones that run it a second time, after something has changed and after a
timetable exists, because that is where delete-and-regenerate quietly destroys work.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.repository import calendar as calendar_repo
from tessera.repository import expansion as repo
from tessera.repository import groups as groups_repo
from tessera.repository import models as m
from tessera.repository import sessions as sessions_repo
from tessera.repository import teaching as teaching_repo
from tessera.repository.errors import ConflictError, NotFoundError


@pytest.fixture
def offering_id(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> int:
    term = calendar_repo.create_term(
        db,
        institution_id=institution.id,
        time_grid_id=grid.id,
        academic_year="2026-27",
        name="Autumn",
    )
    course = teaching_repo.create_course(db, code="CS301", name="Operating Systems")
    assert term.id is not None and course.id is not None
    created = calendar_repo.create_offering(db, term_id=term.id, course_id=course.id)
    assert created.id is not None
    return int(created.id)


@pytest.fixture
def intake(db: DbSession) -> int:
    created = groups_repo.create_group(db, name="2024 Intake", size=120)
    assert created.id is not None
    return int(created.id)


@pytest.fixture
def batches(db: DbSession, intake: int) -> list[int]:
    ids = []
    for name in ("A1", "A2", "A3"):
        created = groups_repo.create_group(db, name=name, size=40, parent_id=intake)
        assert created.id is not None
        ids.append(int(created.id))
    return ids


def lectures(db: DbSession, offering_id: int, intake: int, *, per_week: int = 3) -> int:
    created = sessions_repo.create_template(
        db,
        offering_id=offering_id,
        kind=d.SessionKind.LECTURE,
        duration_slots=2,
        per_week=per_week,
        attendee_ids=[intake],
    )
    assert created.id is not None
    return int(created.id)


def labs(db: DbSession, offering_id: int, batches: list[int], *, per_week: int = 1) -> int:
    created = sessions_repo.create_template(
        db,
        offering_id=offering_id,
        kind=d.SessionKind.LAB,
        duration_slots=4,
        per_week=per_week,
        split_per_attendee=True,
        attendee_ids=batches,
    )
    assert created.id is not None
    return int(created.id)


def schedule(db: DbSession, session_id: int) -> None:
    """Place a session, which is what makes it worth protecting."""
    block = db.get(m.Session, session_id)
    assert block is not None
    room = m.Room(name=f"LH-{session_id}", capacity=200)
    timetable = m.Timetable(term_id=block.term_id, name="Draft", status="draft")
    db.add_all([room, timetable])
    db.flush()
    db.add(
        m.Assignment(
            timetable_id=timetable.id,
            session_id=session_id,
            term_id=block.term_id,
            start_slot=0,
            room_id=room.id,
        )
    )
    db.flush()


class TestTheExitTest:
    def test_three_lectures_and_a_lab_split_three_ways_make_six_sessions(
        self, db: DbSession, offering_id: int, intake: int, batches: list[int]
    ) -> None:
        """The phase's exit test, stated exactly as P5 stated it."""
        lectures(db, offering_id, intake)
        labs(db, offering_id, batches)

        produced = repo.expand(db, offering_id)

        assert len(produced) == 6
        lecture_blocks = [s for s in produced if s.kind is d.SessionKind.LECTURE]
        lab_blocks = [s for s in produced if s.kind is d.SessionKind.LAB]

        assert len(lecture_blocks) == 3
        assert all(s.duration_slots == 2 for s in lecture_blocks)
        assert all(s.attendee_ids == frozenset({intake}) for s in lecture_blocks)
        assert sorted(s.occurrence for s in lecture_blocks) == [0, 1, 2]

        assert len(lab_blocks) == 3
        assert all(s.duration_slots == 4 for s in lab_blocks)
        assert {next(iter(s.attendee_ids)) for s in lab_blocks} == set(batches)
        assert all(s.occurrence == 0 for s in lab_blocks)

    def test_the_count_agrees_with_the_domain(
        self, db: DbSession, offering_id: int, intake: int, batches: list[int]
    ) -> None:
        """`SessionTemplate.session_count` is the same arithmetic in the domain.

        Asserted rather than trusted: two definitions of what a weekly pattern produces
        is precisely the drift Decision #5 exists to prevent.
        """
        lecture_id = lectures(db, offering_id, intake)
        lab_id = labs(db, offering_id, batches, per_week=2)

        produced = repo.expand(db, offering_id)

        expected = sessions_repo.get_template(db, lecture_id).session_count
        expected += sessions_repo.get_template(db, lab_id).session_count
        assert len(produced) == expected


class TestOccurrenceNumbering:
    def test_a_repeat_is_numbered_within_its_attendee(
        self, db: DbSession, offering_id: int, batches: list[int]
    ) -> None:
        """Decision #59. Two labs a week across three sub-batches is
        (A1,0) (A1,1) (A2,0) (A2,1) (A3,0) (A3,1) — "lab 1 of 2 for batch A1".

        A flat 0-5 would lose which sub-batch a repeat belongs to, and would renumber on
        every edit, breaking the key it is part of.
        """
        labs(db, offering_id, batches, per_week=2)

        produced = repo.expand(db, offering_id)

        assert len(produced) == 6
        by_group = {
            next(iter(s.attendee_ids)): sorted(
                p.occurrence for p in produced if p.attendee_ids == s.attendee_ids
            )
            for s in produced
        }
        assert by_group == {batches[0]: [0, 1], batches[1]: [0, 1], batches[2]: [0, 1]}


class TestRunningItTwice:
    def test_the_second_run_changes_nothing(
        self, db: DbSession, offering_id: int, intake: int, batches: list[int]
    ) -> None:
        """Idempotence is what makes this safe to offer as a button."""
        lectures(db, offering_id, intake)
        labs(db, offering_id, batches)

        first = repo.expand(db, offering_id)
        second = repo.expand(db, offering_id)

        assert [s.id for s in first] == [s.id for s in second]

    def test_growing_a_pattern_keeps_the_original_sessions(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """The reason reconciliation exists.

        Delete-and-regenerate would give all three lectures new ids, and the assignment
        below would be gone with the rows it pointed at.
        """
        template_id = lectures(db, offering_id, intake)
        before = repo.expand(db, offering_id)
        assert len(before) == 3
        schedule(db, int(before[0].id or 0))

        sessions_repo.update_template(db, template_id, changes={"per_week": 4})
        after = repo.expand(db, offering_id)

        assert len(after) == 4
        assert {s.id for s in before} <= {s.id for s in after}
        assert db.query(m.Assignment).count() == 1

    def test_a_deliberate_edit_survives_re_expansion(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """Reconciliation adds and removes but never *updates*.

        One lecture lengthened by hand stays lengthened; otherwise expanding would
        quietly revert every per-session decision the user had made.
        """
        template_id = lectures(db, offering_id, intake)
        produced = repo.expand(db, offering_id)
        edited = int(produced[0].id or 0)
        sessions_repo.update_session(db, edited, changes={"duration_slots": 6})

        sessions_repo.update_template(db, template_id, changes={"per_week": 4})
        repo.expand(db, offering_id)

        assert sessions_repo.get_session(db, edited).duration_slots == 6

    def test_shrinking_a_pattern_removes_the_surplus(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        template_id = lectures(db, offering_id, intake)
        repo.expand(db, offering_id)

        sessions_repo.update_template(db, template_id, changes={"per_week": 2})
        after = repo.expand(db, offering_id)

        assert len(after) == 2
        assert sorted(s.occurrence for s in after) == [0, 1]

    def test_shrinking_is_refused_when_the_surplus_is_scheduled(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """The guard proved by breaking the thing it guards.

        Deliberately no `force` flag: a destructive default with an escape hatch is how
        the escape hatch becomes the habit.
        """
        template_id = lectures(db, offering_id, intake)
        produced = repo.expand(db, offering_id)
        doomed = next(s for s in produced if s.occurrence == 2)
        schedule(db, int(doomed.id or 0))

        sessions_repo.update_template(db, template_id, changes={"per_week": 2})

        with pytest.raises(ConflictError) as raised:
            repo.expand(db, offering_id)
        assert raised.value.blockers == {"scheduled_sessions": 1}

    def test_nothing_is_removed_by_the_refusal(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """Refusing is only useful if it refuses *before* deleting anything."""
        template_id = lectures(db, offering_id, intake)
        produced = repo.expand(db, offering_id)
        schedule(db, int(next(s for s in produced if s.occurrence == 2).id or 0))
        sessions_repo.update_template(db, template_id, changes={"per_week": 1})

        with pytest.raises(ConflictError):
            repo.expand(db, offering_id)

        assert db.query(m.Session).count() == 3

    def test_narrowing_a_split_removes_only_the_dropped_batch(
        self, db: DbSession, offering_id: int, batches: list[int]
    ) -> None:
        template_id = labs(db, offering_id, batches)
        before = repo.expand(db, offering_id)
        kept = {s.id for s in before if next(iter(s.attendee_ids)) != batches[2]}

        sessions_repo.update_template(db, template_id, changes={"attendee_ids": batches[:2]})
        after = repo.expand(db, offering_id)

        assert {s.id for s in after} == kept


class TestSessionsItMustNotTouch:
    def test_a_session_with_no_template_is_left_alone(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """Nothing in the API creates one — there is no `POST /sessions` — but a file
        edited by hand can contain one, and silently deleting a row this module did not
        create would be the worst possible answer."""
        offering = db.get(m.Offering, offering_id)
        assert offering is not None
        orphan = m.Session(
            offering_id=offering_id, term_id=offering.term_id, kind="seminar", duration_slots=2
        )
        orphan.attendees = [db.get(m.StudentGroup, intake)]  # type: ignore[list-item]
        db.add(orphan)
        db.flush()
        orphan_id = int(orphan.id)

        lectures(db, offering_id, intake)
        produced = repo.expand(db, offering_id)

        assert orphan_id in {int(s.id or 0) for s in produced}
        assert db.get(m.Session, orphan_id) is not None

    def test_another_offerings_sessions_are_untouched(
        self,
        db: DbSession,
        institution: m.Institution,
        grid: m.TimeGrid,
        offering_id: int,
        intake: int,
    ) -> None:
        other_course = teaching_repo.create_course(db, code="CS302", name="Networks")
        assert other_course.id is not None
        offering = db.get(m.Offering, offering_id)
        assert offering is not None
        other = calendar_repo.create_offering(
            db, term_id=offering.term_id, course_id=other_course.id
        )
        assert other.id is not None
        lectures(db, int(other.id), intake)
        repo.expand(db, int(other.id))

        lectures(db, offering_id, intake)
        repo.expand(db, offering_id)

        assert len(repo.expand(db, int(other.id))) == 3


class TestEmptyCases:
    def test_an_offering_with_no_templates_expands_to_nothing(
        self, db: DbSession, offering_id: int
    ) -> None:
        assert repo.expand(db, offering_id) == []

    def test_removing_every_template_removes_every_session(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """Deleting the component takes its sessions (Decision #54); expanding afterwards
        confirms nothing was left behind for the solver to place."""
        template_id = lectures(db, offering_id, intake)
        repo.expand(db, offering_id)

        sessions_repo.delete_template(db, template_id)

        assert repo.expand(db, offering_id) == []

    def test_expanding_an_unknown_offering(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.expand(db, 999)
