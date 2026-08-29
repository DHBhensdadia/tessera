"""The sixteen rules an institution can set, weighted the way it chose.

`SPECS` has declared these since 1.3 and its docstring says what was always meant to happen
here: *"Adding a rule is an entry here plus an evaluator in 4.1 — no migration, no route, no
schema."* This is the evaluators. `test_every_kind_has_an_evaluator` is what keeps that a fact
rather than an intention.

**Targeted rules are about placements; global preferences are about the term.** A `SAME_ROOM`
over three sessions is broken or kept by where those three sit, and can be answered for a
placement that does not exist yet — which matters, because a targeted rule may be *hard*, and
the drag interface must refuse a drop the solver would refuse. A global preference like
"minimise gaps" is a property of a whole day for a whole group and cannot be attributed to one
placement at all. So the first kind is checked on a move and the second is not, and that split
is not a shortcut: it is the difference between the two questions.

**The score is here, not in the solver.** 4.3 will express these again as CP-SAT objective
terms, and that second expression is deliberate rather than duplication — Phase 0.1 got zero
cost mismatches across 21 instances precisely because the checker and the model were separate
readings. The rule is that this module is the authority for what a finished timetable costs,
and 4.3 must test that its objective agrees.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from itertools import combinations, pairwise

from tessera.domain.constraints import Constraint, ConstraintKind, TargetKind
from tessera.domain.ids import InstructorId, SessionId
from tessera.domain.time_grid import Slot
from tessera.domain.validation.snapshot import Placement, Snapshot
from tessera.domain.validation.violation import Violation


@dataclass(frozen=True, slots=True)
class Lens:
    """What a rule can see: the term as stored, optionally with one session moved.

    The override exists so a move can be checked without rebuilding the placements — copying
    five thousand entries per drag would be correct and would cost exactly the flatness the
    whole design is for. One lookup is redirected; nothing else changes.
    """

    snapshot: Snapshot
    moved: Placement | None = None

    def place(self, session_id: SessionId) -> Placement | None:
        if self.moved is not None and self.moved.session_id == session_id:
            return self.moved
        return self.snapshot.placements.get(session_id)

    def placed(self, session_ids: Iterable[SessionId]) -> list[Placement]:
        """Only the ones that are somewhere.

        A rule about sessions that have not been placed yet has nothing to say. Reporting
        them as violations would make every constraint fire on an empty timetable, which is
        `unplaced`'s job to report and D6's decision not to call a fault.
        """
        found = [self.place(s) for s in session_ids]
        return [p for p in found if p is not None]

    def day(self, placement: Placement) -> int:
        return self.snapshot.grid.day_of(placement.start_slot)

    def hour(self, placement: Placement) -> int:
        return self.snapshot.grid.slot_of_day(placement.start_slot)

    def span(self, placement: Placement) -> tuple[Slot, ...]:
        """The slots a session is taught in — teaching time, not room occupancy.

        A rule about people asks when they are busy, and a room's turnaround is not that.

        **Delegated rather than recomputed.** This started as its own `range(start, start +
        duration)` and disagreed with `Snapshot.teaching` about a session running off the end
        of the week: the snapshot clipped at the last slot, this did not, and a rule counting
        hours in a row therefore counted an hour that does not exist. Found by the property
        test on its first real run. Two spellings of "when is this taught" is one more than
        the codebase can support, so there is now one.
        """
        return self.snapshot.teaching(placement)


Evaluator = Callable[[Constraint, Lens], Iterator[Violation]]


# -- rules over named sessions -----------------------------------------------------


def same_time(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    """Start at the same hour, on whichever day.

    Slot **of day**, not the week-absolute slot. Same-day is a rule of its own, and a person
    who wants both sets both — collapsing them would make `SAME_DAY` unreachable and would
    surprise anybody who has met the same constraint in ITC-2019, where `SameTime` is about
    the hour and `SameDays` about the day.
    """
    yield from _agree_on(constraint, lens, lens.hour, "these do not all start at the same time")


def same_room(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    yield from _agree_on(
        constraint, lens, lambda p: p.room_id, "these are not all in the same room"
    )


def same_day(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    yield from _agree_on(constraint, lens, lens.day, "these are not all on the same day")


def different_day(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    for first, second in _pairs(constraint, lens):
        if lens.day(first) == lens.day(second):
            yield _pair(constraint, first, second, "are on the same day, and should not be")


def not_overlap(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    for first, second in _pairs(constraint, lens):
        if set(lens.span(first)) & set(lens.span(second)):
            yield _pair(constraint, first, second, "run at the same time, and should not")


def precedes(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    """Each session must finish before the next begins, in session-id order.

    **The order is inferred, and that is a gap rather than a design.** `Constraint.targets` is
    a `frozenset`, so the order somebody gave is not stored — where ITC-2019's `Precedence`
    keeps it. Ascending id is the best available reading: sessions are created in order, and
    `occurrence` ascends within a template, so it agrees with intent in the ordinary case of
    "lecture before lab". It will be wrong for a set assembled in some other order, and
    nothing in the data can tell. Recorded in the backlog with this note.
    """
    ordered = sorted(lens.placed(constraint.target_ids), key=lambda p: p.session_id)
    for earlier, later in pairwise(ordered):
        if max(lens.span(earlier)) >= later.start_slot:
            yield _pair(constraint, earlier, later, "are not in the order this rule asks for")


def min_gap(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    wanted = constraint.params["slots"]
    for first, second in _pairs(constraint, lens):
        earlier, later = sorted((first, second), key=lambda p: p.start_slot)
        if later.start_slot - (max(lens.span(earlier)) + 1) < wanted:
            yield _pair(constraint, earlier, later, f"are less than {wanted} hour(s) apart")


def max_days_between(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    placed = lens.placed(constraint.target_ids)
    if len(placed) < 2:
        return
    days = [lens.day(p) for p in placed]
    apart = max(days) - min(days)
    if apart > constraint.params["days"]:
        yield _about(
            constraint,
            min(placed, key=lambda p: p.start_slot),
            f"these are {apart} days apart, more than the {constraint.params['days']} allowed",
            units=apart - constraint.params["days"],
        )


# -- preferences over the whole term -----------------------------------------------


def minimise_group_gaps(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    yield from _gaps(constraint, lens, TargetKind.GROUP)


def minimise_instructor_gaps(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    yield from _gaps(constraint, lens, TargetKind.INSTRUCTOR)


def avoid_same_course_twice_a_day(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    for _course, placements in _per_subject(constraint, lens, TargetKind.COURSE):
        for day, today in _by_day(lens, placements):
            if len(today) > 1:
                yield _about(
                    constraint,
                    today[0],
                    f"this course is taught {len(today)} times on day {day + 1}",
                    units=len(today) - 1,
                )


def respect_instructor_preferences(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    """The hours somebody said they would rather not teach.

    Soft unavailability, which the invariants pass over entirely. Until 2.7b gave those rows
    a `is_hard` flag this kind had no data behind it at all — it existed in the enum and could
    never fire.
    """
    for instructor, placements in _per_subject(constraint, lens, TargetKind.INSTRUCTOR):
        for placement in placements:
            who = InstructorId(instructor)
            cost = sum(
                lens.snapshot.preferred_against.get((who, slot), 0) for slot in lens.span(placement)
            )
            if cost:
                yield _about(
                    constraint,
                    placement,
                    f"this is at an hour instructor {instructor} would rather not teach",
                    units=cost,
                )


def minimise_building_changes(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    for _subject, placements in _per_people(constraint, lens):
        for day, today in _by_day(lens, placements):
            moves = sum(1 for a, b in pairwise(today) if _building(lens, a) != _building(lens, b))
            if moves:
                yield _about(
                    constraint,
                    today[0],
                    f"this means changing building {moves} time(s) on day {day + 1}",
                    units=moves,
                )


def balance_daily_load(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    """How far the heaviest day is above an even share.

    Measured against the even share rather than against the lightest day, so it can reach
    zero. A subject teaching four hours across a five-day week cannot have every day equal;
    scoring `max - min` would leave a floor no weight could reduce, and a preference that
    cannot be satisfied is one that 4.3 could raise the weight of and measure nothing.
    """
    days = lens.snapshot.grid.days
    for _subject, placements in _per_people(constraint, lens):
        load: dict[int, int] = {}
        for placement in placements:
            load[lens.day(placement)] = load.get(lens.day(placement), 0) + len(lens.span(placement))
        total = sum(load.values())
        # The floor is whichever is larger: an even share, or the longest single session —
        # no day can be lighter than a session that has to sit somewhere. Without the second
        # term a subject whose lecture runs longer than its even share is charged a cost no
        # arrangement could remove, and 4.3 could raise the weight and measure nothing.
        longest = max(len(lens.span(p)) for p in placements)
        unavoidable = max(-(-total // days), longest)
        excess = max(load.values()) - unavoidable
        if excess > 0:
            heaviest = max(load, key=lambda d: load[d])
            yield _about(
                constraint,
                next(p for p in placements if lens.day(p) == heaviest),
                f"day {heaviest + 1} is {excess} hour(s) heavier than an even week",
                units=excess,
            )


def prefer_room_stability(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    for _course, placements in _per_subject(constraint, lens, TargetKind.COURSE):
        rooms = {p.room_id for p in placements}
        if len(rooms) > 1:
            yield _about(
                constraint,
                placements[0],
                f"this course is taught in {len(rooms)} different rooms",
                units=len(rooms) - 1,
            )


def limit_consecutive_slots(constraint: Constraint, lens: Lens) -> Iterator[Violation]:
    allowed = constraint.params["slots"]
    for _subject, placements in _per_people(constraint, lens):
        for day, today in _by_day(lens, placements):
            for run in _runs(slot for p in today for slot in lens.span(p)):
                if len(run) > allowed:
                    yield _about(
                        constraint,
                        today[0],
                        f"this is {len(run)} hours in a row on day {day + 1}, "
                        f"more than the {allowed} allowed",
                        units=len(run) - allowed,
                    )


#: One evaluator per kind. The enum is checked against this rather than trusted.
EVALUATORS: dict[ConstraintKind, Evaluator] = {
    ConstraintKind.SAME_TIME: same_time,
    ConstraintKind.SAME_ROOM: same_room,
    ConstraintKind.SAME_DAY: same_day,
    ConstraintKind.DIFFERENT_DAY: different_day,
    ConstraintKind.NOT_OVERLAP: not_overlap,
    ConstraintKind.PRECEDES: precedes,
    ConstraintKind.MIN_GAP: min_gap,
    ConstraintKind.MAX_DAYS_BETWEEN: max_days_between,
    ConstraintKind.MINIMISE_GROUP_GAPS: minimise_group_gaps,
    ConstraintKind.MINIMISE_INSTRUCTOR_GAPS: minimise_instructor_gaps,
    ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY: avoid_same_course_twice_a_day,
    ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES: respect_instructor_preferences,
    ConstraintKind.MINIMISE_BUILDING_CHANGES: minimise_building_changes,
    ConstraintKind.BALANCE_DAILY_LOAD: balance_daily_load,
    ConstraintKind.PREFER_ROOM_STABILITY: prefer_room_stability,
    ConstraintKind.LIMIT_CONSECUTIVE_SLOTS: limit_consecutive_slots,
}

#: The kinds a move can be refused for: anything that could be hard and is about placements.
#:
#: A global preference cannot be hard when it applies to the whole term, and when narrowed it
#: is still a property of a day rather than of one placement. So a drag is checked against the
#: targeted kinds, and the term's preferences are scored afterwards.
ON_A_MOVE = frozenset(
    kind for kind in EVALUATORS if kind.spec.targets == frozenset({TargetKind.SESSION})
)


def violations(lens: Lens) -> Iterator[Violation]:
    """Every rule the term has, applied."""
    for constraint in lens.snapshot.constraints:
        yield from EVALUATORS[constraint.kind](constraint, lens)


def violations_involving(lens: Lens, session_id: SessionId) -> Iterator[Violation]:
    """Only the hard rules that name this session. What a drag has to be refused for.

    Scoped by the `constraints_of_session` index, so a move re-checks a handful of rules
    rather than the term's entire rulebook — the same reason every occupancy check is a
    lookup.
    """
    for constraint in lens.snapshot.constraints_of_session.get(session_id, ()):
        if constraint.is_hard and constraint.kind in ON_A_MOVE:
            yield from EVALUATORS[constraint.kind](constraint, lens)


# -- shared shapes ------------------------------------------------------------------


def _agree_on(
    constraint: Constraint,
    lens: Lens,
    of: Callable[[Placement], int],
    complaint: str,
) -> Iterator[Violation]:
    """Rules of the form "all of these must share X".

    Reported once for the set rather than once per session that differs: a person told four
    times that four sessions disagree has been told one thing.
    """
    placed = lens.placed(constraint.target_ids)
    if len(placed) > 1 and len({of(p) for p in placed}) > 1:
        yield _about(
            constraint,
            min(placed, key=lambda p: p.session_id),
            complaint,
            units=len({of(p) for p in placed}) - 1,
        )


def _pairs(constraint: Constraint, lens: Lens) -> Iterator[tuple[Placement, Placement]]:
    yield from combinations(
        sorted(lens.placed(constraint.target_ids), key=lambda p: p.session_id), 2
    )


def _per_subject(
    constraint: Constraint, lens: Lens, kind: TargetKind
) -> Iterator[tuple[int, list[Placement]]]:
    """Each subject this preference covers, with everything it is involved in, in time order.

    Narrowed to the constraint's targets when it names any, and the whole term otherwise.
    """
    index: dict[int, list[SessionId]] = {
        TargetKind.INSTRUCTOR: lens.snapshot.sessions_of_instructor,
        TargetKind.GROUP: lens.snapshot.sessions_of_group,
        TargetKind.COURSE: lens.snapshot.sessions_of_course,
    }[kind]  # type: ignore[assignment]
    named = lens.snapshot.subjects_named_by(constraint, kind)
    if constraint.targets and not named:
        # Narrowed, but not to anything of this kind. The four rules that apply to both
        # instructors and groups ask for each in turn, and falling back to "everyone" per
        # kind meant a rule aimed at one instructor also charged every group in the term —
        # the exact opposite of narrowing, and silent.
        return
    for subject in named or tuple(sorted(index)):
        placements = sorted(lens.placed(index.get(subject, [])), key=lambda p: p.start_slot)
        if placements:
            yield subject, placements


def _per_people(constraint: Constraint, lens: Lens) -> Iterator[tuple[int, list[Placement]]]:
    """Instructors and groups together, for the four kinds that apply to both."""
    yield from _per_subject(constraint, lens, TargetKind.INSTRUCTOR)
    yield from _per_subject(constraint, lens, TargetKind.GROUP)


def _by_day(lens: Lens, placements: list[Placement]) -> Iterator[tuple[int, list[Placement]]]:
    days: dict[int, list[Placement]] = {}
    for placement in placements:
        days.setdefault(lens.day(placement), []).append(placement)
    for day in sorted(days):
        yield day, days[day]


def _gaps(constraint: Constraint, lens: Lens, kind: TargetKind) -> Iterator[Violation]:
    """Idle hours between the first and last session of a day.

    Breaks do not count. A lunch hour in the middle of a day is not a gap somebody is waiting
    through — it is the timetable working — and counting it would penalise every full day
    equally and tell an institution nothing.
    """
    grid = lens.snapshot.grid
    for _subject, placements in _per_subject(constraint, lens, kind):
        for day, today in _by_day(lens, placements):
            busy = {slot for p in today for slot in lens.span(p)}
            idle = sum(
                1
                for slot in range(min(busy), max(busy) + 1)
                if slot not in busy and not grid.is_break(slot)
            )
            if idle:
                yield _about(
                    constraint,
                    today[0],
                    f"this leaves {idle} idle hour(s) on day {day + 1}",
                    units=idle,
                )


def _runs(slots: Iterable[Slot]) -> Iterator[list[Slot]]:
    """Maximal runs of consecutive slots."""
    run: list[Slot] = []
    for slot in sorted(set(slots)):
        if run and slot != run[-1] + 1:
            yield run
            run = []
        run.append(slot)
    if run:
        yield run


def _building(lens: Lens, placement: Placement) -> int | None:
    room = lens.snapshot.rooms.get(placement.room_id)
    return room.building_id if room else None


def _about(
    constraint: Constraint, placement: Placement, complaint: str, *, units: int = 1
) -> Violation:
    return Violation(
        rule=constraint.kind.value,
        message=f"{constraint.describe()}: {complaint}.",
        session_id=placement.session_id,
        conflicting_assignment_id=placement.assignment_id,
        is_hard=constraint.is_hard,
        units=units,
        weight=constraint.effective_weight,
    )


def _pair(constraint: Constraint, first: Placement, second: Placement, complaint: str) -> Violation:
    return Violation(
        rule=constraint.kind.value,
        message=f"{constraint.describe()}: these two sessions {complaint}.",
        session_id=first.session_id,
        conflicting_session_id=second.session_id,
        conflicting_assignment_id=second.assignment_id,
        is_hard=constraint.is_hard,
        weight=constraint.effective_weight,
    )
