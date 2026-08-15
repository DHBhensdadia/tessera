"""The exit test for Phase 2.7b: every case in R5 §3 can be said.

R5 asked whether the schema could hold what a real department actually needs, and found
five things it could not. Each is written here as data and read back, because "the column
exists" is not the same claim as "the case survives a round trip".

Nothing here solves or enforces anything — that is Stage 4. The question is only whether
the data has somewhere to live.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session as DbSession

from tessera.domain import (
    Constraint,
    ConstraintKind,
    ConstraintTarget,
    Room,
    SessionKind,
    TargetKind,
    Unavailability,
    WeekPattern,
)
from tessera.domain import entities as d
from tessera.domain.ids import (
    FeatureId,
    InstructorId,
    OfferingId,
    StudentGroupId,
    TermId,
)
from tessera.repository import mappers
from tessera.repository import models as m


@pytest.fixture
def computers(db: DbSession, institution: m.Institution) -> m.Feature:
    row = m.Feature(institution_id=institution.id, name="computers")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def offering(db: DbSession, term: m.Term) -> m.Offering:
    course = m.Course(code="CS301", name="Operating Systems")
    db.add(course)
    db.commit()
    row = m.Offering(term_id=term.id, course_id=course.id)
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def batch(db: DbSession) -> m.StudentGroup:
    row = m.StudentGroup(name="CSE5-A1", size=30)
    db.add(row)
    db.commit()
    return row


class TestF1ConstraintsCanNameAnyResource:
    """*"Prof. Shah may teach at most 3 consecutive hours."*

    The finding R5 called urgent, and the only one that had to happen before 2.8.
    """

    def test_a_constraint_can_target_an_instructor(self, db: DbSession, term: m.Term) -> None:
        shah = m.Instructor(name="Prof. Shah")
        db.add(shah)
        db.commit()

        original = Constraint(
            term_id=TermId(term.id),
            kind=ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            targets=frozenset({ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=shah.id)}),
            params={"slots": 3},
        )
        row = mappers.constraint_to_orm(db, original)
        db.add(row)
        db.commit()

        restored = mappers.constraint_to_domain(row)
        assert restored.targets == original.targets
        assert restored.params == {"slots": 3}

    def test_a_constraint_can_target_a_student_group(
        self, db: DbSession, term: m.Term, batch: m.StudentGroup
    ) -> None:
        original = Constraint(
            term_id=TermId(term.id),
            kind=ConstraintKind.MINIMISE_GROUP_GAPS,
            targets=frozenset({ConstraintTarget(kind=TargetKind.GROUP, id=batch.id)}),
        )
        row = mappers.constraint_to_orm(db, original)
        db.add(row)
        db.commit()

        assert mappers.constraint_to_domain(row).targets == original.targets

    def test_one_constraint_can_mix_kinds(
        self, db: DbSession, term: m.Term, batch: m.StudentGroup
    ) -> None:
        """The point of a polymorphic target rather than five nullable columns."""
        shah = m.Instructor(name="Prof. Shah")
        db.add(shah)
        db.commit()

        original = Constraint(
            term_id=TermId(term.id),
            kind=ConstraintKind.MINIMISE_BUILDING_CHANGES,
            targets=frozenset(
                {
                    ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=shah.id),
                    ConstraintTarget(kind=TargetKind.GROUP, id=batch.id),
                }
            ),
        )
        row = mappers.constraint_to_orm(db, original)
        db.add(row)
        db.commit()

        assert mappers.constraint_to_domain(row).targets == original.targets

    def test_target_ids_still_means_sessions_only(
        self, db: DbSession, term: m.Term, batch: m.StudentGroup
    ) -> None:
        """The frozen contract speaks in session ids, and must keep meaning that.

        A group whose id happens to match a session's would otherwise leak into
        ``target_ids`` and be read as a session — a wrong timetable, from a rename.
        """
        constraint = Constraint(
            term_id=TermId(term.id),
            kind=ConstraintKind.MINIMISE_GROUP_GAPS,
            targets=frozenset({ConstraintTarget(kind=TargetKind.GROUP, id=batch.id)}),
        )
        assert constraint.target_ids == frozenset()

    def test_a_target_that_does_not_exist_is_refused(self, db: DbSession, term: m.Term) -> None:
        """``target_id`` carries no foreign key, so this check is the only one there is."""
        constraint = Constraint(
            term_id=TermId(term.id),
            kind=ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
            targets=frozenset({ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=9999)}),
        )
        with pytest.raises(LookupError, match="Instructor"):
            mappers.constraint_to_orm(db, constraint)

    def test_a_targeted_constraint_still_needs_a_target(self, term: m.Term) -> None:
        with pytest.raises(ValidationError, match="must name what it applies to"):
            Constraint(term_id=TermId(term.id), kind=ConstraintKind.SAME_ROOM)


class TestF2FortnightlyTeaching:
    """*"The lab runs in odd weeks; the other batch has it in even weeks."*"""

    def test_a_session_can_run_in_odd_weeks_only(
        self, db: DbSession, term: m.Term, offering: m.Offering, batch: m.StudentGroup
    ) -> None:
        original = d.Session(
            offering_id=OfferingId(offering.id),
            kind=SessionKind.LAB,
            duration_slots=2,
            attendee_ids=frozenset({StudentGroupId(batch.id)}),
            week_pattern=WeekPattern.ODD_WEEKS,
        )
        row = mappers.session_to_orm(db, original, term.id)
        db.add(row)
        db.commit()

        assert mappers.session_to_domain(row).week_pattern is WeekPattern.ODD_WEEKS

    def test_a_template_carries_the_pattern_too(
        self, db: DbSession, offering: m.Offering, batch: m.StudentGroup
    ) -> None:
        original = d.SessionTemplate(
            offering_id=OfferingId(offering.id),
            kind=SessionKind.LAB,
            duration_slots=2,
            per_week=1,
            attendee_ids=frozenset({StudentGroupId(batch.id)}),
            week_pattern=WeekPattern.EVEN_WEEKS,
        )
        row = mappers.template_to_orm(db, original)
        db.add(row)
        db.commit()

        assert mappers.template_to_domain(row).week_pattern is WeekPattern.EVEN_WEEKS

    def test_alternating_patterns_cannot_collide(self) -> None:
        """The whole of the rule the solver needs from this column."""
        assert not WeekPattern.ODD_WEEKS.coincides_with(WeekPattern.EVEN_WEEKS)
        assert WeekPattern.ODD_WEEKS.coincides_with(WeekPattern.ODD_WEEKS)
        assert WeekPattern.EVERY_WEEK.coincides_with(WeekPattern.ODD_WEEKS)
        assert WeekPattern.ODD_WEEKS.coincides_with(WeekPattern.EVERY_WEEK)

    def test_everything_written_before_this_runs_every_week(self) -> None:
        assert (
            d.Session(
                offering_id=OfferingId(1),
                duration_slots=1,
                attendee_ids=frozenset({StudentGroupId(1)}),
            ).week_pattern
            is WeekPattern.EVERY_WEEK
        )


class TestF3EquipmentIsCounted:
    """*"A 30-machine lab that seats 70 cannot take a division of 60 for a lab."*

    The case from the question that prompted R5, and the one the old schema got wrong in
    the most damaging direction: it said yes.
    """

    def test_a_room_records_how_many_it_has(self, db: DbSession, computers: m.Feature) -> None:
        original = Room(
            name="Lab 1",
            capacity=70,
            features=frozenset({FeatureId(computers.id)}),
            feature_counts={FeatureId(computers.id): 30},
        )
        row = mappers.room_to_orm(db, original)
        db.add(row)
        db.commit()

        restored = mappers.room_to_domain(row)
        assert restored.feature_counts == {computers.id: 30}
        assert restored.features == frozenset({computers.id})

    def test_a_session_records_how_many_it_needs(
        self, db: DbSession, term: m.Term, offering: m.Offering, batch: m.StudentGroup
    ) -> None:
        original = d.Session(
            offering_id=OfferingId(offering.id),
            kind=SessionKind.LAB,
            duration_slots=2,
            attendee_ids=frozenset({StudentGroupId(batch.id)}),
            required_features=frozenset({FeatureId(1)}),
            required_counts={FeatureId(1): 30},
        )
        feature = m.Feature(institution_id=1, name="workstations")
        db.add(feature)
        db.commit()
        original = original.model_copy(
            update={
                "required_features": frozenset({FeatureId(feature.id)}),
                "required_counts": {FeatureId(feature.id): 30},
            }
        )

        row = mappers.session_to_orm(db, original, term.id)
        db.add(row)
        db.commit()

        assert mappers.session_to_domain(row).required_counts == {feature.id: 30}

    def test_sixty_students_do_not_fit_thirty_machines(self) -> None:
        """The finding stated as an assertion. This is what the old schema could not say."""
        lab = Room(
            name="Lab 1",
            capacity=70,
            features=frozenset({FeatureId(1)}),
            feature_counts={FeatureId(1): 30},
        )
        assert lab.can_host(60, frozenset({FeatureId(1)}))
        assert not lab.can_host(60, frozenset({FeatureId(1)}), {FeatureId(1): 60})
        assert lab.can_host(30, frozenset({FeatureId(1)}), {FeatureId(1): 30})

    def test_an_uncounted_feature_is_satisfied_by_being_present(self) -> None:
        """A projector is a projector. Nobody counts, and nothing should make them."""
        hall = Room(name="LH-1", capacity=200, features=frozenset({FeatureId(2)}))
        assert hall.can_host(150, frozenset({FeatureId(2)}))

    def test_a_count_for_a_feature_the_room_lacks_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="does not have"):
            Room(name="Lab 1", capacity=70, feature_counts={FeatureId(1): 30})

    def test_a_count_for_a_feature_not_required_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="not required"):
            d.Session(
                offering_id=OfferingId(1),
                duration_slots=2,
                attendee_ids=frozenset({StudentGroupId(1)}),
                required_counts={FeatureId(1): 30},
            )

    def test_renaming_a_room_does_not_forget_its_equipment(
        self, db: DbSession, computers: m.Feature
    ) -> None:
        """``features`` says which, not how many, so a plain edit must not reset counts."""
        row = mappers.room_to_orm(
            db,
            Room(
                name="Lab 1",
                capacity=70,
                features=frozenset({FeatureId(computers.id)}),
                feature_counts={FeatureId(computers.id): 30},
            ),
        )
        db.add(row)
        db.commit()

        row.features = list(row.features)
        db.commit()

        assert mappers.room_to_domain(row).feature_counts == {computers.id: 30}


class TestF4RoomsNeedClearing:
    """*"15 minutes to clear the chemistry lab."*"""

    def test_a_room_records_its_turnaround(self, db: DbSession) -> None:
        row = mappers.room_to_orm(db, Room(name="Chem Lab", capacity=40, turnaround_slots=1))
        db.add(row)
        db.commit()

        assert mappers.room_to_domain(row).turnaround_slots == 1

    def test_an_ordinary_classroom_needs_none(self) -> None:
        assert Room(name="LH-1", capacity=60).turnaround_slots == 0

    def test_a_negative_turnaround_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Room(name="LH-1", capacity=60, turnaround_slots=-1)


class TestF5PreferencesAsWellAsRefusals:
    """*"I would rather not teach Friday afternoons."*

    Gives ``RESPECT_INSTRUCTOR_PREFERENCES`` — a constraint kind with no data behind it
    since 1.3 — something to read.
    """

    def test_an_instructor_can_merely_prefer_not_to(self, db: DbSession, term: m.Term) -> None:
        shah = m.Instructor(name="Prof. Shah")
        db.add(shah)
        db.commit()

        original = Unavailability(
            term_id=TermId(term.id),
            instructor_id=InstructorId(shah.id),
            slot=34,
            reason="Friday afternoon",
            is_hard=False,
            weight=5,
        )
        row = mappers.unavailability_to_orm(original)
        db.add(row)
        db.commit()

        restored = mappers.unavailability_to_domain(row)
        assert restored.is_hard is False
        assert restored.weight == 5
        assert restored.reason == "Friday afternoon"

    def test_a_refusal_is_still_the_default(self) -> None:
        """Every row written before 2.7b meant *cannot*, and still does."""
        assert Unavailability(term_id=TermId(1), instructor_id=InstructorId(1), slot=0).is_hard

    def test_a_preference_worth_nothing_is_refused(self) -> None:
        """A soft rule with zero weight is a rule that does nothing, written by mistake."""
        with pytest.raises(ValidationError):
            Unavailability(
                term_id=TermId(1),
                instructor_id=InstructorId(1),
                slot=0,
                is_hard=False,
                weight=0,
            )


def test_a_room_can_be_the_whole_of_the_lab_case(db: DbSession, computers: m.Feature) -> None:
    """R5's cases are not independent, so one row proves they compose.

    A chemistry-style computer lab: thirty machines, seventy seats, one slot to clear.
    """
    row = mappers.room_to_orm(
        db,
        Room(
            name="CL-2",
            capacity=70,
            features=frozenset({FeatureId(computers.id)}),
            feature_counts={FeatureId(computers.id): 30},
            turnaround_slots=1,
        ),
    )
    db.add(row)
    db.commit()
    db.expire_all()

    reloaded = db.get(m.Room, row.id)
    assert reloaded is not None
    restored = mappers.room_to_domain(reloaded)
    assert restored.capacity == 70
    assert restored.feature_counts == {computers.id: 30}
    assert restored.turnaround_slots == 1
    assert not restored.can_host(
        60, frozenset({FeatureId(computers.id)}), {FeatureId(computers.id): 60}
    )
