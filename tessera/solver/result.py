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

from dataclasses import dataclass
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

    @property
    def solved(self) -> bool:
        return self.outcome is Outcome.SOLVED

    def __post_init__(self) -> None:
        if self.solved and not self.placements:
            raise ValueError("a solved timetable with no placements is not one")
        if not self.solved and self.placements:
            raise ValueError(f"{self.outcome} carries placements, which cannot be trusted")
