"""What is taught: the course catalogue, and later the offerings and sessions built on it.

Courses sit apart from everything else in Stage 2 in one respect — they are the only
structural entity with **no institution above them**. A course belongs to a department or
to nothing at all, which is not an oversight: a syllabus committee creates courses long
before anyone decides which department will own them, and refusing to store one until
that is settled would push the work back into a spreadsheet.

That nullable parent has a cost, paid in `_reject_duplicate`: SQL treats each null as
distinct, so the unique constraint on ``(department_id, code)`` does not fire for two
unassigned courses sharing a code. The repository check does, because SQLAlchemy renders
``== None`` as ``IS NULL``. Both are kept — the constraint is the guarantee where it
applies, and the check is the guarantee everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import ConflictError
from tessera.repository.structure import _get_or_404, _reject_duplicate

# --------------------------------------------------------------------------------
# courses
# --------------------------------------------------------------------------------


def list_courses(session: DbSession, *, department_id: int | None = None) -> list[d.Course]:
    """Ordered by code rather than name, because a catalogue is read by code."""
    query = select(m.Course).order_by(m.Course.code)
    if department_id is not None:
        query = query.where(m.Course.department_id == department_id)
    return [mappers.course_to_domain(row) for row in session.scalars(query)]


def get_course(session: DbSession, course_id: int) -> d.Course:
    return mappers.course_to_domain(_get_or_404(session, m.Course, course_id))


def create_course(
    session: DbSession,
    *,
    code: str,
    name: str,
    credits: int = 0,
    department_id: int | None = None,
) -> d.Course:
    if department_id is not None:
        _get_or_404(session, m.Department, department_id)
    _reject_duplicate(
        session,
        m.Course,
        code,
        column=m.Course.code,
        scope_column=m.Course.department_id,
        scope_value=department_id,
    )
    row = m.Course(department_id=department_id, code=code, name=name, credits=credits)
    session.add(row)
    session.flush()
    return mappers.course_to_domain(row)


def update_course(session: DbSession, course_id: int, *, changes: Mapping[str, Any]) -> d.Course:
    """Apply the fields that were sent.

    Moving a course to another department is a code collision waiting to happen, so the
    duplicate check runs against the *destination* department rather than the current
    one — otherwise CS101 could be moved into a department that already has a CS101.
    """
    row = _get_or_404(session, m.Course, course_id)

    destination = changes.get("department_id", row.department_id)
    if "department_id" in changes and changes["department_id"] is not None:
        _get_or_404(session, m.Department, int(changes["department_id"]))
    if "code" in changes or "department_id" in changes:
        _reject_duplicate(
            session,
            m.Course,
            str(changes.get("code", row.code)),
            column=m.Course.code,
            scope_column=m.Course.department_id,
            scope_value=destination,
            exclude_id=course_id,
        )

    for field in ("code", "name", "credits", "department_id"):
        if field in changes:
            setattr(row, field, changes[field])

    session.flush()
    return mappers.course_to_domain(row)


def delete_course(session: DbSession, course_id: int) -> None:
    """Refuse while the course is offered in any term.

    ``offering.course_id`` is ``ON DELETE CASCADE`` and ``session`` cascades from
    ``offering`` in turn, so without this a mis-click on a course would silently take
    every offering of it, every session those expanded to, and every assignment placing
    them — a whole timetable, from a two-word confirmation dialog.

    The cascade stays as a backstop for paths that bypass this module, where its job is
    preventing dangling rows rather than performing the deletion.
    """
    row = _get_or_404(session, m.Course, course_id)
    offerings = session.scalar(
        select(func.count()).select_from(m.Offering).where(m.Offering.course_id == course_id)
    )
    if offerings:
        raise ConflictError(
            f"{row.code} is offered in {offerings} term(s) and cannot be deleted",
            blockers={"offerings": int(offerings)},
        )
    session.delete(row)
    session.flush()
