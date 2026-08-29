"""One validator, used by the solver and by the drag interface.

Decision #5, and P2 calls it *"the single most important architectural rule"*: validation
written twice — once for the solver, once for the interface — **will** drift, the interface
will permit placements the solver forbids, and the resulting bugs are close to impossible to
reproduce. So the Swift client never decides legality; it asks.

That rule applies one level below where it was written, too. The two questions asked here —
*what is wrong with this timetable* and *what would this move break* — are the same question
folded differently, not two implementations (D2). `violations_for` is the primitive; `validate`
is it applied to every placement, and `validate_move` is it applied to one that does not exist
yet.

**Cost is flat, not merely small.** Phase 0.2 measured 0.676 ms p99 at department scale and
0.514 ms at ten times the sessions, because every occupancy check is a dict lookup. The
budget is not what makes that shape necessary — a scanning validator passes 16 ms at
department scale and fails only for the largest institutions, which is the worst place to
discover it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tessera.domain.ids import RoomId, SessionId
from tessera.domain.time_grid import Slot
from tessera.domain.validation import rules as constraint_rules
from tessera.domain.validation.invariants import RULES, violations_for
from tessera.domain.validation.rules import EVALUATORS, Lens
from tessera.domain.validation.snapshot import Index, Placement, Snapshot
from tessera.domain.validation.violation import Violation

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "EVALUATORS",
    "RULES",
    "Cell",
    "Index",
    "Lens",
    "Placement",
    "Report",
    "Snapshot",
    "Verdict",
    "Violation",
    "validate",
    "validate_move",
    "validate_viewport",
    "violations_for",
]


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether one placement is allowed, and why not."""

    legal: bool
    violations: tuple[Violation, ...] = ()

    @classmethod
    def on(cls, violations: tuple[Violation, ...]) -> Verdict:
        return cls(legal=not any(v.is_hard for v in violations), violations=violations)


@dataclass(frozen=True, slots=True)
class Cell:
    """One candidate position for one session, and whether it would work."""

    start_slot: Slot
    room_id: RoomId
    legal: bool
    violations: tuple[Violation, ...] = ()


@dataclass(frozen=True)
class Report:
    """Everything currently wrong with a whole timetable."""

    violations: tuple[Violation, ...] = ()
    unplaced: tuple[SessionId, ...] = ()

    @property
    def is_feasible(self) -> bool:
        """No placed session breaks a hard rule.

        **Says nothing about completeness** (D6). A half-built timetable is the normal state
        while somebody is working on one, and an interface that called every unplaced session
        an error would be unusable on the first day of a term. The solver needs `unplaced` to
        be empty as well; the person dragging does not.
        """
        return not any(v.is_hard for v in self.violations)

    @property
    def is_complete(self) -> bool:
        return not self.unplaced

    by_rule: dict[str, int] = field(default_factory=dict)
    """How many violations of each rule, for a summary that does not list four hundred."""

    @property
    def hard(self) -> tuple[Violation, ...]:
        """The ones that make the timetable invalid rather than merely worse.

        Listed individually on the wire while soft ones are summarised as a penalty, which is
        the shape `ViolationReport` froze in 1.4: you fix the first kind and you *tune* the
        second.
        """
        return tuple(v for v in self.violations if v.is_hard)

    @property
    def penalty(self) -> int:
        """What this timetable costs. Hard violations are not priced — they are refused."""
        return sum(v.cost for v in self.violations)

    @property
    def penalty_breakdown(self) -> dict[str, int]:
        """The penalty, by rule, largest first.

        Per *kind* rather than per constraint: an institution with three narrowed
        `MIN_GAP` rules wants to know what gaps cost it, not what rule 14 cost it. 4.3
        reports its objective the same way, which is how the two can be compared.
        """
        totals: dict[str, int] = {}
        for violation in self.violations:
            if violation.cost:
                totals[violation.rule] = totals.get(violation.rule, 0) + violation.cost
        return dict(sorted(totals.items(), key=lambda item: -item[1]))


def validate(snapshot: Snapshot) -> Report:
    """Everything wrong with the timetable as it stands.

    The fold over `violations_for` (D2). Each *pair* of clashing sessions is reported from
    both sides, which is intentional: a person who selects one of them must be told it is in
    trouble, and a report that named only the earlier one would leave half the grid looking
    innocent.
    """
    found: list[Violation] = []
    for placement in snapshot.placements.values():
        found.extend(violations_for(snapshot, placement))
    found.extend(constraint_rules.violations(Lens(snapshot)))

    counts: dict[str, int] = {}
    for violation in found:
        counts[violation.rule] = counts.get(violation.rule, 0) + 1

    return Report(
        violations=tuple(found),
        unplaced=snapshot.unplaced,
        by_rule=counts,
    )


def validate_move(
    snapshot: Snapshot, session_id: SessionId, start_slot: Slot, room_id: RoomId
) -> Verdict:
    """Whether one session may sit in one cell.

    The session's own current placement is ignored rather than removed: `Snapshot._others`
    filters it out of every lookup, so a session dragged onto the cell it already occupies does
    not report clashing with itself, and no index has to be rebuilt to answer the question.
    Rebuilding would be correct and would cost the flatness the whole design is for.

    Hard *targeted* rules are checked too, through the `constraints_of_session` index — a
    handful of rules rather than the term's whole rulebook. Without them the interface would
    permit a drop the solver forbids, which is Decision #5's drift arriving one level down.
    """
    placement = Placement(session_id, start_slot, room_id)
    return Verdict.on(
        violations_for(snapshot, placement)
        + tuple(constraint_rules.violations_involving(Lens(snapshot, moved=placement), session_id))
    )


def validate_viewport(
    snapshot: Snapshot,
    session_id: SessionId,
    room_ids: Sequence[RoomId],
    period_from: Slot,
    period_to: Slot,
) -> tuple[Cell, ...]:
    """Legality of every visible cell, for one session being dragged.

    **Scoped, and there is no unscoped form.** Phase 0.2 measured the whole-grid version at
    43 ms p99 at the NFR-9 ceiling — 2.7 times over budget, with 25,000 cells of genuine validation
    before serialisation even began. It measures fine at department scale, which is exactly why
    it had to be measured at the ceiling.

    Answered once when a drag begins, so the interface renders green and red from the result
    and makes no further calls while the pointer moves: around 600 times less transport than
    asking per cell.
    """
    return tuple(
        Cell(
            start_slot=slot,
            room_id=room,
            legal=verdict.legal,
            violations=verdict.violations,
        )
        for room in room_ids
        for slot in range(period_from, period_to)
        if (verdict := validate_move(snapshot, session_id, slot, room)) is not None
    )
