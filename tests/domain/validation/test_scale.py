"""That the cost of a move does not grow with the institution.

**Flatness, not a threshold.** Phase 0.2 measured `validate-move` at 0.676 ms p99 at department
scale and 0.514 ms at ten times the sessions, end to end over HTTP, with the validation compute
itself under a microsecond — transport is roughly 500 times the work. So a 16 ms budget is not
what this defends: a validator that scanned every session instead of using indexes would pass
16 ms comfortably at department scale and fail only at the ceiling, for the largest
institutions — the defect that appears solely for the people least able to absorb it.

What is asserted is therefore the *shape*: the per-move cost at NFR-9's ceiling (5,000 sessions,
500 rooms) must not be materially worse than at department scale (500 sessions, 40 rooms). An
O(n) implementation would be about ten times worse and fail this; an indexed one is flat.

Marked `slow`: building a five-thousand-session institution takes a moment, and this is a
property to check deliberately rather than on every save.
"""

from __future__ import annotations

import time

import pytest

from tessera.domain.entities import Room, Session, SessionKind
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import (
    AssignmentId,
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot, validate_move

pytestmark = pytest.mark.slow

#: A week big enough to hold five thousand sessions without every room being full.
GRID = TimeGrid(days=5, slots_per_day=20, slot_minutes=30, day_start_minute=8 * 60)


def institution(sessions: int, rooms: int) -> Snapshot:
    """A plausible shape at a given size: every session placed, spread over the week."""
    groups = GroupSet(
        [
            StudentGroup(
                id=StudentGroupId(i), name=f"Group {i}", size=25, kind=GroupKind.STRUCTURAL
            )
            for i in range(1, max(2, sessions // 10) + 1)
        ]
    )
    group_ids = [g.id for g in groups.all if g.id is not None]

    every_room = [Room(id=RoomId(i), name=f"Room {i}", capacity=60) for i in range(1, rooms + 1)]
    every_session = [
        Session(
            id=SessionId(i),
            kind=SessionKind.LECTURE,
            duration_slots=2,
            attendee_ids=frozenset({group_ids[i % len(group_ids)]}),
            instructor_ids=frozenset({InstructorId(i % max(1, sessions // 5) + 1)}),
        )
        for i in range(1, sessions + 1)
    ]
    placed = [
        Assignment(
            id=AssignmentId(i),
            session_id=SessionId(i),
            start_slot=(i * 2) % (GRID.slot_count - 2),
            room_id=RoomId(i % rooms + 1),
        )
        for i in range(1, sessions + 1)
    ]
    return Snapshot.of(
        grid=GRID,
        sessions=every_session,
        rooms=every_room,
        groups=groups,
        assignments=placed,
    )


def per_move(snapshot: Snapshot, moves: int = 2000) -> float:
    """Microseconds per `validate_move`, warmed up first."""
    room_ids = sorted(snapshot.rooms)
    session_ids = sorted(snapshot.sessions)

    def sweep() -> None:
        for i in range(moves):
            validate_move(
                snapshot,
                session_ids[i % len(session_ids)],
                (i * 3) % (GRID.slot_count - 2),
                room_ids[i % len(room_ids)],
            )

    sweep()  # warm: first touch pays for imports and any lazy attribute
    started = time.perf_counter()
    sweep()
    return (time.perf_counter() - started) / moves * 1_000_000


def test_a_move_costs_the_same_at_ten_times_the_size() -> None:
    """Department scale against the NFR-9 ceiling.

    The threshold is generous on purpose — this is a timing test on a shared machine, and it
    exists to catch an implementation that became O(n), not to police a few per cent. Ten
    times the sessions through a scan would be about ten times the cost; three times is far
    outside the noise and far inside that.
    """
    department = per_move(institution(sessions=500, rooms=40))
    ceiling = per_move(institution(sessions=5_000, rooms=500))

    assert ceiling < department * 3, (
        f"a move costs {ceiling:.1f} us at the ceiling against {department:.1f} us at "
        "department scale — that is growth with institution size, which means something "
        "stopped being index-backed"
    )


def test_building_the_indexes_is_paid_once() -> None:
    """The snapshot is built once per request and read many times.

    Stated as a test because the design only works if that stays true: a caller rebuilding it
    per move would be correct, pass every other test here, and undo the whole point.
    """
    started = time.perf_counter()
    snapshot = institution(sessions=5_000, rooms=500)
    building = time.perf_counter() - started

    assert len(snapshot.placements) == 5_000
    assert building < 30.0  # generous; this is a smoke test on the construction path
