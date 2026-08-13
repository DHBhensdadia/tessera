"""Student groups: the tree, the electives that cut across it, and who clashes with whom.

A flat list is the wrong shape here. An intake of 120 that splits into three lab batches
of 40 *is* a nesting, and the reason three labs can run in parallel while a lecture
cannot run opposite any of them is entirely about that structure. Showing it flat would
hide the only thing worth looking at.

Headcount and conflicts are read from `GroupSet` — the same object the solver reads — so
what the page shows and what the solver believes cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.domain.groups import GroupKind, GroupSet
from tessera.domain.ids import StudentGroupId
from tessera.repository import groups as repo
from tessera.repository.errors import RepositoryError


@dataclass(frozen=True)
class Node:
    """A group, its depth in the tree, and what the solver makes of it."""

    id: int
    name: str
    kind: str
    depth: int
    size: int
    headcount: int
    clashes_with: str


def _outline(known: GroupSet) -> list[Node]:
    """Structural groups depth-first, then cohorts as roots of their own.

    A cohort has no parent by definition — an elective drawing from three intakes is
    nobody's child — so it cannot appear *in* the tree without the tree becoming a lie.
    It is listed after, marked by its kind.
    """
    by_parent: dict[int | None, list[int]] = {}
    for group in known.all:
        if group.kind is GroupKind.STRUCTURAL and group.id is not None:
            by_parent.setdefault(group.parent_id, []).append(int(group.id))

    nodes: list[Node] = []

    def describe_group(group_id: int, depth: int) -> Node:
        gid = StudentGroupId(group_id)
        group = known.get(gid)
        peers = sorted(known.get(p).name for p in known.conflict_map[gid] if p != gid)
        return Node(
            id=group_id,
            name=group.name,
            kind=group.kind.value,
            depth=depth,
            size=group.size,
            headcount=known.headcount(gid),
            clashes_with=", ".join(peers) or "—",
        )

    def walk(parent: int | None, depth: int) -> None:
        for child in sorted(
            by_parent.get(parent, []), key=lambda i: known.get(StudentGroupId(i)).name
        ):
            nodes.append(describe_group(child, depth))
            walk(child, depth + 1)

    walk(None, 0)
    for group in known.all:
        if group.kind is GroupKind.COHORT and group.id is not None:
            nodes.append(describe_group(int(group.id), 0))
    return nodes


def _render(
    request: Request, db: Db, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    try:
        known = repo.group_set(db)
        outline = _outline(known)
    except RepositoryError as error:  # pragma: no cover - the set is validated on write
        return page(
            request,
            "groups/list.html",
            nodes=[],
            groups=[],
            programs=[],
            problem=describe(error),
            **extra,
        )
    return page(
        request,
        "groups/list.html",
        nodes=outline,
        groups=sorted(known.all, key=lambda g: g.name),
        programs=repo.list_programs(db),
        problem=problem,
        **extra,
    )


@router.get("/student-groups", include_in_schema=False)
def list_groups(request: Request, db: Db) -> HTMLResponse:
    return _render(request, db)


@router.post("/student-groups", include_in_schema=False)
def create_group(
    request: Request,
    db: Db,
    name: str = Form(...),
    kind: str = Form("structural"),
    size: int = Form(0),
    parent_id: str = Form(""),
    program_id: str = Form(""),
    member_ids: list[int] | None = Form(None),
) -> Response:
    """Create a group, structural or cohort.

    The domain refuses the incoherent combinations — a structural group given members, a
    cohort drawing from another cohort, a parent that would close a cycle — so none of
    those checks are repeated here.
    """
    try:
        repo.create_group(
            db,
            name=name,
            kind=GroupKind(kind),
            size=size,
            parent_id=int(parent_id) if parent_id else None,
            program_id=int(program_id) if program_id else None,
            member_ids=member_ids or [],
        )
    except RepositoryError as error:
        return _render(request, db, problem=describe(error), submitted={"name": name, "size": size})
    return redirect("/console/student-groups")


@router.post("/student-groups/{group_id}/delete", include_in_schema=False)
def delete_group(request: Request, db: Db, group_id: int) -> Response:
    try:
        repo.delete_group(db, group_id)
    except RepositoryError as error:
        return _render(request, db, problem=describe(error))
    return redirect("/console/student-groups")


@router.post("/student-groups/{group_id}/resize", include_in_schema=False)
def resize_group(request: Request, db: Db, group_id: int, size: int = Form(...)) -> Response:
    """Headcount is the number that decides whether a room is big enough, and it is the
    one most often typed wrong first time."""
    try:
        repo.update_group(db, group_id, changes={"size": size})
    except RepositoryError as error:
        return _render(request, db, problem=describe(error))
    return redirect("/console/student-groups")
