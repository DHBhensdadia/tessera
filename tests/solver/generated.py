"""Institutions for the solver to try, and a way to check a refusal independently.

Reuses 4.1's strategy rather than writing a second one — the shapes that make a timetable hard
are the same shapes that make one hard to validate, and two generators would drift. Two things
are changed for this phase:

* **no constraints**, for `to_solve`. 4.2 is hard rules only; the weighted rules arrive in
  4.3, and `to_score` is the strategy that asks for them.
* **nothing placed.** The solver's job is to place them. Pins get their own tests, where the
  pin is the point rather than an accident of generation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from itertools import product

from hypothesis import strategies as st

from tessera.domain.constraints import Constraint, ConstraintKind
from tessera.domain.ids import AssignmentId, RoomId, SessionId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Report, Snapshot, validate
from tessera.solver import Placed
from tests.domain.validation.generated import PROJECTOR, Instance, instances


def to_solve() -> st.SearchStrategy[Instance]:
    """A term with rules but no preferences, and nothing placed yet."""
    return instances().map(lambda i: replace(i, constraints=[], assignments=[]))


def to_score(kinds: frozenset[ConstraintKind], least_rules: int = 1) -> st.SearchStrategy[Instance]:
    """A term whose rules are all soft and all cost something. Nothing placed.

    Three deliberate narrowings, each of which was measured to matter.

    `least_rules=1`, because left to chance most generated terms carry no rule of the kind
    under test at all. **Soft**, because a hard rule costs nothing by definition and, on
    instances this small, mostly makes the term infeasible — 213 of 300 were, so the
    agreement test was running on the 87 that were left. **Weight at least one**, because a
    rule worth nothing is scored zero by both implementations however wrong either is.

    The weight tests raise `least_rules` to 2, because they need something for a rule to be
    traded *against*: with one rule in the term, raising its weight cannot change the answer
    and the property under test would hold for a reason that has nothing to do with weights.
    """
    return instances(kinds=kinds, least_rules=least_rules, least_sessions=2, least_targets=2).map(
        lambda i: _roomier(
            replace(
                i,
                assignments=[],
                constraints=[_as(c, is_hard=False, weight=c.weight or 1) for c in i.constraints],
            )
        )
    )


def to_enforce(kinds: frozenset[ConstraintKind]) -> st.SearchStrategy[Instance]:
    """The same, with every rule made hard — so a solved term is one that obeyed them."""
    return instances(kinds=kinds, least_rules=1, least_sessions=2, least_targets=2).map(
        lambda i: _roomier(
            replace(
                i,
                assignments=[],
                constraints=[_as(c, is_hard=True, weight=0) for c in i.constraints if c.targets],
            )
        )
    )


def _roomier(instance: Instance) -> Instance:
    """The same term, with rooms able to hold what it contains.

    **Measured, not assumed.** On the generator as it stands, 178 of 300 terms had a session
    with no room big enough or equipped enough, so the agreement test spent most of its
    examples discarding instances instead of scoring them — and of what survived, aiming the
    objective at the *dearest* timetable still found a violation only eight times, because a
    term with one possible arrangement cannot break a rule about two sessions.

    Capacity and features are 4.2's subject and have their own tests. What this phase needs
    is room to move, so that "is this timetable scored correctly" is asked of timetables that
    differ.
    """
    seats = sum(g.size for g in instance.groups.all)
    return replace(
        instance,
        rooms=[
            r.model_copy(update={"capacity": max(r.capacity, seats), "features": {PROJECTOR}})
            for r in instance.rooms
        ],
    )


def _as(constraint: Constraint, **changes: object) -> Constraint:
    """A constraint with fields changed, rebuilt rather than copied.

    `model_copy` skips validation, and the domain has real opinions about which combinations
    exist — a term-wide preference cannot be hard, for one. Rebuilding means an impossible
    combination fails here rather than becoming a test running against input the application
    would refuse.

    `dict(...)` rather than `model_dump()`: the latter serialises nested models to plain
    dicts, and `targets` is a frozenset of them, so dumping it asks Python to hash a dict.
    """
    return Constraint(**{**dict(constraint), **changes})


def snapshot_of(instance: Instance, assignments: list[Assignment] | None = None) -> Snapshot:
    """The term as both implementations see it.

    Constraints and courses are passed through rather than dropped: 4.3 scores rules, and a
    snapshot missing them would let the solver optimise a rulebook the validator then judged
    by a different one. `to_solve` produces none, so 4.2's tests are unaffected.
    """
    return Snapshot.of(
        grid=instance.grid,
        sessions=instance.sessions,
        rooms=instance.rooms,
        groups=instance.groups,
        assignments=assignments or instance.assignments,
        unavailability=instance.unavailability,
        constraints=instance.constraints,
        course_of=instance.course_of,
    )


def judge(instance: Instance, placements: Sequence[Placed]) -> Report:
    """What the 4.1 validator makes of a set of placements."""
    return validate(
        snapshot_of(
            instance,
            [
                Assignment(
                    id=AssignmentId(i),
                    session_id=p.session,
                    start_slot=p.start_slot,
                    room_id=p.room,
                )
                for i, p in enumerate(placements, start=1)
            ],
        )
    )


def any_valid_timetable(instance: Instance) -> bool:
    """Brute force: is there **any** arrangement the validator would accept?

    The independent check behind a refusal. A solver that said "impossible" too eagerly would
    pass every test that only looks at what it *did* solve, so the negative half needs an
    answer that owes nothing to CP-SAT — and for a handful of sessions in a handful of rooms,
    trying everything is that answer.

    Exponential, and deliberately only used on instances small enough for it not to matter.
    """
    sessions = sorted(s.id for s in instance.sessions if s.id is not None)
    rooms = sorted(r.id for r in instance.rooms if r.id is not None)
    slots = range(instance.grid.slot_count)

    for choice in product(list(product(slots, rooms)), repeat=len(sessions)):
        placed = [
            Assignment(
                id=AssignmentId(i),
                session_id=SessionId(session),
                start_slot=slot,
                room_id=RoomId(room),
            )
            for i, (session, (slot, room)) in enumerate(zip(sessions, choice, strict=True), 1)
        ]
        report = validate(snapshot_of(instance, placed))
        if report.is_feasible and report.is_complete:
            return True
    return False
