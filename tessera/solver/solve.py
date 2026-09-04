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
from tessera.solver import explain, preflight, search
from tessera.solver import model as build_model
from tessera.solver.budget import Budget
from tessera.solver.cancel import Stop
from tessera.solver.cost import CostModel, Preferences
from tessera.solver.result import Explanation, Outcome, Progress, Solution

__all__ = ["Budget", "Stop", "solve"]


def solve(
    snapshot: Snapshot,
    budget: Budget | None = None,
    formulation: build_model.Formulation | None = None,
    on_improvement: Callable[[Solution], None] | None = None,
    costs: CostModel | None = None,
    on_progress: Callable[[Progress], None] | None = None,
    stop: Stop | None = None,
) -> Solution:
    """Find a timetable for this term, make it as good as the budget allows, or say why not.

    `costs` says what *better* means. It defaults to the term's own preferences, which is what
    every caller in the product wants and what this did before there was anything else to
    want; 4.5's benchmark passes CB-CTT's four soft constraints instead, so the published
    metric is computed by the search that ships rather than by a copy of it.

    **`on_progress` and `on_improvement` are not the same promise.** `on_improvement` fires
    once per *accepted round* and its scores strictly decrease, which is what 4.4 asserts and
    what makes it the right thing to hand a listener that stores timetables. `on_progress`
    fires whenever anything is known — the feasibility pass finishing, CP-SAT's own solutions
    during an unrestricted attempt, a round being accepted — and carries a score rather than a
    timetable. 4.7 measured why both exist: on two real terms out of three, an accepted round
    happens **once or never** inside thirty seconds, so a progress panel fed by the first of
    these watches nothing at all.

    `stop` lets another thread end the search. It is honoured between rounds *and* inside a
    running solve; a flag alone is answered up to a whole budget late (`cancel.Stop`).
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

    searched = True
    if stop is None:
        status = solver.solve(model.cp)
    else:
        with stop.running(solver) as too_late:
            # `UNKNOWN` rather than searching: a cancel that landed while the model was being
            # built has already been answered, and starting a solve to abandon it would be a
            # whole budget of searching for a question nobody is waiting on.
            searched = not too_late
            status = solver.solve(model.cp) if searched else cp_model.UNKNOWN
    elapsed = time.perf_counter() - started
    sessions, candidates = build_model.size(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        proven = status == cp_model.INFEASIBLE
        return Solution(
            outcome=Outcome.IMPOSSIBLE if proven else Outcome.OUT_OF_TIME,
            stopped=stop is not None and stop.requested,
            seconds=elapsed,
            sessions=sessions,
            candidates=candidates,
            # A search that never started did no work, and asking CP-SAT how much it did
            # raises rather than answering zero — there is no response to read.
            work=solver.deterministic_time if searched else 0.0,
            # Only once something has proved there is no timetable. Running out of time says
            # nothing about whether one exists, and a set of rules attached to that would read
            # as a reason to change the data when the honest answer is "we did not find one".
            explanation=_why_not(snapshot, budget, formulation) if proven else None,
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

    if on_progress is not None:
        # The moment P7 draws as its own line — *"Feasible solution found in 6s"* — and it is
        # genuinely earlier than any score: what this timetable costs is not known until
        # `improve` prices it, which is a whole model build later. 5.10 s against 7.93 s at
        # department scale, measured, and the person waiting should hear the first one.
        on_progress(
            Progress(phase="feasibility", seconds=time.perf_counter() - started, solutions=0)
        )

    found = search.improve(
        snapshot,
        budget=budget,
        formulation=formulation,
        incumbent=first,
        started=started,
        costs=costs,
        already=solver.deterministic_time,
        on_improvement=on_improvement,
        on_progress=on_progress,
        stop=stop,
    )
    return replace(found, sessions=sessions, candidates=candidates)


def _why_not(
    snapshot: Snapshot, budget: Budget, formulation: build_model.Formulation
) -> Explanation | None:
    """Which rules cannot hold together, if the weaker model can be made to say.

    Deliberately *after* the refutation rather than instead of it. The model that names rules
    is the one that cannot prove them contradictory in reasonable time (#275), so asking it
    first would trade a proof for a sentence and often get neither.

    `None` when nothing was proven inside `explain_seconds`, and that is not an error: the
    term still has no timetable and `Outcome` still says so. Only the sentence is missing.
    """
    found = explain.conflict(snapshot, replace(budget, seconds=budget.explain_seconds), formulation)
    return Explanation(conflict=found) if found else None
