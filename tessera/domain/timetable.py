"""Timetables, the placements inside them, and the record of how they changed.

Three properties here exist from the first migration because retrofitting any of them
would mean reworking code built on top:

``Assignment.is_pinned`` — a placement the user has chosen and the solver must respect.
Without it, re-optimising destroys hand-made edits and the application feels hostile.
It is one boolean, and it is what makes "pin what matters, rebuild the rest" possible.

``Timetable.status`` and ``parent_id`` — a term holds many timetables, not one. That is
what allows generating several candidates, comparing them on real metrics, and
publishing the chosen one. One extra table now against a painful migration later.

``Command`` — every mutation recorded rather than applied and forgotten. Undo, redo, the
audit trail and "what changed since we published" all fall out of the same rows.

See P2 §5.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from tessera.domain.ids import (
    AssignmentId,
    CommandId,
    RoomId,
    SessionId,
    TermId,
    TimetableId,
)
from tessera.domain.time_grid import Slot


class TimetableStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Timetable(BaseModel):
    """One candidate schedule for a term."""

    model_config = ConfigDict(frozen=True)

    id: TimetableId | None = None
    term_id: TermId | None = None
    name: str = Field(default="Draft", min_length=1)
    status: TimetableStatus = TimetableStatus.DRAFT

    parent_id: TimetableId | None = None
    """Where this came from, when it was produced by duplicating another. Gives the
    scenario view a lineage to display rather than a flat list."""

    penalty: int | None = None
    """Total soft-constraint cost. ``None`` means never solved."""

    penalty_breakdown: dict[str, int] = Field(default_factory=dict)
    """Cost per constraint kind. A single number tells a committee nothing; the split is
    what makes "this one favours staff, that one favours students" visible."""

    created_at: datetime | None = None
    published_at: datetime | None = None

    @property
    def is_editable(self) -> bool:
        """Published and archived timetables are read-only; editing forks a new draft."""
        return self.status is TimetableStatus.DRAFT


class Assignment(BaseModel):
    """One session placed at a time and in a room."""

    model_config = ConfigDict(frozen=True)

    id: AssignmentId | None = None
    timetable_id: TimetableId | None = None
    session_id: SessionId
    start_slot: Slot = Field(ge=0)
    room_id: RoomId

    is_pinned: bool = False
    """Fixed by the user. The solver treats pinned placements as hard constraints and
    optimises around them."""

    def moved_to(self, start_slot: Slot, room_id: RoomId) -> Assignment:
        return self.model_copy(update={"start_slot": start_slot, "room_id": room_id})


class CommandKind(StrEnum):
    """What a recorded change did. Each maps to an apply/revert pair."""

    PLACE = "place"
    MOVE = "move"
    REMOVE = "remove"
    PIN = "pin"
    UNPIN = "unpin"
    SOLVE = "solve"
    """A whole solve, recorded as one entry so undo steps over it atomically rather
    than unwinding several hundred individual placements."""


class Command(BaseModel):
    """A recorded mutation, and enough information to reverse it.

    ``before`` and ``after`` hold the payload each direction needs; redo replays
    ``after``, undo replays ``before``. Storing both means neither operation has to
    recompute state that may since have changed.
    """

    model_config = ConfigDict(frozen=True)

    id: CommandId | None = None
    timetable_id: TimetableId | None = None
    sequence: int = Field(ge=0)
    """Position in the timetable's history. Undo walks this backwards."""

    kind: CommandKind
    summary: str = ""
    """Human-readable, written when the command is created. Shown in the history panel,
    so it is recorded rather than reconstructed later from the payload."""

    before: dict[str, int] = Field(default_factory=dict)
    after: dict[str, int] = Field(default_factory=dict)

    created_at: datetime | None = None
    undone_at: datetime | None = None

    @property
    def is_undone(self) -> bool:
        return self.undone_at is not None
