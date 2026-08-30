"""Institutions for the solver to try, and a way to check a refusal independently.

Reuses 4.1's strategy rather than writing a second one — the shapes that make a timetable hard
are the same shapes that make one hard to validate, and two generators would drift. Two things
are changed for this phase:

* **no constraints.** 4.2 is hard rules only; the weighted rules arrive in 4.3. A generated
  rule would make the validator report violations the solver never considered, and the test
  would fail for a reason that is not a defect.
* **nothing placed.** The solver's job is to place them. Pins get their own tests, where the
  pin is the point rather than an accident of generation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from itertools import product

from hypothesis import strategies as st

from tessera.domain.ids import AssignmentId, RoomId, SessionId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Report, Snapshot, validate
from tessera.solver import Placed
from tests.domain.validation.generated import Instance, instances


def to_solve() -> st.SearchStrategy[Instance]:
    """A term with rules but no preferences, and nothing placed yet."""
    return instances().map(lambda i: replace(i, constraints=[], assignments=[]))


def snapshot_of(instance: Instance, assignments: list[Assignment] | None = None) -> Snapshot:
    return Snapshot.of(
        grid=instance.grid,
        sessions=instance.sessions,
        rooms=instance.rooms,
        groups=instance.groups,
        assignments=assignments or instance.assignments,
        unavailability=instance.unavailability,
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
