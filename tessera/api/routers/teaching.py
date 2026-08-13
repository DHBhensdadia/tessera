"""Time grids, terms, offerings, templates and sessions.

Handlers are thin on purpose: translate the wire model, call the repository, translate
back. Anything that decides something belongs in `tessera.repository.calendar`.

**There is no `PATCH /time-grids/{id}` and there must never be one.** A grid gives every
stored slot index its meaning, so editing one reinterprets every assignment and every
blocked slot in every term using it, silently. `tests/api/test_calendar.py` asserts this
route's absence — if you are here to add it, read Decision #51 first.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from tessera.api.deps import Db
from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending
from tessera.api.schemas import (
    OfferingCreate,
    OfferingRead,
    Page,
    Reference,
    SessionRead,
    SessionTemplateCreate,
    SessionTemplateRead,
    SessionUpdate,
    TermCreate,
    TermDuplicate,
    TermRead,
    TermUpdate,
    TimeGridCreate,
    TimeGridRead,
)
from tessera.domain import entities as d
from tessera.domain.time_grid import TimeGrid
from tessera.repository import calendar as repo
from tessera.repository import models as m

router = APIRouter(prefix="/api/v1", tags=["teaching"])
ERRORS = problem_responses(404, 409, 422, 501)


def _page[T](items: list[T]) -> Page[T]:
    return Page(items=items, total=len(items))


def _grid_read(grid: TimeGrid) -> TimeGridRead:
    """`slot_count` is computed by the domain, not recounted here.

    It is `days * slots_per_day`, which is trivial enough that duplicating it would look
    harmless — and would then be a second definition of how long a week is.
    """
    assert grid.id is not None  # everything the repository returns has been flushed
    return TimeGridRead(
        id=grid.id,
        name=grid.name,
        days=grid.days,
        slots_per_day=grid.slots_per_day,
        slot_minutes=grid.slot_minutes,
        day_start_minute=grid.day_start_minute,
        break_slots=sorted(grid.break_slots),
        slot_count=grid.slot_count,
    )


def _term_read(session: DbSession, term: d.Term) -> TermRead:
    assert term.id is not None
    grid = session.get(m.TimeGrid, term.time_grid_id) if term.time_grid_id else None
    return TermRead(
        id=term.id,
        academic_year=term.academic_year,
        name=term.name,
        starts_on=term.starts_on,
        ends_on=term.ends_on,
        time_grid=Reference(id=grid.id, name=grid.name) if grid else None,
    )


def _offering_read(session: DbSession, offering: d.Offering) -> OfferingRead:
    assert offering.id is not None and offering.term_id is not None
    course = session.get(m.Course, offering.course_id) if offering.course_id else None
    return OfferingRead(
        id=offering.id,
        term_id=offering.term_id,
        course=(
            Reference(id=course.id, name=f"{course.code} {course.name}".strip()) if course else None
        ),
        session_count=repo.session_count(session, offering.id),
    )


# -- time grids ----------------------------------------------------------------


@router.get("/time-grids", response_model=Page[TimeGridRead], responses=ERRORS)
def list_time_grids(db: Db, institution_id: int | None = None) -> Page[TimeGridRead]:
    return _page([_grid_read(g) for g in repo.list_time_grids(db, institution_id=institution_id)])


@router.post(
    "/time-grids",
    response_model=TimeGridRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_time_grid(payload: TimeGridCreate, db: Db) -> TimeGridRead:
    return _grid_read(
        repo.create_time_grid(
            db,
            institution_id=payload.institution_id,
            name=payload.name,
            days=payload.days,
            slots_per_day=payload.slots_per_day,
            slot_minutes=payload.slot_minutes,
            day_start_minute=payload.day_start_minute,
            break_slots=payload.break_slots,
        )
    )


@router.get("/time-grids/{grid_id}", response_model=TimeGridRead, responses=ERRORS)
def get_time_grid(grid_id: int, db: Db) -> TimeGridRead:
    return _grid_read(repo.get_time_grid(db, grid_id))


@router.delete("/time-grids/{grid_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_time_grid(grid_id: int, db: Db) -> None:
    """Added in 2.4. The frozen contract could create grids and never remove one — the
    same gap fixed for buildings and features in 2.1 and programmes in 2.3."""
    repo.delete_time_grid(db, grid_id)


# -- terms ---------------------------------------------------------------------


@router.get("/terms", response_model=Page[TermRead], responses=ERRORS)
def list_terms(db: Db, institution_id: int | None = None) -> Page[TermRead]:
    return _page([_term_read(db, t) for t in repo.list_terms(db, institution_id=institution_id)])


@router.post(
    "/terms", response_model=TermRead, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_term(payload: TermCreate, db: Db) -> TermRead:
    created = repo.create_term(
        db,
        institution_id=payload.institution_id,
        time_grid_id=payload.time_grid_id,
        academic_year=payload.academic_year,
        name=payload.name,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
    )
    return _term_read(db, created)


@router.get("/terms/{term_id}", response_model=TermRead, responses=ERRORS)
def get_term(term_id: int, db: Db) -> TermRead:
    return _term_read(db, repo.get_term(db, term_id))


@router.patch("/terms/{term_id}", response_model=TermRead, responses=ERRORS)
def update_term(term_id: int, payload: TermUpdate, db: Db) -> TermRead:
    """Name and dates only. `TermUpdate` carries no `time_grid_id`, deliberately —
    repointing a term at a differently-shaped grid has the same effect as editing one."""
    updated = repo.update_term(db, term_id, changes=payload.model_dump(exclude_unset=True))
    return _term_read(db, updated)


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_term(term_id: int, db: Db) -> None:
    repo.delete_term(db, term_id)


@router.post(
    "/terms/{term_id}/duplicate",
    response_model=TermRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def duplicate_term(term_id: int, payload: TermDuplicate) -> TermRead:
    """Roll a term forward, carrying the structural data with it.

    The feature that makes the application worth keeping: the first semester costs a day
    of data entry and every one after it costs an hour.
    """
    pending("2.9")


# -- offerings and templates ----------------------------------------------------


@router.get("/terms/{term_id}/offerings", response_model=Page[OfferingRead], responses=ERRORS)
def list_offerings(term_id: int, db: Db) -> Page[OfferingRead]:
    return _page([_offering_read(db, o) for o in repo.list_offerings(db, term_id=term_id)])


@router.post(
    "/terms/{term_id}/offerings",
    response_model=OfferingRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_offering(term_id: int, payload: OfferingCreate, db: Db) -> OfferingRead:
    """The term is named twice — once in the path, once in the body.

    `OfferingCreate` carries a `term_id` because the contract was frozen in 1.4, before
    the handlers existed. Rather than pick a winner silently, a disagreement is refused:
    whichever one the caller meant, they believe the offering went somewhere it did not,
    and that belief surfaces much later as a course missing from a timetable.
    """
    if payload.term_id != term_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(f"term_id in the body ({payload.term_id}) does not match the URL ({term_id})"),
        )
    created = repo.create_offering(db, term_id=term_id, course_id=payload.course_id)
    return _offering_read(db, created)


@router.delete("/offerings/{offering_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_offering(offering_id: int, db: Db) -> None:
    repo.delete_offering(db, offering_id)


@router.get(
    "/offerings/{offering_id}/templates",
    response_model=Page[SessionTemplateRead],
    responses=ERRORS,
)
def list_templates(offering_id: int) -> Page[SessionTemplateRead]:
    pending("2.4")


@router.post(
    "/offerings/{offering_id}/templates",
    response_model=SessionTemplateRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_template(offering_id: int, payload: SessionTemplateCreate) -> SessionTemplateRead:
    pending("2.4")


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_template(template_id: int) -> None:
    pending("2.4")


@router.post("/offerings/{offering_id}/expand", response_model=Page[SessionRead], responses=ERRORS)
def expand_offering(offering_id: int) -> Page[SessionRead]:
    """Turn templates into the sessions the solver will place.

    Explicit rather than automatic on template change: expanding replaces sessions, and
    sessions may already be scheduled and pinned.
    """
    pending("2.4")


# -- sessions ------------------------------------------------------------------


@router.get("/terms/{term_id}/sessions", response_model=Page[SessionRead], responses=ERRORS)
def list_sessions(
    term_id: int,
    offering_id: int | None = None,
    group_id: int | None = None,
    instructor_id: int | None = None,
) -> Page[SessionRead]:
    pending("2.4")


@router.get("/sessions/{session_id}", response_model=SessionRead, responses=ERRORS)
def get_session(session_id: int) -> SessionRead:
    pending("2.4")


@router.patch("/sessions/{session_id}", response_model=SessionRead, responses=ERRORS)
def update_session(session_id: int, payload: SessionUpdate) -> SessionRead:
    pending("2.4")
