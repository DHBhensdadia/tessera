"""Everything a rule needs to read, indexed once.

**The indexes are the whole point.** Phase 0.2 measured `validate-move` at 0.676 ms p99 at
department scale and 0.514 ms at ten times the sessions — flat, because every occupancy check
is a dict lookup rather than a scan. A validator that scanned all sessions would be O(n) and
would still pass a 16 ms budget at department scale, failing only for the largest institutions:
the defect that appears solely for the people least able to absorb it. So the shape here is not
an optimisation, it is the requirement.

**Immutable, and built once.** `tessera/domain/` may not import SQLAlchemy, so a rule could not
query a database even if it wanted to; the repository builds one of these and hands it over.
That constraint is also what makes a test able to build a whole institution by hand with no
engine running.

Nothing here decides whether anything is *wrong*. This is the state; `invariants.py` reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tessera.domain.constraints import Constraint, TargetKind
from tessera.domain.entities import Room, Session, Unavailability, WeekPattern
from tessera.domain.groups import GroupSet
from tessera.domain.ids import (
    AssignmentId,
    CourseId,
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import Slot, TimeGrid
from tessera.domain.timetable import Assignment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


#: `(slot, subject)` to the sessions occupying it.
#:
#: Keyed by a plain `int` rather than by `RoomId` / `InstructorId` / `StudentGroupId`, because
#: `dict` is invariant in its key and one shared type is what lets the three indexes share the
#: lookup that filters them. Nothing is lost: **the dict you look in is the discriminator**, and
#: the methods that reach them still take the specific id type, so a `RoomId` cannot be passed
#: where an `InstructorId` belongs.
type Index = dict[tuple[Slot, int], list[SessionId]]


@dataclass(frozen=True, slots=True)
class Placement:
    """One session, at one time, in one room — real or hypothetical.

    The same type answers both questions the validator is asked. A stored assignment becomes
    one of these, and so does the cell a drag is hovering over; the rules cannot tell the
    difference and must not be able to, or the interface would be checking something subtly
    different from what the solver checks.
    """

    session_id: SessionId
    start_slot: Slot
    room_id: RoomId
    assignment_id: AssignmentId | None = None

    @classmethod
    def of(cls, assignment: Assignment) -> Placement:
        return cls(
            session_id=assignment.session_id,
            start_slot=assignment.start_slot,
            room_id=assignment.room_id,
            assignment_id=assignment.id,
        )


@dataclass(frozen=True)
class Snapshot:
    """A term's timetable and everything needed to judge it.

    Built through `Snapshot.of`, which is where the indexes are computed. The fields are
    public because rules read them; nothing mutates them, and `frozen=True` is the reminder
    rather than the enforcement.
    """

    grid: TimeGrid
    sessions: dict[SessionId, Session]
    rooms: dict[RoomId, Room]
    groups: GroupSet
    placements: dict[SessionId, Placement]

    #: `(slot, room)` to the session occupying it. One session, because two is the violation.
    by_room: Index = field(default_factory=dict)

    #: `(slot, instructor)` to the sessions they are teaching then.
    by_instructor: Index = field(default_factory=dict)

    #: `(slot, leaf group)` to the sessions those students are attending then.
    #:
    #: Keyed by **leaf** rather than by the group a session names. Two sessions clash when they
    #: share a student, and `GroupSet` already resolves that to a shared structural leaf — so
    #: indexing leaves turns "do these groups conflict?" from an intersection into a lookup.
    #: A lecture to "Year 1" and a lab to "Year 1 Batch A" collide, and this is what sees it.
    by_group: Index = field(default_factory=dict)

    #: Slots a room or instructor cannot be used in. Hard rows only — a soft one is a
    #: preference, and preferences are scored in part 2 rather than forbidden here.
    room_closed: frozenset[tuple[RoomId, Slot]] = frozenset()
    instructor_away: frozenset[tuple[InstructorId, Slot]] = frozenset()

    #: Slots somebody would rather not use, and what ignoring that costs.
    #:
    #: Soft rows, which the invariants ignore entirely — *would rather not* is not *cannot*,
    #: and a validator treating them alike would make every stated preference an
    #: impossibility. `RESPECT_INSTRUCTOR_PREFERENCES` is what reads them, and until 2.7b
    #: gave them somewhere to live that kind had no data behind it at all.
    preferred_against: dict[tuple[InstructorId, Slot], int] = field(default_factory=dict)

    #: The rules this term has, and what each is worth.
    constraints: tuple[Constraint, ...] = ()

    #: Which course a session belongs to. Sessions know their offering, not their course, and
    #: two kinds need the course — so the mapping is supplied rather than guessed at.
    course_of: dict[SessionId, CourseId] = field(default_factory=dict)

    #: Every session a subject is involved in. Global preferences are per subject per day, so
    #: they start here rather than by filtering all sessions once per subject.
    sessions_of_instructor: dict[InstructorId, list[SessionId]] = field(default_factory=dict)
    sessions_of_group: dict[StudentGroupId, list[SessionId]] = field(default_factory=dict)
    sessions_of_course: dict[CourseId, list[SessionId]] = field(default_factory=dict)

    #: Constraints naming a session, so a move re-checks only what could involve it.
    constraints_of_session: dict[SessionId, list[Constraint]] = field(default_factory=dict)

    #: Why a slot is blocked, where somebody said. Keyed by subject and slot — *"the labs
    #: are being refurbished"* belongs in the sentence a person reads, not in the rule.
    closure_reason: dict[tuple[str, int, Slot], str] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        *,
        grid: TimeGrid,
        sessions: Sequence[Session],
        rooms: Sequence[Room],
        groups: GroupSet,
        assignments: Sequence[Assignment] = (),
        unavailability: Sequence[Unavailability] = (),
        constraints: Sequence[Constraint] = (),
        course_of: Mapping[SessionId, CourseId] | None = None,
    ) -> Snapshot:
        """Index a term. Everything expensive happens here and only here."""
        by_id = {s.id: s for s in sessions if s.id is not None}
        placements = {a.session_id: Placement.of(a) for a in assignments if a.session_id in by_id}

        snapshot = cls(
            grid=grid,
            sessions=by_id,
            rooms={r.id: r for r in rooms if r.id is not None},
            groups=groups,
            placements=placements,
            room_closed=frozenset(
                (u.room_id, u.slot) for u in unavailability if u.is_hard and u.room_id is not None
            ),
            instructor_away=frozenset(
                (u.instructor_id, u.slot)
                for u in unavailability
                if u.is_hard and u.instructor_id is not None
            ),
            closure_reason={
                _subject(u): u.reason for u in unavailability if u.is_hard and u.reason
            },
            preferred_against={
                (u.instructor_id, u.slot): u.weight
                for u in unavailability
                if not u.is_hard and u.instructor_id is not None
            },
            constraints=tuple(c for c in constraints if c.enabled),
            course_of=dict(course_of or {}),
        )
        snapshot._relate()
        for placement in placements.values():
            snapshot._index(placement)
        return snapshot

    def _relate(self) -> None:
        """Who is involved in what, and which rules mention whom.

        Built once, for the same reason the occupancy indexes are: a global preference asks
        "what does this instructor teach on Tuesday" for every instructor in the term, and
        filtering all sessions once per subject would put the institution's size back into
        every question.

        Disabled constraints never arrive here — `of` filters them — so no rule has to
        remember to check `enabled`, and one that forgot would silently enforce something an
        institution had switched off.
        """
        for session_id, session in self.sessions.items():
            for instructor in session.instructor_ids:
                self.sessions_of_instructor.setdefault(instructor, []).append(session_id)
            for leaf in self.leaves(session):
                self.sessions_of_group.setdefault(leaf, []).append(session_id)
            course = self.course_of.get(session_id)
            if course is not None:
                self.sessions_of_course.setdefault(course, []).append(session_id)

        for constraint in self.constraints:
            for session_id in constraint.target_ids:
                self.constraints_of_session.setdefault(session_id, []).append(constraint)

    def subjects_named_by(self, constraint: Constraint, kind: TargetKind) -> tuple[int, ...]:
        """The instructors, groups or courses a global preference was narrowed to.

        Empty means the whole term, which is what `unnarrowed` on the spec is for — a rule
        with no targets applies to everyone, and one with targets applies to those only. The
        rules screen already says which, and 3.5 records what happened when it did not: the
        API reported "Give everyone at most 3 hour(s) in a row" for a rule about one person.
        """
        return tuple(sorted(t.id for t in constraint.targets if t.kind is kind))

    # -- the indexes -------------------------------------------------------------

    def _index(self, placement: Placement) -> None:
        """Record one placement in every index it belongs to.

        Called only from `of`, while the snapshot is still being built. It mutates dicts on a
        frozen dataclass, which is legal — `frozen` prevents rebinding the fields, not writing
        through them — and is the one place in this module where anything changes.
        """
        session = self.sessions[placement.session_id]

        # The room is busy through its turnaround; the people are not. Indexing all three the
        # same way made a lab with a one-slot turnaround clash with the tutorial after it, for
        # students who had already left the room. Caught by asserting the good timetable is
        # clean before breaking it — which is the whole reason that assertion exists.
        for slot in self.occupied(placement):
            _append(self.by_room, (slot, placement.room_id), placement.session_id)
        for slot in self.teaching(placement):
            for instructor in session.instructor_ids:
                _append(self.by_instructor, (slot, instructor), placement.session_id)
            for leaf in self.leaves(session):
                _append(self.by_group, (slot, leaf), placement.session_id)

    def occupied(self, placement: Placement) -> tuple[Slot, ...]:
        """The slots a placement covers, including the room's turnaround afterwards.

        Turnaround is part of occupancy rather than a rule of its own: a chemistry lab that
        needs twenty minutes to clear is *in use* for those twenty minutes, and expressing it
        as a separate constraint would mean two rules could disagree about when the room is
        free.

        Deliberately tolerant of a placement the grid would reject — running past the end of
        the day, or through a break. That is `session_fits_the_grid`'s violation to report,
        and a snapshot that raised here would turn a reportable fault into a crash.
        """
        session = self.sessions[placement.session_id]
        room = self.rooms.get(placement.room_id)
        length = session.duration_slots + (room.turnaround_slots if room else 0)
        last = min(placement.start_slot + length, self.grid.slot_count)
        return tuple(range(placement.start_slot, last))

    def teaching(self, placement: Placement) -> tuple[Slot, ...]:
        """The slots a session is actually taught in — occupancy without the turnaround.

        Kept apart because the two answer different questions. A room is unusable during
        turnaround; an instructor is not still teaching, and a break during turnaround is not
        a class running through lunch.
        """
        session = self.sessions[placement.session_id]
        last = min(placement.start_slot + session.duration_slots, self.grid.slot_count)
        return tuple(range(placement.start_slot, last))

    def leaves(self, session: Session) -> frozenset[StudentGroupId]:
        """Every structural leaf group whose students attend this session."""
        found: set[StudentGroupId] = set()
        for group in session.attendee_ids:
            found |= self.groups.leaves_of(group)
        return frozenset(found)

    def headcount(self, session: Session) -> int:
        """How many students a session must seat.

        Leaves rather than the named groups, so a session taught to both an intake and one of
        its batches does not count those students twice.
        """
        return sum(self.groups.headcount(leaf) for leaf in self.leaves(session))

    # -- lookups the rules use ---------------------------------------------------

    def others_in_room(self, placement: Placement, slot: Slot) -> tuple[SessionId, ...]:
        return self._others(self.by_room, (slot, placement.room_id), placement)

    def others_teaching(
        self, placement: Placement, instructor: InstructorId, slot: Slot
    ) -> tuple[SessionId, ...]:
        return self._others(self.by_instructor, (slot, instructor), placement)

    def others_attending(
        self, placement: Placement, leaf: StudentGroupId, slot: Slot
    ) -> tuple[SessionId, ...]:
        return self._others(self.by_group, (slot, leaf), placement)

    def _others(
        self, index: Index, key: tuple[Slot, int], placement: Placement
    ) -> tuple[SessionId, ...]:
        """Everything else in this cell that could actually collide with this placement.

        Two exclusions, both load-bearing.

        **The session itself.** A move check asks where a session *could* go while that
        session is usually still placed somewhere; without this, dragging a session onto its
        own cell would report it clashing with itself.

        **Sessions whose week pattern cannot coincide.** A Monday lab in odd weeks and one in
        even weeks share a slot and never share a room. Consulting `coincides_with` here rather
        than in each rule is D7: a rule that forgot it would invent clashes for fortnightly
        teaching, which universities run and test suites do not notice.
        """
        mine = self.sessions[placement.session_id].week_pattern
        return tuple(
            other
            for other in index.get(key, ())
            if other != placement.session_id and _coincide(mine, self.sessions[other].week_pattern)
        )

    @property
    def unplaced(self) -> tuple[SessionId, ...]:
        """Sessions with nowhere to be.

        **Not a violation** (D6). A half-built timetable is the normal state while somebody is
        working on one, and an interface that reported every unplaced session as an error would
        be unusable on the first day of a term. The solver needs all of them placed; the person
        dragging them does not.
        """
        return tuple(sorted(s for s in self.sessions if s not in self.placements))


def _subject(unavailability: Unavailability) -> tuple[str, int, Slot]:
    """Which thing is unavailable, and when. Exactly one of the two ids is set."""
    if unavailability.room_id is not None:
        return ("room", unavailability.room_id, unavailability.slot)
    assert unavailability.instructor_id is not None  # the domain enforces exactly one
    return ("instructor", unavailability.instructor_id, unavailability.slot)


def _coincide(a: WeekPattern, b: WeekPattern) -> bool:
    return a.coincides_with(b)


def _append(
    index: dict[tuple[Slot, int], list[SessionId]], key: tuple[Slot, int], value: SessionId
) -> None:
    index.setdefault(key, []).append(value)
