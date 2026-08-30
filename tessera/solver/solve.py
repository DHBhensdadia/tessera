"""Running the model, and reporting what came back.

**Deterministic by default** (D5). P5 warns at 4.5 that parallel CP-SAT is non-deterministic
and that Phase 0.1 saw `comp09` score *worse* with five times the budget. Settling it here
means every number this phase and the next two produce can be reproduced; settling it at 4.5
would mean re-running everything that came before it.

So: `random_seed` is pinned, and the worker count is a parameter with a single-worker default.
Multiple workers are faster and give a different answer each run, which is the right trade for
a person waiting and the wrong one for a benchmark.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from tessera.domain.validation import Snapshot
from tessera.solver import model as build_model
from tessera.solver import objective as score
from tessera.solver.result import Outcome, Placed, Solution


@dataclass(frozen=True, slots=True)
class Budget:
    """How long to search, and how reproducibly.

    A named type rather than four keyword arguments, because these travel together and 4.4
    will add to them.
    """

    seconds: float = 30.0
    """NFR-4 asks for a first feasible solution at department scale in under 30 seconds."""

    workers: int = 1
    """One by default. Deterministic, and what every test and benchmark should use."""

    seed: int = 0


def solve(snapshot: Snapshot, budget: Budget | None = None) -> Solution:
    """Find a timetable for this term, or say why there is not one."""
    budget = budget or Budget()

    started = time.perf_counter()
    try:
        model = build_model.build(snapshot)
    except build_model.UnsatisfiableError:
        # A session with no possible hour or no possible room. Arithmetic already knows the
        # answer, so reporting it as `IMPOSSIBLE` without searching is honest rather than a
        # shortcut — and it is *proven*, which is what distinguishes it from a timeout.
        return Solution(outcome=Outcome.IMPOSSIBLE, seconds=time.perf_counter() - started)

    # After the model, because the terms are arithmetic over its variables — and before the
    # search, because a hard rule pinned to zero violations has to be there to be obeyed.
    objective = score.add(model, snapshot)
    if objective is not None:
        model.cp.minimize(objective.total)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = budget.seconds
    solver.parameters.num_workers = budget.workers
    solver.parameters.random_seed = budget.seed

    status = solver.solve(model.cp)
    elapsed = time.perf_counter() - started
    sessions, candidates = build_model.size(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Solution(
            outcome=Outcome.SOLVED,
            placements=tuple(
                Placed(
                    session=session_id,
                    start_slot=solver.value(model.starts[session_id]),
                    room=model.room_of(solver, session_id),
                )
                for session_id in sorted(model.starts)
            ),
            seconds=elapsed,
            sessions=sessions,
            candidates=candidates,
            penalty=objective.penalty(solver) if objective else 0,
            penalty_breakdown=objective.breakdown(solver) if objective else {},
            lower_bound=_bound(solver) if objective else 0,
        )

    return Solution(
        outcome=Outcome.IMPOSSIBLE if status == cp_model.INFEASIBLE else Outcome.OUT_OF_TIME,
        seconds=elapsed,
        sessions=sessions,
        candidates=candidates,
    )


def _bound(solver: cp_model.CpSolver) -> int:
    """The best proof CP-SAT has that no timetable scores lower.

    Rounded **up**, because the objective is a sum of integers: a bound of 4.2 means no
    solution costs 4. Reported unclamped on purpose — a negative bound is exactly the defect
    Phase 0.1 shipped for a phase, and `Solution` refuses to carry one, so hiding it behind a
    `max(0, ...)` here would remove the only thing that notices.
    """
    return math.ceil(solver.best_objective_bound - 1e-6)
