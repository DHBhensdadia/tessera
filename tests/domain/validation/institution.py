"""A small, valid institution to break on purpose.

Every mutation test starts from this and damages exactly one thing. That constrains the design
more than it looks: for a mutation to prove a rule fires, the mutated timetable must break
**that rule alone** — Phase 0.1's curriculum test made this point by building a clash that
tripped the curriculum rule only, since one that also double-booked a room would have passed
even if only the room rule worked.

So the pieces here are chosen to be separable. Two labs that need different instructors, so
moving one onto the other is a room clash and not also a person in two places. A hall with
spare capacity and no equipment, and a lab with exactly enough of both, so capacity and
features can each be broken without touching the other.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from tessera.domain.entities import Room, Session, SessionKind, Unavailability, WeekPattern
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import (
    AssignmentId,
    FeatureId,
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot

PROJECTOR = FeatureId(1)
COMPUTERS = FeatureId(2)

YEAR_1 = StudentGroupId(1)
BATCH_A = StudentGroupId(2)
BATCH_B = StudentGroupId(3)

HALL = RoomId(1)
LAB = RoomId(2)
CUPBOARD = RoomId(3)
STUDIO = RoomId(4)

#: Monday to Friday, 09:00 to 17:00 in hours, lunch at 13:00.
GRID = TimeGrid(
    days=5, slots_per_day=8, slot_minutes=60, day_start_minute=9 * 60, break_slots=frozenset({4})
)

#: Slot 4 of each day. Named because three tests reach for it and `4` explains nothing.
LUNCH = 4

GROUPS = GroupSet(
    [
        StudentGroup(id=YEAR_1, name="Year 1", size=0, kind=GroupKind.STRUCTURAL),
        StudentGroup(id=BATCH_A, name="Batch A", size=30, parent_id=YEAR_1),
        StudentGroup(id=BATCH_B, name="Batch B", size=30, parent_id=YEAR_1),
    ]
)

ROOMS = (
    Room(id=HALL, name="Main Hall", capacity=100, features=frozenset({PROJECTOR})),
    # Exactly thirty workstations, so a batch of thirty fits and thirty-one would not.
    Room(
        id=LAB,
        name="Computer Lab",
        capacity=30,
        features=frozenset({COMPUTERS}),
        feature_counts={COMPUTERS: 30},
        turnaround_slots=1,
    ),
    Room(id=CUPBOARD, name="Seminar Room", capacity=10),
    Room(id=STUDIO, name="Studio", capacity=40),
)

LECTURE = SessionId(1)
LAB_A = SessionId(2)
LAB_B = SessionId(3)
TUTORIAL = SessionId(4)

SESSIONS = (
    # The whole year, two hours, no equipment.
    Session(
        id=LECTURE,
        kind=SessionKind.LECTURE,
        duration_slots=2,
        attendee_ids=frozenset({YEAR_1}),
        instructor_ids=frozenset({InstructorId(1)}),
    ),
    Session(
        id=LAB_A,
        kind=SessionKind.LAB,
        duration_slots=1,
        attendee_ids=frozenset({BATCH_A}),
        instructor_ids=frozenset({InstructorId(2)}),
        required_features=frozenset({COMPUTERS}),
        required_counts={COMPUTERS: 30},
    ),
    # Instructor 3 rather than 2, deliberately: it is what lets the room-clash mutation be a
    # room clash and nothing else.
    Session(
        id=LAB_B,
        kind=SessionKind.LAB,
        duration_slots=1,
        attendee_ids=frozenset({BATCH_B}),
        instructor_ids=frozenset({InstructorId(3)}),
        required_features=frozenset({COMPUTERS}),
        required_counts={COMPUTERS: 30},
    ),
    Session(
        id=TUTORIAL,
        kind=SessionKind.TUTORIAL,
        duration_slots=1,
        attendee_ids=frozenset({BATCH_B}),
        instructor_ids=frozenset({InstructorId(2)}),
    ),
)

#: A timetable with nothing wrong with it. Every test asserts that first.
ASSIGNMENTS = (
    Assignment(id=AssignmentId(1), session_id=LECTURE, start_slot=0, room_id=HALL),
    Assignment(id=AssignmentId(2), session_id=LAB_A, start_slot=2, room_id=LAB),
    Assignment(id=AssignmentId(3), session_id=LAB_B, start_slot=5, room_id=LAB),
    Assignment(id=AssignmentId(4), session_id=TUTORIAL, start_slot=6, room_id=STUDIO),
)


@dataclass(frozen=True)
class Institution:
    """The pieces, so a test can damage one and rebuild."""

    grid: TimeGrid = GRID
    sessions: tuple[Session, ...] = SESSIONS
    rooms: tuple[Room, ...] = ROOMS
    groups: GroupSet = GROUPS
    assignments: tuple[Assignment, ...] = ASSIGNMENTS
    unavailability: tuple[Unavailability, ...] = ()

    def snapshot(self) -> Snapshot:
        return Snapshot.of(
            grid=self.grid,
            sessions=self.sessions,
            rooms=self.rooms,
            groups=self.groups,
            assignments=self.assignments,
            unavailability=self.unavailability,
        )

    def moved(
        self, session_id: SessionId, *, to: RoomId | None = None, at: int | None = None
    ) -> Institution:
        """The same institution with one session somewhere else. The mutation, in one line."""
        return replace(
            self,
            assignments=tuple(
                # `model_copy`, not `dataclasses.replace`: these are Pydantic models.
                a.model_copy(
                    update={
                        "room_id": to if to is not None else a.room_id,
                        "start_slot": at if at is not None else a.start_slot,
                    }
                )
                if a.session_id == session_id
                else a
                for a in self.assignments
            ),
        )

    def lasting(self, session_id: SessionId, slots: int) -> Institution:
        """The same institution with one session made longer."""
        return replace(
            self,
            sessions=tuple(
                s.model_copy(update={"duration_slots": slots}) if s.id == session_id else s
                for s in self.sessions
            ),
        )

    def closed(self, *unavailability: Unavailability) -> Institution:
        return replace(self, unavailability=self.unavailability + unavailability)

    def patterned(self, session_id: SessionId, pattern: WeekPattern) -> Institution:
        return replace(
            self,
            sessions=tuple(
                s.model_copy(update={"week_pattern": pattern}) if s.id == session_id else s
                for s in self.sessions
            ),
        )
