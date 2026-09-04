"""Timetables, placements, validation, history, comparison and export.

The two validation routes carry the constraint measured in Phase 0.2: a request always
names the cells it asks about. There is deliberately **no whole-grid variant** — an
unscoped check ran at 43 ms p99 at the NFR-9 ceiling against a 16 ms frame budget, so
it would have passed every test at department scale and failed only for the largest
institutions, in production. An endpoint that can be misused eventually is.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse

from tessera.api.deps import Db
from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending
from tessera.api.schemas import (
    AssignmentCreate,
    AssignmentRead,
    AssignmentUpdate,
    CommandRead,
    ComparisonReport,
    GridView,
    MoveCheck,
    MoveVerdict,
    Page,
    TimetableCreate,
    TimetableRead,
    TimetableUpdate,
    ViewportCheck,
    ViewportVerdict,
    ViolationReport,
)
from tessera.domain.timetable import Timetable, TimetableStatus
from tessera.repository import timetables as timetables_repo

router = APIRouter(prefix="/api/v1", tags=["timetables"])
ERRORS = problem_responses(404, 409, 422, 501)


# -- timetables ----------------------------------------------------------------


@router.get("/terms/{term_id}/timetables", response_model=Page[TimetableRead], responses=ERRORS)
def list_timetables(term_id: int, db: Db, status_filter: str | None = None) -> Page[TimetableRead]:
    """A term's candidates, newest first — which is almost always the one just generated."""
    wanted = TimetableStatus(status_filter) if status_filter else None
    items = [
        _read(db, timetable)
        for timetable in timetables_repo.list_timetables(db, term_id=term_id, status=wanted)
    ]
    return Page(items=items, total=len(items))


@router.post(
    "/terms/{term_id}/timetables",
    response_model=TimetableRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_timetable(term_id: int, payload: TimetableCreate, db: Db) -> TimetableRead:
    """An empty candidate, to be filled in by hand. A solve makes its own."""
    return _read(
        db,
        timetables_repo.create_timetable(
            db, term_id=term_id, name=payload.name, parent_id=payload.parent_id
        ),
    )


@router.get("/timetables/{timetable_id}", response_model=TimetableRead, responses=ERRORS)
def get_timetable(timetable_id: int, db: Db) -> TimetableRead:
    return _read(db, timetables_repo.get_timetable(db, timetable_id))


@router.patch("/timetables/{timetable_id}", response_model=TimetableRead, responses=ERRORS)
def update_timetable(timetable_id: int, payload: TimetableUpdate, db: Db) -> TimetableRead:
    """Rename it, or move it between draft, published and archived."""
    changes = payload.model_dump(exclude_unset=True)
    return _read(db, timetables_repo.update_timetable(db, timetable_id, changes=changes))


@router.delete(
    "/timetables/{timetable_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
def delete_timetable(timetable_id: int, db: Db) -> None:
    """Throw a candidate away, with its placements and its history.

    Refused while it is published: that is what an institution is running, and 6.5 owns the
    way back to draft.
    """
    timetables_repo.delete_timetable(db, timetable_id)


def _read(db: Db, timetable: Timetable) -> TimetableRead:
    """One timetable, with the count a list view needs and would otherwise fetch rows for."""
    assert timetable.id is not None
    return TimetableRead(
        id=timetable.id,
        term_id=timetable.term_id or 0,
        name=timetable.name,
        status=timetable.status,
        parent_id=timetable.parent_id,
        penalty=timetable.penalty,
        penalty_breakdown=timetable.penalty_breakdown,
        created_at=timetable.created_at,
        published_at=timetable.published_at,
        is_editable=timetable.is_editable,
        assignment_count=timetables_repo.assignment_count(db, timetable.id),
    )


@router.post(
    "/timetables/{timetable_id}/duplicate",
    response_model=TimetableRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def duplicate_timetable(timetable_id: int, payload: TimetableCreate) -> TimetableRead:
    """Fork a candidate, so alternatives can be generated and compared."""
    pending("6.4")


@router.post("/timetables/{timetable_id}/publish", response_model=TimetableRead, responses=ERRORS)
def publish_timetable(timetable_id: int) -> TimetableRead:
    """Mark a timetable authoritative and lock it. Editing afterwards forks a draft."""
    pending("6.5")


# -- assignments ---------------------------------------------------------------


@router.get(
    "/timetables/{timetable_id}/assignments",
    response_model=Page[AssignmentRead],
    responses=ERRORS,
)
def list_assignments(
    timetable_id: int,
    group_id: int | None = None,
    instructor_id: int | None = None,
    room_id: int | None = None,
) -> Page[AssignmentRead]:
    pending("5.1")


@router.post(
    "/timetables/{timetable_id}/assignments",
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_assignment(timetable_id: int, payload: AssignmentCreate) -> AssignmentRead:
    pending("5.4")


@router.patch("/assignments/{assignment_id}", response_model=AssignmentRead, responses=ERRORS)
def update_assignment(assignment_id: int, payload: AssignmentUpdate) -> AssignmentRead:
    """Where a drag lands, and where pinning is toggled."""
    pending("5.4")


@router.delete(
    "/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
def delete_assignment(assignment_id: int) -> None:
    pending("5.4")


# -- validation ----------------------------------------------------------------


@router.post(
    "/timetables/{timetable_id}/validate-move", response_model=MoveVerdict, responses=ERRORS
)
def validate_move(timetable_id: int, payload: MoveCheck) -> MoveVerdict:
    """Whether one session may sit in one cell, and why not if it may not.

    POST for a read, deliberately: this is kept consistent with the viewport check
    below, whose payload cannot fit in a query string.
    """
    pending("5.5")


@router.post(
    "/timetables/{timetable_id}/validate-viewport",
    response_model=ViewportVerdict,
    responses=ERRORS,
)
def validate_viewport(timetable_id: int, payload: ViewportCheck) -> ViewportVerdict:
    """Legality of every cell currently on screen, for one session.

    Called once when a drag begins; the interface then renders green and red from the
    result and makes no further calls while the pointer moves. Around 600 times less
    transport than checking each cell as the cursor crosses it.

    The request must name its rooms and period range. There is no unscoped form —
    see the module docstring.
    """
    pending("5.5")


@router.get(
    "/timetables/{timetable_id}/violations", response_model=ViolationReport, responses=ERRORS
)
def list_violations(timetable_id: int) -> ViolationReport:
    pending("5.8")


# -- history -------------------------------------------------------------------


@router.get(
    "/timetables/{timetable_id}/commands", response_model=Page[CommandRead], responses=ERRORS
)
def list_commands(timetable_id: int) -> Page[CommandRead]:
    """The change history. Also the audit trail — one mechanism, both uses."""
    pending("5.6")


@router.post("/timetables/{timetable_id}/undo", response_model=CommandRead, responses=ERRORS)
def undo(timetable_id: int) -> CommandRead:
    pending("5.6")


@router.post("/timetables/{timetable_id}/redo", response_model=CommandRead, responses=ERRORS)
def redo(timetable_id: int) -> CommandRead:
    pending("5.6")


# -- views, comparison and export ----------------------------------------------


@router.get("/timetables/{timetable_id}/grid", response_model=GridView, responses=ERRORS)
def grid_view(
    timetable_id: int,
    pivot: str = Query(default="group", pattern="^(group|instructor|room)$"),
    subject_ids: str = Query(default="", description="Comma-separated ids to include."),
) -> GridView:
    """The same timetable read by group, by instructor, or by room.

    Three pivots because those are the three documents a timetabling committee actually
    produces and hands out.
    """
    pending("5.1")


@router.get("/timetables/compare", response_model=ComparisonReport, responses=ERRORS)
def compare(left: int, right: int) -> ComparisonReport:
    pending("6.4")


@router.post(
    "/timetables/{timetable_id}/export",
    responses=problem_responses(404, 422, 501),
    response_class=StreamingResponse,
    summary="Render a timetable to PDF, HTML, CSV or ICS",
)
def export(
    timetable_id: int,
    export_format: str = Query(default="pdf", alias="format", pattern="^(pdf|html|csv|ics)$"),
    pivot: str = Query(default="group", pattern="^(group|instructor|room)$"),
) -> StreamingResponse:
    pending("6.1")
