"""Timetables and the placements in them: the first thing in this project that a solve produces.

The tables have existed since the first migration and nothing has ever written to them.
Decision #94 says why the routes point here — 4.7 is *"the first phase in which a timetable can
exist at all"* — and #11 says why `status` and `parent_id` were in that migration rather than a
later one: a term holds several candidates, and retrofitting that is a painful change to
everything built on top.

**A solve never overwrites a timetable.** `record` always writes a new one, with `parent_id`
pointing at whatever it was seeded from, so re-optimising around a person's pins is
non-destructive and the thing they had is still there to compare against. That is what
`parent_id` was put in the schema for, and it is what makes P7's *"Keep Result"* a choice
rather than a race.

**This module takes domain objects, never a `Solution`.** `tessera.solver` may not be imported
from here — `pyproject.toml` forbids the repository OR-Tools, and `Solution` reaches it through
`Shortfall` — so the caller converts. That is the layering working rather than an inconvenience:
storage should not know that a timetable came from a search rather than from a person.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain.ids import TermId, TimetableId
from tessera.domain.timetable import Assignment, Timetable, TimetableStatus
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import (
    ConflictError,
    InvalidReferenceError,
    RuleViolationError,
    first_message,
)
from tessera.repository.structure import _get_or_404

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "assignment_count",
    "assignments_of",
    "create_timetable",
    "delete_timetable",
    "get_timetable",
    "list_timetables",
    "record",
    "update_timetable",
]


def list_timetables(
    session: DbSession, *, term_id: int, status: TimetableStatus | None = None
) -> list[Timetable]:
    """A term's candidates, newest first.

    Newest first because the interesting one is almost always the one just generated, and a
    term accumulates drafts: P7 Act 9 compares them rather than replacing them.
    """
    _get_or_404(session, m.Term, term_id)
    query = (
        select(m.Timetable).where(m.Timetable.term_id == term_id).order_by(m.Timetable.id.desc())
    )
    if status is not None:
        query = query.where(m.Timetable.status == status.value)
    return [mappers.timetable_to_domain(row) for row in session.scalars(query)]


def get_timetable(session: DbSession, timetable_id: int) -> Timetable:
    return mappers.timetable_to_domain(_get_or_404(session, m.Timetable, timetable_id))


def assignment_count(session: DbSession, timetable_id: int) -> int:
    """How many sessions are placed. Counted rather than loaded — a grid is 500 rows."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(m.Assignment)
            .where(m.Assignment.timetable_id == timetable_id)
        )
        or 0
    )


def assignments_of(session: DbSession, timetable_id: int) -> list[Assignment]:
    """One timetable's placements, in session order.

    Here rather than beside the loader that reads them, because they are a property of the
    timetable: 5.1 draws them, 5.4 moves them, and re-optimising is only one of the things that
    wants them back.
    """
    return [
        mappers.assignment_to_domain(row)
        for row in session.scalars(
            select(m.Assignment)
            .where(m.Assignment.timetable_id == timetable_id)
            .order_by(m.Assignment.session_id)
        )
    ]


def create_timetable(
    session: DbSession, *, term_id: int, name: str = "Draft", parent_id: int | None = None
) -> Timetable:
    """An empty candidate. What a solve fills in, and what a person can start by hand."""
    _get_or_404(session, m.Term, term_id)
    parent = _parent_in_term(session, term_id, parent_id)
    row = m.Timetable(
        term_id=term_id,
        name=_validated(name=name, term_id=term_id, parent_id=parent).name,
        status=TimetableStatus.DRAFT.value,
        parent_id=parent,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(row)
    session.flush()
    return mappers.timetable_to_domain(row)


def update_timetable(
    session: DbSession, timetable_id: int, *, changes: Mapping[str, Any]
) -> Timetable:
    """Rename it, or move it between draft, published and archived.

    The domain owns what a name may be, so an empty one is refused in the one place that rule
    lives rather than by a column width.
    """
    row = _get_or_404(session, m.Timetable, timetable_id)
    current = mappers.timetable_to_domain(row)
    wanted = _validated(
        name=str(changes.get("name", current.name)),
        term_id=row.term_id,
        parent_id=row.parent_id,
        status=changes.get("status", current.status),
    )
    row.name = wanted.name
    if wanted.status is not current.status:
        row.status = wanted.status.value
        row.published_at = (
            datetime.now(UTC).replace(tzinfo=None)
            if wanted.status is TimetableStatus.PUBLISHED
            else None
        )
    session.flush()
    return mappers.timetable_to_domain(row)


def delete_timetable(session: DbSession, timetable_id: int) -> None:
    """Throw a candidate away. Its assignments and its history go with it.

    **Refused while it is published.** A published timetable is what an institution is
    actually running, and a delete that quietly took it out is not something to discover
    afterwards; 6.5 owns the transition back to draft. Drafts and archives go without
    ceremony, which is what makes discarding a cancelled solve's result a one-liner.
    """
    row = _get_or_404(session, m.Timetable, timetable_id)
    if row.status == TimetableStatus.PUBLISHED.value:
        raise ConflictError(
            f"timetable {timetable_id} is published; archive it before deleting",
            blockers={"published": 1},
        )
    session.delete(row)
    session.flush()


def record(
    session: DbSession,
    *,
    term_id: int,
    placements: Sequence[Assignment],
    name: str = "Draft",
    parent_id: int | None = None,
    penalty: int | None = None,
    penalty_breakdown: Mapping[str, int] | None = None,
) -> Timetable:
    """Store a timetable somebody or something produced, as one transaction.

    The whole result or none of it. A half-written timetable is a term with some sessions
    placed and some not, which the validator calls *incomplete* and a person calls a bug —
    and 4.1's D6 made completeness a separate question precisely so that state could not be
    passed off as feasible.

    Measured: 5.3 ms for 150 placements, 15.3 ms for 500, 248 ms for NFR-9's ceiling of 5,000.
    """
    timetable = create_timetable(session, term_id=term_id, name=name, parent_id=parent_id)
    assert timetable.id is not None

    _sessions_belong_to(session, term_id, [p.session_id for p in placements])
    session.add_all(
        [
            m.Assignment(
                timetable_id=timetable.id,
                term_id=term_id,
                session_id=placement.session_id,
                start_slot=placement.start_slot,
                room_id=placement.room_id,
                is_pinned=placement.is_pinned,
            )
            for placement in placements
        ]
    )

    row = _get_or_404(session, m.Timetable, timetable.id)
    row.penalty = penalty
    row.penalty_breakdown = dict(penalty_breakdown or {})
    session.flush()
    return mappers.timetable_to_domain(row)


def _validated(
    *,
    name: str,
    term_id: int,
    parent_id: int | None,
    status: TimetableStatus = TimetableStatus.DRAFT,
) -> Timetable:
    """Hand the prospective row to the domain and let it object."""
    try:
        return Timetable(
            term_id=TermId(term_id),
            name=name,
            parent_id=TimetableId(parent_id) if parent_id is not None else None,
            status=status,
        )
    except ValueError as error:
        raise RuleViolationError(first_message(error), field="name") from error


def _parent_in_term(session: DbSession, term_id: int, parent_id: int | None) -> int | None:
    """A lineage may not cross terms.

    `parent_id` is a plain foreign key with nothing to stop it pointing at last semester, and
    a comparison view drawing two timetables of different terms side by side would be
    comparing nothing.
    """
    if parent_id is None:
        return None
    parent = _get_or_404(session, m.Timetable, parent_id)
    if parent.term_id != term_id:
        raise ConflictError(
            f"timetable {parent_id} belongs to term {parent.term_id}, not {term_id}"
        )
    return parent_id


def _sessions_belong_to(session: DbSession, term_id: int, session_ids: Sequence[int]) -> None:
    """Every placement names a session of this term.

    The composite foreign key refuses the mismatch anyway, and reports it as a constraint
    name at commit — long after the call that caused it. Checking here names the field and
    the ids, which is what an importer or a client can act on.
    """
    wanted = {int(s) for s in session_ids}
    found = set(
        session.scalars(
            select(m.Session.id).where(m.Session.term_id == term_id, m.Session.id.in_(wanted))
        )
    )
    if missing := wanted - found:
        raise InvalidReferenceError("session_id", list(missing))
