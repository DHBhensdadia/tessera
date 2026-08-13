"""Teaching weeks and terms.

Neither fits the declared table in `places`: a grid is six numbers and a set of breaks, a
term hangs off both an institution and a grid. More importantly a grid has **no edit
form at all**, and that absence is a rule rather than an omission.

Every stored slot is an integer index whose meaning comes entirely from its grid's shape
(Decision #51). Changing `slots_per_day` after anything is scheduled would silently
reinterpret every assignment and every blocked hour in every term using it — no error, no
warning, a timetable that is simply wrong. So the page explains that and offers a second
grid instead of an edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.repository import calendar as repo
from tessera.repository import structure as structure_repo
from tessera.repository.errors import RepositoryError


@dataclass(frozen=True)
class GridRow:
    id: int
    name: str
    shape: str
    breaks: str
    slot_count: int
    longest_block: int


def _grid_rows(db: Db) -> list[GridRow]:
    rows = []
    for grid in repo.list_time_grids(db):
        longest = max(
            (n for n in range(1, grid.slots_per_day + 1) if grid.start_slots_for(n)), default=0
        )
        rows.append(
            GridRow(
                id=int(grid.id or 0),
                name=grid.name,
                shape=f"{grid.days} days x {grid.slots_per_day} x {grid.slot_minutes} min",
                breaks=", ".join(grid.clock(s) for s in sorted(grid.break_slots)) or "—",
                slot_count=grid.slot_count,
                # The number that decides whether a two-hour lab is placeable at all, and
                # the one nobody thinks to check until a solve fails.
                longest_block=longest,
            )
        )
    return rows


def _render_grids(
    request: Request, db: Db, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    return page(
        request,
        "calendar/grids.html",
        grids=_grid_rows(db),
        institutions=structure_repo.list_institutions(db),
        problem=problem,
        **extra,
    )


@router.get("/time-grids", include_in_schema=False)
def list_grids(request: Request, db: Db) -> HTMLResponse:
    return _render_grids(request, db)


@router.post("/time-grids", include_in_schema=False)
def create_grid(
    request: Request,
    db: Db,
    institution_id: int = Form(...),
    name: str = Form("Default"),
    days: int = Form(...),
    slots_per_day: int = Form(...),
    slot_minutes: int = Form(...),
    day_start_minute: int = Form(...),
    break_slots: list[int] | None = Form(None),
) -> Response:
    try:
        repo.create_time_grid(
            db,
            institution_id=institution_id,
            name=name,
            days=days,
            slots_per_day=slots_per_day,
            slot_minutes=slot_minutes,
            day_start_minute=day_start_minute,
            break_slots=break_slots or [],
        )
    except RepositoryError as error:
        return _render_grids(request, db, problem=describe(error), submitted={"name": name})
    return redirect("/console/time-grids")


@router.post("/time-grids/{grid_id}/delete", include_in_schema=False)
def delete_grid(request: Request, db: Db, grid_id: int) -> Response:
    try:
        repo.delete_time_grid(db, grid_id)
    except RepositoryError as error:
        return _render_grids(request, db, problem=describe(error))
    return redirect("/console/time-grids")


# -- terms ---------------------------------------------------------------------


def _render_terms(
    request: Request, db: Db, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    return page(
        request,
        "calendar/terms.html",
        terms=repo.list_terms(db),
        grids=repo.list_time_grids(db),
        institutions=structure_repo.list_institutions(db),
        problem=problem,
        **extra,
    )


@router.get("/terms", include_in_schema=False)
def list_terms(request: Request, db: Db) -> HTMLResponse:
    return _render_terms(request, db)


@router.post("/terms", include_in_schema=False)
def create_term(
    request: Request,
    db: Db,
    institution_id: int = Form(...),
    time_grid_id: int = Form(...),
    academic_year: str = Form(...),
    name: str = Form(...),
    starts_on: str = Form(""),
    ends_on: str = Form(""),
) -> Response:
    """Dates arrive as strings because an empty date input posts `""`, not a date.

    They are optional on purpose: a department starts building next year's timetable long
    before the calendar is confirmed, and nothing in the scheduler reads them.
    """
    try:
        repo.create_term(
            db,
            institution_id=institution_id,
            time_grid_id=time_grid_id,
            academic_year=academic_year,
            name=name,
            starts_on=date.fromisoformat(starts_on) if starts_on else None,
            ends_on=date.fromisoformat(ends_on) if ends_on else None,
        )
    except RepositoryError as error:
        return _render_terms(
            request, db, problem=describe(error), submitted={"name": name, "year": academic_year}
        )
    except ValueError:
        return _render_terms(request, db, problem="Those dates could not be read.")
    return redirect("/console/terms")


@router.post("/terms/{term_id}/delete", include_in_schema=False)
def delete_term(request: Request, db: Db, term_id: int) -> Response:
    try:
        repo.delete_term(db, term_id)
    except RepositoryError as error:
        return _render_terms(request, db, problem=describe(error))
    return redirect("/console/terms")
