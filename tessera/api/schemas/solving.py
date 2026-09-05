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
    """One member of a minimal conflicting set, and the thing it is about."""

    summary: str = Field(
        description="The rule in the words the rules screen uses for it, e.g. 'No instructor "
        "teaches two sessions at once'. Subject-agnostic: the engine holds ids and the client "
        "holds names, so 'Prof. Sharma' is composed from this and `subject_id`."
    )
    detail: str = Field(
        default="",
        description="Why the rule is unconditional, where the domain says so, or the "
        "arithmetic behind a shortage — '64 sessions need 64 hours and the rooms that could "
        "take them offer 60'.",
    )
    subject_kind: str = Field(
        default="",
        description="instructor, room, group, constraint — or grid, for the one rule that "
        "belongs to the teaching week itself rather than to anything in it.",
    )
    subject_id: int | None = None


class InfeasibilityReport(Wire):
    """Why no valid timetable exists.

    The differentiating feature: every comparable tool reports "no solution found". This
    carries a set of requirements that cannot hold together, each linked to the screen that
    can relax it.
    """

    summary: str
    requirements: list[ConflictingRequirement] = Field(default_factory=list)
    suggestion: str = Field(
        default="",
        description="What is and is not known about the set. Every requirement listed is "
        "necessary — remove any one and a timetable becomes possible under the rest — but "
        "where several independent conflicts exist the solver reports one of them, so this "
        "never promises that relaxing a member is sufficient. It used to; it could not.",
    )


class PreflightProblem(Wire):
    summary: str
    detail: str = ""
    affected_session_ids: list[int] = Field(default_factory=list)
    fix_hint: str = ""
    subject_kind: str = Field(
        default="",
        description="instructor, room or group — what the shortage is about, so a client can "
        "name it and link to the screen that changes it. `ConflictingRequirement` has carried "
        "this since 1.4 and this model did not, so nothing reading a pre-flight could say "
        "*which* instructor was over-committed.",
    )
    subject_id: int | None = Field(
        default=None,
        description="Null where the argument is about the room estate as a whole rather than "
        "about one room.",
    )


class PreflightReport(Wire):
    """Structural problems detectable without solving.

    Runs in milliseconds. Failing after two minutes for a reason findable in fifty
    is the behaviour this exists to prevent (Decision #29).
    """

    can_solve: bool = Field(
        description="**Nothing here proves this term impossible** — which is weaker than a "
        "promise that it can be solved, and deliberately so. The checks behind this are "
        "counting arguments: each asks whether some set of sessions could fit in the resource "
        "that must hold them, ignoring every rule about where. One that fails proves the real "
        "problem cannot be satisfied either; none failing proves nothing at all. `Outcome` "
        "draws the same line between *we did not find one* and *there is not one*."
    )
    problems: list[PreflightProblem] = Field(default_factory=list)
    session_count: int = 0
    unplaceable_session_ids: list[int] = Field(default_factory=list)
