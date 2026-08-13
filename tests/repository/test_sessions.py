"""Weekly patterns and the blocks they generate.

Sessions are generated, never authored — there is no `POST /sessions` in the contract
and P7 shows the pattern producing them. Expansion arrives in part 4, so the sessions
here are inserted through the ORM. That is not a workaround: these tests are about the
rules that hold *once a session exists*, and waiting for part 4 to test them would mean
shipping guards nobody has seen fire.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.repository import calendar as calendar_repo
from tessera.repository import groups as groups_repo
from tessera.repository import models as m
from tessera.repository import sessions as repo
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as teaching_repo
from tessera.repository.errors import ConflictError, InvalidReferenceError, NotFoundError


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


def a_session(db: DbSession, offering_id: int, *, attendees: list[int], duration: int = 2) -> int:
    """A session inserted directly, standing in for what part 4 will generate."""
    offering = db.get(m.Offering, offering_id)
    assert offering is not None
    row = m.Session(
        offering_id=offering_id,
        term_id=offering.term_id,
        kind="lecture",
        duration_slots=duration,
    )
    row.attendees = [db.get(m.StudentGroup, g) for g in attendees]  # type: ignore[misc]
    db.add(row)
    db.flush()
    return int(row.id)


def schedule(db: DbSession, session_id: int, *, status: str = "draft") -> None:
    """Place a session in a timetable, which is what "scheduled" means everywhere here.

    An assignment needs a room, and `room_id` is RESTRICT rather than nullable — the
    schema does not model a half-placed session, and neither does this.
    """
    block = db.get(m.Session, session_id)
    assert block is not None
    room = m.Room(name=f"LH-{session_id}", capacity=200)
    timetable = m.Timetable(term_id=block.term_id, name="Draft", status=status)
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


class TestTemplates:
    def test_a_template_records_the_weekly_pattern(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        template = repo.create_template(
            db, offering_id=offering_id, duration_slots=2, per_week=3, attendee_ids=[intake]
        )

        assert template.per_week == 3
        assert template.attendee_ids == frozenset({intake})

    def test_the_domain_computes_how_many_sessions_a_pattern_makes(
        self, db: DbSession, offering_id: int, batches: list[int]
    ) -> None:
        """`session_count` is the expansion arithmetic and it already exists.

        Part 4 must produce exactly this many; recomputing it there would be a second
        definition of what a weekly pattern means.
        """
        split = repo.create_template(
            db,
            offering_id=offering_id,
            kind=d.SessionKind.LAB,
            duration_slots=4,
            per_week=1,
            split_per_attendee=True,
            attendee_ids=batches,
        )
        together = repo.create_template(
            db, offering_id=offering_id, duration_slots=2, per_week=3, attendee_ids=batches
        )

        assert split.session_count == 3
        assert together.session_count == 3

    def test_a_template_taught_to_nobody_is_refused(self, db: DbSession, offering_id: int) -> None:
        """Rejected by the domain, surfaced as a conflict."""
        with pytest.raises(ConflictError, match="at least one group"):
            repo.create_template(
                db, offering_id=offering_id, duration_slots=2, per_week=1, attendee_ids=[]
            )

    def test_an_unknown_attendee_is_rejected_against_its_field(
        self, db: DbSession, offering_id: int
    ) -> None:
        with pytest.raises(InvalidReferenceError) as raised:
            repo.create_template(
                db, offering_id=offering_id, duration_slots=2, per_week=1, attendee_ids=[999]
            )

        assert raised.value.field == "attendee_ids"

    def test_a_component_longer_than_the_day_is_refused(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """The `grid` fixture is 16 slots a day with lunch at 8 and 9, so the longest
        placeable block is 8. A 12-slot lab could never be scheduled anywhere, and
        finding that out at solve time is the late failure Decision #29 exists to stop.
        """
        with pytest.raises(ConflictError, match="fits in this term's teaching week"):
            repo.create_template(
                db, offering_id=offering_id, duration_slots=12, per_week=1, attendee_ids=[intake]
            )

    def test_a_group_from_another_institution_is_refused(
        self, db: DbSession, offering_id: int
    ) -> None:
        elsewhere = structure_repo.create_institution(db, name="Somewhere Else")
        assert elsewhere.id is not None
        department = structure_repo.create_department(
            db, institution_id=elsewhere.id, name="Physics"
        )
        assert department.id is not None
        program = groups_repo.create_program(db, name="BSc", department_id=department.id)
        assert program.id is not None
        foreign = groups_repo.create_group(db, name="Their Intake", size=50, program_id=program.id)
        assert foreign.id is not None

        with pytest.raises(ConflictError, match="another institution"):
            repo.create_template(
                db,
                offering_id=offering_id,
                duration_slots=2,
                per_week=1,
                attendee_ids=[int(foreign.id)],
            )

    def test_templates_are_listed_for_their_offering(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        repo.create_template(
            db, offering_id=offering_id, duration_slots=2, per_week=3, attendee_ids=[intake]
        )

        assert len(repo.list_templates(db, offering_id=offering_id)) == 1

    def test_listing_for_an_unknown_offering(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.list_templates(db, offering_id=999)


class TestDeletingATemplate:
    def test_deleting_a_component_takes_its_sessions(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """Sessions are derived data with no independent existence, so removing the
        component they came from is what the caller means."""
        template = repo.create_template(
            db, offering_id=offering_id, duration_slots=2, per_week=1, attendee_ids=[intake]
        )
        assert template.id is not None
        generated = a_session(db, offering_id, attendees=[intake])
        db.get(m.Session, generated).template_id = template.id  # type: ignore[union-attr]
        db.flush()

        repo.delete_template(db, template.id)

        assert db.query(m.Session).count() == 0

    def test_deleting_is_refused_while_a_session_is_scheduled(
        self, db: DbSession, offering_id: int, intake: int, grid: m.TimeGrid
    ) -> None:
        """The guard proved by breaking the thing it guards.

        A placed session is somebody's work rather than derived data, so this is the one
        case where removing the component is refused. Symmetric with expansion's rule.
        """
        template = repo.create_template(
            db, offering_id=offering_id, duration_slots=2, per_week=1, attendee_ids=[intake]
        )
        assert template.id is not None
        generated = a_session(db, offering_id, attendees=[intake])
        block = db.get(m.Session, generated)
        assert block is not None
        block.template_id = template.id
        db.flush()
        schedule(db, generated)

        with pytest.raises(ConflictError) as raised:
            repo.delete_template(db, template.id)

        assert raised.value.blockers == {"scheduled_sessions": 1}

    def test_nothing_is_destroyed_by_the_refusal(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        template = repo.create_template(
            db, offering_id=offering_id, duration_slots=2, per_week=1, attendee_ids=[intake]
        )
        assert template.id is not None
        generated = a_session(db, offering_id, attendees=[intake])
        block = db.get(m.Session, generated)
        assert block is not None
        block.template_id = template.id
        db.flush()
        schedule(db, generated)

        with pytest.raises(ConflictError):
            repo.delete_template(db, template.id)

        assert db.query(m.Session).count() == 1
        assert repo.get_template(db, template.id).per_week == 1

    def test_an_unexpanded_template_is_deleted(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        template = repo.create_template(
            db, offering_id=offering_id, duration_slots=2, per_week=1, attendee_ids=[intake]
        )
        assert template.id is not None

        repo.delete_template(db, template.id)

        assert repo.list_templates(db, offering_id=offering_id) == []


class TestSessions:
    def test_sessions_are_filtered_by_group(
        self, db: DbSession, offering_id: int, intake: int, batches: list[int]
    ) -> None:
        a_session(db, offering_id, attendees=[intake])
        a_session(db, offering_id, attendees=[batches[0]])
        offering = db.get(m.Offering, offering_id)
        assert offering is not None

        found = repo.list_sessions(db, term_id=offering.term_id, group_id=batches[0])

        assert len(found) == 1

    def test_sessions_are_filtered_by_instructor(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        from tessera.repository import people as people_repo

        teacher = people_repo.create_instructor(db, name="Prof. Sharma")
        assert teacher.id is not None
        first = a_session(db, offering_id, attendees=[intake])
        a_session(db, offering_id, attendees=[intake])
        block = db.get(m.Session, first)
        assert block is not None
        block.instructors = [db.get(m.Instructor, teacher.id)]  # type: ignore[list-item]
        db.flush()
        offering = db.get(m.Offering, offering_id)
        assert offering is not None

        found = repo.list_sessions(db, term_id=offering.term_id, instructor_id=int(teacher.id))

        assert [s.id for s in found] == [first]

    def test_headcount_does_not_double_count_overlapping_groups(
        self, db: DbSession, offering_id: int, intake: int, batches: list[int]
    ) -> None:
        """An intake of 120 split into three batches of 40 is 120 students, not 240.

        The resolution to leaves is the domain's; this proves the repository unions them
        rather than summing headcounts per attendee.
        """
        assert repo.headcount_of(db, [intake]) == 120
        assert repo.headcount_of(db, [intake, *batches]) == 120
        assert repo.headcount_of(db, batches) == 120

    def test_a_session_can_diverge_from_its_template(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """One lab running long is a real thing to want, and the domain expects it:
        duration is copied into a session precisely so this is possible."""
        created = a_session(db, offering_id, attendees=[intake], duration=2)

        updated = repo.update_session(db, created, changes={"duration_slots": 4})

        assert updated.duration_slots == 4

    def test_editing_is_refused_while_scheduled(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        """Every editable field changes whether an existing placement is still legal —
        a longer session may run through a break, a new feature may not be in the
        assigned room. Silently invalidating a published timetable is the failure this
        phase keeps guarding against.
        """
        created = a_session(db, offering_id, attendees=[intake])
        schedule(db, created, status="published")

        with pytest.raises(ConflictError, match="unschedule it before editing"):
            repo.update_session(db, created, changes={"duration_slots": 4})

    def test_editing_beyond_the_teaching_day_is_refused(
        self, db: DbSession, offering_id: int, intake: int
    ) -> None:
        created = a_session(db, offering_id, attendees=[intake])

        with pytest.raises(ConflictError, match="fits in this term's teaching week"):
            repo.update_session(db, created, changes={"duration_slots": 12})

    def test_an_unknown_session(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.get_session(db, 999)
