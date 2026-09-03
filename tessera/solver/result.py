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
from itertools import pairwise

from tessera.domain.ids import RoomId, SessionId
from tessera.domain.time_grid import Slot
from tessera.solver.preflight import Shortfall


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
class Requirement:
    """One rule, narrowed to the thing it is about.

    The unit an explanation is made of, and the unit a person can actually change: you extend
    *one* instructor's availability, not "availability". P7 draws each line of the
    infeasibility panel with a button beside it, and `subject_kind` and `subject_id` are what
    let 4.7 point that button at the screen that would relax this one (D4).

    It is also the granularity the assumption literals are created at. Per *rule* would give
    seven literals and a core that says "instructors clash" while naming nobody, which is "no
    solution found" with a longer sentence; per *session* would give thousands and a core
    listing forty of them, which is not an explanation either.
    """

    rule: str
    """An `INVARIANTS` key, or a `ConstraintKind` value for a hard distribution rule."""

    subject_kind: str
    """`room`, `instructor`, `group`, `constraint` — or `grid`, for the one rule that belongs
    to the teaching week itself rather than to anything in it."""

    subject_id: int | None = None

    def __str__(self) -> str:
        where = f" {self.subject_id}" if self.subject_id is not None else ""
        return f"{self.rule}/{self.subject_kind}{where}"


@dataclass(frozen=True, slots=True)
class Explanation:
    """Why no timetable exists, as far as something has proved it.

    **Only ever attached to `IMPOSSIBLE`.** `OUT_OF_TIME` means the search ran out, which
    says nothing about whether a timetable exists, and attaching an explanation to it would
    turn "we could not find one" into "there is not one" — the two sentences `Outcome` was
    written to keep apart.

    Three things can prove it, and they are kept apart rather than flattened into a list of
    sentences, because they are not equally strong. A count is arithmetic and needs no search.
    A refusal from the builder names one session. A **conflict** is CP-SAT's: a set of
    requirements that cannot all hold, every member of which has been shown to be necessary.
    """

    shortfalls: tuple[Shortfall, ...] = ()
    """Counting arguments no timetable can satisfy, worst first."""

    conflict: tuple[Requirement, ...] = ()
    """A set of requirements that cannot hold together, and **not necessarily the only one**.

    Every member is necessary — dropping any one of them makes the term solvable, and the
    tests prove that by re-solving rather than by asserting it. What is *not* true, and what
    P7's mockup and the wire schema both used to claim, is that relaxing one of them makes a
    timetable possible: where several independent conflicts exist, CP-SAT returns one of them
    and never mentions the others (D5). The report says so instead of implying otherwise.
    """

    unbuildable: str = ""
    """What `model.build` refused, in its own words.

    It already names the session, the room or the two colliding pins, and until now `solve`
    caught the exception and threw the sentence away — an explanation the code had already
    written and nobody could read.
    """

    def __post_init__(self) -> None:
        if not self.shortfalls and not self.conflict and not self.unbuildable:
            raise ValueError("an explanation that explains nothing is not one")


@dataclass(frozen=True, slots=True)
class Step:
    """One round of the outer search, and what it did with it.

    Kept so the loop can be read afterwards rather than inferred from its answer. 4.5 wants the
    shape of the descent to compare runs, 4.7 draws it live, and a round that changed nothing
    is as informative as one that did — a long tail of refusals is what a stalled neighbourhood
    strategy looks like from outside.
    """

    round: int
    strategy: str
    freed: int
    """How many sessions this round was allowed to move. **Zero means the whole problem**,
    which is the only kind of round whose lower bound is a bound (D6)."""

    penalty: int
    seconds: float
    accepted: bool


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

    bound_is_proven: bool = False
    """Whether anything actually proved the bound above (D6).

    **A sub-problem's lower bound is not a lower bound.** A Fix-and-Optimize round searches a
    restricted problem — every timetable it can reach agrees with the frozen part — so its
    optimum is at or above the true one and its bound says nothing about the term. Reporting
    it here would pass every check in `_the_score_makes_sense`, because a sub-bound is still
    at or below the incumbent's penalty, and would make `is_optimal` true the moment a round
    proved its own window: the whole timetable declared best possible because forty of its
    five hundred sessions are.

    So only an unrestricted solve sets this. When nothing did, the bound is 0 — true, sound,
    and saying nothing, which is the right amount to say. *No bound* and *a bound of zero*
    must not look the same to 4.7, and this is what tells them apart."""

    trajectory: tuple[Step, ...] = ()
    """Every round of the outer search, in order. Empty when there was no outer search."""

    explanation: Explanation | None = None
    """Why there is no timetable, when something proved there is none.

    `None` on every outcome but `IMPOSSIBLE`, and `None` on an `IMPOSSIBLE` that CP-SAT
    reached by search without anything being able to say which rules did it — which part 2
    turns into a defect rather than a case, but is honest here.
    """

    @property
    def solved(self) -> bool:
        return self.outcome is Outcome.SOLVED

    @property
    def is_optimal(self) -> bool:
        """Proven, not merely unimproved. What 4.4 is trying to make true more often."""
        return self.solved and self.lower_bound == self.penalty

    def __post_init__(self) -> None:
        if self.explanation is not None and self.outcome is not Outcome.IMPOSSIBLE:
            raise ValueError(
                f"{self.outcome} carries an explanation of why no timetable exists, and it "
                "has not been shown that none does"
            )
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
        if self.lower_bound and not self.bound_is_proven:
            raise ValueError(
                f"a lower bound of {self.lower_bound} is reported with nothing having proven "
                "it — a Fix-and-Optimize round bounds its own window, not the term"
            )
        self._the_descent_makes_sense()

    def _the_descent_makes_sense(self) -> None:
        """What a monotone loop can never have produced (D5).

        Every round hands CP-SAT the incumbent as a hint and lets it move a subset, so the
        incumbent is a feasible point of the sub-problem and a round can only come back at or
        below it. Accepting only a strict improvement makes the accepted scores strictly
        decreasing — and that is a theorem about the loop rather than a hope about it, so a
        violation is a bug in the fixing rather than a bad run.

        The last accepted round is also the answer. A loop that improved and then returned
        something else would be the same defect as a score that disagrees with its breakdown:
        two numbers about one timetable, and no way to tell which is the timetable.
        """
        accepted = [step for step in self.trajectory if step.accepted]
        for earlier, later in pairwise(accepted):
            if later.penalty >= earlier.penalty:
                raise ValueError(
                    f"round {later.round} was accepted at {later.penalty}, which is not an "
                    f"improvement on round {earlier.round}'s {earlier.penalty}"
                )
        if accepted and accepted[-1].penalty != self.penalty:
            raise ValueError(
                f"the last accepted round scored {accepted[-1].penalty} and the answer scores "
                f"{self.penalty} — they are not the same timetable"
            )
