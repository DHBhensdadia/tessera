"""The course catalogue.

Repository-level, so the rules are tested without HTTP in the way. The same rules are
checked again through the API in `tests/api/test_teaching.py`, which is not duplication:
one proves the behaviour, the other proves it survives translation to and from the wire.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.repository import models as m
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as repo
from tessera.repository.errors import ConflictError, NotFoundError


@pytest.fixture
def department(db: DbSession, institution: m.Institution) -> m.Department:
    return structure_repo.create_department(  # type: ignore[return-value]
        db, institution_id=institution.id, name="Computer Science"
    )


@pytest.fixture
def other_department(db: DbSession, institution: m.Institution) -> m.Department:
    return structure_repo.create_department(  # type: ignore[return-value]
        db, institution_id=institution.id, name="Mathematics"
    )


class TestCodes:
    def test_a_code_may_repeat_across_departments(
        self, db: DbSession, department: m.Department, other_department: m.Department
    ) -> None:
        """Two departments numbering their first course 101 is the normal case, not a
        collision — which is why the constraint is scoped rather than global."""
        repo.create_course(db, code="101", name="Intro to Programming", department_id=department.id)
        repo.create_course(db, code="101", name="Calculus", department_id=other_department.id)

        assert len(repo.list_courses(db)) == 2

    def test_a_code_may_not_repeat_within_a_department(
        self, db: DbSession, department: m.Department
    ) -> None:
        repo.create_course(db, code="CS101", name="Intro", department_id=department.id)

        with pytest.raises(ConflictError):
            repo.create_course(db, code="CS101", name="Something Else", department_id=department.id)

    def test_two_unassigned_courses_may_not_share_a_code(self, db: DbSession) -> None:
        """The case the database alone would allow.

        With ``department_id`` null the unique constraint does not fire, because SQL
        treats each null as distinct. The repository check does, because SQLAlchemy
        renders ``== None`` as ``IS NULL``. Without this test the gap would look closed.
        """
        repo.create_course(db, code="CS101", name="Intro")

        with pytest.raises(ConflictError):
            repo.create_course(db, code="CS101", name="Intro Again")

    def test_the_database_alone_would_permit_it(self, db: DbSession) -> None:
        """The other half of the test above, stated so the reason is not lost.

        This inserts through the ORM, bypassing the repository, and *succeeds*. That is
        the demonstration that the constraint is not what stops it — so if the check in
        `_reject_duplicate` is ever removed as redundant, the test above fails and this
        one explains why it cannot be.
        """
        db.add(m.Course(department_id=None, code="CS101", name="Intro"))
        db.add(m.Course(department_id=None, code="CS101", name="Intro Again"))
        db.flush()

        assert len(repo.list_courses(db)) == 2

    def test_names_may_repeat_freely(self, db: DbSession, department: m.Department) -> None:
        """ "Project Work" is a real course in several departments and often twice in
        one, at different levels. Only the code identifies."""
        repo.create_course(db, code="CS301", name="Project Work", department_id=department.id)
        repo.create_course(db, code="CS401", name="Project Work", department_id=department.id)

        assert len(repo.list_courses(db)) == 2


class TestEditing:
    def test_changing_a_code_is_checked_against_the_department(
        self, db: DbSession, department: m.Department
    ) -> None:
        repo.create_course(db, code="CS101", name="Intro", department_id=department.id)
        second = repo.create_course(db, code="CS102", name="Data", department_id=department.id)
        assert second.id is not None

        with pytest.raises(ConflictError):
            repo.update_course(db, second.id, changes={"code": "CS101"})

    def test_moving_a_course_is_checked_against_the_destination(
        self, db: DbSession, department: m.Department, other_department: m.Department
    ) -> None:
        """The collision this creates is invisible until the move happens.

        Both courses are legal where they are. Checking against the current department
        rather than the destination would let the second one land on top of the first.
        """
        repo.create_course(db, code="101", name="Intro", department_id=department.id)
        moving = repo.create_course(
            db, code="101", name="Calculus", department_id=other_department.id
        )
        assert moving.id is not None

        with pytest.raises(ConflictError):
            repo.update_course(db, moving.id, changes={"department_id": department.id})

    def test_renaming_leaves_the_code_alone(self, db: DbSession, department: m.Department) -> None:
        course = repo.create_course(db, code="CS101", name="Intro", department_id=department.id)
        assert course.id is not None

        updated = repo.update_course(db, course.id, changes={"name": "Introduction to Computing"})

        assert updated.name == "Introduction to Computing"
        assert updated.code == "CS101"

    def test_a_course_keeps_its_own_code_when_edited(
        self, db: DbSession, department: m.Department
    ) -> None:
        """`exclude_id` is what makes this work — without it a course would collide with
        itself the moment any other field was edited."""
        course = repo.create_course(db, code="CS101", name="Intro", department_id=department.id)
        assert course.id is not None

        updated = repo.update_course(db, course.id, changes={"code": "CS101", "credits": 4})

        assert updated.credits == 4


class TestDeleting:
    def test_an_unoffered_course_is_deleted(self, db: DbSession, department: m.Department) -> None:
        course = repo.create_course(db, code="CS101", name="Intro", department_id=department.id)
        assert course.id is not None

        repo.delete_course(db, course.id)

        assert repo.list_courses(db) == []

    def test_deleting_an_offered_course_is_refused(
        self, db: DbSession, department: m.Department, term: m.Term
    ) -> None:
        """The guard proved by breaking the thing it guards.

        ``offering.course_id`` cascades, and ``session`` cascades from ``offering``, so
        without the refusal this delete would silently remove the offering too. The
        offering is inserted through the ORM because no endpoint creates one yet — the
        table has existed since 1.3, and waiting for part 2 would mean shipping a guard
        nobody has seen fire.
        """
        course = repo.create_course(db, code="CS101", name="Intro", department_id=department.id)
        assert course.id is not None
        db.add(m.Offering(term_id=term.id, course_id=course.id))
        db.flush()

        with pytest.raises(ConflictError) as raised:
            repo.delete_course(db, course.id)

        assert raised.value.blockers == {"offerings": 1}

    def test_the_offering_survives_the_refusal(
        self, db: DbSession, department: m.Department, term: m.Term
    ) -> None:
        """Refusing is only useful if nothing was destroyed on the way to refusing."""
        course = repo.create_course(db, code="CS101", name="Intro", department_id=department.id)
        assert course.id is not None
        db.add(m.Offering(term_id=term.id, course_id=course.id))
        db.flush()

        with pytest.raises(ConflictError):
            repo.delete_course(db, course.id)

        assert db.query(m.Offering).count() == 1
        assert repo.get_course(db, course.id).code == "CS101"

    def test_deleting_something_that_is_not_there(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.delete_course(db, 999)


class TestListing:
    def test_courses_are_ordered_by_code(self, db: DbSession, department: m.Department) -> None:
        for code in ("CS201", "CS101", "CS301"):
            repo.create_course(db, code=code, name=code, department_id=department.id)

        assert [c.code for c in repo.list_courses(db)] == ["CS101", "CS201", "CS301"]

    def test_listing_filters_by_department(
        self, db: DbSession, department: m.Department, other_department: m.Department
    ) -> None:
        repo.create_course(db, code="CS101", name="Intro", department_id=department.id)
        repo.create_course(db, code="MA101", name="Calculus", department_id=other_department.id)
        repo.create_course(db, code="GEN101", name="Unassigned")

        found = repo.list_courses(db, department_id=department.id)

        assert [c.code for c in found] == ["CS101"]

    def test_an_unknown_department_is_rejected_on_create(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.create_course(db, code="CS101", name="Intro", department_id=999)
