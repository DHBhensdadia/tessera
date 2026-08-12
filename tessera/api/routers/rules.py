"""Availability and constraints — everything that narrows what the solver may do."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from tessera.api.deps import Db
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
from tessera.repository import people as people_repo

router = APIRouter(prefix="/api/v1", tags=["rules"])
ERRORS = problem_responses(404, 422, 501)


@router.get(
    "/terms/{term_id}/unavailability",
    response_model=Page[UnavailabilityRead],
    responses=ERRORS,
)
def list_unavailability(
    term_id: int, db: Db, kind: str | None = None, subject_id: int | None = None
) -> Page[UnavailabilityRead]:
    items = [
        UnavailabilityRead(kind=x.kind, subject_id=x.subject_id, slot=x.slot, reason=x.reason)
        for x in people_repo.list_unavailability(db, term_id, kind=kind, subject_id=subject_id)
    ]
    return Page(items=items, total=len(items))


@router.post(
    "/terms/{term_id}/unavailability",
    response_model=Page[UnavailabilityRead],
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def add_unavailability(
    term_id: int, payload: UnavailabilityCreate, db: Db
) -> Page[UnavailabilityRead]:
    """Takes a list of slots rather than one.

    Availability is edited by dragging across a grid, so a single interaction produces
    a range; one request per slot would mean dozens per gesture.

    Blocking an already-blocked slot is a no-op rather than a conflict: dragging across
    a partly-blocked range is ordinary use.
    """
    rows = people_repo.block_slots(
        db,
        term_id,
        kind=payload.kind,
        subject_id=payload.subject_id,
        slots=payload.slots,
        reason=payload.reason,
    )
    items = [
        UnavailabilityRead(kind=x.kind, subject_id=x.subject_id, slot=x.slot, reason=x.reason)
        for x in rows
    ]
    return Page(items=items, total=len(items))


@router.delete(
    "/terms/{term_id}/unavailability",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERRORS,
)
def clear_unavailability(
    term_id: int,
    db: Db,
    kind: str,
    subject_id: int,
    slot: list[int] | None = Query(
        default=None,
        description="Repeat to free specific slots. Omit to clear the whole subject.",
    ),
) -> None:
    """Free slots again.

    Without `slot` this clears everything for the subject, which is what it always did.
    With it, only those slots are freed — which is what dragging across blocked cells to
    release them actually needs.
    """
    people_repo.unblock_slots(db, term_id, kind=kind, subject_id=subject_id, slots=slot)


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
