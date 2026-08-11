"""Time grids, terms, offerings, templates and sessions."""

from __future__ import annotations

from fastapi import APIRouter, status

from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending
from tessera.api.schemas import (
    OfferingCreate,
    OfferingRead,
    Page,
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

router = APIRouter(prefix="/api/v1", tags=["teaching"])
ERRORS = problem_responses(404, 409, 422, 501)


# -- time grids ----------------------------------------------------------------


@router.get("/time-grids", response_model=Page[TimeGridRead], responses=ERRORS)
def list_time_grids() -> Page[TimeGridRead]:
    pending("2.9")


@router.post(
    "/time-grids",
    response_model=TimeGridRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_time_grid(payload: TimeGridCreate) -> TimeGridRead:
    pending("2.9")


@router.get("/time-grids/{grid_id}", response_model=TimeGridRead, responses=ERRORS)
def get_time_grid(grid_id: int) -> TimeGridRead:
    pending("2.9")


# -- terms ---------------------------------------------------------------------


@router.get("/terms", response_model=Page[TermRead], responses=ERRORS)
def list_terms() -> Page[TermRead]:
    pending("2.9")


@router.post(
    "/terms", response_model=TermRead, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_term(payload: TermCreate) -> TermRead:
    pending("2.9")


@router.get("/terms/{term_id}", response_model=TermRead, responses=ERRORS)
def get_term(term_id: int) -> TermRead:
    pending("2.9")


@router.patch("/terms/{term_id}", response_model=TermRead, responses=ERRORS)
def update_term(term_id: int, payload: TermUpdate) -> TermRead:
    pending("2.9")


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_term(term_id: int) -> None:
    pending("2.9")


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
def list_offerings(term_id: int) -> Page[OfferingRead]:
    pending("2.4")


@router.post(
    "/terms/{term_id}/offerings",
    response_model=OfferingRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_offering(term_id: int, payload: OfferingCreate) -> OfferingRead:
    pending("2.4")


@router.delete("/offerings/{offering_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_offering(offering_id: int) -> None:
    pending("2.4")


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
