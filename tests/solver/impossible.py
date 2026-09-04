"""Terms with no timetable, one nameable reason each.

P5 asks the explainer to be checked against *"hand-built impossible instances"*, and a
hand-built instance is the weakest evidence there is: the author knows the answer and the
test asserts they got it back. These are the floor rather than the evidence — `comp01`,
which nobody built to be impossible and which #213 refuted independently, is what the
suite is actually judged on.

What they are good for is **coverage of the reasons**. Each term below is impossible for
exactly one arithmetic reason, and each comes with the smallest change that makes the
reason go away — which is what turns "the check fired" into "the check fired *for this*".

Small on purpose: two days of four hours, so a term is legible in a docstring and CP-SAT
can refute the same instances independently where a test wants a second opinion.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tessera.domain.constraints import (
    Constraint,
    ConstraintKind,
    ConstraintTarget,
    TargetKind,
)
from tessera.domain.entities import Room, Session, SessionKind, Unavailability, WeekPattern
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import (
    AssignmentId,
    ConstraintId,
    FeatureId,
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot

#: Two days of four hours. Eight slots is enough for a shortfall of one to be visible and
#: small enough that a whole term fits in the head of whoever is reading the failure.
GRID = TimeGrid(days=2, slots_per_day=4, slot_minutes=60, day_start_minute=9 * 60)

PROJECTOR = FeatureId(1)

WEEK = GRID.slot_count


def term(
    *,
    sessions: Sequence[Session],
    rooms: Sequence[Room],
    sizes: Mapping[int, int],
    unavailability: Sequence[Unavailability] = (),
    grid: TimeGrid = GRID,
) -> Snapshot:
    """A term of exactly these parts, with a structural group per entry in `sizes`."""
    groups = GroupSet(
        [
            StudentGroup(
                id=StudentGroupId(number),
                name=f"Group {number}",
                size=size,
                kind=GroupKind.STRUCTURAL,
            )
            for number, size in sorted(sizes.items())
        ]
    )
    return Snapshot.of(
        grid=grid,
        sessions=list(sessions),
        rooms=list(rooms),
        groups=groups,
        unavailability=list(unavailability),
    )


def lecture(
    number: int,
    *,
    group: int,
    instructor: int = 0,
    duration: int = 1,
    features: frozenset[FeatureId] = frozenset(),
    pattern: WeekPattern = WeekPattern.EVERY_WEEK,
) -> Session:
    """One session. `instructor=0` means nobody is named, which no rule then constrains."""
    return Session(
        id=SessionId(number),
        kind=SessionKind.LECTURE,
        duration_slots=duration,
        attendee_ids=frozenset({StudentGroupId(group)}),
        instructor_ids=frozenset({InstructorId(instructor)} if instructor else set()),
        required_features=features,
        week_pattern=pattern,
    )


def room(number: int, *, seats: int, features: frozenset[FeatureId] = frozenset()) -> Room:
    return Room(id=RoomId(number), name=f"Room {number}", capacity=seats, features=features)


def no_room_big_enough() -> Snapshot:
    """Forty students, and the largest room seats ten.

    `model.build` refuses this too, and says so. What the count adds is that it finds
    *every* such session rather than stopping at the first.
    """
    return term(
        sessions=[lecture(1, group=1), lecture(2, group=1)],
        rooms=[room(1, seats=10)],
        sizes={1: 40},
    )


def no_room_with_the_feature() -> Snapshot:
    """A session needing a projector, in an institution that owns none."""
    return term(
        sessions=[lecture(1, group=1, features=frozenset({PROJECTOR}))],
        rooms=[room(1, seats=100)],
        sizes={1: 10},
    )


def capacity_threshold() -> Snapshot:
    """`comp01`'s shape, at eight slots.

    Nine large classes need one of the two rooms that can seat them, and those two rooms
    offer sixteen hours between them — but each class runs two hours, so the large classes
    need eighteen. Every session has its own group and its own instructor, and there are
    plenty of small rooms, so **nothing but the capacity threshold is short**: the global
    room count is comfortable and no person or group is over-committed.
    """
    return term(
        sessions=[lecture(n, group=n, instructor=n, duration=2) for n in range(1, 10)],
        rooms=[room(1, seats=60), room(2, seats=60), *(room(n, seats=5) for n in range(3, 20))],
        sizes=dict.fromkeys(range(1, 10), 50),
    )


def more_sessions_than_room_periods() -> Snapshot:
    """Nine hours of teaching, one room, eight hours in the week.

    Nothing narrows the room set — every session fits every room — so the rule that has to
    give is the one that says a room holds one thing at a time.
    """
    return term(
        sessions=[lecture(n, group=n, instructor=n) for n in range(1, 10)],
        rooms=[room(1, seats=100)],
        sizes=dict.fromkeys(range(1, 10), 10),
    )


def instructor_away_most_of_the_week() -> Snapshot:
    """P7's headline case: three classes, and the person is in on Monday morning.

    Two hours of availability against three hours of teaching. The rule named is
    availability, because that is what bounds the supply — with the week open the same
    three classes fit easily.
    """
    return term(
        sessions=[lecture(n, group=n, instructor=1) for n in range(1, 4)],
        rooms=[room(n, seats=100) for n in range(1, 4)],
        sizes=dict.fromkeys(range(1, 4), 10),
        unavailability=[
            Unavailability(instructor_id=InstructorId(1), slot=slot) for slot in range(2, WEEK)
        ],
    )


def instructor_away_all_week() -> Snapshot:
    """The same person, marked unavailable for every hour there is.

    Ordinary data entry: somebody is blocked out for a semester and never unblocked. The
    arithmetic is the same as a room shut all week — a supply of zero — and the *sentence* is
    not, which is what this term exists to catch. The rooms here are open every hour.
    """
    return term(
        sessions=[lecture(1, group=1, instructor=1)],
        rooms=[room(1, seats=100)],
        sizes={1: 10},
        unavailability=[
            Unavailability(instructor_id=InstructorId(1), slot=slot) for slot in range(WEEK)
        ],
    )


def instructor_teaching_more_than_the_week() -> Snapshot:
    """Nine hours of teaching for one person, in a week eight hours long.

    No unavailability anywhere, so nothing has been *said* about when they are free —
    the week itself is the bound, and the rule is that one person teaches one class.
    """
    return term(
        sessions=[lecture(n, group=n, instructor=1) for n in range(1, 10)],
        rooms=[room(n, seats=100) for n in range(1, 10)],
        sizes=dict.fromkeys(range(1, 10), 10),
    )


def group_attending_more_than_the_week() -> Snapshot:
    """The same from the students' side: nine classes for one group, eight hours to attend."""
    return term(
        sessions=[lecture(n, group=1, instructor=n) for n in range(1, 10)],
        rooms=[room(n, seats=100) for n in range(1, 10)],
        sizes={1: 10},
    )


def two_thresholds_short_by_different_amounts() -> Snapshot:
    """Short at two capacities at once, and the worse one is the one reported.

    Six two-hour classes of a hundred need the single room that seats them, which offers
    eight hours — short by four. Drop the threshold to fifty and both rooms are in play,
    sixteen hours against seventeen — short by one. Both are true; a panel listing them both
    would be telling somebody the same problem twice at two levels of detail, so the sweep
    keeps the deeper one.
    """
    return term(
        sessions=[
            *(lecture(n, group=n, instructor=n, duration=2) for n in range(1, 7)),
            *(lecture(n, group=n, instructor=n) for n in range(7, 12)),
        ],
        rooms=[room(1, seats=100), room(2, seats=50)],
        sizes={**dict.fromkeys(range(1, 7), 100), **dict.fromkeys(range(7, 12), 50)},
    )


#: The same week with the third hour of each day given over to lunch: eight slots, six of
#: them teachable.
WITH_LUNCH = TimeGrid(
    days=2, slots_per_day=4, slot_minutes=60, day_start_minute=9 * 60, break_slots=frozenset({2})
)


def short_only_once_lunch_is_taken_out() -> Snapshot:
    """Seven hours of teaching, one room, and a week that is eight hours long — but six of
    them teachable.

    Nothing can be scheduled during a break (`breaks_protected`), so a room supplies its
    teaching slots and not its slots. Counted the lazy way this term has an hour to spare;
    counted correctly it is an hour short, and the difference is the whole reason the supply
    is measured in teaching slots.
    """
    return term(
        sessions=[lecture(n, group=n, instructor=n) for n in range(1, 8)],
        rooms=[room(1, seats=100)],
        sizes=dict.fromkeys(range(1, 8), 10),
        grid=WITH_LUNCH,
    )


def an_institution_with_no_rooms() -> Snapshot:
    """A term whose sessions want a projector and whose institution owns no rooms at all.

    Degenerate, and reachable: a project is created before anything is entered into it, and
    P7's pre-flight runs on whatever is there. Every session is unplaceable and the estate
    has nothing to count.
    """
    return term(
        sessions=[lecture(1, group=1, features=frozenset({PROJECTOR}))],
        rooms=[],
        sizes={1: 10},
    )


def one_instructor_pinned_into_two_rooms() -> Snapshot:
    """Two classes, one person, both pinned to nine o'clock in different rooms.

    **Nothing here is short of anything**, which is the point: two rooms, two hours of
    teaching, a week of eight. No count sees it, and the pin check does not either — it looks
    for two pins fighting over one *room*. Only the search can find it, and only the conflict
    set can say what it found.
    """
    base = term(
        sessions=[lecture(1, group=1, instructor=1), lecture(2, group=2, instructor=1)],
        rooms=[room(1, seats=100), room(2, seats=100)],
        sizes={1: 10, 2: 10},
    )
    return Snapshot.of(
        grid=base.grid,
        sessions=list(base.sessions.values()),
        rooms=list(base.rooms.values()),
        groups=base.groups,
        assignments=[
            Assignment(
                id=AssignmentId(1),
                session_id=SessionId(1),
                start_slot=0,
                room_id=RoomId(1),
                is_pinned=True,
            ),
            Assignment(
                id=AssignmentId(2),
                session_id=SessionId(2),
                start_slot=0,
                room_id=RoomId(2),
                is_pinned=True,
            ),
        ],
    )


def two_pins_in_one_room() -> Snapshot:
    """The case the builder refuses before a model exists, naming both sessions and the room.

    Kept because it is the one path where `model.build` is a *better* explanation than any
    conflict set: it says which two sessions and which room, where a core would say
    `room_not_double_booked` and leave the reader to find them.
    """
    base = term(
        sessions=[lecture(1, group=1), lecture(2, group=2)],
        rooms=[room(1, seats=100), room(2, seats=100)],
        sizes={1: 10, 2: 10},
    )
    return Snapshot.of(
        grid=base.grid,
        sessions=list(base.sessions.values()),
        rooms=list(base.rooms.values()),
        groups=base.groups,
        assignments=[
            Assignment(
                id=AssignmentId(n),
                session_id=SessionId(n),
                start_slot=0,
                room_id=RoomId(1),
                is_pinned=True,
            )
            for n in (1, 2)
        ],
    )


def rules_that_contradict_each_other() -> Snapshot:
    """Two sessions asked to be on the same day and on different days, both rules hard.

    A conflict between rows of the rules screen rather than between a term and its building,
    and the explanation has to name the rows: an institution with a dozen hard rules needs to
    be told which two, and it is a single row it would edit.
    """
    base = term(
        sessions=[lecture(1, group=1), lecture(2, group=2)],
        rooms=[room(1, seats=100), room(2, seats=100)],
        sizes={1: 10, 2: 10},
    )
    return Snapshot.of(
        grid=base.grid,
        sessions=list(base.sessions.values()),
        rooms=list(base.rooms.values()),
        groups=base.groups,
        constraints=[
            Constraint(
                id=ConstraintId(7),
                kind=ConstraintKind.SAME_DAY,
                is_hard=True,
                weight=0,
                targets=frozenset(ConstraintTarget(kind=TargetKind.SESSION, id=n) for n in (1, 2)),
            ),
            Constraint(
                id=ConstraintId(8),
                kind=ConstraintKind.DIFFERENT_DAY,
                is_hard=True,
                weight=0,
                targets=frozenset(ConstraintTarget(kind=TargetKind.SESSION, id=n) for n in (1, 2)),
            ),
        ],
    )


def the_only_room_is_shut_all_week() -> Snapshot:
    """A room that could hold the class, closed every hour of the week."""
    return term(
        sessions=[lecture(1, group=1)],
        rooms=[room(1, seats=100)],
        sizes={1: 10},
        unavailability=[Unavailability(room_id=RoomId(1), slot=slot) for slot in range(WEEK)],
    )


def alternating_weeks_are_not_a_conflict() -> Snapshot:
    """Sixteen hours for one group, half in odd weeks and half in even.

    **Feasible**, and the reason it is worth a fixture: counted without regard to week
    pattern this term wants sixteen hours out of eight and reads as impossible. It is the
    false positive the whole module is arranged to avoid.
    """
    return term(
        sessions=[
            *(
                lecture(n, group=1, instructor=n, pattern=WeekPattern.ODD_WEEKS)
                for n in range(1, 9)
            ),
            *(
                lecture(n, group=1, instructor=n, pattern=WeekPattern.EVEN_WEEKS)
                for n in range(9, 17)
            ),
        ],
        rooms=[room(n, seats=100) for n in range(1, 3)],
        sizes={1: 10},
    )
