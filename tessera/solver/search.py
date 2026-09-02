"""Fix-and-Optimize: freeze almost everything, re-solve a window, keep what is better.

ADR-002 chose this family on evidence, and R2 §4 states the loop. What it does not state is
why the loop is *necessary* rather than merely better, and 4.4 part 1 measured that: the three
model-level improvements P5 asked to be tried first are indistinguishable from seed noise, and
at department scale with the default preferences a single solve returns **nothing at all** in
thirty seconds. The outer search is not an optimisation on top of a working solver. It is what
makes the solver work at that size.

**Why a round is small, and not merely constrained.** Freezing by adding equalities would leave
the model exactly as large as before and simply forbid most of it: three of the sixteen scored
terms need a boolean per subject per hour, and at 500 sessions that is 182,694 variables and
2.15 seconds to construct, every round. Freezing by narrowing a session's domain to the one
hour and the one room it currently occupies leaves it a single boolean in each channel, and the
same round costs **40,531 variables and 0.46 seconds**. That ratio is the loop.

**A round cannot make things worse.** The incumbent is a feasible point of every sub-problem —
the frozen sessions are already at their values and the free ones may simply stay — so with the
incumbent hinted, the round returns something at or below what it started with. Accepting only
a strict improvement makes the whole descent monotone, which is a theorem about the arrangement
rather than a policy applied to it, and `Solution` refuses a trajectory that violates it.

**A round's lower bound is not the term's.** It bounds the restricted problem, which is a
different and easier one. Only an unrestricted attempt sets `lower_bound`, and `bound_is_proven`
says whether anything did.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from ortools.sat.python import cp_model

from tessera.domain.ids import SessionId
from tessera.domain.validation import Snapshot
from tessera.domain.validation.snapshot import Placement
from tessera.solver import model as build_model
from tessera.solver import neighbourhood
from tessera.solver.budget import Budget
from tessera.solver.cost import CostModel
from tessera.solver.objective import Objective
from tessera.solver.result import Outcome, Placed, Solution, Step


@dataclass(frozen=True, slots=True)
class Attempt:
    """One CP-SAT solve, read back."""

    placements: dict[SessionId, Placement]
    penalty: int
    breakdown: dict[str, int]
    bound: int
    proven: bool
    seconds: float
    work: float


def improve(
    snapshot: Snapshot,
    *,
    budget: Budget,
    formulation: build_model.Formulation,
    incumbent: Mapping[SessionId, Placement],
    started: float,
    costs: CostModel,
    already: float = 0.0,
    on_improvement: Callable[[Solution], None] | None = None,
) -> Solution:
    """Make a timetable better until the budget runs out, never returning a worse one.

    The whole problem is attempted first when it is small enough to hold, and **cold**: handing
    CP-SAT the feasibility answer as a starting point for a fresh optimisation makes it markedly
    worse, because an arbitrary valid timetable is a bad neighbourhood to anchor a search in.
    The rounds that follow are warm, where the incumbent is the thing being improved.

    **`costs` is what "better" means, and this function does not know.** Tessera's sixteen
    weighted rules are one answer and CB-CTT's four are another (4.5's D1); everything below is
    the same either way, which is the whole point of the split.
    """
    rng = random.Random(budget.seed)
    # The loop supplies its own warm start, from the incumbent rather than from the term. A
    # `Formulation` that also hints would hint the same variables a second time, and CP-SAT
    # answers that with MODEL_INVALID — which cost a full suite run to find, because a round
    # that cannot build looks exactly like a round that found nothing.
    formulation = replace(formulation, hint=False)
    best = _what_it_costs(snapshot, formulation, incumbent, costs)
    if best is None and any(c.effective_weight for c in snapshot.constraints):
        # The two reasons this can be `None` are not alike. A term that prices nothing costs
        # nothing, and zero is the answer. A term that prices something and could not be
        # scored has a cost nobody measured, and reporting zero would be #235 once more: the
        # timetable that could not be judged comes back as the perfect one.
        raise AssertionError(
            "the incumbent could not be scored, so its cost is unknown and is not zero"
        )
    if best is None:
        # Nothing is priced, so every timetable is as good as every other and there is no
        # search to run. Not an error: a term may carry no preferences at all.
        return _answer(
            incumbent,
            penalty=0,
            breakdown={},
            bound=0,
            proven=False,
            trajectory=(),
            seconds=time.perf_counter() - started,
            work=already,
            snapshot=snapshot,
        )

    trajectory: list[Step] = []
    bound, proven = 0, False
    # Work accumulates across every phase. Reporting only the feasibility pass would say a
    # thirty-second optimisation cost whatever the first four seconds cost, and #231's whole
    # point is that this number is the one a benchmark can compare.
    work = already + best.work

    whole = build_model.build(snapshot, formulation)
    objective = costs.add(whole)
    assert objective is not None  # `_what_it_costs` already established that something is

    if len(whole.cp.proto.variables) <= budget.whole_model_ceiling:
        attempt, spent, burnt = _run(
            whole,
            objective,
            incumbent=best.placements,
            warm=False,
            budget=budget,
            seconds=_share(budget, started),
            deterministic=budget.deterministic_seconds,
        )
        work += burnt
        if attempt is not None:
            improved = attempt.penalty < best.penalty
            trajectory.append(
                Step(
                    round=0,
                    strategy="whole",
                    freed=0,
                    penalty=min(attempt.penalty, best.penalty),
                    seconds=spent,
                    accepted=improved,
                )
            )
            bound, proven = attempt.bound, True
            if improved:
                best = attempt
                _tell(on_improvement, snapshot, best, bound, proven, trajectory, started, work)
            if attempt.proven and best.penalty == bound:
                return _answer(
                    best.placements,
                    penalty=best.penalty,
                    breakdown=best.breakdown,
                    bound=bound,
                    proven=True,
                    trajectory=tuple(trajectory),
                    seconds=time.perf_counter() - started,
                    work=work,
                    snapshot=snapshot,
                )

    # Bound to *this* cost model's reading of what a session costs. With the validator's
    # ranking and a CB-CTT objective, `worst_first` would free the sessions Tessera dislikes
    # while the search minimised something else — a loop that runs, improves, and reports a
    # worse solver than the one that is there.
    strategies = neighbourhood.with_blame(costs.blame)
    rotation = budget.strategies or tuple(strategies)
    turn = len(trajectory)
    while _keep_going(budget, started, turn, best.penalty):
        named = rotation[turn % len(rotation)]
        window = budget.windows[turn % len(budget.windows)]
        free = strategies[named](snapshot, best.placements, rng, window)
        frozen = {s: p for s, p in best.placements.items() if s not in free}
        sub = build_model.build(snapshot, formulation, frozen)
        priced = costs.add(sub)
        assert priced is not None

        attempt, spent, burnt = _run(
            sub,
            priced,
            incumbent=best.placements,
            warm=True,
            budget=budget,
            seconds=min(budget.round_seconds, _left(budget, started)),
            deterministic=budget.round_deterministic_seconds,
        )
        work += burnt
        improved = attempt is not None and attempt.penalty < best.penalty
        trajectory.append(
            Step(
                round=turn,
                strategy=named,
                freed=len(free),
                penalty=attempt.penalty if improved and attempt else best.penalty,
                seconds=spent,
                accepted=improved,
            )
        )
        if improved and attempt is not None:
            best = attempt
            _tell(on_improvement, snapshot, best, bound, proven, trajectory, started, work)
        turn += 1

    return _answer(
        best.placements,
        penalty=best.penalty,
        breakdown=best.breakdown,
        bound=bound,
        proven=proven,
        trajectory=tuple(trajectory),
        seconds=time.perf_counter() - started,
        work=work,
        snapshot=snapshot,
    )


def _what_it_costs(
    snapshot: Snapshot,
    formulation: build_model.Formulation,
    placed: Mapping[SessionId, Placement],
    costs: CostModel,
) -> Attempt | None:
    """What the solver's own objective makes of a timetable it has already got.

    The loop needs a number to improve on, and it has to be **the solver's** number. Asking the
    validator would be quicker and would couple the two readings that 4.1 kept apart on purpose
    — 4.3 proved they agree, and that proof is worth something only while neither is derived
    from the other.

    Freezing every session gives a model with exactly one solution, so this is a read rather
    than a search: every domain is a single value and CP-SAT has nothing to decide.

    `None` when the term prices nothing, which is a term with no preferences rather than an
    error.
    """
    model = build_model.build(snapshot, formulation, placed)
    objective = costs.add(model)
    if objective is None:
        return None
    attempt, _, _ = _run(
        model,
        objective,
        incumbent=placed,
        warm=True,
        budget=Budget(seconds=30.0),
        seconds=30.0,
        deterministic=None,
    )
    return attempt


def _run(
    model: build_model.Model,
    objective: Objective,
    *,
    incumbent: Mapping[SessionId, Placement],
    warm: bool,
    budget: Budget,
    seconds: float,
    deterministic: float | None,
) -> tuple[Attempt | None, float, float]:
    """Minimise, optionally from the timetable in hand. Returns the attempt, seconds and work.

    **`warm` is false for the unrestricted attempt, and that is not a detail.** Handing CP-SAT
    the feasibility answer as a starting point for a *fresh* optimisation makes it markedly
    worse — 3,470 to 4,565 on `comp05`, 1,434 to 2,273 on `comp11`, 603 to 835 on a generated
    department — because an arbitrary valid timetable is a bad neighbourhood to anchor the
    search in, and the solver spends its budget near it.

    A round is the opposite case and stays warm: there the incumbent is the thing being
    improved rather than an accident of how feasibility was reached, and starting from it is
    what makes a round unable to come back worse.

    `None` when the round came back with nothing, which is a real outcome rather than an error:
    a hint is advice and not a floor, so a sub-solve given too little time can fail to produce
    even the timetable it was handed — and the log says exactly why, that the hint covers the
    decision variables and not the objective's own, so CP-SAT cannot evaluate it as a solution.

    **What it cost comes back either way** — both the seconds and the work. Reporting a failed
    round as having taken nothing is #235 again: the round that gave up looks like the cheap
    one, a trajectory full of instant refusals reads as a loop with budget to spare rather than
    one whose window was too big to solve, and a run that spent its whole deterministic budget
    failing reports having done no work at all.
    """
    if warm:
        build_model.start_from(model, incumbent)
    model.cp.minimize(objective.total)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(seconds, 0.0)
    solver.parameters.num_workers = budget.workers
    solver.parameters.random_seed = budget.seed
    if deterministic is not None:
        solver.parameters.max_deterministic_time = deterministic

    began = time.perf_counter()
    status = solver.solve(model.cp)
    elapsed = time.perf_counter() - began

    # A model CP-SAT will not read is a bug in this file, not an unlucky round, and the two
    # are one enum apart. Treating them alike hid a duplicated solution hint behind forty-one
    # failing tests in another module — every round silently returning nothing, and the loop
    # reporting that it had simply not found an improvement.
    if status == cp_model.MODEL_INVALID:
        raise AssertionError(f"the sub-problem is not a valid model: {model.cp.validate()[:400]}")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, elapsed, solver.deterministic_time

    found = Attempt(
        placements={
            session_id: Placement(
                session_id=session_id,
                start_slot=solver.value(model.starts[session_id]),
                room_id=model.room_of(solver, session_id),
                is_pinned=incumbent[session_id].is_pinned if session_id in incumbent else False,
            )
            for session_id in sorted(model.starts)
        },
        penalty=objective.penalty(solver),
        breakdown=objective.breakdown(solver),
        bound=math.ceil(solver.best_objective_bound - 1e-6),
        proven=status == cp_model.OPTIMAL,
        seconds=elapsed,
        work=solver.deterministic_time,
    )
    return found, elapsed, solver.deterministic_time


#: Held back from the wall-clock budget so a solve finishes *inside* it rather than around it.
#: CP-SAT's time limit is a target and not a guarantee, and a round that stops on time still
#: has to be read back and scored — which is how a thirty-second budget returned at 30.013 s.
RESERVE = 0.5


def _left(budget: Budget, started: float) -> float:
    """How much of the wall clock is left to spend, less what it takes to stop cleanly."""
    return budget.seconds - RESERVE - (time.perf_counter() - started)


def _share(budget: Budget, started: float) -> float:
    """What the one unrestricted attempt may take.

    All of it, unless the caller says otherwise — which is what it always did, and what makes a
    long budget spend everything on a single solve and never reach a round (`Budget.whole_seconds`).
    """
    left = _left(budget, started)
    return left if budget.whole_seconds is None else min(left, budget.whole_seconds)


def _keep_going(budget: Budget, started: float, turn: int, penalty: int) -> bool:
    """Whether there is another round worth running.

    **Nothing is worth running once the penalty is zero.** Every term is a sum of
    non-negative units, so a timetable that costs nothing is optimal and no rearrangement can
    beat it — the loop otherwise spent a full three hundred seconds and a hundred and fifty
    rounds on a term it had already finished, which is not anytime behaviour but a busy wait.


    A round count wins over the clock when both are set: that is the whole point of counting
    rounds, and a loop that stopped early because the machine was slow would give back the
    reproducibility the count was asked for. `seconds` is still a ceiling, and a test asserts
    a round-budgeted run does not reach it.
    """
    if penalty == 0:
        return False
    if budget.rounds is not None:
        return turn < budget.rounds
    return _left(budget, started) > budget.round_seconds


def _answer(
    placed: Mapping[SessionId, Placement],
    *,
    penalty: int,
    breakdown: dict[str, int],
    bound: int,
    proven: bool,
    trajectory: tuple[Step, ...],
    seconds: float,
    work: float,
    snapshot: Snapshot,
) -> Solution:
    sessions, candidates = len(snapshot.sessions), 0
    return Solution(
        outcome=Outcome.SOLVED,
        placements=tuple(
            Placed(session=s, start_slot=p.start_slot, room=p.room_id)
            for s, p in sorted(placed.items())
        ),
        seconds=seconds,
        sessions=sessions,
        candidates=candidates,
        penalty=penalty,
        penalty_breakdown=breakdown,
        lower_bound=bound,
        bound_is_proven=proven,
        trajectory=trajectory,
        work=work,
    )


def _tell(
    listener: Callable[[Solution], None] | None,
    snapshot: Snapshot,
    best: Attempt,
    bound: int,
    proven: bool,
    trajectory: list[Step],
    started: float,
    work: float,
) -> None:
    """Hand out the improved timetable as it happens.

    R2 promises the interface *"watch it get better, press stop when satisfied"*, and 4.7 turns
    this into an SSE stream. It is here rather than there so the loop has one emission point
    instead of 4.7 reaching in to find its own — and it fires only on an accepted round, so a
    listener sees the descent and not the attempts.
    """
    if listener is None:
        return
    listener(
        _answer(
            best.placements,
            penalty=best.penalty,
            breakdown=best.breakdown,
            bound=bound,
            proven=proven,
            trajectory=tuple(trajectory),
            seconds=time.perf_counter() - started,
            work=work,
            snapshot=snapshot,
        )
    )
