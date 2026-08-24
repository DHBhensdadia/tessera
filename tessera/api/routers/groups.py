"""Student groups: the tree, the cohorts, and who clashes with whom."""

from __future__ import annotations

from fastapi import APIRouter, status

from tessera.api.deps import Db
from tessera.api.errors import problem_responses
from tessera.api.schemas import (
    Page,
    StudentGroupCreate,
    StudentGroupRead,
    StudentGroupTree,
    StudentGroupUpdate,
)
from tessera.domain import groups as dg
from tessera.repository import groups as repo

router = APIRouter(prefix="/api/v1/student-groups", tags=["groups"])


def _read(group: dg.StudentGroup, resolved: dg.GroupSet) -> StudentGroupRead:
    """Both sizes are returned, and they mean different things.

    `size` is what the user typed. `headcount` is what the solver must seat, falling
    back to the sum of leaves when a parent was left at zero — far more likely to mean
    "nobody filled this in" than "this intake has no students".

    `program_id` is returned because it was accepted. It has been settable on create and
    filterable on list since 2.3, `update_group` in the repository has always known how to
    change it, and the wire never carried it back — so a group's programme was write-once
    and invisible: nothing could show it and nothing could correct a wrong one. The console
    form has offered the field the whole time, which made it a parity failure against 3.4's
    own exit test rather than a missing nicety.
    """
    assert group.id is not None
    return StudentGroupRead(
        id=group.id,
        name=group.name,
        kind=group.kind,
        size=group.size,
        program_id=group.program_id,
        parent_id=group.parent_id,
        member_ids=sorted(group.member_ids),
        headcount=resolved.headcount(group.id),
    )


ERRORS = problem_responses(404, 409, 422, 501)


@router.get("", response_model=Page[StudentGroupRead], responses=ERRORS)
def list_groups(db: Db, program_id: int | None = None) -> Page[StudentGroupRead]:
    resolved = repo.group_set(db)
    items = [_read(group, resolved) for group in repo.list_groups(db, program_id=program_id)]
    return Page(items=items, total=len(items))


@router.get("/tree", response_model=list[StudentGroupTree], responses=ERRORS)
def group_tree(db: Db, program_id: int | None = None) -> list[StudentGroupTree]:
    """The hierarchy already resolved, for the outline view.

    Separate from the flat listing because the client would otherwise rebuild the tree
    itself — a second implementation of the parent/child rules, and a second place for
    them to be wrong.

    Cohorts appear as additional roots with no children. They have no parent by
    definition — an elective drawing from three intakes is nobody's child — and omitting
    them would hide exactly the groups most likely to cause conflicts. `kind` tells the
    two apart so the interface can render electives in their own section.
    """
    resolved = repo.group_set(db)
    wanted = {g.id for g in repo.list_groups(db, program_id=program_id) if g.id is not None}

    def node(group: dg.StudentGroup) -> StudentGroupTree:
        assert group.id is not None
        return StudentGroupTree(
            id=group.id,
            name=group.name,
            kind=group.kind,
            size=group.size,
            program_id=group.program_id,
            headcount=resolved.headcount(group.id),
            children=[
                node(resolved.get(child))
                for child in resolved.children_of(group.id)
                if child in wanted
            ],
        )

    roots = [
        g
        for g in resolved.all
        if g.id in wanted
        and (g.kind is dg.GroupKind.COHORT or g.parent_id is None or g.parent_id not in wanted)
    ]
    return [node(g) for g in roots]


@router.post(
    "", response_model=StudentGroupRead, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_group(payload: StudentGroupCreate, db: Db) -> StudentGroupRead:
    created = repo.create_group(
        db,
        name=payload.name,
        kind=payload.kind,
        size=payload.size,
        program_id=payload.program_id,
        parent_id=payload.parent_id,
        member_ids=payload.member_ids,
    )
    return _read(created, repo.group_set(db))


@router.get("/{group_id}", response_model=StudentGroupRead, responses=ERRORS)
def get_group(group_id: int, db: Db) -> StudentGroupRead:
    return _read(repo.get_group(db, group_id), repo.group_set(db))


@router.patch("/{group_id}", response_model=StudentGroupRead, responses=ERRORS)
def update_group(group_id: int, payload: StudentGroupUpdate, db: Db) -> StudentGroupRead:
    updated = repo.update_group(db, group_id, changes=payload.model_dump(exclude_unset=True))
    return _read(updated, repo.group_set(db))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_group(group_id: int, db: Db) -> None:
    repo.delete_group(db, group_id)


@router.get("/{group_id}/conflicts", response_model=list[int], responses=ERRORS)
def group_conflicts(group_id: int, db: Db) -> list[int]:
    """Groups that share students with this one and so cannot be taught opposite it.

    Answered by the domain rather than by a query — the solver reads the same relation
    from the same place, which is what stops the two disagreeing.
    """
    return list(repo.conflicts_of(db, group_id))
