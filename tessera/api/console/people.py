"""Instructors, and the week each one cannot teach.

The availability grid is the only page in the console with any real shape to it, and it
is the reason the console is worth building at all: blocking Tuesday afternoons through
`curl` means computing slot indices by hand, and nobody checks a timetable they had to
compute slot indices to enter.

Slots are integers (Decision #6). The grid turns them back into days and clock times
using the term's own `TimeGrid`, so the labels here and the labels the solver reasons
about come from one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.domain.time_grid import TimeGrid
from tessera.repository import calendar as calendar_repo
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository import people as repo
from tessera.repository.errors import RepositoryError

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class Cell:
    """One slot in the grid, already resolved to what it means."""

    slot: int
    label: str
    blocked: bool
    is_break: bool


@dataclass(frozen=True)
class Row:
    """One slot-of-day across the week — the shape a timetable is actually read in."""

    time: str
    cells: tuple[Cell, ...]


def _grid_of(db: Db, term_id: int) -> TimeGrid | None:
    row = db.get(m.Term, term_id)
    if row is None:
        return None
    grid = db.get(m.TimeGrid, row.time_grid_id)
    return mappers.time_grid_to_domain(grid) if grid else None


def _week(grid: TimeGrid, blocked: frozenset[int]) -> list[Row]:
    """The week as rows of times and columns of days.

    Built here rather than in the template because working out what slot 40 means is the
    domain's job, and a template that does arithmetic is a template nobody can check.
    """
    rows: list[Row] = []
    for slot_of_day in range(grid.slots_per_day):
        cells = []
        for day in range(grid.days):
            slot = day * grid.slots_per_day + slot_of_day
            cells.append(
                Cell(
                    slot=slot,
                    label=f"{DAY_NAMES[day]} {grid.clock(slot)}",
                    blocked=slot in blocked,
                    is_break=grid.is_break(slot),
                )
            )
        rows.append(Row(time=grid.clock(slot_of_day), cells=tuple(cells)))
    return rows


def _render(
    request: Request, db: Db, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    return page(
        request,
        "instructors/list.html",
        instructors=repo.list_instructors(db),
        terms=calendar_repo.list_terms(db),
        problem=problem,
        **extra,
    )


@router.get("/instructors", include_in_schema=False)
def list_instructors(request: Request, db: Db) -> HTMLResponse:
    return _render(request, db)


@router.post("/instructors", include_in_schema=False)
def create_instructor(
    request: Request, db: Db, name: str = Form(...), email: str = Form("")
) -> Response:
    try:
        repo.create_instructor(db, name=name, email=email)
    except RepositoryError as error:
        return _render(request, db, problem=describe(error), submitted={"name": name})
    return redirect("/console/instructors")


@router.post("/instructors/{instructor_id}/delete", include_in_schema=False)
def delete_instructor(request: Request, db: Db, instructor_id: int) -> Response:
    try:
        repo.delete_instructor(db, instructor_id)
    except RepositoryError as error:
        return _render(request, db, problem=describe(error))
    return redirect("/console/instructors")


@router.get("/instructors/{instructor_id}/availability", include_in_schema=False)
def availability(
    request: Request, db: Db, instructor_id: int, term_id: int | None = None
) -> HTMLResponse:
    """The week, with blocked slots ticked.

    Availability is per term because the teaching week is: a slot index only means a time
    by reference to a term's grid, so the same instructor's Tuesday afternoon is a
    different set of integers in a term built on a different week.
    """
    terms = calendar_repo.list_terms(db)
    chosen = term_id or (int(terms[0].id or 0) if terms else None)
    instructor = repo.get_instructor(db, instructor_id)

    grid = _grid_of(db, chosen) if chosen else None
    blocked = (
        repo.blocked_slots(db, chosen, instructor_id=instructor_id)
        if chosen is not None
        else frozenset()
    )
    return page(
        request,
        "instructors/availability.html",
        instructor=instructor,
        terms=terms,
        term_id=chosen,
        days=DAY_NAMES[: grid.days] if grid else (),
        week=_week(grid, blocked) if grid else [],
        blocked_count=len(blocked),
    )


@router.post("/instructors/{instructor_id}/availability", include_in_schema=False)
def set_availability(
    request: Request,
    db: Db,
    instructor_id: int,
    term_id: int = Form(...),
    blocked: list[int] | None = Form(None),
) -> Response:
    """Replace the whole week rather than diffing it.

    A checkbox that is *off* is simply absent from the form, so there is no way to tell
    "unticked" from "never shown" in a partial submission. Clearing the term and
    re-blocking what came back is the only reading of the form that cannot silently keep
    a slot the user just freed.
    """
    try:
        repo.unblock_slots(db, term_id, kind="instructor", subject_id=instructor_id)
        if blocked:
            repo.block_slots(
                db, term_id, kind="instructor", subject_id=instructor_id, slots=blocked
            )
    except RepositoryError as error:
        return _render(request, db, problem=describe(error))
    return redirect(f"/console/instructors/{instructor_id}/availability?term_id={term_id}")
