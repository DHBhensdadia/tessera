"""Timetables in the browser: what a term has produced, and how to read one.

Until 4.8 the console knew nothing about any of this — grep found eleven mentions of the word
*timetable* across the console and its templates, ten of them in prose. The engine could
generate one from 4.7 and the only way to look at it was `curl`.

**The grid is `tessera.export.grid`, rendered through a macro.** Nothing about *whose week is
this* is decided here: `GET /timetables/{id}/grid` reads the same projection, and 6.2's static
export will read it too. This module loads rows, resolves names and picks a template — which is
the same division every other console section already follows.

**One subject at a time**, which is a measurement and not a preference: every room of a
500-room institution rendered into one page is 1.7 MiB of HTML, fine at department scale and
wrong only for the largest institutions. That is the shape of defect ADR-0012 exists to refuse.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api import targets
from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.domain.validation import Report, Snapshot, validate
from tessera.export import grid
from tessera.repository import calendar as calendar_repo
from tessera.repository import snapshot as snapshot_repo
from tessera.repository import timetables as repo
from tessera.repository.errors import RepositoryError

DEFAULT_BUDGET_SECONDS = 60
"""What the Generate form offers. Lower than the API's 300 because somebody at a browser is
watching it happen, and a minute is long enough to see the score move on a real term."""


@dataclass(frozen=True)
class TimetableRow:
    """One candidate, with the count a list needs and would otherwise load placements for."""

    id: int
    name: str
    status: str
    penalty: int | None
    placed: int


def _rows(db: Db, term_id: int) -> list[TimetableRow]:
    return [
        TimetableRow(
            id=int(timetable.id or 0),
            name=timetable.name,
            status=timetable.status.value,
            penalty=timetable.penalty,
            placed=repo.assignment_count(db, int(timetable.id or 0)),
        )
        for timetable in repo.list_timetables(db, term_id=term_id)
    ]


def render_list(
    request: Request, db: Db, term_id: int, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    """The term's timetables and the form that makes another.

    Exported rather than private because `solving` renders this page when a generate is
    refused — the error belongs beside the button that caused it, which is the rule the whole
    console follows and the reason it does not share failure rendering with the API.
    """
    term = calendar_repo.get_term(db, term_id)
    extra.setdefault("budget", DEFAULT_BUDGET_SECONDS)
    return page(
        request,
        "timetables/list.html",
        term=term,
        timetables=_rows(db, term_id),
        sessions=calendar_repo.term_session_count(db, term_id),
        problem=problem,
        **extra,
    )


@router.get("/terms/{term_id}/timetables", include_in_schema=False)
def list_timetables(request: Request, db: Db, term_id: int) -> HTMLResponse:
    return render_list(request, db, term_id)


@router.post("/timetables/{timetable_id}/delete", include_in_schema=False)
def delete_timetable(request: Request, db: Db, timetable_id: int) -> Response:
    term_id = int(repo.get_timetable(db, timetable_id).term_id or 0)
    try:
        repo.delete_timetable(db, timetable_id)
    except RepositoryError as error:
        return render_list(request, db, term_id, problem=describe(error))
    return redirect(f"/console/terms/{term_id}/timetables")


@router.get("/timetables/{timetable_id}", include_in_schema=False)
def read_timetable(
    request: Request,
    db: Db,
    timetable_id: int,
    pivot: str = Query(default=grid.Pivot.GROUP.value),
    subject: int | None = None,
) -> HTMLResponse:
    """One timetable, one pivot, one subject.

    The whole timetable is loaded — the projection needs the term around it to know which
    group a session is taught to — and one subject's week is drawn from it. That is 27 to
    37 ms at department scale (4.7 §2.4), against a page a person is about to read.
    """
    timetable = repo.get_timetable(db, timetable_id)
    term_id = int(timetable.term_id or 0)
    term = snapshot_repo.load(db, term_id, seed_timetable_id=timetable_id)
    labels = targets.labels(db, term_id=term_id)

    by = grid.Pivot(pivot) if pivot in set(grid.Pivot) else grid.Pivot.GROUP
    available = grid.subjects(term, labels, by)
    broken = grid.broken_by_session(term)
    chosen = _chosen(available, subject, grid.occupied(term, by))

    return page(
        request,
        "timetables/grid.html",
        term=calendar_repo.get_term(db, term_id),
        timetable=timetable,
        placed=len(term.placements),
        unplaced=len(term.unplaced),
        report=_report(term),
        pivots=[one.value for one in grid.Pivot],
        pivot=by.value,
        subjects=available,
        subject=chosen,
        week=grid.week(term, labels, chosen, broken) if chosen else None,
    )


def _chosen(
    available: tuple[grid.Subject, ...], wanted: int | None, occupied: set[int]
) -> grid.Subject | None:
    """The subject asked for, or the first one with teaching in it.

    A pivot change posts the *old* pivot's subject id — the two selects are one form — so an
    id that means nothing here is an ordinary event rather than a mistake worth an error page.

    Falling back to the first subject with something in it rather than the first by name: a
    room estate sorts `LH-1` before `LH-2`, and a solver that used only the second would open
    this page on an empty week, which reads as a broken grid rather than as a free room.
    """
    for subject in available:
        if subject.id == wanted:
            return subject
    for subject in available:
        if subject.id in occupied:
            return subject
    return available[0] if available else None


def _report(term: Snapshot) -> Report:
    """What the 4.1 validator says about this timetable, which is not what the solver said.

    `Timetable.penalty` is the score the search reported for its own answer. This is a second,
    independently written reading of the same placements, and the two agreeing is the evidence
    4.1 was built separately to provide.
    """
    return validate(term)
