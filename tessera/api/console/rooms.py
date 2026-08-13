"""Rooms in the browser — the entity that proves the pattern.

Every other section of the console is this shape: a list built from the repository, a
form that posts, and a failure re-rendered beside the form rather than thrown at the
user as a status code. Nothing here decides anything; the rules are all in
`tessera.repository.structure` and were tested there in 2.1.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.repository import structure as repo
from tessera.repository.errors import RepositoryError


@dataclass(frozen=True)
class RoomRow:
    """One table row, with ids already resolved to names.

    Built here rather than in the template because a template that queries is a template
    that cannot be rendered from a file — and the read half of these views is meant to
    survive into the static export, which has no database behind it.
    """

    id: int
    name: str
    capacity: int
    building: str | None
    features: list[str]


def _rows(db: Db) -> list[RoomRow]:
    buildings = {b.id: b.name for b in repo.list_buildings(db)}
    features = {f.id: f.name for f in repo.list_features(db)}
    return [
        RoomRow(
            id=int(room.id or 0),
            name=room.name,
            capacity=room.capacity,
            building=buildings.get(room.building_id),
            features=sorted(features[f] for f in room.features if f in features),
        )
        for room in repo.list_rooms(db)
    ]


def _render(
    request: Request, db: Db, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    return page(
        request,
        "rooms/list.html",
        rooms=_rows(db),
        buildings=repo.list_buildings(db),
        features=repo.list_features(db),
        problem=problem,
        **extra,
    )


@router.get("/rooms", include_in_schema=False)
def list_rooms(request: Request, db: Db) -> HTMLResponse:
    return _render(request, db)


@router.post("/rooms", include_in_schema=False)
def create_room(
    request: Request,
    db: Db,
    name: str = Form(...),
    capacity: int = Form(...),
    building_id: str = Form(""),
    feature_ids: list[int] | None = Form(None),
) -> Response:
    """Create, or re-render the form with the reason it could not be created.

    `building_id` arrives as a string because an unselected `<select>` posts `""`, which
    is not an int and never will be. Converting here keeps the repository's signature
    honest about what it wants.
    """
    try:
        repo.create_room(
            db,
            name=name,
            capacity=capacity,
            building_id=int(building_id) if building_id else None,
            feature_ids=feature_ids or [],
        )
    except RepositoryError as error:
        return _render(
            request,
            db,
            problem=describe(error),
            submitted={"name": name, "capacity": capacity},
        )
    return redirect("/console/rooms")


@router.post("/rooms/{room_id}/delete", include_in_schema=False)
def delete_room(request: Request, db: Db, room_id: int) -> Response:
    try:
        repo.delete_room(db, room_id)
    except RepositoryError as error:
        return _render(request, db, problem=describe(error))
    return redirect("/console/rooms")
