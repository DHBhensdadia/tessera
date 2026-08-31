"""One instance, one budget, several formulations — and no way to vary more than one.

Every claim from here to the end of the phase is a comparison, and the failure with precedent
in comparisons is moving two things at once: a formulation that "wins" because it was handed a
different instance, a different seed, or a longer budget than the thing it beat. So the
instrument takes the instance and the budget **once** and hands the same pair to each
formulation, rather than letting each carry its own. That is a structural guard rather than a
careful habit.

`work` is why the table can be believed twice. It is CP-SAT's own count of how much searching
it did, in a unit that does not depend on what else the machine was doing, so two runs of the
same row agree on it exactly while their wall clocks do not (D4).
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tessera.domain.validation import Snapshot
from tessera.solver import Budget, Outcome, solve
from tessera.solver.model import Formulation, build, size
from tessera.solver.objective import add as score


@dataclass(frozen=True, slots=True)
class Run:
    """What one formulation did with one instance."""

    name: str
    outcome: Outcome
    penalty: int
    bound: int
    seconds: float
    work: float
    built: float
    variables: int
    sessions: int
    candidates: int

    @property
    def optimal(self) -> bool:
        return self.outcome is Outcome.SOLVED and self.bound == self.penalty

    @property
    def gap(self) -> int:
        """How much of the score is not yet proven necessary.

        Absolute, not a percentage. P5's reporting rules for 4.5 say so for a reason measured
        in 0.1: on an instance whose optimum is near zero a ratio explodes — comp20 read
        +4525 % at an absolute gap of 181, which looks worse than comp05's +85 % at 242 and is
        not.
        """
        return self.penalty - self.bound


def measure(
    snapshot: Snapshot,
    *,
    name: str,
    budget: Budget,
    formulation: Formulation | None = None,
) -> Run:
    """Solve once and record everything the comparison might turn on.

    The model is built a second time to be counted and timed. That is deliberate waste in a
    measuring tool: `solve` does not report how big the model it made was, and a construction
    time is exactly the number #225 and the NFR-9 backlog entry both turn on, so it is worth a
    duplicated build to have it beside the score rather than in somebody's memory.

    **The objective is added before counting**, which is the whole point. #225's finding is
    that three of the sixteen terms multiply the model by six; a count taken after `build` and
    before `add` would report the 20,500 and miss the 470,000, and the row would say the model
    is small while the solver is failing to search it.
    """
    started = time.perf_counter()
    model = build(snapshot, formulation)
    score(model, snapshot)
    built = time.perf_counter() - started
    sessions, candidates = size(model)

    found = solve(snapshot, budget, formulation)
    return Run(
        name=name,
        outcome=found.outcome,
        penalty=found.penalty,
        bound=found.lower_bound,
        seconds=found.seconds,
        work=found.work,
        built=built,
        variables=len(model.cp.proto.variables),
        sessions=sessions,
        candidates=candidates,
    )


def compare(
    snapshot: Snapshot, budget: Budget, formulations: Mapping[str, Formulation]
) -> tuple[Run, ...]:
    """The same term and the same budget, under each formulation in turn."""
    return tuple(
        measure(snapshot, name=name, budget=budget, formulation=formulation)
        for name, formulation in formulations.items()
    )


@dataclass(frozen=True, slots=True)
class Portfolio:
    """What CP-SAT does with the same instance when it is allowed to run its own search.

    D1. One worker is a single search with no LNS in it, which is the deterministic control
    P5 asks for and also the weakest baseline available. Eight workers is CP-SAT's own
    portfolio, and that portfolio contains LNS subsolvers — a competing implementation of this
    phase's algorithm, written by the people who wrote the solver.

    Beating the first while not mentioning the second would be a true sentence and a dishonest
    result, so both numbers travel together in one object rather than in two tables somebody
    could publish separately.
    """

    instance: str
    seconds: float
    alone: tuple[int | None, ...]
    portfolio: tuple[int | None, ...]

    @staticmethod
    def _median(scores: Sequence[int | None]) -> int | None:
        """The median, per P5's reporting rules — and `None` if any seed found nothing.

        A run that found no timetable has no score, and averaging around it would report the
        seeds that happened to work as though they were the whole story.
        """
        if any(score is None for score in scores):
            return None
        return int(statistics.median([score for score in scores if score is not None]))

    @property
    def alone_median(self) -> int | None:
        return self._median(self.alone)

    @property
    def portfolio_median(self) -> int | None:
        return self._median(self.portfolio)


def against_the_portfolio(
    snapshot: Snapshot, *, instance: str, seconds: float, seeds: Sequence[int] = (0, 1, 2)
) -> Portfolio:
    """The same instance and the same wall clock, one worker and eight.

    **Wall clock, not work.** A parallel search cannot be given a deterministic budget — that
    is what parallel means — so the only budget the two share is time, and the comparison is
    only worth reading on an idle machine. Several seeds and a median rather than one run,
    because a single sample of a non-deterministic search is an anecdote: 0.1 watched `comp09`
    come back *worse* with five times the budget.
    """

    def scores(workers: int) -> tuple[int | None, ...]:
        return tuple(
            found.penalty if found.outcome is Outcome.SOLVED else None
            for seed in seeds
            for found in [solve(snapshot, Budget(seconds=seconds, workers=workers, seed=seed))]
        )

    return Portfolio(instance=instance, seconds=seconds, alone=scores(1), portfolio=scores(8))


def table(runs: Mapping[str, tuple[Run, ...]]) -> str:
    """The rows as a markdown table, for pasting into the phase record.

    Written out rather than printed from a test: a number that lives only in a terminal is a
    number nobody can check later, and every measurement this project has leaned on is in a
    document with the instance beside it.
    """
    lines = [
        "| instance | formulation | outcome | penalty | bound | gap | vars | built s | work | s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for instance, rows in runs.items():
        for run in rows:
            # A run that found nothing carries penalty 0, bound 0 and therefore gap 0 —
            # `Solution` refuses to attach a score to a failed solve, which is right, and in a
            # table of scores it reads as a perfect one. The formulation that gave up would be
            # the best row on the page.
            scored = (
                f"{run.penalty} | {run.bound} | {run.gap}"
                if run.outcome is Outcome.SOLVED
                else "— | — | —"
            )
            lines.append(
                f"| {instance} | {run.name} | {run.outcome.value}"
                f"{' (optimal)' if run.optimal else ''} | {scored} "
                f"| {run.variables:,} | {run.built:.2f} | {run.work:.1f} "
                f"| {run.seconds:.1f} |"
            )
    return "\n".join(lines)
