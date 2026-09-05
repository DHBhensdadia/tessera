"""A timetable pivoted for reading: by group, by instructor, or by room.

The three documents a timetabling committee actually produces (R1 §5), from one set of
placements. Three things want this projection and they are two stages apart, so it is written
once here rather than three times where each of them lives:

* the browser console's timetable page, which is its first consumer,
* `GET /timetables/{id}/grid`, whose `GridView` was frozen in the 1.4 contract,
* and the static HTML export (P5 6.2 — *"reuses the 2.5 renderer"*, and Decision #21).

**It lives in `tessera.export` because of where it is allowed to be imported from.**
`pyproject.toml` forbids this package `fastapi`, `starlette` and `sqlalchemy`, so the export
cannot reach a projection kept in `tessera.api` or in `tessera.repository` — which is where it
would naturally have gone, and where it would have had to be moved once 6.2 arrived. Nothing
here touches a database or a request: it takes a `Snapshot`, which the repository has known how
to build since 4.7, and the names, which the caller resolves.

**Names are supplied rather than looked up.** A timetable stores ids; *"CS301 Operating
Systems"* needs four tables. `api/targets.py` already resolves exactly these four in one query
set per request (#168), and a second resolver here would be the fifth instance of the drift
that decision was written about.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from tessera.domain.ids import SessionId
from tessera.domain.validation import Placement, Snapshot, validate

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DAY_NAMES",
    "Block",
    "Cell",
    "Labels",
    "Pivot",
    "Row",
    "Subject",
    "Week",
    "broken_by_session",
    "occupied",
    "subjects",
    "week",
    "weeks",
]

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: Hard rules a placement breaks, by session. Empty for a solved timetable, which is what a
#: valid one is — but a timetable is also something a person edits, and a grid that could not
#: show a clash would be the wrong tool for looking at one.
type Broken = Mapping[SessionId, tuple[str, ...]]


class Pivot(StrEnum):
    """Whose week this is."""

    GROUP = "group"
    INSTRUCTOR = "instructor"
    ROOM = "room"


@dataclass(frozen=True, slots=True)
class Labels:
    """What the ids in a timetable are called.

    Four mappings rather than one, because an id is only unique within its kind: room 3 and
    course 3 are different things and a single dict would silently answer for either.
    """

    rooms: Mapping[int, str]
    instructors: Mapping[int, str]
    groups: Mapping[int, str]
    courses: Mapping[int, str]

    @classmethod
    def unresolved(cls) -> Labels:
        """Ids only, rendered as *room 3*. For a caller with no database behind it — the
        agreement test, and 6.2's fixtures before there is a project behind them."""
        return cls(rooms={}, instructors={}, groups={}, courses={})


@dataclass(frozen=True, slots=True)
class Subject:
    """One thing a week can be read for: a group, an instructor or a room."""

    kind: Pivot
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class Block:
    """One placed session, as it appears in somebody's week."""

    session_id: int
    assignment_id: int | None
    start_slot: int
    duration_slots: int
    course: str
    kind: str
    room_id: int
    room: str
    instructors: tuple[str, ...]
    attendees: tuple[str, ...]
    is_pinned: bool
    broken_rules: tuple[str, ...] = ()

    @property
    def is_broken(self) -> bool:
        return bool(self.broken_rules)


@dataclass(frozen=True, slots=True)
class Cell:
    """One position in the rendered week.

    `span` and `covered` are the two halves of drawing a two-hour lab as one block: the cell
    it starts in spans two rows, and the slot beneath it is not drawn at all. A renderer that
    ignored either would draw the lab twice.
    """

    slot: int
    is_break: bool
    block: Block | None = None
    span: int = 1
    covered: bool = False


@dataclass(frozen=True, slots=True)
class Row:
    """One clock time, across every day of the week."""

    clock: str
    is_break: bool
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class Week:
    """One subject's timetable, ready to render."""

    subject: Subject
    days: tuple[str, ...]
    rows: tuple[Row, ...]
    blocks: int

    @property
    def is_empty(self) -> bool:
        return self.blocks == 0


def subjects(snapshot: Snapshot, labels: Labels, by: Pivot) -> tuple[Subject, ...]:
    """Everything this timetable can be read for, in the order a menu should offer them.

    **Rooms come from the term; groups and instructors come from the teaching.** A room with
    nothing in it is worth looking at — an empty week answers *"is this lab free?"* — whereas
    an instructor who teaches nothing this term has no timetable rather than an empty one, and
    offering a thousand of those would bury the dozen that matter.

    Groups are the **leaf** groups, which is the reading the clash rule already uses: a leaf
    is the set of students who share a week, so a lecture to *Sem 5* appears in the week of
    *Sem 5 Batch A* and of *Batch B* alike. Pivoting on the parent would produce a document no
    student is handed. `sessions_of_group` is keyed that way already — `Snapshot._index` folds
    every session through `leaves`, so resolving them again here would be a line that cannot
    be seen to fail, which is how it was found.
    """
    if by is Pivot.ROOM:
        found = [int(room_id) for room_id in snapshot.rooms]
    elif by is Pivot.INSTRUCTOR:
        found = [int(instructor_id) for instructor_id in snapshot.sessions_of_instructor]
    else:
        found = sorted(int(leaf) for leaf in snapshot.sessions_of_group)

    named = [Subject(kind=by, id=one, name=_name(labels, by, one)) for one in dict.fromkeys(found)]
    return tuple(sorted(named, key=lambda subject: (subject.name, subject.id)))


def week(
    snapshot: Snapshot, labels: Labels, subject: Subject, broken: Broken | None = None
) -> Week:
    """One subject's week.

    Built for a single subject rather than for all of them because the payload is the
    constraint and not the arithmetic: rendering every room of a 500-room institution at once
    measured 1.7 MiB of HTML in 9 ms — fine at department scale, wrong only for the largest
    institutions, which is the failure ADR-0012 exists to refuse. One at a time is also what
    P7 Act 7 draws.
    """
    grid = snapshot.grid
    starts: dict[int, Block] = {}
    covered: set[int] = set()

    for placement in snapshot.placements.values():
        if not _belongs(snapshot, placement, subject):
            continue
        block = _block(snapshot, labels, placement, broken or {})
        starts[int(placement.start_slot)] = block
        covered.update(range(block.start_slot + 1, block.start_slot + block.duration_slots))

    rows = [
        Row(
            clock=grid.clock(slot_of_day),
            is_break=slot_of_day in grid.break_slots,
            cells=tuple(
                _cell(grid.slots_per_day * day + slot_of_day, snapshot, starts, covered)
                for day in range(grid.days)
            ),
        )
        for slot_of_day in range(grid.slots_per_day)
    ]

    return Week(subject=subject, days=DAY_NAMES[: grid.days], rows=tuple(rows), blocks=len(starts))


def weeks(
    snapshot: Snapshot, labels: Labels, by: Pivot, broken: Broken | None = None
) -> tuple[Week, ...]:
    """Every subject's week. What the static export writes and what the route serves.

    A page never calls this — `week` says why — but an export produces one file and the
    agreement test compares every cell, and both want the whole set.
    """
    return tuple(
        week(snapshot, labels, subject, broken) for subject in subjects(snapshot, labels, by)
    )


def occupied(snapshot: Snapshot, by: Pivot) -> set[int]:
    """The subjects this timetable actually places anything in.

    A page opening on an empty week reads as a broken grid rather than as a free room, and a
    room estate that sorts `LH-1` first will do exactly that whenever the solver used `LH-2`.
    Cheap enough to compute for every subject at once: it walks the placements, not the cells.
    """
    found: set[int] = set()
    for placement in snapshot.placements.values():
        if by is Pivot.ROOM:
            found.add(int(placement.room_id))
            continue
        session = snapshot.sessions[placement.session_id]
        if by is Pivot.INSTRUCTOR:
            found.update(int(one) for one in session.instructor_ids)
        else:
            found.update(int(leaf) for leaf in snapshot.leaves(session))
    return found


def broken_by_session(snapshot: Snapshot) -> dict[SessionId, tuple[str, ...]]:
    """Which hard rules each placement breaks, so a cell can be marked.

    Empty for anything a solve produced — that is what makes a solved timetable valid. A
    timetable is also something a person edits, and a grid that could not show a clash would
    be the wrong tool for looking at one.

    Here rather than beside either renderer because both want it and a second fold over the
    validator's report is a second chance to disagree about what counts as broken.
    """
    found: dict[SessionId, tuple[str, ...]] = {}
    for violation in validate(snapshot).hard:
        found[violation.session_id] = (*found.get(violation.session_id, ()), violation.rule)
    return found


def _cell(slot: int, snapshot: Snapshot, starts: dict[int, Block], covered: set[int]) -> Cell:
    block = starts.get(slot)
    return Cell(
        slot=slot,
        is_break=snapshot.grid.is_break(slot),
        block=block,
        span=block.duration_slots if block else 1,
        covered=slot in covered,
    )


def _belongs(snapshot: Snapshot, placement: Placement, subject: Subject) -> bool:
    if subject.kind is Pivot.ROOM:
        return int(placement.room_id) == subject.id
    # Indexed rather than guarded: `Snapshot.of` drops any assignment whose session it does
    # not hold, so a placement here always has one. A `None` branch would be a line no input
    # can reach, and `_block` indexes the same dict directly.
    session = snapshot.sessions[placement.session_id]
    if subject.kind is Pivot.INSTRUCTOR:
        return subject.id in {int(one) for one in session.instructor_ids}
    # `Snapshot.leaves` rather than a second walk of the tree: a lecture to an intake belongs
    # on every batch's week, and that resolution is the domain's to make once.
    return subject.id in {int(leaf) for leaf in snapshot.leaves(session)}


def _block(snapshot: Snapshot, labels: Labels, placement: Placement, broken: Broken) -> Block:
    session = snapshot.sessions[placement.session_id]
    course_id = snapshot.course_of.get(placement.session_id)
    start = int(placement.start_slot)

    return Block(
        session_id=int(placement.session_id),
        assignment_id=int(placement.assignment_id) if placement.assignment_id else None,
        start_slot=start,
        duration_slots=_drawable(snapshot, start, session.duration_slots),
        course=_course(labels, course_id, placement.session_id),
        kind=session.kind.value,
        room_id=int(placement.room_id),
        room=_named(labels.rooms, int(placement.room_id), "room"),
        instructors=tuple(
            sorted(
                _named(labels.instructors, int(one), "instructor") for one in session.instructor_ids
            )
        ),
        attendees=tuple(
            sorted(_named(labels.groups, int(one), "group") for one in session.attendee_ids)
        ),
        is_pinned=placement.is_pinned,
        broken_rules=tuple(broken.get(placement.session_id, ())),
    )


def _drawable(snapshot: Snapshot, start: int, duration: int) -> int:
    """How many rows this block may occupy without running off its day.

    A solver never produces a placement `TimeGrid.span` would refuse, but a person will:
    `Assignment` accepts any non-negative slot and 5.4 lets one be dragged. Drawing one row
    for a placement the grid rejects shows the fault where it is, which is more use than a
    renderer that raises and shows nothing at all.
    """
    return duration if snapshot.grid.can_hold(start, duration) else 1


def _course(labels: Labels, course_id: int | None, session_id: SessionId) -> str:
    if course_id is None:
        return f"session {int(session_id)}"
    return labels.courses.get(int(course_id), f"course {int(course_id)}")


def _named(names: Mapping[int, str], subject_id: int, kind: str) -> str:
    return names.get(subject_id, f"{kind} {subject_id}")


def _name(labels: Labels, by: Pivot, subject_id: int) -> str:
    if by is Pivot.ROOM:
        return _named(labels.rooms, subject_id, "room")
    if by is Pivot.INSTRUCTOR:
        return _named(labels.instructors, subject_id, "instructor")
    return _named(labels.groups, subject_id, "group")
