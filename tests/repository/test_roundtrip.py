"""Domain objects survive a trip through the database unchanged.

Keeping the domain free of SQLAlchemy means two model sets and a translation between
them (ADR-0003, Decision #14). The risk that buys is silent divergence — a field added
to one side and forgotten on the other, which loses data with no error anywhere. These
tests exist to make that loud.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from tessera.domain import (
    Assignment,
    CommandKind,
    Constraint,
    ConstraintKind,
    GroupKind,
    Room,
    SessionKind,
    StudentGroup,
    TimeGrid,
    TimetableStatus,
)
from tessera.domain import entities as d
from tessera.domain.ids import (
    FeatureId,
    InstructorId,
    OfferingId,
    RoomId,
    SessionId,
    StudentGroupId,
    TermId,
    TimetableId,
)
from tessera.repository import mappers
from tessera.repository import models as m


class TestTimeGrid:
    def test_survives_a_round_trip(self, db: DbSession, institution: m.Institution) -> None:
        original = TimeGrid(
            name="Standard",
            days=6,
            slots_per_day=16,
            slot_minutes=30,
            day_start_minute=540,
            break_slots=frozenset({8, 9}),
        )
        row = mappers.time_grid_to_orm(original, institution.id)
        db.add(row)
        db.commit()

        restored = mappers.time_grid_to_domain(row)
        assert restored.days == original.days
        assert restored.slots_per_day == original.slots_per_day
        assert restored.slot_minutes == original.slot_minutes
        assert restored.day_start_minute == original.day_start_minute
        assert restored.break_slots == original.break_slots
        assert restored.id is not None

    def test_breaks_are_not_silently_dropped(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        """A grid whose breaks vanished would schedule straight through lunch."""
        grid = TimeGrid(
            days=5,
            slots_per_day=10,
            slot_minutes=60,
            day_start_minute=540,
            break_slots=frozenset({3, 7}),
        )
        row = mappers.time_grid_to_orm(grid, institution.id)
        db.add(row)
        db.commit()
        db.expire_all()

        reloaded = db.get(m.TimeGrid, row.id)
        assert reloaded is not None
        assert mappers.time_grid_to_domain(reloaded).break_slots == {3, 7}


class TestRoom:
    def test_capabilities_survive(self, db: DbSession, features: dict[str, m.Feature]) -> None:
        room = Room(
            name="LH-201",
            capacity=120,
            features=frozenset(
                {FeatureId(features["projector"].id), FeatureId(features["smartboard"].id)}
            ),
        )
        row = mappers.room_to_orm(db, room)
        db.add(row)
        db.commit()

        restored = mappers.room_to_domain(row)
        assert restored.name == "LH-201"
        assert restored.capacity == 120
        assert restored.features == room.features

    def test_can_host_reflects_capacity_and_features(
        self, db: DbSession, features: dict[str, m.Feature]
    ) -> None:
        computers = FeatureId(features["computers"].id)
        room = mappers.room_to_domain(
            mappers.room_to_orm(
                db, Room(name="CL-01", capacity=40, features=frozenset({computers}))
            )
        )
        assert room.can_host(40, frozenset({computers}))
        assert not room.can_host(41, frozenset())
        assert not room.can_host(10, frozenset({FeatureId(features["projector"].id)}))


class TestStudentGroup:
    def test_tree_links_survive(self, db: DbSession) -> None:
        parent = m.StudentGroup(name="2024 intake", size=120)
        db.add(parent)
        db.commit()

        child = mappers.group_to_orm(
            db,
            StudentGroup(name="Lab A1", size=40, parent_id=StudentGroupId(parent.id)),
        )
        db.add(child)
        db.commit()

        restored = mappers.group_to_domain(child)
        assert restored.parent_id == parent.id
        assert restored.kind is GroupKind.STRUCTURAL

    def test_cohort_membership_survives(self, db: DbSession) -> None:
        members = [m.StudentGroup(name=f"intake {i}", size=60) for i in range(2)]
        db.add_all(members)
        db.commit()

        cohort = mappers.group_to_orm(
            db,
            StudentGroup(
                name="ML elective",
                size=45,
                kind=GroupKind.COHORT,
                member_ids=frozenset(StudentGroupId(g.id) for g in members),
            ),
        )
        db.add(cohort)
        db.commit()

        restored = mappers.group_to_domain(cohort)
        assert restored.kind is GroupKind.COHORT
        assert restored.member_ids == {g.id for g in members}


class TestSession:
    def test_every_association_survives(
        self, db: DbSession, term: m.Term, features: dict[str, m.Feature]
    ) -> None:
        course = m.Course(code="CS301", name="Operating Systems")
        group = m.StudentGroup(name="Lab A1", size=40)
        instructor = m.Instructor(name="Prof. Sharma")
        db.add_all([course, group, instructor])
        db.commit()

        offering = m.Offering(term_id=term.id, course_id=course.id)
        db.add(offering)
        db.commit()

        original = d.Session(
            offering_id=OfferingId(offering.id),
            kind=SessionKind.LAB,
            duration_slots=4,
            occurrence=1,
            attendee_ids=frozenset({StudentGroupId(group.id)}),
            instructor_ids=frozenset({InstructorId(instructor.id)}),
            required_features=frozenset({FeatureId(features["computers"].id)}),
        )
        row = mappers.session_to_orm(db, original)
        db.add(row)
        db.commit()

        restored = mappers.session_to_domain(row)
        assert restored.kind is SessionKind.LAB
        assert restored.duration_slots == 4
        assert restored.occurrence == 1
        assert restored.attendee_ids == {group.id}
        assert restored.instructor_ids == {instructor.id}
        assert restored.required_features == {features["computers"].id}

    def test_an_unknown_association_is_an_error_not_a_silent_drop(
        self, db: DbSession, term: m.Term
    ) -> None:
        course = m.Course(code="CS999", name="Ghost")
        db.add(course)
        db.commit()
        offering = m.Offering(term_id=term.id, course_id=course.id)
        db.add(offering)
        db.commit()

        ghost = d.Session(
            offering_id=OfferingId(offering.id),
            duration_slots=2,
            attendee_ids=frozenset({StudentGroupId(4242)}),
        )
        try:
            mappers.session_to_orm(db, ghost)
        except LookupError as error:
            assert "4242" in str(error)
        else:
            raise AssertionError("a missing attendee must raise rather than be dropped")


class TestConstraint:
    def test_a_global_preference_survives(self, db: DbSession, term: m.Term) -> None:
        original = Constraint(
            term_id=TermId(term.id), kind=ConstraintKind.MINIMISE_GROUP_GAPS, weight=8
        )
        row = mappers.constraint_to_orm(db, original)
        db.add(row)
        db.commit()

        restored = mappers.constraint_to_domain(row)
        assert restored.kind is ConstraintKind.MINIMISE_GROUP_GAPS
        assert restored.weight == 8
        assert restored.target_ids == frozenset()

    def test_a_targeted_constraint_keeps_its_targets_and_params(
        self, db: DbSession, term: m.Term
    ) -> None:
        course = m.Course(code="CS301", name="OS")
        group = m.StudentGroup(name="A1", size=40)
        db.add_all([course, group])
        db.commit()
        offering = m.Offering(term_id=term.id, course_id=course.id)
        db.add(offering)
        db.commit()

        sessions = []
        for i in range(2):
            session_row = mappers.session_to_orm(
                db,
                d.Session(
                    offering_id=OfferingId(offering.id),
                    duration_slots=2,
                    occurrence=i,
                    attendee_ids=frozenset({StudentGroupId(group.id)}),
                ),
            )
            db.add(session_row)
            sessions.append(session_row)
        db.commit()

        original = Constraint(
            term_id=TermId(term.id),
            kind=ConstraintKind.MIN_GAP,
            is_hard=True,
            target_ids=frozenset(SessionId(s.id) for s in sessions),
            params={"slots": 4},
        )
        constraint_row = mappers.constraint_to_orm(db, original)
        db.add(constraint_row)
        db.commit()

        restored = mappers.constraint_to_domain(constraint_row)
        assert restored.is_hard
        assert restored.params == {"slots": 4}
        assert restored.target_ids == {s.id for s in sessions}


class TestTimetableAndAssignment:
    def test_status_lineage_and_score_survive(self, db: DbSession, term: m.Term) -> None:
        parent = m.Timetable(term_id=term.id, name="Draft A", status="draft")
        db.add(parent)
        db.commit()

        row = m.Timetable(
            term_id=term.id,
            name="Draft B",
            status="published",
            parent_id=parent.id,
            penalty=1094,
            penalty_breakdown={"minimise_group_gaps": 51, "prefer_room_stability": 3},
            created_at=datetime(2026, 8, 12, 9, 0),
            published_at=datetime(2026, 8, 12, 10, 0),
        )
        db.add(row)
        db.commit()

        restored = mappers.timetable_to_domain(row)
        assert restored.status is TimetableStatus.PUBLISHED
        assert restored.parent_id == parent.id
        assert restored.penalty == 1094
        assert restored.penalty_breakdown["minimise_group_gaps"] == 51
        assert not restored.is_editable

    def test_pinning_survives(self, db: DbSession, term: m.Term) -> None:
        """The flag that makes pin-and-re-optimise possible. If it were lost in
        storage, re-solving would silently discard the user's manual work."""
        course = m.Course(code="CS301", name="OS")
        group = m.StudentGroup(name="A1", size=40)
        room = m.Room(name="LH-201", capacity=120)
        db.add_all([course, group, room])
        db.commit()
        offering = m.Offering(term_id=term.id, course_id=course.id)
        db.add(offering)
        db.commit()
        session_row = mappers.session_to_orm(
            db,
            d.Session(
                offering_id=OfferingId(offering.id),
                duration_slots=2,
                attendee_ids=frozenset({StudentGroupId(group.id)}),
            ),
        )
        timetable = m.Timetable(term_id=term.id, name="Draft")
        db.add_all([session_row, timetable])
        db.commit()

        original = Assignment(
            timetable_id=TimetableId(timetable.id),
            session_id=SessionId(session_row.id),
            start_slot=12,
            room_id=RoomId(room.id),
            is_pinned=True,
        )
        row = mappers.assignment_to_orm(original)
        db.add(row)
        db.commit()

        restored = mappers.assignment_to_domain(row)
        assert restored.is_pinned
        assert restored.start_slot == 12
        assert restored.room_id == room.id

    def test_moving_an_assignment_leaves_the_original_untouched(self) -> None:
        original = Assignment(
            session_id=SessionId(1), start_slot=4, room_id=RoomId(2), is_pinned=True
        )
        moved = original.moved_to(8, RoomId(3))
        assert (original.start_slot, original.room_id) == (4, 2)
        assert (moved.start_slot, moved.room_id) == (8, 3)
        assert moved.is_pinned


class TestCommand:
    def test_history_survives(self, db: DbSession, term: m.Term) -> None:
        timetable = m.Timetable(term_id=term.id, name="Draft")
        db.add(timetable)
        db.commit()

        row = m.Command(
            timetable_id=timetable.id,
            sequence=0,
            kind=CommandKind.MOVE.value,
            summary="Moved CS301 lecture to Tue 11:00",
            before={"start_slot": 4, "room_id": 1},
            after={"start_slot": 20, "room_id": 1},
            created_at=datetime(2026, 8, 12, 11, 0),
        )
        db.add(row)
        db.commit()

        restored = mappers.command_to_domain(row)
        assert restored.kind is CommandKind.MOVE
        assert restored.before == {"start_slot": 4, "room_id": 1}
        assert restored.after == {"start_slot": 20, "room_id": 1}
        assert not restored.is_undone

    def test_a_timetable_cannot_have_two_commands_at_one_position(
        self, db: DbSession, term: m.Term
    ) -> None:
        """History has to be a sequence, or undo has no defined order."""
        timetable = m.Timetable(term_id=term.id, name="Draft")
        db.add(timetable)
        db.commit()

        db.add(m.Command(timetable_id=timetable.id, sequence=0, kind="move"))
        db.commit()
        db.add(m.Command(timetable_id=timetable.id, sequence=0, kind="pin"))

        from sqlalchemy.exc import IntegrityError

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("duplicate sequence should violate the unique constraint")


class TestDefaults:
    def test_a_new_term_starts_with_sensible_preferences(self) -> None:
        from tessera.domain import default_constraints

        defaults = default_constraints()
        kinds = {c.kind for c in defaults}
        assert ConstraintKind.MINIMISE_GROUP_GAPS in kinds
        assert all(not c.is_hard for c in defaults)
        # Student time is weighted above staff convenience; see R1 §3.
        by_kind = {c.kind: c.weight for c in defaults}
        assert (
            by_kind[ConstraintKind.MINIMISE_GROUP_GAPS]
            > by_kind[ConstraintKind.MINIMISE_INSTRUCTOR_GAPS]
        )
