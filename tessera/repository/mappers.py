"""Translation between stored rows and domain objects.

This module is the cost of keeping ``domain`` free of SQLAlchemy (ADR-0003) and it is
paid deliberately. Reading is pure and side-effect free; writing needs a session,
because associating rows means resolving foreign keys.

Domain objects are frozen and use ``None`` ids to mean "not yet persisted", so the read
direction always produces a fully identified object and the write direction is the only
place an id is assigned.

The typed-id constructors below (``RoomId(...)`` and friends) are no-ops at runtime.
They exist so that mypy can tell a ``RoomId`` from a ``SessionId``; writing them out
rather than casting keeps that boundary visible instead of silently erased.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain import groups as dg
from tessera.domain import timetable as dt
from tessera.domain.constraints import Constraint, ConstraintKind
from tessera.domain.ids import (
    AssignmentId,
    BuildingId,
    CommandId,
    ConstraintId,
    DepartmentId,
    FeatureId,
    InstitutionId,
    InstructorId,
    OfferingId,
    ProgramId,
    RoomId,
    SessionId,
    SessionTemplateId,
    StudentGroupId,
    TermId,
    TimeGridId,
    TimetableId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.repository import models as m


def _resolve[T: m.Base](session: DbSession, model: type[T], ids: frozenset[int]) -> list[T]:
    """Load the rows an association should point at, failing loudly on a bad id.

    A silently dropped association is a data-loss bug that surfaces much later as a
    session with no attendees, so a missing id is an error rather than an omission.
    """
    if not ids:
        return []
    found = list(session.scalars(select(model).where(model.id.in_(ids))))
    if len(found) != len(ids):
        missing = ids - {row.id for row in found}
        raise LookupError(f"{model.__name__} rows not found: {sorted(missing)}")
    return found


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def time_grid_to_domain(row: m.TimeGrid) -> TimeGrid:
    return TimeGrid(
        id=TimeGridId(row.id),
        institution_id=InstitutionId(row.institution_id),
        name=row.name,
        days=row.days,
        slots_per_day=row.slots_per_day,
        slot_minutes=row.slot_minutes,
        day_start_minute=row.day_start_minute,
        break_slots=frozenset(b.slot_of_day for b in row.breaks),
    )


def institution_to_domain(row: m.Institution) -> d.Institution:
    return d.Institution(id=InstitutionId(row.id), name=row.name)


def department_to_domain(row: m.Department) -> d.Department:
    return d.Department(
        id=DepartmentId(row.id),
        institution_id=InstitutionId(row.institution_id),
        name=row.name,
        code=row.code,
    )


def building_to_domain(row: m.Building) -> d.Building:
    return d.Building(
        id=BuildingId(row.id), institution_id=InstitutionId(row.institution_id), name=row.name
    )


def feature_to_domain(row: m.Feature) -> d.Feature:
    return d.Feature(
        id=FeatureId(row.id), institution_id=InstitutionId(row.institution_id), name=row.name
    )


def room_to_domain(row: m.Room) -> d.Room:
    return d.Room(
        id=RoomId(row.id),
        building_id=BuildingId(row.building_id) if row.building_id is not None else None,
        name=row.name,
        capacity=row.capacity,
        features=frozenset(FeatureId(f.id) for f in row.features),
    )


def instructor_to_domain(row: m.Instructor) -> d.Instructor:
    return d.Instructor(
        id=InstructorId(row.id),
        department_id=DepartmentId(row.department_id) if row.department_id is not None else None,
        name=row.name,
        email=row.email,
        max_slots_per_day=row.max_slots_per_day,
        max_slots_per_week=row.max_slots_per_week,
        max_consecutive_slots=row.max_consecutive_slots,
    )


def group_to_domain(row: m.StudentGroup) -> dg.StudentGroup:
    return dg.StudentGroup(
        id=StudentGroupId(row.id),
        program_id=ProgramId(row.program_id) if row.program_id is not None else None,
        name=row.name,
        kind=dg.GroupKind(row.kind),
        size=row.size,
        parent_id=StudentGroupId(row.parent_id) if row.parent_id is not None else None,
        member_ids=frozenset(StudentGroupId(g.id) for g in row.members),
    )


def session_to_domain(row: m.Session) -> d.Session:
    return d.Session(
        id=SessionId(row.id),
        offering_id=OfferingId(row.offering_id),
        template_id=SessionTemplateId(row.template_id) if row.template_id is not None else None,
        kind=d.SessionKind(row.kind),
        duration_slots=row.duration_slots,
        occurrence=row.occurrence,
        attendee_ids=frozenset(StudentGroupId(g.id) for g in row.attendees),
        instructor_ids=frozenset(InstructorId(i.id) for i in row.instructors),
        required_features=frozenset(FeatureId(f.id) for f in row.required_features),
    )


def template_to_domain(row: m.SessionTemplate) -> d.SessionTemplate:
    return d.SessionTemplate(
        id=SessionTemplateId(row.id),
        offering_id=OfferingId(row.offering_id),
        kind=d.SessionKind(row.kind),
        duration_slots=row.duration_slots,
        per_week=row.per_week,
        split_per_attendee=row.split_per_attendee,
        attendee_ids=frozenset(StudentGroupId(g.id) for g in row.attendees),
        instructor_ids=frozenset(InstructorId(i.id) for i in row.instructors),
        required_features=frozenset(FeatureId(f.id) for f in row.required_features),
    )


def constraint_to_domain(row: m.Constraint) -> Constraint:
    return Constraint(
        id=ConstraintId(row.id),
        term_id=TermId(row.term_id),
        kind=ConstraintKind(row.kind),
        is_hard=row.is_hard,
        weight=row.weight,
        target_ids=frozenset(SessionId(s.id) for s in row.targets),
        params=dict(row.params or {}),
        enabled=row.enabled,
    )


def timetable_to_domain(row: m.Timetable) -> dt.Timetable:
    return dt.Timetable(
        id=TimetableId(row.id),
        term_id=TermId(row.term_id),
        name=row.name,
        status=dt.TimetableStatus(row.status),
        parent_id=TimetableId(row.parent_id) if row.parent_id is not None else None,
        penalty=row.penalty,
        penalty_breakdown=dict(row.penalty_breakdown or {}),
        created_at=row.created_at,
        published_at=row.published_at,
    )


def assignment_to_domain(row: m.Assignment) -> dt.Assignment:
    return dt.Assignment(
        id=AssignmentId(row.id),
        timetable_id=TimetableId(row.timetable_id),
        session_id=SessionId(row.session_id),
        start_slot=row.start_slot,
        room_id=RoomId(row.room_id),
        is_pinned=row.is_pinned,
    )


def unavailability_to_domain(row: m.Unavailability) -> d.Unavailability:
    return d.Unavailability(
        term_id=TermId(row.term_id),
        instructor_id=InstructorId(row.instructor_id) if row.instructor_id is not None else None,
        room_id=RoomId(row.room_id) if row.room_id is not None else None,
        slot=row.slot,
        reason=row.reason,
    )


def unavailability_to_orm(item: d.Unavailability) -> m.Unavailability:
    return m.Unavailability(
        term_id=item.term_id,
        instructor_id=item.instructor_id,
        room_id=item.room_id,
        slot=item.slot,
        reason=item.reason,
    )


def command_to_domain(row: m.Command) -> dt.Command:
    return dt.Command(
        id=CommandId(row.id),
        timetable_id=TimetableId(row.timetable_id),
        sequence=row.sequence,
        kind=dt.CommandKind(row.kind),
        summary=row.summary,
        before=dict(row.before or {}),
        after=dict(row.after or {}),
        created_at=row.created_at,
        undone_at=row.undone_at,
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def time_grid_to_orm(grid: TimeGrid, institution_id: int) -> m.TimeGrid:
    row = m.TimeGrid(
        institution_id=institution_id,
        name=grid.name,
        days=grid.days,
        slots_per_day=grid.slots_per_day,
        slot_minutes=grid.slot_minutes,
        day_start_minute=grid.day_start_minute,
    )
    row.breaks = [m.TimeGridBreak(slot_of_day=s) for s in sorted(grid.break_slots)]
    return row


def room_to_orm(session: DbSession, room: d.Room) -> m.Room:
    row = m.Room(building_id=room.building_id, name=room.name, capacity=room.capacity)
    row.features = _resolve(session, m.Feature, frozenset(room.features))
    return row


def group_to_orm(session: DbSession, group: dg.StudentGroup) -> m.StudentGroup:
    row = m.StudentGroup(
        program_id=group.program_id,
        name=group.name,
        kind=group.kind.value,
        size=group.size,
        parent_id=group.parent_id,
    )
    row.members = _resolve(session, m.StudentGroup, frozenset(group.member_ids))
    return row


def session_to_orm(session: DbSession, item: d.Session, term_id: int) -> m.Session:
    """``term_id`` is passed rather than derived.

    It is denormalised storage detail that the domain has no reason to carry, and the
    caller always knows it — it comes from the offering being expanded.
    """
    row = m.Session(
        offering_id=item.offering_id,
        term_id=term_id,
        template_id=item.template_id,
        kind=item.kind.value,
        duration_slots=item.duration_slots,
        occurrence=item.occurrence,
    )
    row.attendees = _resolve(session, m.StudentGroup, frozenset(item.attendee_ids))
    row.instructors = _resolve(session, m.Instructor, frozenset(item.instructor_ids))
    row.required_features = _resolve(session, m.Feature, frozenset(item.required_features))
    return row


def template_to_orm(session: DbSession, item: d.SessionTemplate) -> m.SessionTemplate:
    row = m.SessionTemplate(
        offering_id=item.offering_id,
        kind=item.kind.value,
        duration_slots=item.duration_slots,
        per_week=item.per_week,
        split_per_attendee=item.split_per_attendee,
    )
    row.attendees = _resolve(session, m.StudentGroup, frozenset(item.attendee_ids))
    row.instructors = _resolve(session, m.Instructor, frozenset(item.instructor_ids))
    row.required_features = _resolve(session, m.Feature, frozenset(item.required_features))
    return row


def constraint_to_orm(session: DbSession, item: Constraint) -> m.Constraint:
    row = m.Constraint(
        term_id=item.term_id,
        kind=item.kind.value,
        is_hard=item.is_hard,
        weight=item.weight,
        params=dict(item.params),
        enabled=item.enabled,
    )
    row.targets = _resolve(session, m.Session, frozenset(item.target_ids))
    return row


def assignment_to_orm(item: dt.Assignment, term_id: int) -> m.Assignment:
    """``term_id`` is what lets the composite keys refuse a cross-term placement."""
    return m.Assignment(
        timetable_id=item.timetable_id,
        term_id=term_id,
        session_id=item.session_id,
        start_slot=item.start_slot,
        room_id=item.room_id,
        is_pinned=item.is_pinned,
    )
