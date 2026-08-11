"""Student groups: the tree, the cohorts, and who clashes with whom."""

from __future__ import annotations

from fastapi import APIRouter, status

from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending
from tessera.api.schemas import (
    Page,
    StudentGroupCreate,
    StudentGroupRead,
    StudentGroupTree,
    StudentGroupUpdate,
)

router = APIRouter(prefix="/api/v1/student-groups", tags=["groups"])
ERRORS = problem_responses(404, 409, 422, 501)


@router.get("", response_model=Page[StudentGroupRead], responses=ERRORS)
def list_groups(program_id: int | None = None) -> Page[StudentGroupRead]:
    pending("2.3")


@router.get("/tree", response_model=list[StudentGroupTree], responses=ERRORS)
def group_tree(program_id: int | None = None) -> list[StudentGroupTree]:
    """The hierarchy already resolved, for the outline view.

    Separate from the flat listing because the client would otherwise rebuild the tree
    itself — a second implementation of the parent/child rules, and a second place for
    them to be wrong.
    """
    pending("2.3")


@router.post(
    "", response_model=StudentGroupRead, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_group(payload: StudentGroupCreate) -> StudentGroupRead:
    pending("2.3")


@router.get("/{group_id}", response_model=StudentGroupRead, responses=ERRORS)
def get_group(group_id: int) -> StudentGroupRead:
    pending("2.3")


@router.patch("/{group_id}", response_model=StudentGroupRead, responses=ERRORS)
def update_group(group_id: int, payload: StudentGroupUpdate) -> StudentGroupRead:
    pending("2.3")


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_group(group_id: int) -> None:
    pending("2.3")


@router.get("/{group_id}/conflicts", response_model=list[int], responses=ERRORS)
def group_conflicts(group_id: int) -> list[int]:
    """Groups that share students with this one and so cannot be taught opposite it."""
    pending("2.3")
