"""Which rules cannot hold together, when counting them was not enough.

`preflight` refutes what arithmetic can see: a set of sessions that does not fit in the
resource that has to hold it. What it cannot see is a *structural* contradiction — two
sessions pinned into one room at one hour, a person whose three classes must all be on
Tuesday and who is only in on Monday, a pair of distribution rules that contradict each
other. Nothing is short of anything there; the pieces simply do not fit together.

CP-SAT can say which pieces. Write each hard rule behind a literal of its own, assert every
literal, and on `INFEASIBLE` read back `sufficient_assumptions_for_infeasibility()` — a
subset of those rules that cannot all hold.

**Three things about that subset, all measured, and the report has to survive each.**

*It is minimal but not unique.* Every member is necessary — drop one and the term becomes
solvable, which `necessary_one_at_a_time` proves by re-solving rather than by asserting.
Where two independent contradictions exist, CP-SAT names one and never mentions the other,
so *relaxing one of these makes a timetable possible* is a sentence this cannot support and
does not print (D5).

*It costs the refutation.* A constraint behind a literal keeps its meaning and loses its
propagation: the same `cumulative` refutes a pigeonhole in **0.001 s** unconditional and
does not refute it in **ten seconds** from behind a literal (#275). So the relaxable model
is strictly worse at proving a term impossible than the model that just proved it, and this
runs only *after* something else has — never as the way of finding out.

*It can come back empty.* That means the model was refuted by something carrying no literal,
which in a model where every hard rule carries one is a defect rather than a case. It raises
instead of returning an explanation with nothing in it (D9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from tessera.solver import model as build_model
from tessera.solver import objective
from tessera.solver.result import Requirement

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tessera.domain.validation import Snapshot
    from tessera.solver.budget import Budget

__all__ = ["conflict", "necessary_one_at_a_time"]


def conflict(
    snapshot: Snapshot,
    budget: Budget,
    formulation: build_model.Formulation | None = None,
) -> tuple[Requirement, ...]:
    """A set of requirements that cannot hold together, or nothing if none was proven.

    Empty is an ordinary answer and means *not proven here*: the relaxable model is weaker
    than the one that refuted the term (#275), so it can run out of budget on a term that is
    genuinely impossible. Saying nothing is then correct — an explanation that named rules
    without having shown they conflict would be a guess wearing a proof's clothes.

    Raises `AssertionError` if the model is refuted with no literal in the core, because
    every hard rule in it carries one and a core of nothing means one of them does not.
    """
    model = build_model.build(snapshot, formulation, relaxable=True)
    objective.enforce(model, snapshot, relaxable=True)
    found = _core(model, budget, model.assumptions)
    if found is None:
        return ()
    if not found:
        raise AssertionError(
            "the relaxable model is infeasible with no rule to blame — some hard rule was "
            "written without an assumption literal, so it cannot be reported or relaxed"
        )
    return found


def necessary_one_at_a_time(
    snapshot: Snapshot,
    budget: Budget,
    found: Iterable[Requirement],
    formulation: build_model.Formulation | None = None,
) -> dict[Requirement, bool]:
    """Whether each member of a conflict is load-bearing, by asking without it.

    The deletion filter. For each requirement, assert every *other* member and nothing else:
    if the term becomes solvable, that requirement was necessary; if it stays infeasible, the
    conflict was not minimal and the report is claiming more than it has.

    Expensive — one solve per member — and it is a test's tool rather than a caller's. It
    lives here rather than in the tests because the property it checks is a property of
    `conflict`, and a check that lives beside what it checks is one implementation of the
    idea instead of two.
    """
    members = list(found)
    verdict: dict[Requirement, bool] = {}
    for dropped in members:
        model = build_model.build(snapshot, formulation, relaxable=True)
        objective.enforce(model, snapshot, relaxable=True)
        kept = {
            requirement: literal
            for requirement, literal in model.assumptions.items()
            if requirement in members and requirement != dropped
        }
        verdict[dropped] = _core(model, budget, kept) is None
    return verdict


def _core(
    model: build_model.Model,
    budget: Budget,
    assume: dict[Requirement, cp_model.IntVar],
) -> tuple[Requirement, ...] | None:
    """Solve asserting exactly `assume`, and read the conflict back. `None` if there is none.

    `None` covers both a term that has a timetable under these rules and a search that ran out
    of budget, and the difference does not matter to either caller: neither is a conflict, and
    reporting a timeout as one would be the failure `Outcome` exists to prevent.
    """
    model.cp.clear_assumptions()
    for literal in assume.values():
        model.cp.add_assumption(literal)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = budget.seconds
    solver.parameters.num_workers = budget.workers
    solver.parameters.random_seed = budget.seed
    if budget.deterministic_seconds is not None:
        solver.parameters.max_deterministic_time = budget.deterministic_seconds

    if solver.solve(model.cp) != cp_model.INFEASIBLE:
        return None

    named = {literal.index: requirement for requirement, literal in assume.items()}
    return tuple(
        sorted(
            (named[index] for index in solver.sufficient_assumptions_for_infeasibility()),
            key=lambda r: (r.rule, r.subject_kind, r.subject_id or 0),
        )
    )
