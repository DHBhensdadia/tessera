"""Running the solver, and reporting what came back.

**Two phases, and the split is load-bearing** (ADR-002). Finding *a* valid timetable and
finding a good one are different problems, and 4.4 part 1 measured how different: at 500
sessions with the default preferences, one solve of the scored model returns **nothing in
thirty seconds**, while the same term without the objective is solved to optimality in 4.6.
Three of the sixteen scored terms need a boolean per subject per hour, and carrying them into
the search for a first answer is what stops there being one (#225).

So feasibility runs against a model with the hard rules and no cost — including the hard
*distribution* rules, because a first timetable that breaks one is not a first timetable — and
everything about making it good belongs to `search`.

**Deterministic by default** (#206). `random_seed` is pinned and the worker count defaults to
one. Multiple workers are faster and give a different answer each run, which is the right trade
for a person waiting and the wrong one for a benchmark.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

from ortools.sat.python import cp_model

from tessera.domain.validation import Snapshot
from tessera.domain.validation.snapshot import Placement
from tessera.solver import model as build_model
from tessera.solver import preflight, search
from tessera.solver.budget import Budget
from tessera.solver.cost import CostModel, Preferences
from tessera.solver.result import Explanation, Outcome, Solution

__all__ = ["Budget", "solve"]


def solve(
    snapshot: Snapshot,
    budget: Budget | None = None,
    formulation: build_model.Formulation | None = None,
    on_improvement: Callable[[Solution], None] | None = None,
    costs: CostModel | None = None,
) -> Solution:
    """Find a timetable for this term, make it as good as the budget allows, or say why not.

    `costs` says what *better* means. It defaults to the term's own preferences, which is what
    every caller in the product wants and what this did before there was anything else to
    want; 4.5's benchmark passes CB-CTT's four soft constraints instead, so the published
    metric is computed by the search that ships rather than by a copy of it.
    """
    budget = budget or Budget()
    formulation = formulation or build_model.Formulation()
    costs = costs if costs is not None else Preferences(snapshot)

    started = time.perf_counter()

    shortfalls = preflight.check(snapshot, capacity_is_priced=formulation.capacity_is_priced)
    if shortfalls:
        # Counted, not searched. `comp01` is impossible for a reason that fits in one
        # sentence and CP-SAT does not reach in thirty seconds under any formulation this
        # project has (#213 and 4.6 §1a), so a term refuted here is one the search would
        # otherwise have spent the whole budget failing to refute.
        return Solution(
            outcome=Outcome.IMPOSSIBLE,
            seconds=time.perf_counter() - started,
            explanation=Explanation(shortfalls=shortfalls),
        )

    try:
        model = build_model.build(snapshot, formulation)
    except build_model.UnsatisfiableError as refusal:
        # A session with no possible hour, or two pins fighting over one room. Arithmetic
        # already knows the answer, so reporting it as `IMPOSSIBLE` without searching is
        # honest rather than a shortcut — and it is *proven*, which is what distinguishes it
        # from a timeout. The sentence names what it found, and used to be discarded here.
        return Solution(
            outcome=Outcome.IMPOSSIBLE,
            seconds=time.perf_counter() - started,
            explanation=Explanation(unbuildable=str(refusal)),
        )

    costs.enforce(model)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = budget.seconds
    solver.parameters.num_workers = budget.workers
    solver.parameters.random_seed = budget.seed
    if budget.deterministic_seconds is not None:
        solver.parameters.max_deterministic_time = budget.deterministic_seconds

    status = solver.solve(model.cp)
    elapsed = time.perf_counter() - started
    sessions, candidates = build_model.size(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Solution(
            outcome=Outcome.IMPOSSIBLE if status == cp_model.INFEASIBLE else Outcome.OUT_OF_TIME,
            seconds=elapsed,
            sessions=sessions,
            candidates=candidates,
            work=solver.deterministic_time,
        )

    first = {
        session_id: Placement(
            session_id=session_id,
            start_slot=solver.value(model.starts[session_id]),
            room_id=model.room_of(solver, session_id),
            is_pinned=snapshot.placements[session_id].is_pinned
            if session_id in snapshot.placements
            else False,
        )
        for session_id in sorted(model.starts)
    }

    found = search.improve(
        snapshot,
        budget=budget,
        formulation=formulation,
        incumbent=first,
        started=started,
        costs=costs,
        already=solver.deterministic_time,
        on_improvement=on_improvement,
    )
    return replace(found, sessions=sessions, candidates=candidates)
