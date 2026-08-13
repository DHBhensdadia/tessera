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
from sqlalchemy import select
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
    SessionTemplateUpdate,
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
from tessera.repository import expansion
from tessera.repository import models as m
from tessera.repository import sessions as sessions_repo

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


def _refs(session: DbSession, model: type[m.Base], ids: frozenset[int]) -> list[Reference]:
    """Ids expanded into id-and-name pairs, so a list renders in one request.

    A session carries three of these. Returning bare ids would make drawing one week
    hundreds of round trips.
    """
    if not ids:
        return []
    rows = session.scalars(select(model).where(model.id.in_(list(ids)))).all()
    return [Reference(id=row.id, name=getattr(row, "name", "")) for row in rows]


def _course_of(session: DbSession, offering_id: int | None) -> Reference | None:
    if offering_id is None:
        return None
    course = session.scalar(
        select(m.Course)
        .join(m.Offering, m.Offering.course_id == m.Course.id)
        .where(m.Offering.id == offering_id)
    )
    return Reference(id=course.id, name=f"{course.code} {course.name}".strip()) if course else None


def _template_read(session: DbSession, template: d.SessionTemplate) -> SessionTemplateRead:
    assert template.id is not None and template.offering_id is not None
    return SessionTemplateRead(
        id=template.id,
        offering_id=template.offering_id,
        kind=template.kind,
        duration_slots=template.duration_slots,
        per_week=template.per_week,
        split_per_attendee=template.split_per_attendee,
        attendees=_refs(session, m.StudentGroup, template.attendee_ids),
        instructors=_refs(session, m.Instructor, template.instructor_ids),
        required_features=_refs(session, m.Feature, template.required_features),
        session_count=sessions_repo.template_session_count(session, template.id),
    )


def _session_read(session: DbSession, block: d.Session) -> SessionRead:
    """``session_count`` on a template is what it *has* generated; ``headcount`` here is
    what the session must seat, resolved through the group hierarchy so overlapping
    attendees are not counted twice."""
    assert block.id is not None and block.offering_id is not None
    return SessionRead(
        id=block.id,
        offering_id=block.offering_id,
        course=_course_of(session, block.offering_id),
        kind=block.kind,
        duration_slots=block.duration_slots,
        occurrence=block.occurrence,
        attendees=_refs(session, m.StudentGroup, block.attendee_ids),
        instructors=_refs(session, m.Instructor, block.instructor_ids),
        required_features=_refs(session, m.Feature, block.required_features),
        headcount=sessions_repo.headcount_of(session, sorted(block.attendee_ids)),
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
def list_templates(offering_id: int, db: Db) -> Page[SessionTemplateRead]:
    return _page(
        [_template_read(db, t) for t in sessions_repo.list_templates(db, offering_id=offering_id)]
    )


@router.post(
    "/offerings/{offering_id}/templates",
    response_model=SessionTemplateRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_template(
    offering_id: int, payload: SessionTemplateCreate, db: Db
) -> SessionTemplateRead:
    """The offering is named twice, as with offerings themselves — path and body must
    agree rather than one silently winning."""
    if payload.offering_id != offering_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"offering_id in the body ({payload.offering_id}) "
                f"does not match the URL ({offering_id})"
            ),
        )
    created = sessions_repo.create_template(
        db,
        offering_id=offering_id,
        kind=payload.kind,
        duration_slots=payload.duration_slots,
        per_week=payload.per_week,
        split_per_attendee=payload.split_per_attendee,
        attendee_ids=payload.attendee_ids,
        instructor_ids=payload.instructor_ids,
        required_feature_ids=payload.required_feature_ids,
    )
    return _template_read(db, created)


@router.patch("/templates/{template_id}", response_model=SessionTemplateRead, responses=ERRORS)
def update_template(
    template_id: int, payload: SessionTemplateUpdate, db: Db
) -> SessionTemplateRead:
    """Added in 2.4. Without it a component could be created and deleted but never
    adjusted, and reconciliation would have nothing to reconcile.

    Multiplicity only — see `SessionTemplateUpdate`. This changes no sessions; expanding
    afterwards is what reconciles them, and keeping the two separate is what lets the
    caller find out what an edit would cost before paying it.
    """
    updated = sessions_repo.update_template(
        db, template_id, changes=payload.model_dump(exclude_unset=True)
    )
    return _template_read(db, updated)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_template(template_id: int, db: Db) -> None:
    """Removes the component and the sessions it generated. Refused while any of those
    are scheduled — see `repository.sessions.delete_template`."""
    sessions_repo.delete_template(db, template_id)


@router.post("/offerings/{offering_id}/expand", response_model=Page[SessionRead], responses=ERRORS)
def expand_offering(offering_id: int, db: Db) -> Page[SessionRead]:
    """Turn templates into the sessions the solver will place.

    Explicit rather than automatic on template change, because it is a **reconciliation**
    against sessions that may already be scheduled and pinned: it adds what is missing,
    removes what is no longer wanted, and leaves everything else untouched. Running it
    twice changes nothing the second time.

    Refused, in full, when it would remove a session somebody has placed.
    """
    return _page([_session_read(db, s) for s in expansion.expand(db, offering_id)])


# -- sessions ------------------------------------------------------------------


@router.get("/terms/{term_id}/sessions", response_model=Page[SessionRead], responses=ERRORS)
def list_sessions(
    term_id: int,
    db: Db,
    offering_id: int | None = None,
    group_id: int | None = None,
    instructor_id: int | None = None,
) -> Page[SessionRead]:
    """Filtered server-side so the client can draw one person's or one group's week
    without fetching a whole department and narrowing locally."""
    found = sessions_repo.list_sessions(
        db,
        term_id=term_id,
        offering_id=offering_id,
        group_id=group_id,
        instructor_id=instructor_id,
    )
    return _page([_session_read(db, s) for s in found])


@router.get("/sessions/{session_id}", response_model=SessionRead, responses=ERRORS)
def get_session(session_id: int, db: Db) -> SessionRead:
    return _session_read(db, sessions_repo.get_session(db, session_id))


@router.patch("/sessions/{session_id}", response_model=SessionRead, responses=ERRORS)
def update_session(session_id: int, payload: SessionUpdate, db: Db) -> SessionRead:
    """Lets one session diverge from its template. Refused while it is scheduled, since
    every editable field here changes whether an existing placement is still legal."""
    updated = sessions_repo.update_session(
        db, session_id, changes=payload.model_dump(exclude_unset=True)
    )
    return _session_read(db, updated)
