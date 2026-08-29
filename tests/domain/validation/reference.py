"""A second, slower reading of the same rules.

The exit test compares the real validator against this one, and that comparison is worth
exactly as much as the independence of the two. So this is written from the **English** —
`INVARIANTS[*].statement` and `SPECS[*].summary` — by the most obvious route available: nested
loops over every pair, no indexes, no early exits, nothing shared with `domain/validation/`
beyond the domain objects themselves. It is O(n²) on purpose and lives in `tests/` because the
package must never import it.

**What this independence is, and is not.** It is structural: a different algorithm, written
from the sentences rather than transcribed from the implementation, so a mistake in one has to
be reproduced from scratch to hide in the other. It is not two people — Phase 0.1's checker and
solver model were also one author, and that separation still caught real faults across 21
instances, which is the standard being reproduced rather than exceeded. Where the English is
silent — whether a room's turnaround counts as occupancy, whether lunch counts as an idle hour
— this follows the decisions recorded in DECISIONS.md, because the alternative is a reference
that disagrees on a question nobody has answered rather than on a mistake.

Deliberately dull. Every loop here should be the one somebody would write first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import combinations, pairwise

from tessera.domain.constraints import Constraint, ConstraintKind, TargetKind
from tessera.domain.entities import Room, Session, Unavailability
from tessera.domain.groups import GroupSet
from tessera.domain.ids import CourseId, RoomId, SessionId, StudentGroupId
from tessera.domain.time_grid import Slot, TimeGrid
from tessera.domain.timetable import Assignment

#: What a rule does when it is broken: how many units, and about which sessions.
type Hit = Callable[..., None]


@dataclass
class Reading:
    """What one implementation says is wrong, in a form the other can be compared against.

    Not violation objects: the two produce different sentences, and comparing prose would
    test the wording rather than the rules. What is compared is **which rule is broken and
    which sessions it is broken about** — attribution-independent, because the pair is
    unordered — plus the penalty and feasibility.
    """

    facts: set[tuple[str, frozenset[SessionId]]] = field(default_factory=set)
    penalty: int = 0
    feasible: bool = True

    def note(self, rule: str, *sessions: SessionId) -> None:
        self.facts.add((rule, frozenset(sessions)))

    def charge(self, rule: str, units: int, weight: int, *sessions: SessionId) -> None:
        self.facts.add((rule, frozenset(sessions)))
        self.penalty += units * weight


def read(
    *,
    grid: TimeGrid,
    sessions: list[Session],
    rooms: list[Room],
    groups: GroupSet,
    assignments: list[Assignment],
    unavailability: list[Unavailability] | None = None,
    constraints: list[Constraint] | None = None,
    course_of: dict[SessionId, CourseId] | None = None,
) -> Reading:
    """Everything wrong with this timetable, worked out the slow way."""
    unavailability = unavailability or []
    constraints = [c for c in (constraints or []) if c.enabled]
    course_of = course_of or {}

    by_id = {s.id: s for s in sessions if s.id is not None}
    placed = {a.session_id: a for a in assignments if a.session_id in by_id}
    found = Reading()

    _invariants(
        found,
        grid,
        by_id,
        {r.id: r for r in rooms if r.id is not None},
        groups,
        placed,
        unavailability,
    )
    for constraint in constraints:
        _constraint(
            found,
            constraint,
            grid,
            by_id,
            {r.id: r for r in rooms if r.id is not None},
            groups,
            placed,
            unavailability,
            course_of,
        )

    return found


# -- the seven that cannot be switched off ------------------------------------------


def _invariants(
    found: Reading,
    grid: TimeGrid,
    sessions: dict[SessionId, Session],
    rooms: dict[RoomId, Room],
    groups: GroupSet,
    placed: dict[SessionId, Assignment],
    unavailability: list[Unavailability],
) -> None:
    """Read straight off the seven sentences in `INVARIANTS`."""
    for session_id, assignment in placed.items():
        session = sessions[session_id]

        # "Nothing is scheduled during a break, and no session runs through one" — and the
        # grid refuses the other two impossible placements in the same breath.
        if not grid.can_hold(assignment.start_slot, session.duration_slots):
            found.note("breaks_protected", session_id)
            found.feasible = False

        room = rooms.get(assignment.room_id)
        if room is not None:
            # "A room must seat everyone assigned to it."
            if room.capacity < _headcount(groups, session):
                found.note("room_fits_group", session_id)
                found.feasible = False

            # "A room must have every feature a session requires" — including how many.
            enough = all(
                room.feature_counts.get(f, 0) >= n for f, n in session.required_counts.items()
            )
            if not session.required_features <= room.features or not enough:
                found.note("room_has_required_features", session_id)
                found.feasible = False

        # "Nothing is scheduled when a room or an instructor is unavailable."
        for row in unavailability:
            if not row.is_hard:
                continue
            if row.room_id == assignment.room_id and row.slot in _room_slots(
                grid, session, room, assignment
            ):
                found.note("availability_respected", session_id)
                found.feasible = False
            if row.instructor_id in session.instructor_ids and row.slot in _taught(
                grid, session, assignment
            ):
                found.note("availability_respected", session_id)
                found.feasible = False

    # The three "not two at once" rules, over every pair there is.
    for a, b in combinations(sorted(placed), 2):
        first, second = sessions[a], sessions[b]
        if not first.week_pattern.coincides_with(second.week_pattern):
            continue
        one, two = placed[a], placed[b]

        # "No room hosts two sessions at once" — a room being cleared is still in use.
        if one.room_id == two.room_id and _room_slots(
            grid, first, rooms.get(one.room_id), one
        ) & _room_slots(grid, second, rooms.get(two.room_id), two):
            found.note("room_not_double_booked", a, b)
            found.feasible = False

        together = _taught(grid, first, one) & _taught(grid, second, two)
        if not together:
            continue

        # "No instructor teaches two sessions at once."
        if first.instructor_ids & second.instructor_ids:
            found.note("instructor_not_double_booked", a, b)
            found.feasible = False

        # "No student group attends two sessions at once" — through the tree, so an intake
        # and one of its batches count as the same students.
        if any(groups.conflicts(x, y) for x in first.attendee_ids for y in second.attendee_ids):
            found.note("group_not_double_booked", a, b)
            found.feasible = False


def _headcount(groups: GroupSet, session: Session) -> int:
    leaves: set[StudentGroupId] = set()
    for group in session.attendee_ids:
        leaves |= groups.leaves_of(group)
    return sum(groups.headcount(StudentGroupId(leaf)) for leaf in leaves)


def _taught(grid: TimeGrid, session: Session, assignment: Assignment) -> set[Slot]:
    """The slots a session is actually being taught in."""
    return {
        s
        for s in range(assignment.start_slot, assignment.start_slot + session.duration_slots)
        if s < grid.slot_count
    }


def _room_slots(
    grid: TimeGrid, session: Session, room: Room | None, assignment: Assignment
) -> set[Slot]:
    """Teaching plus the time the room takes to clear.

    The sentence says a room must not host two sessions at once, and `Room.turnaround_slots`
    says what "clear the room before the next class" means — so a room being cleared is still
    hosting. #190 settled the same question the other way for people, who have left.
    """
    length = session.duration_slots + (room.turnaround_slots if room else 0)
    start = assignment.start_slot
    return {s for s in range(start, start + length) if s < grid.slot_count}


# -- the sixteen an institution can set ---------------------------------------------


def _constraint(
    found: Reading,
    constraint: Constraint,
    grid: TimeGrid,
    sessions: dict[SessionId, Session],
    rooms: dict[RoomId, Room],
    groups: GroupSet,
    placed: dict[SessionId, Assignment],
    unavailability: list[Unavailability],
    course_of: dict[SessionId, CourseId],
) -> None:
    kind = constraint.kind
    weight = constraint.effective_weight
    rule = kind.value

    def hit(units: int, *involved: SessionId) -> None:
        if constraint.is_hard:
            found.note(rule, *involved)
            found.feasible = False
        else:
            found.charge(rule, units, weight, *involved)

    named = sorted(s for s in constraint.target_ids if s in placed)

    if kind is ConstraintKind.SAME_TIME:
        _all_share(hit, named, lambda s: grid.slot_of_day(placed[s].start_slot))
    elif kind is ConstraintKind.SAME_ROOM:
        _all_share(hit, named, lambda s: placed[s].room_id)
    elif kind is ConstraintKind.SAME_DAY:
        _all_share(hit, named, lambda s: grid.day_of(placed[s].start_slot))
    elif kind is ConstraintKind.DIFFERENT_DAY:
        for a, b in combinations(named, 2):
            if grid.day_of(placed[a].start_slot) == grid.day_of(placed[b].start_slot):
                hit(1, a, b)
    elif kind is ConstraintKind.NOT_OVERLAP:
        for a, b in combinations(named, 2):
            if _taught(grid, sessions[a], placed[a]) & _taught(grid, sessions[b], placed[b]):
                hit(1, a, b)
    elif kind is ConstraintKind.PRECEDES:
        for a, b in pairwise(named):
            if max(_taught(grid, sessions[a], placed[a])) >= placed[b].start_slot:
                hit(1, a, b)
    elif kind is ConstraintKind.MIN_GAP:
        for a, b in combinations(named, 2):
            earlier, later = sorted((a, b), key=lambda s: placed[s].start_slot)
            gap = (
                placed[later].start_slot
                - max(_taught(grid, sessions[earlier], placed[earlier]))
                - 1
            )
            if gap < constraint.params["slots"]:
                hit(1, earlier, later)
    elif kind is ConstraintKind.MAX_DAYS_BETWEEN:
        if len(named) >= 2:
            days = [grid.day_of(placed[s].start_slot) for s in named]
            over = (max(days) - min(days)) - constraint.params["days"]
            if over > 0:
                hit(over, min(named, key=lambda s: placed[s].start_slot))
    else:
        _preference(
            hit, constraint, grid, sessions, rooms, groups, placed, unavailability, course_of
        )


def _all_share(hit: Hit, named: list[SessionId], of: Callable[[SessionId], object]) -> None:
    if len(named) > 1:
        distinct = {of(s) for s in named}
        if len(distinct) > 1:
            hit(len(distinct) - 1, min(named))


def _preference(
    hit: Hit,
    constraint: Constraint,
    grid: TimeGrid,
    sessions: dict[SessionId, Session],
    rooms: dict[RoomId, Room],
    groups: GroupSet,
    placed: dict[SessionId, Assignment],
    unavailability: list[Unavailability],
    course_of: dict[SessionId, CourseId],
) -> None:
    """The eight that are about the term rather than about named sessions."""
    kind = constraint.kind
    for subject_kind in _subject_kinds(kind):
        for subject, mine in _for_each_subject(
            constraint, subject_kind, sessions, groups, placed, course_of
        ):
            if not mine:
                continue
            if kind is ConstraintKind.PREFER_ROOM_STABILITY:
                distinct = {placed[s].room_id for s in mine}
                if len(distinct) > 1:
                    hit(len(distinct) - 1, min(mine))
            elif kind is ConstraintKind.BALANCE_DAILY_LOAD:
                # Clipped at the end of the week, like every other span here: teaching that
                # would happen outside the week is not teaching. Using the declared duration
                # instead made this line disagree with `_taught` two functions away.
                load: dict[int, int] = {}
                for s in mine:
                    day = grid.day_of(placed[s].start_slot)
                    load[day] = load.get(day, 0) + len(_taught(grid, sessions[s], placed[s]))
                total = sum(load.values())
                longest = max(len(_taught(grid, sessions[s], placed[s])) for s in mine)
                floor = max(-(-total // grid.days), longest)
                if max(load.values()) > floor:
                    heaviest = max(load, key=lambda d: load[d])
                    hit(
                        max(load.values()) - floor,
                        min(s for s in mine if grid.day_of(placed[s].start_slot) == heaviest),
                    )
            elif kind is ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES:
                for s in mine:
                    cost = sum(
                        row.weight
                        for row in unavailability
                        if not row.is_hard
                        and row.instructor_id == subject
                        and row.slot in _taught(grid, sessions[s], placed[s])
                    )
                    if cost:
                        hit(cost, s)
            else:
                _per_day(hit, constraint, grid, sessions, rooms, placed, mine)


def _per_day(
    hit: Hit,
    constraint: Constraint,
    grid: TimeGrid,
    sessions: dict[SessionId, Session],
    rooms: dict[RoomId, Room],
    placed: dict[SessionId, Assignment],
    mine: list[SessionId],
) -> None:
    kind = constraint.kind
    days: dict[int, list[SessionId]] = {}
    for s in mine:
        days.setdefault(grid.day_of(placed[s].start_slot), []).append(s)

    for day in sorted(days):
        today = sorted(days[day], key=lambda s: placed[s].start_slot)
        if kind is ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY:
            if len(today) > 1:
                hit(len(today) - 1, today[0])
        elif kind is ConstraintKind.MINIMISE_BUILDING_CHANGES:
            moves = sum(
                1
                for a, b in pairwise(today)
                if _building(rooms, placed[a].room_id) != _building(rooms, placed[b].room_id)
            )
            if moves:
                hit(moves, today[0])
        else:
            busy = {s for x in today for s in _taught(grid, sessions[x], placed[x])}
            if kind in (
                ConstraintKind.MINIMISE_GROUP_GAPS,
                ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
            ):
                idle = sum(
                    1
                    for slot in range(min(busy), max(busy) + 1)
                    if slot not in busy and not grid.is_break(slot)
                )
                if idle:
                    hit(idle, today[0])
            elif kind is ConstraintKind.LIMIT_CONSECUTIVE_SLOTS:
                allowed = constraint.params["slots"]
                run = 0
                for slot in range(min(busy), max(busy) + 2):
                    if slot in busy:
                        run += 1
                    else:
                        if run > allowed:
                            hit(run - allowed, today[0])
                        run = 0


def _subject_kinds(kind: ConstraintKind) -> list[TargetKind]:
    return sorted(kind.spec.targets, key=lambda t: t.value)


def _for_each_subject(
    constraint: Constraint,
    subject_kind: TargetKind,
    sessions: dict[SessionId, Session],
    groups: GroupSet,
    placed: dict[SessionId, Assignment],
    course_of: dict[SessionId, CourseId],
) -> Iterator[tuple[int, list[SessionId]]]:
    named = {t.id for t in constraint.targets if t.kind is subject_kind}
    if constraint.targets and not named:
        return

    everyone: dict[int, list[SessionId]] = {}
    for session_id, session in sessions.items():
        if session_id not in placed:
            continue
        if subject_kind is TargetKind.INSTRUCTOR:
            keys: set[int] = set(session.instructor_ids)
        elif subject_kind is TargetKind.GROUP:
            keys = {leaf for g in session.attendee_ids for leaf in groups.leaves_of(g)}
        else:
            course = course_of.get(session_id)
            keys = {course} if course is not None else set()
        for key in keys:
            everyone.setdefault(key, []).append(session_id)

    for subject in sorted(everyone):
        if named and subject not in named:
            continue
        yield subject, everyone[subject]


def _building(rooms: dict[RoomId, Room], room_id: RoomId) -> int | None:
    room = rooms.get(room_id)
    return room.building_id if room else None
