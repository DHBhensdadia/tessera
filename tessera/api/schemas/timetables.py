"""Timetables, placements, validation, history and comparison.

The two validation shapes here carry the constraint from Phase 0.2: a request always
names the cells it cares about. There is no whole-grid variant, because an unscoped
check measured 43 ms at the NFR-9 ceiling against a 16 ms frame budget — it would have
passed every test at department scale and failed only for the largest institutions, in
production.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from tessera.api.schemas.common import Reference, Wire
from tessera.domain.timetable import CommandKind, TimetableStatus


class TimetableCreate(Wire):
    name: str = Field(default="Draft", min_length=1, max_length=100)
    parent_id: int | None = None


class TimetableUpdate(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: TimetableStatus | None = None


class TimetableRead(Wire):
    id: int
    term_id: int
    name: str
    status: TimetableStatus
    parent_id: int | None
    penalty: int | None
    penalty_breakdown: dict[str, int] = Field(default_factory=dict)
    created_at: datetime | None
    published_at: datetime | None
    is_editable: bool = Field(
        default=True, description="Published and archived timetables fork on edit."
    )
    assignment_count: int = 0


class AssignmentCreate(Wire):
    session_id: int
    start_slot: int = Field(ge=0)
    room_id: int
    is_pinned: bool = False


class AssignmentUpdate(Wire):
    start_slot: int | None = Field(default=None, ge=0)
    room_id: int | None = None
    is_pinned: bool | None = Field(
        default=None,
        description="Pinned placements are held fixed by any later solve.",
    )


class AssignmentRead(Wire):
    id: int
    session_id: int
    start_slot: int
    end_slot: int = Field(default=0, description="Exclusive: start + duration.")
    room: Reference | None = None
    is_pinned: bool
    course: Reference | None = None
    instructors: list[Reference] = Field(default_factory=list)
    attendees: list[Reference] = Field(default_factory=list)


# -- validation ---------------------------------------------------------------


class MoveCheck(Wire):
    """Can this one session sit in this one cell?

    POST rather than GET because the viewport variant below cannot fit in a query
    string, and the two are kept consistent so the client uses one calling convention.
    """

    session_id: int
    start_slot: int = Field(ge=0)
    room_id: int


class Violation(Wire):
    rule: str = Field(
        description=(
            "Which rule. An invariant key such as 'room_not_double_booked', or a constraint "
            "kind such as 'same_room'. Stable across releases: the interface looks the "
            "explanation up by it."
        )
    )
    message: str = Field(description="Plain language, shown directly to the user.")
    session_id: int | None = Field(
        default=None,
        description="Which placement is in trouble. Redundant where the request named a "
        "session — a move verdict is about the session that moved — and load-bearing in "
        "`ViolationReport`, which describes a whole timetable and until 4.8 sent a list "
        "nothing could attribute to a cell.",
    )
    conflicting_session_id: int | None = None
    conflicting_assignment_id: int | None = None


class MoveVerdict(Wire):
    legal: bool
    violations: list[Violation] = Field(default_factory=list)


class ViewportCheck(Wire):
    """Which of the visible cells could this session legally occupy?

    Answered once when a drag begins, so the interface renders green and red from the
    result and makes no further calls while the pointer moves. Around 600 times less
    transport than checking each cell as the cursor crosses it.
    """

    session_id: int
    room_ids: list[int] = Field(min_length=1, description="Rooms currently on screen.")
    period_from: int = Field(ge=0)
    period_to: int = Field(gt=0, description="Exclusive.")


class CellVerdict(Wire):
    start_slot: int
    room_id: int
    legal: bool
    violations: list[Violation] = Field(default_factory=list)


class ViewportVerdict(Wire):
    session_id: int
    cells: list[CellVerdict] = Field(default_factory=list)


class ViolationReport(Wire):
    """Everything currently wrong with a timetable."""

    timetable_id: int
    is_feasible: bool
    hard_violations: list[Violation] = Field(default_factory=list)
    penalty: int | None = None
    penalty_breakdown: dict[str, int] = Field(default_factory=dict)


# -- history ------------------------------------------------------------------


class CommandRead(Wire):
    id: int
    sequence: int
    kind: CommandKind
    summary: str
    created_at: datetime | None
    undone_at: datetime | None
    is_undone: bool = False


# -- comparison and views ------------------------------------------------------


class ComparisonMetric(Wire):
    name: str
    left: float
    right: float
    better: str = Field(default="", description="'left', 'right' or '' when equivalent.")


class ComparisonReport(Wire):
    """Two candidate timetables, side by side.

    ``interpretation`` matters more than the numbers: a committee cannot act on
    "1094 versus 1180", but can act on "this one favours staff, that one favours
    students".
    """

    left_id: int
    right_id: int
    metrics: list[ComparisonMetric] = Field(default_factory=list)
    interpretation: str = ""
    differing_session_ids: list[int] = Field(default_factory=list)


class GridCell(Wire):
    start_slot: int
    duration_slots: int
    assignment_id: int
    session_id: int
    label: str
    room: Reference | None = None
    is_pinned: bool = False
    has_violation: bool = False


class GridColumn(Wire):
    """One pivot subject: a group, an instructor or a room."""

    subject: Reference
    cells: list[GridCell] = Field(default_factory=list)


class GridView(Wire):
    """A timetable pivoted for display.

    The same data read three ways — by group, by instructor, by room — because those are
    the three documents a timetabling committee actually produces.
    """

    timetable_id: int
    pivot: str
    days: int
    slots_per_day: int
    break_slots: list[int] = Field(default_factory=list)
    columns: list[GridColumn] = Field(default_factory=list)
