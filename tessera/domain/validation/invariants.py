"""The seven rules that cannot be switched off, and how to see one broken.

`domain/constraints.py` has declared these since 3.5 as prose with stable keys, and said
outright that this phase would *"write the validator that checks them and attaches itself by
`key`"*. This is that. Nothing here invents an eighth rule, and nothing here restates a
sentence the interface already shows — a rule's *statement* lives with `INVARIANTS`, and what
this module produces is the particular sentence about a particular collision.

**One evaluator per invariant, each answering the same narrow question:** what does this one
placement break? The whole-timetable check is that question folded over every placement (D2),
which is what keeps a single implementation behind both the solver and the drag interface.
Decision #5 makes that the most important architectural rule in the project; two
implementations here would break it one level below where it was written down.

**Every rule must be shown to fail.** Phase 0.1 reported FEASIBLE on all 21 instances, and a
checker that always returned "no violations" would have produced identical output — every
result worthless while looking perfect. `tests/domain/validation/test_invariants.py` breaks a
good timetable one rule at a time and asserts each names itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from tessera.domain.constraints import INVARIANTS
from tessera.domain.ids import AssignmentId, SessionId
from tessera.domain.validation.snapshot import Placement, Snapshot
from tessera.domain.validation.violation import Violation

#: Every key `INVARIANTS` declares, so a rule cannot be attached to one that does not exist.
KEYS = frozenset(invariant.key for invariant in INVARIANTS)

Rule = Callable[[Snapshot, Placement], Iterator[Violation]]


def _named(key: str) -> str:
    """A key, checked against the domain's list at import time.

    A typo would otherwise produce a violation naming a rule the interface cannot explain —
    the rules screen reads `INVARIANTS`, so an unknown key would render as nothing at all.
    """
    if key not in KEYS:
        raise AssertionError(f"{key!r} is not one of the invariants the domain declares")
    return key


def room_not_double_booked(snapshot: Snapshot, placement: Placement) -> Iterator[Violation]:
    """Two classes in one room is a collision somebody discovers at the door."""
    seen: set[SessionId] = set()
    for slot in snapshot.occupied(placement):
        for other in snapshot.others_in_room(placement, slot):
            if other in seen:
                continue
            seen.add(other)
            yield Violation(
                rule=_named("room_not_double_booked"),
                message=(
                    f"{_room(snapshot, placement)} is already taken by "
                    f"{_session(snapshot, other)} at {_when(snapshot, slot)}."
                ),
                session_id=placement.session_id,
                conflicting_session_id=other,
                conflicting_assignment_id=_assignment(snapshot, other),
            )


def instructor_not_double_booked(snapshot: Snapshot, placement: Placement) -> Iterator[Violation]:
    """A person cannot be in two rooms."""
    session = snapshot.sessions[placement.session_id]
    seen: set[tuple[int, SessionId]] = set()
    for slot in snapshot.teaching(placement):
        for instructor in sorted(session.instructor_ids):
            for other in snapshot.others_teaching(placement, instructor, slot):
                if (instructor, other) in seen:
                    continue
                seen.add((instructor, other))
                yield Violation(
                    rule=_named("instructor_not_double_booked"),
                    message=(
                        f"Instructor {instructor} is already teaching "
                        f"{_session(snapshot, other)} at {_when(snapshot, slot)}."
                    ),
                    session_id=placement.session_id,
                    conflicting_session_id=other,
                    conflicting_assignment_id=_assignment(snapshot, other),
                )


def group_not_double_booked(snapshot: Snapshot, placement: Placement) -> Iterator[Violation]:
    """The same, from the students' side.

    Checked against **leaf** groups, so a lecture to an intake and a lab to one of its batches
    collide — those students are in both. Reporting the leaf rather than the group the session
    names would be precise and unhelpful, so the message names the session instead.
    """
    session = snapshot.sessions[placement.session_id]
    seen: set[SessionId] = set()
    for slot in snapshot.teaching(placement):
        for leaf in sorted(snapshot.leaves(session)):
            for other in snapshot.others_attending(placement, leaf, slot):
                if other in seen:
                    continue
                seen.add(other)
                yield Violation(
                    rule=_named("group_not_double_booked"),
                    message=(
                        f"These students are already in {_session(snapshot, other)} "
                        f"at {_when(snapshot, slot)}."
                    ),
                    session_id=placement.session_id,
                    conflicting_session_id=other,
                    conflicting_assignment_id=_assignment(snapshot, other),
                )


def room_fits_group(snapshot: Snapshot, placement: Placement) -> Iterator[Violation]:
    """Capacity is a fact about the building, not a cost to weigh against convenience."""
    room = snapshot.rooms.get(placement.room_id)
    if room is None:
        return
    needed = snapshot.headcount(snapshot.sessions[placement.session_id])
    if room.capacity < needed:
        yield Violation(
            rule=_named("room_fits_group"),
            message=(f"{room.name} seats {room.capacity}, and this session has {needed} students."),
            session_id=placement.session_id,
        )


def room_has_required_features(snapshot: Snapshot, placement: Placement) -> Iterator[Violation]:
    """A lab without computers cannot hold the lab, however well it scores on everything else.

    `Room.can_host` already answers this and already knows the difference between a feature
    that must be present and one that must be present *thirty times*. Re-deriving it here would
    be a second answer to a question the domain has settled.
    """
    room = snapshot.rooms.get(placement.room_id)
    session = snapshot.sessions[placement.session_id]
    if room is None or room.can_host(0, session.required_features, session.required_counts):
        return

    # Asked with a headcount of zero, so capacity always passes and only the two feature
    # cases can have refused: something absent, or something present but not in the number
    # the session needs. There is no third branch to guard against.
    missing = session.required_features - room.features
    yield Violation(
        rule=_named("room_has_required_features"),
        message=(
            f"{room.name} does not have everything this session needs."
            if missing
            else f"{room.name} does not have enough of what this session needs."
        ),
        session_id=placement.session_id,
    )


def availability_respected(snapshot: Snapshot, placement: Placement) -> Iterator[Violation]:
    """Unavailability is a statement about the world, not a preference to be balanced.

    The room is checked across its whole occupancy including turnaround — a room being
    refurbished cannot be used to clear up in either — and the instructor only across the slots
    they are actually teaching.
    """
    session = snapshot.sessions[placement.session_id]
    room = snapshot.rooms.get(placement.room_id)

    for slot in snapshot.occupied(placement):
        if (placement.room_id, slot) in snapshot.room_closed:
            name = room.name if room else f"Room {placement.room_id}"
            yield Violation(
                rule=_named("availability_respected"),
                message=_because(
                    f"{name} is unavailable at {_when(snapshot, slot)}",
                    snapshot.closure_reason.get(("room", placement.room_id, slot), ""),
                ),
                session_id=placement.session_id,
            )
            break

    for instructor in sorted(session.instructor_ids):
        for slot in snapshot.teaching(placement):
            if (instructor, slot) in snapshot.instructor_away:
                yield Violation(
                    rule=_named("availability_respected"),
                    message=_because(
                        f"Instructor {instructor} is unavailable at {_when(snapshot, slot)}",
                        snapshot.closure_reason.get(("instructor", instructor, slot), ""),
                    ),
                    session_id=placement.session_id,
                )
                break


def breaks_protected(snapshot: Snapshot, placement: Placement) -> Iterator[Violation]:
    """Nothing during a break, and nothing running through one.

    `TimeGrid.span` already refuses all three ways a placement can be impossible — past the end
    of the week, across midnight into the next day, and through a break — **and says which**.
    So the grid's own sentence is the message, rather than a second wording that could drift
    from the rule it describes.

    P7 draws this as a slider. It is stronger than that, and a preference that can never be
    broken is a misleading control.
    """
    session = snapshot.sessions[placement.session_id]
    try:
        snapshot.grid.span(placement.start_slot, session.duration_slots)
    except ValueError as refusal:
        yield Violation(
            rule=_named("breaks_protected"),
            message=f"{refusal}.".capitalize(),
            session_id=placement.session_id,
        )


#: Every invariant, in the order `INVARIANTS` declares them.
RULES: tuple[Rule, ...] = (
    instructor_not_double_booked,
    group_not_double_booked,
    room_not_double_booked,
    room_fits_group,
    room_has_required_features,
    availability_respected,
    breaks_protected,
)


def violations_for(snapshot: Snapshot, placement: Placement) -> tuple[Violation, ...]:
    """Everything this one placement breaks. **The primitive** (D2).

    The whole-timetable check folds this over every placement, and a move check runs it on a
    placement that does not exist yet. Making the move the primitive rather than the special
    case is deliberate: it is the one that has to be fast, and the one the interface asks
    hundreds of times during a drag.
    """
    return tuple(violation for rule in RULES for violation in rule(snapshot, placement))


# -- the words --------------------------------------------------------------------


def _room(snapshot: Snapshot, placement: Placement) -> str:
    room = snapshot.rooms.get(placement.room_id)
    return room.name if room else f"Room {placement.room_id}"


def _session(snapshot: Snapshot, session_id: SessionId) -> str:
    """A session, named the way somebody looking at the screen would name it.

    Sessions have no name of their own — they are the *n*th occurrence of a template of an
    offering of a course — and the snapshot deliberately does not carry the course catalogue.
    So this is honest rather than pretty, and 5.8 can enrich it where the names are loaded.
    """
    return f"session {session_id}"


def _when(snapshot: Snapshot, slot: int) -> str:
    """A slot as a person reads it, from the grid that defines it."""
    grid = snapshot.grid
    minute = grid.day_start_minute + grid.slot_of_day(slot) * grid.slot_minutes
    return f"day {grid.day_of(slot) + 1}, {minute // 60:02d}:{minute % 60:02d}"


def _because(what: str, reason: str) -> str:
    return f"{what} ({reason})." if reason else f"{what}."


def _assignment(snapshot: Snapshot, session_id: SessionId) -> AssignmentId | None:
    placement = snapshot.placements.get(session_id)
    return placement.assignment_id if placement else None
