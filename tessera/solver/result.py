"""What a solve produced, or why it produced nothing.

**Infeasible is an answer** (D4). A timetable can genuinely have no solution — too few rooms,
an instructor claimed by two departments — and that is a fact about the term rather than a
failure of the solver. Saying so plainly is what lets 4.6 explain it and what stops 4.7
rendering a spinner for ever.

**There is deliberately no partial result.** A solver that returned the sessions it managed to
place would produce something the validator calls *feasible*, because the ones it could not
place are simply absent — 4.1's D6 made completeness a separate question precisely so that
could not be blurred, and this is the module where blurring it would be convenient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tessera.domain.ids import RoomId, SessionId
from tessera.domain.time_grid import Slot


class Outcome(StrEnum):
    """Which of the three things happened. Never a fourth."""

    SOLVED = "solved"
    """Every session is placed and no hard rule is broken."""

    IMPOSSIBLE = "impossible"
    """No timetable exists. Proven, not guessed — CP-SAT searched the whole space."""

    OUT_OF_TIME = "out_of_time"
    """The budget ran out with nothing found. **Says nothing about whether a solution
    exists**, and must not be reported as though it did: "we could not find one" and "there
    is not one" are different sentences, and only the second is a reason to change the data.
    """


@dataclass(frozen=True, slots=True)
class Placed:
    """One session, and where the solver put it."""

    session: SessionId
    start_slot: Slot
    room: RoomId


@dataclass(frozen=True)
class Solution:
    outcome: Outcome
    placements: tuple[Placed, ...] = ()
    seconds: float = 0.0

    #: Sessions and (session, room) candidates the model was built from. Recorded because
    #: #35 is a warning about model size, and a warning nobody measures is a comment.
    sessions: int = 0
    candidates: int = 0

    work: float = 0.0
    """How much searching was done, in CP-SAT's own machine-independent unit.

    `seconds` says how long this took here; this says how much was done, and two runs of the
    same instance under a deterministic budget agree on it whatever else the machine was doing
    (D4). It is what makes a comparison between two formulations a comparison of the
    formulations rather than of the afternoon."""

    penalty: int = 0
    """What the soft rules cost, as the solver's objective measured it.

    The validator is the authority for what a finished timetable costs, and 4.3's exit test
    is that this equals `Report.penalty` exactly. Two readings that agree are evidence;
    one reading agreeing with itself is not."""

    penalty_breakdown: dict[str, int] = field(default_factory=dict)
    """The penalty by `ConstraintKind`, largest first. `Report.penalty_breakdown`'s shape."""

    lower_bound: int = 0
    """No timetable for this term can score below this. Zero when nothing was optimised.

    Reported only for a solved timetable, because a bound is a statement *about a score* and
    a failed solve has none. When it equals `penalty` the answer is proven optimal, and
    saying so is the difference between "this is the best there is" and "this is the best we
    found"."""

    @property
    def solved(self) -> bool:
        return self.outcome is Outcome.SOLVED

    @property
    def is_optimal(self) -> bool:
        """Proven, not merely unimproved. What 4.4 is trying to make true more often."""
        return self.solved and self.lower_bound == self.penalty

    def __post_init__(self) -> None:
        if self.solved and not self.placements:
            raise ValueError("a solved timetable with no placements is not one")
        if not self.solved and self.placements:
            raise ValueError(f"{self.outcome} carries placements, which cannot be trusted")
        self._the_score_makes_sense()

    def _the_score_makes_sense(self) -> None:
        """The four things a penalty and a bound can never be.

        **This is the assertion Phase 0.1 did not have.** Its first optimising run returned
        cost 5 with a lower bound of **-7** — room stability written as `sum(uses_room) - 1`,
        so a course in one room contributed minus nothing — and the solver then burned the
        full 60 s unable to prove what it had already found at 3.41 s. Nobody noticed for the
        length of a phase, because a negative number in a log looks like a number.

        Cheap enough to run on every solve, and it turns an unsound objective from something
        found by reading a benchmark table into something found by a test.
        """
        if self.penalty < 0:
            raise ValueError(f"a penalty of {self.penalty} is not a cost")
        if self.lower_bound < 0:
            raise ValueError(
                f"a lower bound of {self.lower_bound} is unsound: an all-penalty objective "
                "cannot go below zero, so some term is not clamped"
            )
        if self.solved and self.lower_bound > self.penalty:
            raise ValueError(
                f"a lower bound of {self.lower_bound} is above the best solution found "
                f"({self.penalty}), so it is not a bound"
            )
        if not self.solved and (self.penalty or self.penalty_breakdown):
            raise ValueError(f"{self.outcome} has no timetable, so it has no score")
        if sum(self.penalty_breakdown.values()) != self.penalty:
            raise ValueError(
                f"the breakdown sums to {sum(self.penalty_breakdown.values())}, not "
                f"{self.penalty} — a rule is being counted in one place and not the other"
            )
