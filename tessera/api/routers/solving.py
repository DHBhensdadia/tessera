"""Solving: pre-flight, jobs, live progress, and the infeasibility report.

A solve takes seconds to minutes, so it cannot be a blocking request. POST returns a job
identifier, progress streams over SSE, and the result is fetched separately — which is
also what makes "watch the score fall and stop when it is good enough" possible.

**The term is loaded here, on the request thread, and that is deliberate.** Reading a
department-sized term is 27 to 37 ms; a job that started and then discovered it had no term
would turn a 404 into a failure a client has to poll for.
"""

from __future__ import annotations

import anyio.to_thread
from fastapi import APIRouter, status
from sse_starlette.sse import EventSourceResponse

from tessera.api.deps import Db, Jobs
from tessera.api.errors import ERROR_BASE, ProblemError, problem_responses
from tessera.api.jobs import AlreadySolvingError, Job, events
from tessera.api.schemas import (
    ConflictingRequirement,
    InfeasibilityReport,
    PreflightProblem,
    PreflightReport,
    SolvePhase,
    SolveRequest,
    SolveStatus,
)
from tessera.domain.constraints import INVARIANT_BY_KEY
from tessera.domain.validation import Snapshot
from tessera.repository import snapshot as snapshot_repo
from tessera.solver import Shortfall
from tessera.solver.preflight import check
from tessera.solver.result import Explanation

router = APIRouter(prefix="/api/v1", tags=["solving"])
ERRORS = problem_responses(404, 409, 422, 501)


@router.post("/terms/{term_id}/preflight", response_model=PreflightReport, responses=ERRORS)
def preflight(term_id: int, db: Db) -> PreflightReport:
    """Structural problems findable without solving, in milliseconds.

    Failing after two minutes for a reason detectable in fifty milliseconds is the
    behaviour this exists to prevent.
    """
    return preflight_report(snapshot_repo.load(db, term_id))


def preflight_report(term: Snapshot) -> PreflightReport:
    """The counting checks on a loaded term.

    A function rather than only a handler because the console runs the same check before it
    starts a job (4.8 D7) and must say the same thing about it. Two readings of *what is
    structurally wrong with this term* is the drift #168 was written about.
    """
    shortfalls = check(term)
    return PreflightReport(
        can_solve=not shortfalls,
        problems=[_problem(shortfall) for shortfall in shortfalls],
        session_count=len(term.sessions),
        # A set that can occupy nothing has every member individually stuck. Where the
        # supply is merely too small the set collides but no one session is unplaceable, and
        # listing them all would send somebody to look at sessions that are individually
        # fine.
        unplaceable_session_ids=sorted(
            {
                int(session_id)
                for shortfall in shortfalls
                if shortfall.available == 0
                for session_id in shortfall.sessions
            }
        ),
    )


@router.post(
    "/terms/{term_id}/solve",
    response_model=SolveStatus,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
async def start_solve(term_id: int, payload: SolveRequest, db: Db, jobs: Jobs) -> SolveStatus:
    """Begin a solve and answer with the job that is running it.

    202 rather than 201: nothing has been created yet, and whether anything will be is the
    question the job exists to answer.

    **`async` because the job outlives the request.** A sync handler runs in Starlette's
    threadpool, where there is no running loop to attach a task to; the reading of the term
    goes to a thread of its own instead, so the 27 to 37 ms it costs at department scale is
    not spent on the loop.
    """
    term = await anyio.to_thread.run_sync(
        lambda: snapshot_repo.load(
            db,
            term_id,
            seed_timetable_id=payload.seed_timetable_id,
            respect_pins=payload.respect_pins,
        )
    )
    if not term.sessions:
        # Caught here rather than in the solver, because `Solution` refuses a solved timetable
        # with no placements on purpose (4.1's D6: a solver must not pass by leaving sessions
        # out) and an empty term would trip that invariant from the wrong side. A term nobody
        # has put anything in yet is an ordinary state on the first day, not a failure.
        raise ProblemError(
            status_code=status.HTTP_409_CONFLICT,
            title="Nothing to schedule",
            detail=f"Term {term_id} has no sessions yet. Add teaching before generating.",
            error_type=f"{ERROR_BASE}/nothing-to-schedule",
        )

    try:
        job = jobs.start(term, term_id=term_id, wanted=payload)
    except AlreadySolvingError as busy:
        raise ProblemError(
            status_code=status.HTTP_409_CONFLICT,
            title="A solve is already running",
            detail=f"Job {busy.job_id} has the engine. Watch or cancel it first.",
            error_type=f"{ERROR_BASE}/already-solving",
        ) from busy
    return job.reading()


@router.get("/solve/{job_id}", response_model=SolveStatus, responses=ERRORS)
def solve_status(job_id: str, jobs: Jobs) -> SolveStatus:
    return _job(job_id, jobs).reading()


@router.get(
    "/solve/{job_id}/result",
    response_model=InfeasibilityReport,
    responses=problem_responses(404, 409, 501),
)
def solve_result(job_id: str, jobs: Jobs) -> InfeasibilityReport:
    """The explanation when no valid timetable exists.

    Not "no solution found": the minimal set of requirements that cannot hold together,
    each linked to the screen that can relax one.
    """
    job = _job(job_id, jobs)
    if job.status.phase is not SolvePhase.INFEASIBLE or job.explanation is None:
        raise ProblemError(
            status_code=status.HTTP_409_CONFLICT,
            title="Nothing was proven impossible",
            detail=(
                f"Job {job_id} ended {job.status.phase.value}. An infeasibility report exists "
                "only where something proved there is no timetable."
            ),
            error_type=f"{ERROR_BASE}/not-infeasible",
        )
    return infeasibility_report(job.explanation)


#: What the stream sends, declared so a generated client can see it.
#:
#: The frozen contract said `200: Successful Response` with no content at all, which made the
#: payload the one part of this API a client could not generate from — 4.8 and 5.3 would each
#: have read the shape out of the source and agreed with it by convention, which is the shape
#: most drift in this project has taken. Three named events carry a `SolveStatus`: `status` on
#: every tick, `phase` when the solve moves between them, and `done` once, last.
STREAM = {
    200: {
        "description": (
            "An event every 250 ms until the job settles. `status` carries the current "
            "`SolveStatus`, `phase` the name of a phase the solve has just entered, and "
            "`done` the final status, after which the stream closes."
        ),
        "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/SolveStatus"}}},
    },
    **problem_responses(404, 501),
}


@router.get(
    "/solve/{job_id}/stream",
    responses=STREAM,
    response_class=EventSourceResponse,
    summary="Server-sent stream of improving solutions",
)
async def solve_stream(job_id: str, jobs: Jobs) -> EventSourceResponse:
    """Where the solve has got to, four times a second, until it settles.

    **Not a simulated progress bar, and not only the improvements either.** The score comes
    from three places — the feasibility pass finishing, CP-SAT's own solutions during an
    unrestricted attempt, and each accepted Fix-and-Optimize round — because on two real
    terms out of three the last of those fires once or never in thirty seconds.

    The first event carries the whole current status, so attaching late costs nothing.
    """
    return EventSourceResponse(events(_job(job_id, jobs)))


@router.post("/solve/{job_id}/cancel", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def cancel_solve(job_id: str, jobs: Jobs) -> None:
    """Stop searching and keep whatever was found.

    Idempotent, including on a job that has already finished: pressing *Stop* a moment after
    the answer arrived is not a mistake worth an error about.
    """
    jobs.cancel(_job(job_id, jobs))


def _job(job_id: str, jobs: Jobs) -> Job:
    job = jobs.get(job_id)
    if job is None:
        raise ProblemError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such solve",
            detail=(
                f"Job {job_id} is not running and is not remembered. Jobs do not survive an "
                "engine restart, and only the most recent are kept."
            ),
            error_type=f"{ERROR_BASE}/no-such-job",
        )
    return job


def _problem(shortfall: Shortfall) -> PreflightProblem:
    """One counting argument, as a line somebody can act on.

    The rule's own sentence comes from the domain and the arithmetic from the shortfall, which
    is the division D8 settled: an eighth set of prose here would drift from the rules screen.
    """
    invariant = INVARIANT_BY_KEY.get(shortfall.rule)
    return PreflightProblem(
        summary=invariant.statement if invariant else shortfall.rule,
        detail=shortfall.statement,
        affected_session_ids=[int(session_id) for session_id in shortfall.sessions],
        fix_hint=invariant.because if invariant else "",
        subject_kind=shortfall.subject_kind,
        subject_id=shortfall.subject_id,
    )


def infeasibility_report(explanation: Explanation) -> InfeasibilityReport:
    """`Explanation` on the wire, and on the console's page for it.

    A count and a conflict are different strengths of evidence and stay different lines: the
    count carries its arithmetic, the conflict carries the rule and what it is about. Both
    say what they proved and no more, which is what #286 corrected.
    """
    return InfeasibilityReport(
        summary=explanation.summary,
        requirements=[
            ConflictingRequirement(
                summary=_problem(shortfall).summary,
                detail=shortfall.statement,
                subject_kind=shortfall.subject_kind,
                subject_id=shortfall.subject_id,
            )
            for shortfall in explanation.shortfalls
        ]
        + [
            ConflictingRequirement(
                summary=requirement.statement,
                detail=requirement.because,
                subject_kind=requirement.subject_kind,
                subject_id=requirement.subject_id,
            )
            for requirement in explanation.conflict
        ],
        suggestion=(
            "Every requirement listed is necessary for the contradiction. Where several "
            "independent conflicts exist the solver reports one of them, so relaxing a "
            "member is not on its own a promise that a timetable appears."
            if explanation.conflict
            else ""
        ),
    )
