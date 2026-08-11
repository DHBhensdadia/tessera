"""Solving: pre-flight, jobs, live progress, and the infeasibility report.

A solve takes seconds to minutes, so it cannot be a blocking request. POST returns a job
identifier, progress streams over SSE, and the result is fetched separately — which is
also what makes "watch the score fall and stop when it is good enough" possible.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending
from tessera.api.schemas import (
    InfeasibilityReport,
    PreflightReport,
    SolveRequest,
    SolveStatus,
)

router = APIRouter(prefix="/api/v1", tags=["solving"])
ERRORS = problem_responses(404, 409, 422, 501)


@router.post("/terms/{term_id}/preflight", response_model=PreflightReport, responses=ERRORS)
def preflight(term_id: int) -> PreflightReport:
    """Structural problems findable without solving, in milliseconds.

    Failing after two minutes for a reason detectable in fifty milliseconds is the
    behaviour this exists to prevent.
    """
    pending("4.7", "Pre-flight checking")


@router.post(
    "/terms/{term_id}/solve",
    response_model=SolveStatus,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
def start_solve(term_id: int, payload: SolveRequest) -> SolveStatus:
    pending("4.7", "Solving")


@router.get("/solve/{job_id}", response_model=SolveStatus, responses=ERRORS)
def solve_status(job_id: str) -> SolveStatus:
    pending("4.7")


@router.get(
    "/solve/{job_id}/result",
    response_model=InfeasibilityReport,
    responses=problem_responses(404, 409, 501),
)
def solve_result(job_id: str) -> InfeasibilityReport:
    """The explanation when no valid timetable exists.

    Not "no solution found": the minimal set of requirements that cannot hold together,
    each linked to the screen that can relax one.
    """
    pending("4.6", "Infeasibility explanation")


@router.get(
    "/solve/{job_id}/stream",
    responses=problem_responses(404, 501),
    response_class=StreamingResponse,
    summary="Server-sent stream of improving solutions",
)
async def solve_stream(job_id: str) -> StreamingResponse:
    """Emits an event per improved solution, carrying score and elapsed time.

    A native property of the solver rather than a simulated progress bar: CP-SAT calls
    back on every improvement, and those callbacks are what this forwards.
    """
    pending("4.7", "Live solve progress")


@router.post("/solve/{job_id}/cancel", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def cancel_solve(job_id: str) -> None:
    pending("4.7")
