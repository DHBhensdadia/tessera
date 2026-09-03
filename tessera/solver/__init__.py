"""Timetable generation: a CP-SAT model driven by a Fix-and-Optimize search.

Feasibility and optimisation are separate phases. Finding *a* valid timetable is fast;
finding a good one is not, and the outer search is what closes that gap (ADR-002).
"""

from tessera.solver.budget import Budget
from tessera.solver.model import Formulation
from tessera.solver.preflight import Shortfall
from tessera.solver.result import Explanation, Outcome, Placed, Requirement, Solution, Step
from tessera.solver.solve import solve

__all__ = [
    "Budget",
    "Explanation",
    "Formulation",
    "Outcome",
    "Placed",
    "Requirement",
    "Shortfall",
    "Solution",
    "Step",
    "solve",
]
