"""Instructors, and the slots in which they or a room may not be used.

Instructors follow the pattern set in `structure.py`. Availability does not, because it
is edited by dragging across a grid rather than a row at a time: the operations are
*block a range* and *unblock a range*, and one request per cell would mean dozens per
gesture.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import ConflictError, InvalidReferenceError
from tessera.repository.structure import _get_or_404, _reject_duplicate

# --------------------------------------------------------------------------------
# instructors
# --------------------------------------------------------------------------------


def list_instructors(session: DbSession, *, department_id: int | None = None) -> list[d.Instructor]:
    query = select(m.Instructor).order_by(m.Instructor.name)
    if department_id is not None:
        query = query.where(m.Instructor.department_id == department_id)
    return [mappers.instructor_to_domain(row) for row in session.scalars(query)]


def get_instructor(session: DbSession, instructor_id: int) -> d.Instructor:
    return mappers.instructor_to_domain(_get_or_404(session, m.Instructor, instructor_id))


def create_instructor(
    session: DbSession,
    *,
    name: str,
    email: str = "",
    department_id: int | None = None,
    max_slots_per_day: int | None = None,
    max_slots_per_week: int | None = None,
    max_consecutive_slots: int | None = None,
) -> d.Instructor:
    if department_id is not None:
        _get_or_404(session, m.Department, department_id)
    # Scoped to the department rather than globally: two departments can each employ a
    # different A. Sharma, and refusing the second would be wrong.
    _reject_duplicate(
        session,
        m.Instructor,
        name,
        scope_column=m.Instructor.department_id,
        scope_value=department_id,
    )

    row = m.Instructor(
        department_id=department_id,
        name=name,
        email=email,
        max_slots_per_day=max_slots_per_day,
        max_slots_per_week=max_slots_per_week,
        max_consecutive_slots=max_consecutive_slots,
    )
    session.add(row)
    session.flush()
    return mappers.instructor_to_domain(row)


def update_instructor(
    session: DbSession, instructor_id: int, *, changes: Mapping[str, Any]
) -> d.Instructor:
    """Applies only what the caller sent — see `structure.update_room` for why."""
    row = _get_or_404(session, m.Instructor, instructor_id)

    if "department_id" in changes:
        if changes["department_id"] is not None:
            _get_or_404(session, m.Department, int(changes["department_id"]))
        row.department_id = changes["department_id"]

    if "name" in changes:
        _reject_duplicate(
            session,
            m.Instructor,
            str(changes["name"]),
            scope_column=m.Instructor.department_id,
            scope_value=row.department_id,
            exclude_id=instructor_id,
        )
        row.name = str(changes["name"])

    for field in ("email", "max_slots_per_day", "max_slots_per_week", "max_consecutive_slots"):
        if field in changes:
            setattr(row, field, changes[field])

    session.flush()
    return mappers.instructor_to_domain(row)


def delete_instructor(session: DbSession, instructor_id: int) -> None:
    """Refuse if they are still teaching; their availability goes with them otherwise.

    Availability cascades because those rows describe the instructor and mean nothing
    without them. Teaching assignments do not: an instructor who still has sessions is
    a data-entry mistake to fix, not a deletion to complete quietly.
    """
    row = _get_or_404(session, m.Instructor, instructor_id)

    teaching = session.scalar(
        select(func.count())
        .select_from(m.session_instructor)
        .where(m.session_instructor.c.instructor_id == instructor_id)
    )
    if teaching:
        raise ConflictError(
            f"{row.name} is still assigned to sessions and cannot be deleted",
            blockers={"sessions": int(teaching)},
        )

    session.delete(row)
    session.flush()


# --------------------------------------------------------------------------------
# availability
# --------------------------------------------------------------------------------


def _term_slot_count(session: DbSession, term_id: int) -> int:
    """How many slots the term's grid actually has.

    Blocking slot 9999 in a thirty-slot week would otherwise be stored, ignored by the
    solver and displayed nowhere — a silent no-op with nothing for the user to debug.
    """
    term = _get_or_404(session, m.Term, term_id)
    grid = _get_or_404(session, m.TimeGrid, term.time_grid_id)
    return int(grid.days) * int(grid.slots_per_day)


def _resolve_subject(
    session: DbSession, kind: str, subject_id: int
) -> tuple[int | None, int | None]:
    """Map the wire's (kind, subject_id) onto the two nullable columns underneath.

    The wire format predates the storage change made during the 1.3 corrective pass, and
    keeping it means a storage decision did not become a breaking API change — which is
    the entire reason wire models are separate from domain models.
    """
    if kind == "instructor":
        _get_or_404(session, m.Instructor, subject_id)
        return subject_id, None
    if kind == "room":
        _get_or_404(session, m.Room, subject_id)
        return None, subject_id
    raise InvalidReferenceError("kind", [])


def list_unavailability(
    session: DbSession,
    term_id: int,
    *,
    kind: str | None = None,
    subject_id: int | None = None,
) -> list[d.Unavailability]:
    query = select(m.Unavailability).where(m.Unavailability.term_id == term_id)
    if kind == "instructor":
        query = query.where(m.Unavailability.instructor_id.is_not(None))
    elif kind == "room":
        query = query.where(m.Unavailability.room_id.is_not(None))
    if subject_id is not None:
        query = query.where(
            (m.Unavailability.instructor_id == subject_id)
            | (m.Unavailability.room_id == subject_id)
        )
    query = query.order_by(m.Unavailability.slot)
    return [mappers.unavailability_to_domain(row) for row in session.scalars(query)]


def block_slots(
    session: DbSession,
    term_id: int,
    *,
    kind: str,
    subject_id: int,
    slots: Iterable[int],
    reason: str = "",
) -> list[d.Unavailability]:
    """Mark slots unavailable. Blocking an already-blocked slot is a no-op.

    Idempotent on purpose: dragging across a partly-blocked range is ordinary use, and
    failing halfway through a gesture would be worse than useless. The unique constraint
    remains the backstop.
    """
    instructor_id, room_id = _resolve_subject(session, kind, subject_id)
    limit = _term_slot_count(session, term_id)

    wanted = sorted(set(slots))
    if out_of_range := [s for s in wanted if not 0 <= s < limit]:
        raise ConflictError(
            f"slots must be between 0 and {limit - 1} for this term; got {out_of_range}"
        )

    already = {
        row.slot
        for row in session.scalars(
            select(m.Unavailability).where(
                m.Unavailability.term_id == term_id,
                m.Unavailability.instructor_id == instructor_id,
                m.Unavailability.room_id == room_id,
                m.Unavailability.slot.in_(wanted),
            )
        )
    }

    session.add_all(
        m.Unavailability(
            term_id=term_id,
            instructor_id=instructor_id,
            room_id=room_id,
            slot=slot,
            reason=reason,
        )
        for slot in wanted
        if slot not in already
    )
    session.flush()
    return list_unavailability(session, term_id, kind=kind, subject_id=subject_id)


def unblock_slots(
    session: DbSession,
    term_id: int,
    *,
    kind: str,
    subject_id: int,
    slots: Sequence[int] | None = None,
) -> int:
    """Free slots again. With no slots named, clears everything for that subject.

    The selective form is what makes the availability grid usable: dragging over blocked
    cells to release them removes a range, not the lot. Clearing everything remains the
    default so the original meaning of this endpoint is unchanged.
    """
    instructor_id, room_id = _resolve_subject(session, kind, subject_id)

    statement = delete(m.Unavailability).where(
        m.Unavailability.term_id == term_id,
        m.Unavailability.instructor_id == instructor_id,
        m.Unavailability.room_id == room_id,
    )
    if slots is not None:
        statement = statement.where(m.Unavailability.slot.in_(sorted(set(slots))))

    result = session.execute(statement)
    session.flush()
    return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult, not Result


def blocked_slots(session: DbSession, term_id: int, *, instructor_id: int) -> frozenset[int]:
    """The set the solver asks for, as a set rather than rows.

    Kept beside the row-level functions so the solver and the interface read the same
    data through the same module rather than each assembling it from the table.
    """
    rows = session.scalars(
        select(m.Unavailability.slot).where(
            m.Unavailability.term_id == term_id,
            m.Unavailability.instructor_id == instructor_id,
        )
    )
    return frozenset(rows)
