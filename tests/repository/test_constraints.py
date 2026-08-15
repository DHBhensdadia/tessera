"""Storing and retuning the rules an institution chose."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain.constraints import ConstraintKind, ConstraintTarget, TargetKind
from tessera.domain.ids import OfferingId, StudentGroupId
from tessera.repository import calendar as calendar_repo
from tessera.repository import constraints as repo
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import (
    InvalidReferenceError,
    NotFoundError,
    RuleViolationError,
)


@pytest.fixture
def seeded_term(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> m.Term:
    """A term made the way the application makes one.

    The shared `term` fixture builds the row directly, which is right for tests that only
    need something to hang data off — but the defaults arrive in `create_term`, so a test
    about them has to go through it.
    """
    created = calendar_repo.create_term(
        db,
        institution_id=institution.id,
        time_grid_id=grid.id,
        academic_year="2026-27",
        name="Autumn",
    )
    db.commit()
    row = db.get(m.Term, int(created.id or 0))
    assert row is not None
    return row


@pytest.fixture
def shah(db: DbSession) -> m.Instructor:
    row = m.Instructor(name="Prof. Shah")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def batch(db: DbSession) -> m.StudentGroup:
    row = m.StudentGroup(name="CSE5-A1", size=30)
    db.add(row)
    db.commit()
    return row


def make_session(db: DbSession, term: m.Term, group: m.StudentGroup, occurrence: int) -> m.Session:
    course = db.query(m.Course).filter_by(code="CS301").one_or_none() or m.Course(
        code="CS301", name="Operating Systems"
    )
    db.add(course)
    db.commit()
    offering = db.query(m.Offering).filter_by(term_id=term.id, course_id=course.id).one_or_none()
    if offering is None:
        offering = m.Offering(term_id=term.id, course_id=course.id)
        db.add(offering)
        db.commit()

    from tessera.domain import entities as d

    row = mappers.session_to_orm(
        db,
        d.Session(
            offering_id=OfferingId(offering.id),
            duration_slots=2,
            occurrence=occurrence,
            attendee_ids=frozenset({StudentGroupId(group.id)}),
        ),
        term.id,
    )
    db.add(row)
    db.commit()
    return row


class TestDefaultsComeWithTheTerm:
    def test_a_new_term_starts_with_the_default_preferences(
        self, db: DbSession, seeded_term: m.Term
    ) -> None:
        """`default_constraints` existed from 1.3 and was called by nothing until 2.8."""
        stored = repo.list_constraints(db, seeded_term.id)
        assert {c.kind for c in stored} == {
            ConstraintKind.MINIMISE_GROUP_GAPS,
            ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
            ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY,
            ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES,
            ConstraintKind.MINIMISE_BUILDING_CHANGES,
            ConstraintKind.BALANCE_DAILY_LOAD,
            ConstraintKind.PREFER_ROOM_STABILITY,
        }

    def test_student_time_is_weighted_above_staff_convenience(
        self, db: DbSession, seeded_term: m.Term
    ) -> None:
        """R1 §3's emphasis, which is the argument the weights are meant to encode."""
        weights = {c.kind: c.weight for c in repo.list_constraints(db, seeded_term.id)}
        assert (
            weights[ConstraintKind.MINIMISE_GROUP_GAPS]
            > weights[ConstraintKind.MINIMISE_INSTRUCTOR_GAPS]
        )
        assert (
            weights[ConstraintKind.PREFER_ROOM_STABILITY]
            < weights[ConstraintKind.MINIMISE_GROUP_GAPS]
        )

    def test_every_default_is_a_soft_term_wide_preference(
        self, db: DbSession, seeded_term: m.Term
    ) -> None:
        for constraint in repo.list_constraints(db, seeded_term.id):
            assert not constraint.is_hard
            assert not constraint.targets

    def test_the_defaults_belong_to_their_own_term(
        self, db: DbSession, seeded_term: m.Term, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        other = calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2027-28",
            name="Autumn",
        )
        db.commit()
        assert len(repo.list_constraints(db, seeded_term.id)) == 7
        assert len(repo.list_constraints(db, int(other.id or 0))) == 7


class TestCreating:
    def test_a_rule_about_one_instructor(
        self, db: DbSession, term: m.Term, shah: m.Instructor
    ) -> None:
        stored = repo.create_constraint(
            db,
            term.id,
            kind=ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            targets=[ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=shah.id)],
            params={"slots": 3},
            is_hard=True,
        )
        db.commit()

        assert stored.is_hard
        assert stored.describe("Prof. Shah") == "Give Prof. Shah at most 3 hour(s) in a row"
        assert repo.get_constraint(db, int(stored.id or 0)).targets == stored.targets

    def test_a_distribution_rule_over_sessions(
        self, db: DbSession, term: m.Term, batch: m.StudentGroup
    ) -> None:
        sessions = [make_session(db, term, batch, i) for i in range(2)]
        stored = repo.create_constraint(
            db,
            term.id,
            kind=ConstraintKind.NOT_OVERLAP,
            targets=[ConstraintTarget(kind=TargetKind.SESSION, id=s.id) for s in sessions],
        )
        db.commit()
        assert stored.target_ids == {s.id for s in sessions}

    def test_a_target_that_does_not_exist_names_the_field(
        self, db: DbSession, term: m.Term
    ) -> None:
        with pytest.raises(InvalidReferenceError) as caught:
            repo.create_constraint(
                db,
                term.id,
                kind=ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
                targets=[ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=404)],
            )
        assert caught.value.field == "targets[instructor]"
        assert caught.value.missing == [404]

    def test_a_rule_on_another_term_s_session_is_refused(
        self,
        db: DbSession,
        term: m.Term,
        batch: m.StudentGroup,
        institution: m.Institution,
        grid: m.TimeGrid,
    ) -> None:
        """Nothing in the schema relates a target to a term, so this is the only check.

        It would otherwise be stored, match nothing the solver placed, and read as a
        rule that simply does not work.
        """
        elsewhere = calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2027-28",
            name="Autumn",
        )
        db.commit()
        stray = make_session(db, term, batch, 0)

        with pytest.raises(RuleViolationError, match="belong to another term"):
            repo.create_constraint(
                db,
                int(elsewhere.id or 0),
                kind=ConstraintKind.SAME_ROOM,
                targets=[ConstraintTarget(kind=TargetKind.SESSION, id=stray.id)],
            )

    def test_a_constraint_on_a_term_that_does_not_exist(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.create_constraint(db, 999, kind=ConstraintKind.MINIMISE_GROUP_GAPS)


class TestRetuning:
    def test_the_weight_slider(self, db: DbSession, seeded_term: m.Term) -> None:
        original = repo.list_constraints(
            db, seeded_term.id, kind=ConstraintKind.MINIMISE_GROUP_GAPS
        )[0]
        updated = repo.update_constraint(db, int(original.id or 0), changes={"weight": 20})
        db.commit()

        assert updated.weight == 20
        assert updated.kind is original.kind

    def test_a_preference_can_be_switched_off_without_losing_its_tuning(
        self, db: DbSession, seeded_term: m.Term
    ) -> None:
        original = repo.list_constraints(
            db, seeded_term.id, kind=ConstraintKind.BALANCE_DAILY_LOAD
        )[0]
        updated = repo.update_constraint(db, int(original.id or 0), changes={"enabled": False})
        db.commit()

        assert not updated.enabled
        assert updated.weight == original.weight

    def test_narrowing_a_term_wide_preference_to_one_person(
        self, db: DbSession, seeded_term: m.Term, shah: m.Instructor
    ) -> None:
        original = repo.list_constraints(
            db, seeded_term.id, kind=ConstraintKind.MINIMISE_INSTRUCTOR_GAPS
        )[0]
        updated = repo.update_constraint(
            db,
            int(original.id or 0),
            changes={"targets": {ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=shah.id)}},
        )
        db.commit()

        assert updated.targets == {ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=shah.id)}

    def test_dropping_the_targets_from_a_hard_rule_is_refused(
        self, db: DbSession, term: m.Term, shah: m.Instructor
    ) -> None:
        """The reason an edit is re-validated as a whole rather than field by field.

        Hard and untargeted is a state neither field is wrong on its own.
        """
        stored = repo.create_constraint(
            db,
            term.id,
            kind=ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            targets=[ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=shah.id)],
            params={"slots": 3},
            is_hard=True,
        )
        db.commit()

        with pytest.raises(RuleViolationError, match="cannot be hard"):
            repo.update_constraint(db, int(stored.id or 0), changes={"targets": set()})

    def test_a_parameter_outside_its_range_is_refused_on_edit_too(
        self, db: DbSession, term: m.Term, batch: m.StudentGroup
    ) -> None:
        sessions = [make_session(db, term, batch, i) for i in range(2)]
        stored = repo.create_constraint(
            db,
            term.id,
            kind=ConstraintKind.MAX_DAYS_BETWEEN,
            targets=[ConstraintTarget(kind=TargetKind.SESSION, id=s.id) for s in sessions],
            params={"days": 2},
        )
        db.commit()

        with pytest.raises(RuleViolationError, match="days must be between 1 and 7"):
            repo.update_constraint(db, int(stored.id or 0), changes={"params": {"days": 900}})


class TestRemoving:
    def test_a_rule_can_always_be_withdrawn(self, db: DbSession, seeded_term: m.Term) -> None:
        stored = repo.list_constraints(db, seeded_term.id)[0]
        repo.delete_constraint(db, int(stored.id or 0))
        db.commit()

        assert stored.kind not in {c.kind for c in repo.list_constraints(db, seeded_term.id)}

    def test_deleting_a_term_takes_its_constraints(
        self, db: DbSession, seeded_term: m.Term
    ) -> None:
        constraint_id = int(repo.list_constraints(db, seeded_term.id)[0].id or 0)
        db.delete(db.get(m.Term, seeded_term.id))
        db.commit()

        assert db.get(m.Constraint, constraint_id) is None

    def test_deleting_one_that_is_gone(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.delete_constraint(db, 999)


def test_the_kind_column_does_not_enumerate_the_kinds() -> None:
    """The "no migration" half of the exit test, checked against the schema itself.

    A ``sa.Enum`` column would put every kind name in the database's type definition, and
    adding one would then need a migration on every existing project — which is exactly
    the promise Decision #12 made and this phase is meant to keep. A plain string cannot
    have that problem.
    """
    from sqlalchemy import String

    kind_column = m.Constraint.__table__.c.kind
    assert isinstance(kind_column.type, String)
    assert not hasattr(kind_column.type, "enums")
