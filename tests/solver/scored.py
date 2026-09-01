"""Terms that actually cost something, because the ones this project already had do not.

**The suite P5 names cannot be used.** Its exit test compares scores across the twenty-one
ITC-2007 instances, and 4.2's import carries none of CB-CTT's four soft constraints — they are
what a CB-CTT solution is *scored* on, and 4.0's D5 had already given native scoring to 4.5. A
mapped instance therefore arrives with an empty constraint set, `objective.add` returns `None`,
and the solver reports *penalty 0, bound 0, optimal* before any search worth the name. Comparing
two solvers on that suite compares nothing with nothing.

So D2 builds two suites of its own:

* **generated departments**, sized to order, which is what #225 needs — the finding is about
  what happens at five hundred sessions and it cannot be reproduced on four;
* **the CB-CTT instances with Tessera's default preferences attached**, which have the
  structure no generator produces: real curricula, real teaching loads, a real room mix.

The second is **not an ITC-2007 result** and is never to be reported as one. It is CB-CTT
*structure* under Tessera *rules*, the instance files unchanged and checksummed, and the
constraint set stated here rather than chosen per run.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tessera.domain.constraints import Constraint, default_constraints
from tessera.domain.entities import Room, Session, SessionKind, Unavailability
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import (
    AssignmentId,
    BuildingId,
    CourseId,
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot
from tessera.importers.cbctt import read
from tessera.importers.cbctt.apply import mapped
from tessera.solver import Placed

#: Five days of twenty half-hour slots — the hundred-hour week #225 was measured on, so the
#: numbers here and the numbers there are about the same shape of thing.
GRID = TimeGrid(days=5, slots_per_day=20, slot_minutes=30, day_start_minute=8 * 60)

#: What a new term starts with, unmodified. Group gaps at 8 and instructor gaps at 5 are the
#: two terms #225 measured at +111,502 and +130,502 variables, and using anything else here
#: would be choosing the configuration this phase is judged on.
DEFAULTS = tuple(default_constraints())


def department(
    sessions: int,
    rooms: int,
    *,
    buildings: int = 1,
    constraints: tuple[Constraint, ...] = DEFAULTS,
    placed: bool = False,
) -> Snapshot:
    """A term of a given size that the default preferences have something to say about.

    Shaped so the rules bite rather than merely being present. Sessions are spread over
    groups, instructors and courses at ratios that leave every subject with several sessions
    a week — a group with one class has no gaps, a course with one session is in one room by
    definition, and a term built without noticing that scores zero on four of the seven
    defaults while looking like a full test.

    `placed` fills in a timetable, which is what the hint lever needs something to start from.
    """
    group_count = max(2, sessions // 10)
    instructors = max(1, sessions // 5)
    courses = max(1, sessions // 3)

    groups = GroupSet(
        [
            StudentGroup(
                id=StudentGroupId(i), name=f"Group {i}", size=25, kind=GroupKind.STRUCTURAL
            )
            for i in range(1, group_count + 1)
        ]
    )
    every_room = [
        Room(
            id=RoomId(i),
            name=f"Room {i}",
            capacity=60,
            building_id=BuildingId(i % buildings + 1) if buildings > 1 else None,
        )
        for i in range(1, rooms + 1)
    ]
    every_session = [
        Session(
            id=SessionId(i),
            kind=SessionKind.LECTURE,
            duration_slots=2,
            attendee_ids=frozenset({StudentGroupId(i % group_count + 1)}),
            instructor_ids=frozenset({InstructorId(i % instructors + 1)}),
        )
        for i in range(1, sessions + 1)
    ]
    assignments = (
        [
            Assignment(
                id=AssignmentId(i),
                session_id=SessionId(i),
                start_slot=(i * 2) % (GRID.slot_count - 2),
                room_id=RoomId(i % rooms + 1),
            )
            for i in range(1, sessions + 1)
        ]
        if placed
        else []
    )

    return Snapshot.of(
        grid=GRID,
        sessions=every_session,
        rooms=every_room,
        groups=groups,
        assignments=assignments,
        constraints=constraints,
        course_of={SessionId(i): CourseId(i % courses + 1) for i in range(1, sessions + 1)},
    )


def with_timetable(term: Snapshot, placed: Sequence[Placed]) -> Snapshot:
    """The same term with a timetable in it.

    What re-optimisation is handed, and what the validator has to be given to judge a solve:
    `Snapshot` indexes placements at construction, so a timetable cannot be attached to one
    afterwards.
    """
    return Snapshot.of(
        grid=term.grid,
        sessions=list(term.sessions.values()),
        rooms=list(term.rooms.values()),
        groups=term.groups,
        unavailability=_unavailability(term),
        constraints=list(term.constraints),
        course_of=term.course_of,
        assignments=[
            Assignment(
                id=AssignmentId(i),
                session_id=placement.session,
                start_slot=placement.start_slot,
                room_id=placement.room,
            )
            for i, placement in enumerate(placed, start=1)
        ],
    )


def _unavailability(term: Snapshot) -> list[Unavailability]:
    """The rows a snapshot was built from, read back out of what it indexed them into.

    `Snapshot` keeps closures and preferences as three lookup sets rather than as the rows they
    came from, so a term cannot simply be copied. Rebuilt exactly for everything the validator
    reads; `reason` is dropped, which appears only in the sentence a person sees.
    """
    return [
        *(Unavailability(room_id=room, slot=slot) for room, slot in sorted(term.room_closed)),
        *(
            Unavailability(instructor_id=who, slot=slot)
            for who, slot in sorted(term.instructor_away)
        ),
        *(
            Unavailability(instructor_id=who, slot=slot, is_hard=False, weight=weight)
            for (who, slot), weight in sorted(term.preferred_against.items())
        ),
    ]


def cbctt(instance: Path, constraints: tuple[Constraint, ...] = DEFAULTS) -> Snapshot:
    """A CB-CTT instance under Tessera's rules — structure from the file, preferences from us.

    The mapping is 4.2's, unchanged and re-run rather than cached, so this cannot describe an
    importer other than the one that ships.

    **Courses are recovered rather than invented**, because two of the seven defaults are about
    a course. The mapping gives every course a group of its own to carry the headcount —
    *"CS101 students"* — so the course a session belongs to is already in the term; this reads
    it back out by that group rather than by re-deriving the order sessions were built in,
    which would agree with `mapped` today and silently stop agreeing the day it changes.

    4.5 gave `Mapped` a `course_of`, and it is deliberately not used here: that one names the
    *instance's* course, a string, for writing a result back in the competition's format. This
    one needs Tessera `CourseId`s for a `Snapshot`. Same word, different quantity.
    """
    term = mapped(read(instance))
    of_course = {
        group.id: CourseId(n)
        for n, group in enumerate(
            sorted(
                (g for g in term.groups.all if g.name.endswith(" students")),
                key=lambda g: g.name,
            ),
            start=1,
        )
        if group.id is not None
    }
    course_of = {
        session.id: of_course[attended]
        for session in term.sessions
        if session.id is not None
        for attended in session.attendee_ids
        if attended in of_course
    }
    if len(course_of) != len(term.sessions):
        raise AssertionError(
            f"{len(term.sessions) - len(course_of)} sessions of {instance.name} could not be "
            "traced back to a course group — the mapping's naming has changed"
        )

    return Snapshot.of(
        grid=term.grid,
        sessions=list(term.sessions),
        rooms=list(term.rooms),
        groups=term.groups,
        unavailability=list(term.unavailability),
        constraints=constraints,
        course_of=course_of,
    )
