"""Solve jobs, pre-flight checks, and the infeasibility report.

Solving takes seconds to minutes, so it is a job rather than a request: POST returns an
identifier, progress streams over SSE, and the result is fetched separately.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from tessera.api.schemas.common import Wire


class SolveRequest(Wire):
    time_budget_seconds: int = Field(default=300, ge=1, le=3600)
    seed_timetable_id: int | None = Field(
        default=None,
        description="Warm start from this timetable, keeping its pinned assignments "
        "fixed. How re-optimising around manual edits works.",
    )
    respect_pins: bool = True


class SolvePhase(StrEnum):
    QUEUED = "queued"
    FEASIBILITY = "feasibility"
    OPTIMISING = "optimising"
    DONE = "done"
    INFEASIBLE = "infeasible"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SolveStatus(Wire):
    job_id: str
    phase: SolvePhase
    elapsed_seconds: float = 0.0
    penalty: int | None = Field(
        default=None, description="Best score so far; null before feasible."
    )
    penalty_breakdown: dict[str, int] = Field(default_factory=dict)
    lower_bound: int | None = None
    solutions_found: int = 0
    timetable_id: int | None = Field(default=None, description="Set once a solution exists.")


class ConflictingRequirement(Wire):
    """One member of a minimal conflicting set."""

    summary: str = Field(
        description="Plain language, e.g. 'Prof. Sharma is available Mon-Wed only'."
    )
    detail: str = ""
    subject_kind: str = Field(
        default="", description="instructor, room, group, course or constraint."
    )
    subject_id: int | None = None


class InfeasibilityReport(Wire):
    """Why no valid timetable exists.

    The differentiating feature: every comparable tool reports "no solution found". This
    carries the minimal set of requirements that cannot hold together, each linked to
    the screen that can relax it.
    """

    summary: str
    requirements: list[ConflictingRequirement] = Field(default_factory=list)
    suggestion: str = Field(default="", description="What relaxing any one of them would achieve.")


class PreflightProblem(Wire):
    summary: str
    detail: str = ""
    affected_session_ids: list[int] = Field(default_factory=list)
    fix_hint: str = ""


class PreflightReport(Wire):
    """Structural problems detectable without solving.

    Runs in milliseconds. Failing after two minutes for a reason findable in fifty
    is the behaviour this exists to prevent (Decision #29).
    """

    can_solve: bool
    problems: list[PreflightProblem] = Field(default_factory=list)
    session_count: int = 0
    unplaceable_session_ids: list[int] = Field(default_factory=list)
