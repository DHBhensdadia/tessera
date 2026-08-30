"""Random institutions, and random timetables for them.

Small on purpose — a handful of sessions, rooms and groups. The reference is O(n²) and
Hypothesis shrinks a failure toward the smallest instance that still shows it, so a strategy
producing hundreds of sessions would be slow to run and useless to read.

The point is **variety, not size**. What has to vary is the shapes that produce disagreement:
overlapping placements, week patterns that do and do not coincide, groups nested so a parent
and child collide, rooms with turnaround, sessions that run past the end of a day or into a
break, and constraints of every kind pointed at whatever happens to exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import strategies as st

from tessera.domain.constraints import Constraint, ConstraintKind, ConstraintTarget, TargetKind
from tessera.domain.entities import Room, Session, SessionKind, Unavailability, WeekPattern
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import (
    AssignmentId,
    BuildingId,
    CourseId,
    FeatureId,
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.domain.timetable import Assignment

#: One feature, so "the room lacks what this needs" is reachable without a large catalogue.
PROJECTOR = FeatureId(1)


@dataclass(frozen=True)
class Instance:
    """Everything both implementations are given."""

    grid: TimeGrid
    sessions: list[Session]
    rooms: list[Room]
    groups: GroupSet
    assignments: list[Assignment]
    unavailability: list[Unavailability]
    constraints: list[Constraint]
    course_of: dict[SessionId, CourseId]


@st.composite
def instances(
    draw: st.DrawFn,
    kinds: frozenset[ConstraintKind] | None = None,
    least_rules: int = 0,
    least_sessions: int = 1,
    least_targets: int = 1,
) -> Instance:
    """A whole institution, and a timetable for some of it.

    The four keywords narrow what a caller gets, and every one of them exists because a test
    was measured to be running on nothing. 4.3 asks for rules of the kinds it can score
    (`kinds`), at least one of them (`least_rules`), enough sessions for a rule about two
    sessions to have two (`least_sessions`), and rules that actually name two
    (`least_targets`) — without which a rule over one session is silence, and the agreement
    it then tests is between two implementations that both said nothing.
    """
    days = draw(st.integers(min_value=2, max_value=3))
    slots_per_day = draw(st.integers(min_value=4, max_value=6))
    # A break somewhere in the middle, sometimes, so "no session runs through one" is
    # reachable without every generated day being unusable.
    breaks = draw(st.sampled_from([frozenset(), frozenset({2})]))
    grid = TimeGrid(
        days=days,
        slots_per_day=slots_per_day,
        slot_minutes=60,
        day_start_minute=9 * 60,
        break_slots=breaks,
    )

    # A parent with two batches, so a lecture to the parent and a lab to a batch collide
    # through the tree rather than by naming the same group.
    groups = GroupSet(
        [
            StudentGroup(id=StudentGroupId(1), name="Year", size=0, kind=GroupKind.STRUCTURAL),
            StudentGroup(
                id=StudentGroupId(2),
                name="A",
                size=draw(st.integers(min_value=1, max_value=40)),
                parent_id=StudentGroupId(1),
            ),
            StudentGroup(
                id=StudentGroupId(3),
                name="B",
                size=draw(st.integers(min_value=1, max_value=40)),
                parent_id=StudentGroupId(1),
            ),
        ]
    )

    rooms = [
        Room(
            id=RoomId(i),
            name=f"Room {i}",
            capacity=draw(st.integers(min_value=0, max_value=60)),
            features=draw(st.sampled_from([frozenset(), frozenset({PROJECTOR})])),
            turnaround_slots=draw(st.integers(min_value=0, max_value=1)),
            building_id=BuildingId(draw(st.integers(min_value=1, max_value=2))),
        )
        for i in range(1, draw(st.integers(min_value=1, max_value=3)) + 1)
    ]

    how_many = draw(st.integers(min_value=least_sessions, max_value=max(5, least_sessions)))
    sessions = [
        Session(
            id=SessionId(i),
            kind=SessionKind.LECTURE,
            duration_slots=draw(st.integers(min_value=1, max_value=3)),
            attendee_ids=frozenset(
                {draw(st.sampled_from([StudentGroupId(1), StudentGroupId(2), StudentGroupId(3)]))}
            ),
            instructor_ids=frozenset(
                draw(st.sets(st.sampled_from([InstructorId(1), InstructorId(2)]), max_size=2))
            ),
            required_features=draw(st.sampled_from([frozenset(), frozenset({PROJECTOR})])),
            week_pattern=draw(st.sampled_from(list(WeekPattern))),
        )
        for i in range(1, how_many + 1)
    ]

    # Not every session is placed: an unplaced one is incompleteness rather than a fault, and
    # both implementations have to agree about saying nothing.
    # Biased heavily toward placing. An unplaced session is a fault-free state, and a
    # generator that mostly produced empty timetables would compare "nothing wrong" with
    # "nothing wrong" a thousand times and prove nothing.
    placed = [
        s.id
        for s in sessions
        if s.id is not None and draw(st.integers(min_value=0, max_value=4)) > 0
    ]
    assignments = [
        Assignment(
            id=AssignmentId(n),
            session_id=session_id,
            # Deliberately allowed to run off the end of a day, which is a violation rather
            # than an impossible input.
            start_slot=draw(st.integers(min_value=0, max_value=grid.slot_count - 1)),
            room_id=RoomId(draw(st.sampled_from([r.id for r in rooms if r.id is not None]))),
        )
        for n, session_id in enumerate(placed, start=1)
    ]

    # One row per subject and slot, because that is what the repository can hold: the
    # unavailability table is unique on (term, subject, slot) and `block_slots` treats
    # re-blocking as a no-op. Generating duplicates would test behaviour on input the
    # database refuses — and it did, briefly, with the two implementations disagreeing about
    # whether two soft rows for one hour cost once or twice.
    rows = draw(
        st.lists(
            st.tuples(
                st.sampled_from(["room", "instructor"]),
                st.integers(min_value=1, max_value=2),
                st.integers(min_value=0, max_value=grid.slot_count - 1),
                st.booleans(),
                st.integers(min_value=1, max_value=3),
            ),
            max_size=3,
            unique_by=lambda row: row[:3],
        )
    )
    unavailability = [
        Unavailability(
            room_id=RoomId(subject) if kind == "room" and subject <= len(rooms) else None,
            instructor_id=InstructorId(subject) if kind == "instructor" else None,
            slot=slot,
            is_hard=hard,
            weight=weight,
        )
        for kind, subject, slot, hard, weight in rows
        if kind == "instructor" or subject <= len(rooms)
    ]

    course_of = {
        s.id: CourseId(draw(st.integers(min_value=1, max_value=2)))
        for s in sessions
        if s.id is not None
    }

    # At most one rule per kind. A violation carries the *kind* it broke, not which
    # constraint raised it, so two rules of one kind are indistinguishable in the output —
    # which makes "did the move check consider this rule?" unanswerable. Multiplicity is
    # covered by `test_the_breakdown_is_by_kind_not_by_rule` instead.
    constraints = draw(
        st.lists(
            _constraints(sessions, course_of, kinds, least_targets),
            min_size=least_rules,
            max_size=max(3, least_rules),
            unique_by=lambda c: c.kind,
        )
    )

    return Instance(
        grid=grid,
        sessions=sessions,
        rooms=rooms,
        groups=groups,
        assignments=assignments,
        unavailability=unavailability,
        constraints=constraints,
        course_of=course_of,
    )


@st.composite
def _constraints(
    draw: st.DrawFn,
    sessions: list[Session],
    course_of: dict[SessionId, CourseId],
    kinds: frozenset[ConstraintKind] | None = None,
    least_targets: int = 1,
) -> Constraint:
    """One rule of any kind, pointed at whatever this instance happens to contain."""
    kind = draw(st.sampled_from(sorted(kinds or set(ConstraintKind))))
    spec = kind.spec
    target_kind = draw(st.sampled_from(sorted(spec.targets, key=lambda t: t.value)))

    if target_kind is TargetKind.SESSION:
        available = [s.id for s in sessions if s.id is not None]
        chosen = draw(
            st.lists(
                st.sampled_from(available),
                min_size=min(least_targets, len(available)),
                max_size=3,
                unique=True,
            )
        )
    elif target_kind is TargetKind.COURSE:
        chosen = draw(
            st.lists(st.sampled_from(sorted(set(course_of.values()))), max_size=2, unique=True)
        )
    elif target_kind is TargetKind.INSTRUCTOR:
        chosen = draw(st.lists(st.sampled_from([1, 2]), max_size=2, unique=True))
    else:
        chosen = draw(st.lists(st.sampled_from([1, 2, 3]), max_size=2, unique=True))

    params = {
        name: draw(st.integers(min_value=p.minimum, max_value=min(p.maximum, 4)))
        for name, p in spec.params.items()
    }

    return Constraint(
        kind=kind,
        # A term-wide preference cannot be hard, and the domain refuses it — so hardness is
        # only offered where the rule names something.
        is_hard=bool(chosen) and draw(st.booleans()),
        weight=draw(st.integers(min_value=0, max_value=4)),
        targets=frozenset(ConstraintTarget(kind=target_kind, id=i) for i in chosen),
        params=params,
    )
