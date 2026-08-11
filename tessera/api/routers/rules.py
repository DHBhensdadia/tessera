"""Availability and constraints — everything that narrows what the solver may do."""

from __future__ import annotations

from fastapi import APIRouter, status

from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending
from tessera.api.schemas import (
    ConstraintCreate,
    ConstraintRead,
    ConstraintUpdate,
    Page,
    UnavailabilityCreate,
    UnavailabilityRead,
)

router = APIRouter(prefix="/api/v1", tags=["rules"])
ERRORS = problem_responses(404, 422, 501)


@router.get(
    "/terms/{term_id}/unavailability",
    response_model=Page[UnavailabilityRead],
    responses=ERRORS,
)
def list_unavailability(
    term_id: int, kind: str | None = None, subject_id: int | None = None
) -> Page[UnavailabilityRead]:
    pending("2.2")


@router.post(
    "/terms/{term_id}/unavailability",
    response_model=Page[UnavailabilityRead],
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def add_unavailability(term_id: int, payload: UnavailabilityCreate) -> Page[UnavailabilityRead]:
    """Takes a list of slots rather than one.

    Availability is edited by dragging across a grid, so a single interaction produces
    a range; one request per slot would mean dozens per gesture.
    """
    pending("2.2")


@router.delete(
    "/terms/{term_id}/unavailability",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERRORS,
)
def clear_unavailability(term_id: int, kind: str, subject_id: int) -> None:
    pending("2.2")


@router.get("/terms/{term_id}/constraints", response_model=Page[ConstraintRead], responses=ERRORS)
def list_constraints(term_id: int) -> Page[ConstraintRead]:
    pending("2.8")


@router.post(
    "/terms/{term_id}/constraints",
    response_model=ConstraintRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_constraint(term_id: int, payload: ConstraintCreate) -> ConstraintRead:
    pending("2.8")


@router.patch("/constraints/{constraint_id}", response_model=ConstraintRead, responses=ERRORS)
def update_constraint(constraint_id: int, payload: ConstraintUpdate) -> ConstraintRead:
    """Where the weight sliders write to.

    Different institutions genuinely disagree about how these should be balanced, so the
    argument is settled by the user rather than by us.
    """
    pending("2.8")


@router.delete(
    "/constraints/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
def delete_constraint(constraint_id: int) -> None:
    pending("2.8")
