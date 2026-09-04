"""A stored term, as the validator and the solver read one.

**Nothing in this package built a `Snapshot` until 4.7.** The validator has taken one since
4.1, the model since 4.2, the pre-flight since 4.6 — and the only things that ever constructed
one were the tests and the benchmark, which reads a competition file. So the engine had a
solver, a scorer and an explainer, and no way at all to point them at the project a person had
open. This is that missing half-inch of pipe.

**Everything expensive happens in `Snapshot.of`**, which indexes the term; this module's job is
to ask the database for the right rows once each rather than once per session. Measured on a
project file: 27.6 to 36.9 ms at department scale (500 sessions, 40 rooms) and 278 to 304 ms at
NFR-9's ceiling. That is cheap enough to run on the request thread, which is what lets
`POST /solve` refuse a term that cannot be loaded with a 404 instead of accepting a job that
immediately fails.

**Which rooms belong to a term is decided the way 2.6 decided it** (`imports.catalogue_for`):
a project file can hold more than one institution, so a room reached through a building at a
*different* one is not this term's room. Where the chain is broken — a room with no building —
the question cannot be answered and the room is kept rather than dropped, which is the same
partial-guard honesty `_reject_foreign_groups` is written with. Groups are project-wide for
the same reason they are there: a group reaches an institution only through a programme and a
department, both optional links, and a `GroupSet` has to be whole or its tree does not resolve.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from tessera.domain.entities import Room
from tessera.domain.ids import CourseId, SessionId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot
from tessera.repository import groups as groups_repo
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository import timetables as timetables_repo
from tessera.repository.errors import ConflictError
from tessera.repository.structure import _get_or_404

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["load"]


def load(
    session: DbSession,
    term_id: int,
    *,
    seed_timetable_id: int | None = None,
    respect_pins: bool = True,
) -> Snapshot:
    """Everything a solve of this term needs, indexed.

    `seed_timetable_id` names a timetable to start from. Its placements arrive as the term's
    own, which is what makes re-optimising *re*-optimising: `Formulation.hint` hands them to
    CP-SAT as a starting point and `model._pins` fixes the pinned ones outright. Without a
    seed the term is solved from nothing, which is what a first generate does.

    `respect_pins=False` keeps the warm start and drops the pins — *"use this as a starting
    point, but you may move anything"*. The two are separate on the wire (`SolveRequest`) and
    have to be separate here, or the only way to unpin for one solve would be to unpin in the
    data.

    Raises `NotFoundError` for a term or timetable that does not exist, and `ConflictError`
    for a seed timetable belonging to a different term — which would otherwise silently
    contribute no placements at all, because `Snapshot.of` drops assignments whose session is
    not in the term.
    """
    term = _get_or_404(session, m.Term, term_id)
    grid = mappers.time_grid_to_domain(_get_or_404(session, m.TimeGrid, term.time_grid_id))

    session_rows = list(
        session.scalars(
            select(m.Session).where(m.Session.term_id == term_id).order_by(m.Session.id)
        )
    )

    return Snapshot.of(
        grid=grid,
        sessions=[mappers.session_to_domain(row) for row in session_rows],
        rooms=_rooms(session, term.institution_id),
        groups=groups_repo.group_set(session),
        assignments=_seed(session, term_id, seed_timetable_id, respect_pins=respect_pins),
        unavailability=[
            mappers.unavailability_to_domain(row)
            for row in session.scalars(
                select(m.Unavailability).where(m.Unavailability.term_id == term_id)
            )
        ],
        constraints=[
            mappers.constraint_to_domain(row)
            for row in session.scalars(select(m.Constraint).where(m.Constraint.term_id == term_id))
        ],
        course_of=_course_of(session, term_id, session_rows),
    )


def _rooms(session: DbSession, institution_id: int) -> list[Room]:
    query = (
        select(m.Room)
        .outerjoin(m.Building, m.Building.id == m.Room.building_id)
        .where(
            (m.Room.building_id.is_(None)) | (m.Building.institution_id == institution_id),
        )
        .order_by(m.Room.id)
    )
    return [mappers.room_to_domain(row) for row in session.scalars(query).unique()]


def _seed(
    session: DbSession,
    term_id: int,
    timetable_id: int | None,
    *,
    respect_pins: bool,
) -> list[Assignment]:
    if timetable_id is None:
        return []
    timetable = _get_or_404(session, m.Timetable, timetable_id)
    if timetable.term_id != term_id:
        raise ConflictError(
            f"timetable {timetable_id} belongs to term {timetable.term_id}, not {term_id}"
        )
    placed = timetables_repo.assignments_of(session, timetable_id)
    if respect_pins:
        return placed
    return [a.model_copy(update={"is_pinned": False}) for a in placed]


def _course_of(
    session: DbSession, term_id: int, session_rows: Sequence[m.Session]
) -> dict[SessionId, CourseId]:
    """Which course each session belongs to.

    A session knows its offering and an offering knows its course, so this is one extra
    statement rather than a join onto every session row. Two of the sixteen scored rules need
    it — a course in one room, a course not twice in a day — and `Snapshot` asks for it
    explicitly rather than guessing, so forgetting it here would silently price two rules at
    zero instead of raising.
    """
    of_offering = {
        int(offering_id): CourseId(course_id)
        for offering_id, course_id in session.execute(
            select(m.Offering.id, m.Offering.course_id).where(m.Offering.term_id == term_id)
        ).all()
    }
    return {
        SessionId(row.id): of_offering[row.offering_id]
        for row in session_rows
        if row.offering_id in of_offering
    }
