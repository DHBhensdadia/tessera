"""The calendar: teaching weeks, the terms that use them, and the courses offered in each.

Three entities that look like ordinary CRUD and are not, because between them they carry
the meaning of every stored slot index in the project.

A slot is an integer (Decision #6). Slot 40 means "Tuesday 14:00" only by reference to a
grid's ``days``, ``slots_per_day``, ``slot_minutes`` and ``day_start_minute``. Change any
of those and every ``assignment.slot``, every blocked slot, every pinned placement in
every term using that grid silently means something else — no error, no warning, just a
timetable that is now wrong. **That is why a grid cannot be edited** (Decision #51), why
deleting one is refused while a term uses it, and why ``time_grid_id`` is ``RESTRICT``
rather than ``CASCADE`` in the schema.

The grid's own rules — breaks inside the day, a week that has some teaching in it,
what ``slot_count`` means — are not here. They live in `tessera.domain.time_grid`, and
this module reaches them by constructing a `TimeGrid` and letting it object, exactly as
`repository.groups` does with `GroupSet`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain.time_grid import TimeGrid
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import ConflictError
from tessera.repository.structure import _get_or_404, _reject_duplicate

# --------------------------------------------------------------------------------
# time grids
# --------------------------------------------------------------------------------


def _validated(**fields: Any) -> TimeGrid:
    """Hand the prospective grid to the domain and let it object.

    Breaks outside the day, or a day made entirely of breaks, are rejected there. Both
    are coherent requests producing an incoherent *state*, which is what a 409 is for.
    """
    try:
        return TimeGrid(**fields)
    except ValueError as error:
        raise ConflictError(str(error)) from error


def list_time_grids(session: DbSession, *, institution_id: int | None = None) -> list[TimeGrid]:
    query = select(m.TimeGrid).order_by(m.TimeGrid.name)
    if institution_id is not None:
        query = query.where(m.TimeGrid.institution_id == institution_id)
    return [mappers.time_grid_to_domain(row) for row in session.scalars(query)]


def get_time_grid(session: DbSession, grid_id: int) -> TimeGrid:
    return mappers.time_grid_to_domain(_get_or_404(session, m.TimeGrid, grid_id))


def create_time_grid(
    session: DbSession,
    *,
    institution_id: int,
    name: str = "Default",
    days: int,
    slots_per_day: int,
    slot_minutes: int,
    day_start_minute: int,
    break_slots: Sequence[int] = (),
) -> TimeGrid:
    """Create a grid, validated by the domain before anything is written.

    There is deliberately no ``update_time_grid`` to pair with this. See the module
    docstring: editing a grid reinterprets stored slot indices rather than moving them.
    To change the shape of the week, create a second grid and point a term at it — the
    old grid stays, so timetables built against it keep their meaning.
    """
    _get_or_404(session, m.Institution, institution_id)
    _reject_duplicate(
        session,
        m.TimeGrid,
        name,
        scope_column=m.TimeGrid.institution_id,
        scope_value=institution_id,
    )
    _validated(
        institution_id=institution_id,
        name=name,
        days=days,
        slots_per_day=slots_per_day,
        slot_minutes=slot_minutes,
        day_start_minute=day_start_minute,
        break_slots=frozenset(break_slots),
    )

    row = m.TimeGrid(
        institution_id=institution_id,
        name=name,
        days=days,
        slots_per_day=slots_per_day,
        slot_minutes=slot_minutes,
        day_start_minute=day_start_minute,
    )
    row.breaks = [m.TimeGridBreak(slot_of_day=slot) for slot in sorted(set(break_slots))]
    session.add(row)
    session.flush()
    return mappers.time_grid_to_domain(row)


def delete_time_grid(session: DbSession, grid_id: int) -> None:
    """Refuse while any term uses it.

    ``time_grid_id`` is ``ON DELETE RESTRICT``, so the database refuses too — but with a
    message naming a constraint. This one names the terms, which is what the person
    clicking delete needs to know.
    """
    row = _get_or_404(session, m.TimeGrid, grid_id)
    terms = session.scalar(
        select(func.count()).select_from(m.Term).where(m.Term.time_grid_id == grid_id)
    )
    if terms:
        raise ConflictError(
            f"{row.name} is used by {terms} term(s) and cannot be deleted",
            blockers={"terms": int(terms)},
        )
    session.delete(row)
    session.flush()


# --------------------------------------------------------------------------------
# terms
# --------------------------------------------------------------------------------


def _validated_term(**fields: Any) -> d.Term:
    try:
        return d.Term(**fields)
    except ValueError as error:
        raise ConflictError(str(error)) from error


def list_terms(session: DbSession, *, institution_id: int | None = None) -> list[d.Term]:
    """Newest academic year first — a term list is read to find the current one."""
    query = select(m.Term).order_by(m.Term.academic_year.desc(), m.Term.name)
    if institution_id is not None:
        query = query.where(m.Term.institution_id == institution_id)
    return [mappers.term_to_domain(row) for row in session.scalars(query)]


def get_term(session: DbSession, term_id: int) -> d.Term:
    return mappers.term_to_domain(_get_or_404(session, m.Term, term_id))


def create_term(
    session: DbSession,
    *,
    institution_id: int,
    time_grid_id: int,
    academic_year: str,
    name: str,
    starts_on: date | None = None,
    ends_on: date | None = None,
) -> d.Term:
    """Create a term against an existing grid.

    The grid must belong to the same institution. Nothing in the schema prevents
    otherwise — ``institution_id`` and ``time_grid_id`` are independent foreign keys — so
    without this a term could be built on another university's teaching week, and the
    error would surface much later as rooms and staff that do not exist.
    """
    _get_or_404(session, m.Institution, institution_id)
    grid = _get_or_404(session, m.TimeGrid, time_grid_id)
    if grid.institution_id != institution_id:
        raise ConflictError(
            f"time grid {grid.name!r} belongs to another institution",
            blockers={"time_grid_institution_id": int(grid.institution_id)},
        )

    _reject_duplicate_term(session, institution_id, academic_year, name)
    _validated_term(
        institution_id=institution_id,
        time_grid_id=time_grid_id,
        academic_year=academic_year,
        name=name,
        starts_on=starts_on,
        ends_on=ends_on,
    )

    row = m.Term(
        institution_id=institution_id,
        time_grid_id=time_grid_id,
        academic_year=academic_year,
        name=name,
        starts_on=starts_on,
        ends_on=ends_on,
    )
    session.add(row)
    session.flush()
    return mappers.term_to_domain(row)


def _reject_duplicate_term(
    session: DbSession,
    institution_id: int,
    academic_year: str,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    """ "Autumn" twice in one academic year is a mistake, not two terms.

    Scoped rather than global: "Autumn" recurs every year, and every institution has one.
    Not expressible through `_reject_duplicate`, which scopes by a single column.
    """
    query = select(m.Term.id).where(
        m.Term.institution_id == institution_id,
        m.Term.academic_year == academic_year,
        m.Term.name == name,
    )
    if exclude_id is not None:
        query = query.where(m.Term.id != exclude_id)
    if session.scalars(query).first() is not None:
        raise ConflictError(f"{name!r} already exists in {academic_year}")


def update_term(session: DbSession, term_id: int, *, changes: Mapping[str, Any]) -> d.Term:
    """Rename a term or set its dates.

    ``time_grid_id`` is deliberately absent from what can be changed, and is not in the
    wire model either. Repointing a term at a differently-shaped grid has exactly the
    effect that editing a grid would — every slot index already stored against the term
    would silently mean something else.
    """
    row = _get_or_404(session, m.Term, term_id)

    name = str(changes.get("name", row.name))
    if "name" in changes:
        _reject_duplicate_term(
            session, row.institution_id, row.academic_year, name, exclude_id=term_id
        )

    _validated_term(
        institution_id=row.institution_id,
        time_grid_id=row.time_grid_id,
        academic_year=row.academic_year,
        name=name,
        starts_on=changes.get("starts_on", row.starts_on),
        ends_on=changes.get("ends_on", row.ends_on),
    )

    for field in ("name", "starts_on", "ends_on"):
        if field in changes:
            setattr(row, field, changes[field])

    session.flush()
    return mappers.term_to_domain(row)


def delete_term(session: DbSession, term_id: int) -> None:
    """Refuse while the term has offerings.

    ``offering.term_id`` cascades, ``session`` cascades from ``offering``, and
    ``assignment`` from ``session``. Deleting a term is therefore "delete this semester
    and everything ever scheduled in it" — not something a confirmation dialog should be
    able to do by accident.
    """
    row = _get_or_404(session, m.Term, term_id)
    offerings = session.scalar(
        select(func.count()).select_from(m.Offering).where(m.Offering.term_id == term_id)
    )
    if offerings:
        raise ConflictError(
            f"{row.name} has {offerings} offering(s) and cannot be deleted",
            blockers={"offerings": int(offerings)},
        )
    session.delete(row)
    session.flush()


# --------------------------------------------------------------------------------
# offerings
# --------------------------------------------------------------------------------


def list_offerings(session: DbSession, *, term_id: int) -> list[d.Offering]:
    _get_or_404(session, m.Term, term_id)
    rows = session.scalars(
        select(m.Offering)
        .join(m.Course, m.Course.id == m.Offering.course_id)
        .where(m.Offering.term_id == term_id)
        .order_by(m.Course.code)
    )
    return [mappers.offering_to_domain(row) for row in rows]


def get_offering(session: DbSession, offering_id: int) -> d.Offering:
    return mappers.offering_to_domain(_get_or_404(session, m.Offering, offering_id))


def create_offering(session: DbSession, *, term_id: int, course_id: int) -> d.Offering:
    """Offer a course in a term.

    A course is deliberately institution-agnostic — it has no institution above it, only
    an optional department — so there is no cross-institution check to make here, unlike
    `create_term`. The only rule is that a course cannot be offered twice in one term.
    """
    _get_or_404(session, m.Term, term_id)
    course = _get_or_404(session, m.Course, course_id)

    existing = session.scalars(
        select(m.Offering.id).where(
            m.Offering.term_id == term_id, m.Offering.course_id == course_id
        )
    ).first()
    if existing is not None:
        raise ConflictError(f"{course.code} is already offered in this term")

    row = m.Offering(term_id=term_id, course_id=course_id)
    session.add(row)
    session.flush()
    return mappers.offering_to_domain(row)


def delete_offering(session: DbSession, offering_id: int) -> None:
    """Refuse while sessions exist.

    ``session`` has a composite cascade to ``(offering.id, offering.term_id)`` and
    ``assignment`` cascades from ``session``, so this delete would otherwise take the
    offering's whole expanded session set and any placements built on it.

    Sessions arrive in part 3; the guard is written and tested now rather than later,
    because a guard nobody has seen fire is not known to work.
    """
    row = _get_or_404(session, m.Offering, offering_id)
    sessions = session.scalar(
        select(func.count()).select_from(m.Session).where(m.Session.offering_id == offering_id)
    )
    if sessions:
        raise ConflictError(
            f"this offering has {sessions} session(s) and cannot be deleted",
            blockers={"sessions": int(sessions)},
        )
    session.delete(row)
    session.flush()


def session_count(session: DbSession, offering_id: int) -> int:
    """How many sessions an offering has expanded to, for the offering list."""
    return int(
        session.scalar(
            select(func.count()).select_from(m.Session).where(m.Session.offering_id == offering_id)
        )
        or 0
    )
