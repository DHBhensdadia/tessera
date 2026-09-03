"""What arithmetic already knows about a term, before any search.

**A solver that cannot prove a term impossible is the ordinary case, not the exception.**
Measured on `comp01`, which #213 proved impossible by counting — 64 lectures need a room
seating 31 or more, two rooms qualify, and the week gives them 60 room-periods — CP-SAT
returns `out_of_time` after thirty seconds under every formulation this project has. It
returns the same on a generated department of 120 sessions and two rooms, where the
shortfall is forty room-periods out of two hundred. So the mechanism P5 plans for 4.6,
`SufficientAssumptionsForInfeasibility()` on UNSAT, never runs on the cases that occur:
there is no UNSAT to read a core out of.

The same facts, counted rather than searched, take about a millisecond. That is what this
module does, and Decision #29 asked for it in August: *failing after two minutes for a
reason detectable in fifty is unacceptable*.

**Every check here is a relaxation, and the direction is load-bearing.** Each one asks
whether some set of sessions could fit into the resource that must hold them, ignoring
every rule about *where* — contiguity, day boundaries, whether two of them clash with each
other. A relaxation that cannot be satisfied proves the real problem cannot be either. The
converse is not true and is never claimed: **this can prove a term impossible and can never
prove one possible.** `Outcome` already draws that line (#205), and silence here means
nothing was proven rather than that all is well.

So every count under-states demand and over-states supply, deliberately:

* a session demands its `duration_slots` and not the room's turnaround on top, because a
  room in use for its turnaround is a fact this argument does not need;
* a room supplies every teaching slot it is not closed in, though a session near the end
  of a day could not start there.

Both make a shortfall harder to find and neither can invent one. A check that reported an
impossibility that was not there would be worse than no check at all — it would refuse a
term somebody could have run, which is the failure `comp01` already shows is possible in
the other direction (#213).
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from itertools import accumulate
from typing import TYPE_CHECKING

from ortools.graph.python import max_flow

from tessera.domain.entities import Room, Session, WeekPattern
from tessera.domain.ids import FeatureId, RoomId, SessionId
from tessera.domain.validation.invariants import KEYS

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from tessera.domain.time_grid import Slot
    from tessera.domain.validation import Snapshot

__all__ = ["Shortfall", "check"]

#: How eligibility was decided, named in the shortfall so a reader knows which argument
#: produced it. The sweep is exact wherever a room's eligibility is a threshold on capacity
#: alone; where features narrow it too the family stops being nested and the flow answers
#: instead. Both are relaxations and neither is stronger — they differ in what they can be
#: *asked*, not in what they prove.
BY_SWEEP = "capacity sweep"
BY_CLASSES = "room classes"
BY_LOAD = "load against availability"

#: What a room offers and a session wants, in the only terms `Room.can_host` reads.
Profile = tuple[int, frozenset[FeatureId], tuple[tuple[int, int], ...]]


@dataclass(frozen=True, slots=True)
class Shortfall:
    """A set of sessions that does not fit in the resource that has to hold it.

    Carries the whole witness rather than a verdict. P7's panel offers *"Show sessions"*
    beside every line, and a count with no way to see what it is counting is the same
    unhelpfulness as "no solution found" with a number attached.
    """

    rule: str
    """The `INVARIANTS` key that would have to be relaxed. Checked against the domain's own
    list, so a shortfall cannot name a rule the rules screen has no sentence for."""

    subject_kind: str
    """`room`, `instructor` or `group` — what `ConflictingRequirement.subject_kind` expects,
    so 4.7 can link the line to the screen that changes it."""

    subject_id: int | None
    """Which one, or `None` where the argument is about the room estate as a whole."""

    sessions: tuple[SessionId, ...]
    """Every session in the witness set, in order. Not a sample: this is what the set *is*,
    and the interface decides how much of it to draw."""

    needed: int
    """Slots those sessions must occupy."""

    available: int
    """Slots the resource can offer them."""

    threshold: int = 0
    """The capacity that selected the witness, where one did. `comp01`'s is **31**, which is
    a number no room in the instance has — the binding threshold is a headcount somebody
    needs, not a capacity somebody built."""

    counted_by: str = BY_LOAD

    week_pattern: WeekPattern = WeekPattern.EVERY_WEEK
    """Which weeks the argument holds in. Sessions in alternating weeks share a room without
    clashing, so the count is made per pattern; `EVERY_WEEK` means the term draws no
    distinction and the shortfall is about all of it."""

    @property
    def short(self) -> int:
        """How many slots the resource is missing. Always positive — a shortfall of zero or
        less is not one, and `check` does not construct it."""
        return self.needed - self.available


@dataclass(frozen=True, slots=True)
class _Term:
    """A term with the two things every count needs worked out once.

    `TimeGrid.teaching_slots` is a property that rebuilds its tuple on every read, and the
    counts below read it once per room, once per instructor and once per session — 19,503
    reads at NFR-9's ceiling, three quarters of the whole check. Nothing here changes what
    is computed; it changes how often.
    """

    snapshot: Snapshot
    week: tuple[Slot, ...]
    seats: Mapping[SessionId, int]
    """How many the session must seat, or zero throughout when capacity is priced."""

    @classmethod
    def of(cls, snapshot: Snapshot, *, capacity_is_priced: bool) -> _Term:
        return cls(
            snapshot=snapshot,
            week=snapshot.grid.teaching_slots,
            seats={
                session_id: 0 if capacity_is_priced else snapshot.headcount(session)
                for session_id, session in snapshot.sessions.items()
            },
        )

    def session(self, session_id: SessionId) -> Session:
        return self.snapshot.sessions[session_id]

    def hours(self, sessions: Sequence[SessionId]) -> int:
        return sum(self.session(s).duration_slots for s in sessions)

    def fits(self, room: Room, session_id: SessionId) -> bool:
        session = self.session(session_id)
        return room.can_host(
            self.seats[session_id], session.required_features, session.required_counts
        )

    def wants(self, session_id: SessionId) -> Profile:
        session = self.session(session_id)
        return (self.seats[session_id], session.required_features, _counts(session.required_counts))

    def supply(self, room_id: RoomId) -> int:
        """Slots this room could hold something in.

        Teaching slots rather than every slot, because a break is schedulable in no room
        (`breaks_protected`), less the ones the room is closed for. Still an over-statement
        — a session cannot start in the last slots of a day — and over-stating supply is the
        safe direction.
        """
        closed = self.snapshot.room_closed
        return sum(1 for slot in self.week if (room_id, slot) not in closed)


def check(snapshot: Snapshot, *, capacity_is_priced: bool = False) -> tuple[Shortfall, ...]:
    """Everything about this term that arithmetic alone refutes, worst first.

    Empty means nothing was proven, which is **not** a statement that a timetable exists.

    `capacity_is_priced` mirrors `Formulation.capacity_is_priced`: when a room too small for
    a session is a cost rather than a refusal, capacity cannot make a term impossible and
    the counts must not pretend otherwise. Without this the benchmark would start reporting
    `comp01` — an ordinary instance under CB-CTT's own rules (#260) — as having no solution,
    and 4.5's twenty-one valid CB-CTT solutions would become twenty.
    """
    term = _Term.of(snapshot, capacity_is_priced=capacity_is_priced)
    stranded = _unplaceable(term)

    # A session no room can hold is named on its own line, and both room counts leave it out
    # of their demand. Keeping it in would restate the same fact as a shortfall of a whole
    # set — vaguer, and it made the two counts disagree: the sweep still carried three
    # unplaceable sessions into the demand at a threshold they could never compete at, while
    # the flow had already dropped them.
    homeless = {shortfall.sessions[0] for shortfall in stranded}
    found = [*stranded, *_rooms(term, homeless), *_people(term)]
    return tuple(sorted(found, key=lambda s: (-s.short, s.subject_kind, s.subject_id or 0)))


def _unplaceable(term: _Term) -> list[Shortfall]:
    """Sessions no room in the institution could hold, named one at a time.

    `model.build` finds these too and raises, which is a slower way to learn it and a
    coarser one — it stops at the first. A term with four unplaceable labs is one problem
    with four instances, and somebody fixing it wants all four.
    """
    open_at_all = {room_id for room_id in term.snapshot.rooms if term.supply(room_id) > 0}
    found: list[Shortfall] = []
    for session_id in sorted(term.snapshot.sessions):
        session = term.session(session_id)
        able = {
            room_id for room_id, room in term.snapshot.rooms.items() if term.fits(room, session_id)
        }
        if able & open_at_all:
            continue
        found.append(
            Shortfall(
                rule=_named(_why_nowhere(session, able)),
                subject_kind="room",
                subject_id=None,
                sessions=(session_id,),
                needed=session.duration_slots,
                available=0,
                threshold=term.seats[session_id],
                counted_by=BY_CLASSES if session.required_features else BY_SWEEP,
            )
        )
    return found


def _why_nowhere(session: Session, able: set[RoomId]) -> str:
    """Which rule leaves this session with nowhere to go.

    **A room that could hold it and is shut all week is a different problem**, and saying
    `room_fits_group` about it sends somebody to look at capacities that are fine. Part 1
    conflated the two; 4.6's core, which reads the same term through CP-SAT, named
    `availability_respected` where the count named capacity, and the core was right.
    """
    if able:
        return "availability_respected"
    if session.required_features or session.required_counts:
        return "room_has_required_features"
    return "room_fits_group"


def _rooms(term: _Term, homeless: set[SessionId]) -> list[Shortfall]:
    """Whether the sessions that have somewhere to go fit into the room-periods at all.

    Two algorithms for one question, chosen by the shape of the term rather than by
    preference. Where a room's eligibility is decided by capacity alone the eligible sets
    are **nested** — a session that fits a room seating a hundred fits every larger room —
    and Hall's condition on a nested family needs testing only at each distinct threshold,
    which is a sorted sweep. Required features break the nesting, because feature sets order
    as a lattice and not as a chain, and then the general transportation argument is what is
    left.

    The difference is not academic. At NFR-9's ceiling on an estate of four hundred distinct
    capacities the flow prototype took 766 ms against P7's budget of fifty.

    Both are handed the same `homeless` set to leave out, and that is not tidiness. They
    were written excluding different things and **disagreed on the second Hypothesis run**:
    a term of four sessions, one room seating one, where the sweep counted three sessions
    that could never enter that room into the demand competing for it. Both verdicts were
    *true* — the term is impossible either way, and `_unplaceable` says so by name — but a
    check with two implementations that answer differently has no defensible answer.
    """
    if _capacity_is_the_only_filter(term):
        return _sweep(term, homeless)
    return _classes(term, homeless)


def _sweep(term: _Term, homeless: set[SessionId]) -> list[Shortfall]:
    """Hall's condition at every headcount somebody actually needs.

    For a threshold *c*: the sessions needing *c* seats or more can only go in rooms seating
    *c* or more, so their total duration cannot exceed what those rooms offer. Both sides
    are prefix sums over sorted lists, so the whole sweep is one pass per week pattern after
    the sort.

    **The thresholds come from headcounts, never from room capacities**, and that is the
    difference between a check and a decoration. `comp01`'s binding threshold is 31, which
    no room in the instance has; keyed on capacities the same argument adds eight
    constraints to the model and proves nothing, and keyed on headcounts it refutes the
    instance in nineteen milliseconds.
    """
    rooms = sorted(term.snapshot.rooms.items(), key=lambda item: -item[1].capacity)
    descending = [-room.capacity for _room_id, room in rooms]
    supplies = [0, *accumulate(term.supply(room_id) for room_id, _room in rooms)]

    worst: dict[WeekPattern, Shortfall] = {}
    for pattern, sessions in _buckets(term):
        ordered = sorted((s for s in sessions if s not in homeless), key=lambda s: -term.seats[s])
        demands = [0, *accumulate(term.session(s).duration_slots for s in ordered)]

        for taken, session_id in enumerate(ordered, start=1):
            seats = term.seats[session_id]
            if taken < len(ordered) and seats == term.seats[ordered[taken]]:
                continue  # mid-threshold: the next session competes for the same rooms
            # At least one room fits every session left here, so the eligible prefix is
            # never empty — the ones with nowhere to go were taken out above.
            eligible = bisect_right(descending, -seats)
            needed, available = demands[taken], supplies[eligible]
            if needed <= available:
                continue
            candidate = Shortfall(
                rule=_named(
                    "room_not_double_booked" if eligible == len(rooms) else "room_fits_group"
                ),
                subject_kind="room",
                subject_id=None,
                sessions=tuple(sorted(ordered[:taken])),
                needed=needed,
                available=available,
                threshold=seats,
                counted_by=BY_SWEEP,
                week_pattern=pattern,
            )
            if pattern not in worst or candidate.short > worst[pattern].short:
                worst[pattern] = candidate

    return list(worst.values())


def _classes(term: _Term, homeless: set[SessionId]) -> list[Shortfall]:
    """The same question as a transportation problem, when features make it one.

    Sessions wanting the same thing are one demand and rooms offering the same thing are one
    supply, which is exact — two sessions with identical requirements are interchangeable in
    an argument that has already given up on *where* — and it is what keeps the graph small:
    a term of five thousand sessions has a few dozen distinct requirements, not five
    thousand.

    The witness is read back from the minimum cut. Its source side holds exactly the demands
    that could not be served, which is Hall's violating set rather than an approximation.
    """
    classes = _room_classes(term)
    profiles = _profiles(term)
    if not classes:
        return []

    found: list[Shortfall] = []
    for pattern, sessions in _buckets(term):
        wanted = set(sessions) - homeless
        demands = [
            (key, kept)
            for key, members in profiles.items()
            if (kept := [s for s in members if s in wanted])
        ]
        if not demands:
            continue
        shortfall = _cut(term, demands, classes, pattern)
        if shortfall is not None:
            found.append(shortfall)
    return found


def _cut(
    term: _Term,
    demands: Sequence[tuple[Profile, list[SessionId]]],
    classes: Sequence[tuple[Room, int]],
    pattern: WeekPattern,
) -> Shortfall | None:
    """Solve one bipartite feasibility question and read its violating set back out."""
    flow = max_flow.SimpleMaxFlow()
    source, sink = 0, 1
    first_class = 2 + len(demands)

    total = 0
    for index, (_profile, members) in enumerate(demands):
        need = term.hours(members)
        total += need
        flow.add_arc_with_capacity(source, 2 + index, need)
        for offset, (room, _supply) in enumerate(classes):
            if term.fits(room, members[0]):
                flow.add_arc_with_capacity(2 + index, first_class + offset, need)
    for offset, (_room, supply) in enumerate(classes):
        flow.add_arc_with_capacity(first_class + offset, sink, supply)

    # `solve` is the one method OR-Tools leaves as `(*args, **kwargs)` in its own stub, so
    # strict mode refuses the call while every other method on this object is annotated.
    status = flow.solve(source, sink)  # type: ignore[no-untyped-call]
    if status != max_flow.SimpleMaxFlow.OPTIMAL:  # pragma: no cover
        raise AssertionError("the room transportation problem has no maximum flow")
    if flow.optimal_flow() >= total:
        return None

    starved = [
        (profile, members)
        for index, (profile, members) in enumerate(demands)
        if 2 + index in set(flow.get_source_side_min_cut())
    ]
    witness = sorted(session for _profile, members in starved for session in members)
    reachable = {
        offset
        for offset, (room, _supply) in enumerate(classes)
        for _profile, members in starved
        if term.fits(room, members[0])
    }
    wants_features = any(
        term.session(members[0]).required_features or term.session(members[0]).required_counts
        for _profile, members in starved
    )
    return Shortfall(
        rule=_named(
            "room_not_double_booked"
            if len(reachable) == len(classes)
            else "room_has_required_features"
            if wants_features
            else "room_fits_group"
        ),
        subject_kind="room",
        subject_id=None,
        sessions=tuple(witness),
        needed=term.hours(witness),
        available=sum(classes[offset][1] for offset in reachable),
        threshold=min((term.seats[s] for s in witness), default=0),
        counted_by=BY_CLASSES,
        week_pattern=pattern,
    )


def _people(term: _Term) -> Iterator[Shortfall]:
    """An instructor with more teaching than hours, and a group with more classes than week.

    The same count as the rooms, against a different resource. An instructor supplies the
    teaching slots they are not marked away for; a student group supplies the whole teaching
    week, because a group has no unavailability to record.
    """
    snapshot = term.snapshot
    week = len(term.week)
    for pattern, sessions in _buckets(term):
        wanted = set(sessions)
        for instructor, taught in sorted(snapshot.sessions_of_instructor.items()):
            away = sum(1 for slot in term.week if (instructor, slot) in snapshot.instructor_away)
            yield from _overloaded(
                term,
                [s for s in taught if s in wanted],
                available=week - away,
                rule="availability_respected" if away else "instructor_not_double_booked",
                subject_kind="instructor",
                subject_id=instructor,
                pattern=pattern,
            )
        for group, attended in sorted(snapshot.sessions_of_group.items()):
            yield from _overloaded(
                term,
                [s for s in attended if s in wanted],
                available=week,
                rule="group_not_double_booked",
                subject_kind="group",
                subject_id=group,
                pattern=pattern,
            )


def _overloaded(
    term: _Term,
    sessions: Sequence[SessionId],
    *,
    available: int,
    rule: str,
    subject_kind: str,
    subject_id: int,
    pattern: WeekPattern,
) -> Iterator[Shortfall]:
    needed = term.hours(sessions)
    if needed <= available:
        return
    yield Shortfall(
        rule=_named(rule),
        subject_kind=subject_kind,
        subject_id=subject_id,
        sessions=tuple(sorted(sessions)),
        needed=needed,
        available=available,
        counted_by=BY_LOAD,
        week_pattern=pattern,
    )


def _buckets(term: _Term) -> list[tuple[WeekPattern, list[SessionId]]]:
    """The session sets whose members pairwise cannot share a slot.

    Two sessions collide only if their week patterns can coincide, so a fortnightly lab in
    odd weeks and one in even weeks are not competing for anything. Counting the whole term
    at once would invent a shortfall between them, which is exactly the false positive this
    module may not produce.

    A term drawing no distinction gets one bucket rather than two identical ones.
    """
    sessions = term.snapshot.sessions
    if all(s.week_pattern is WeekPattern.EVERY_WEEK for s in sessions.values()):
        return [(WeekPattern.EVERY_WEEK, sorted(sessions))]
    return [
        (
            pattern,
            sorted(
                session_id
                for session_id, session in sessions.items()
                if session.week_pattern.coincides_with(pattern)
            ),
        )
        for pattern in (WeekPattern.ODD_WEEKS, WeekPattern.EVEN_WEEKS)
    ]


def _capacity_is_the_only_filter(term: _Term) -> bool:
    """Whether `can_host` reduces to a comparison of two numbers for every session here."""
    return not any(
        session.required_features or session.required_counts
        for session in term.snapshot.sessions.values()
    )


def _profiles(term: _Term) -> dict[Profile, list[SessionId]]:
    """Sessions grouped by what they need of a room. Identical requirements are one demand."""
    found: dict[Profile, list[SessionId]] = defaultdict(list)
    for session_id in sorted(term.snapshot.sessions):
        found[term.wants(session_id)].append(session_id)
    return dict(found)


def _room_classes(term: _Term) -> list[tuple[Room, int]]:
    """Rooms grouped by what they offer, with the slots each group supplies.

    The representative room answers `can_host` for the whole class, which is sound because
    the key is every field `can_host` reads.
    """
    found: dict[Profile, list[RoomId]] = defaultdict(list)
    for room_id, room in sorted(term.snapshot.rooms.items()):
        found[(room.capacity, room.features, _counts(room.feature_counts))].append(room_id)
    return [
        (term.snapshot.rooms[members[0]], sum(term.supply(room_id) for room_id in members))
        for _profile, members in sorted(found.items(), key=lambda item: -item[0][0])
    ]


def _counts(counts: Mapping[FeatureId, int]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted((int(feature), n) for feature, n in counts.items()))


def _named(key: str) -> str:
    """A rule key, checked against the domain's own list at the point of use.

    `invariants.py` guards its evaluators the same way and for the same reason: a shortfall
    naming a key `INVARIANTS` does not declare would render as nothing at all, because the
    rules screen looks the sentence up by it.
    """
    if key not in KEYS:  # pragma: no cover - a typo, caught the first time it is reached
        raise AssertionError(f"{key!r} is not one of the invariants the domain declares")
    return key
