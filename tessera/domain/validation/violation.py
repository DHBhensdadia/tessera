"""What the validator says, and the shape the wire already fixed.

The frozen `Violation` schema in `api/schemas/timetables.py` has carried these fields since
1.4, so this is not a new design — it is the domain half of one that already exists.

One difference, and it is deliberate. The wire documents `rule` with the examples
`'room_occupied'` and `'instructor_clash'`, **names that appear nowhere in this codebase**;
the real keys have been in `domain.constraints.INVARIANTS` since 3.5, where the rules screen
already reads them. A client matching on the documented examples would match strings the engine
will never send. The keys win, and the schema's description is corrected to name them (D5).
"""

from __future__ import annotations

from dataclasses import dataclass

from tessera.domain.ids import AssignmentId, SessionId


@dataclass(frozen=True, slots=True)
class Violation:
    """One thing wrong with one placement, in words a person can act on."""

    rule: str
    """An `INVARIANTS` key, or in part 2 a `ConstraintKind` value. Stable across releases,
    because the interface looks the explanation up by it."""

    message: str
    """Plain language, shown directly. The engine says what is wrong; the screen says what to
    do about it — the same division 3.5 settled for the import report."""

    session_id: SessionId
    conflicting_session_id: SessionId | None = None
    conflicting_assignment_id: AssignmentId | None = None

    is_hard: bool = True
    """A hard violation makes a timetable invalid; a soft one makes it worse."""

    units: int = 1
    """How many times this counts. Three idle hours on a Tuesday is **one** sentence and
    three units of cost — a person reading three identical lines learns nothing from the
    second, and a score that counted it once would rate a wasted morning as a wasted hour."""

    weight: int = 0
    """What one unit costs, from the constraint that raised it. Zero for an invariant: a
    hard rule is refused rather than priced, and a weight on one would suggest it could be
    traded away."""

    @property
    def cost(self) -> int:
        """What this violation adds to the timetable's penalty."""
        return 0 if self.is_hard else self.units * self.weight
