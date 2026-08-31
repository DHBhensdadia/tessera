"""Which sessions a round is allowed to move.

A Fix-and-Optimize round freezes almost everything and re-solves a window, so the choice of
window is the search. R2 lists three shapes — a department, a day, the sessions carrying the
most penalty — and part 3 measures those against each other. This part carries the one that
has to beat all of them to be worth keeping: **a random handful**, which is the control.

Every strategy is a plain function of the term, the timetable it currently has, and a seeded
`Random`. That makes the choice testable without a solver, and it is what lets the two rules
below be properties over the whole set rather than four copies of the same assertion.

**A strategy never frees a pinned session.** Decision #10 put `is_pinned` in the schema on the
first day so that *"re-optimise around my manual edits"* would not need a solver rewrite; a
window that quietly moved a pinned session would turn that promise into a lie in the one place
nobody looks — the timetable came back better, so why read it closely.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping

from tessera.domain.ids import SessionId
from tessera.domain.validation import Snapshot
from tessera.domain.validation.snapshot import Placement

type Strategy = Callable[
    [Snapshot, Mapping[SessionId, Placement], random.Random, int], frozenset[SessionId]
]


def movable(snapshot: Snapshot) -> list[SessionId]:
    """Every session a round may touch: all of them, less the ones somebody pinned."""
    return sorted(
        session_id
        for session_id in snapshot.sessions
        if not (placed := snapshot.placements.get(session_id)) or not placed.is_pinned
    )


def anywhere(
    snapshot: Snapshot,
    placed: Mapping[SessionId, Placement],
    rng: random.Random,
    window: int,
) -> frozenset[SessionId]:
    """A random handful, drawn without regard to what anything costs.

    The control, and it is here first on purpose. A strategy that reasons about the timetable
    has to be shown to beat one that does not, and the usual way that comparison goes wrong is
    that the clever strategy is never measured against anything.
    """
    choices = movable(snapshot)
    return frozenset(rng.sample(choices, min(window, len(choices))))


#: Every strategy there is, by name. Part 3 adds the three that read the timetable; the loop
#: takes its strategies from here rather than from a list, so a fourth joins the tests that
#: check the two rules by existing.
STRATEGIES: dict[str, Strategy] = {"anywhere": anywhere}
