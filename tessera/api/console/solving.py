"""Generating a timetable from a browser: the pre-flight, the solve, and watching it.

4.7 put a solve behind three routes and `curl` was the only client. This is the phase where a
person presses a button, and the difference is not cosmetic — a stream nobody has watched is a
stream nobody has checked, and the pre-flight, the cancellation and the infeasibility report
had each been exercised only by a test.

**The actions are console routes and the reading is the API's.** A form cannot post to
`POST /api/v1/terms/{id}/solve`: it answers 202 with a JSON body, and a browser renders that
as text. So the console owns what needs post-redirect-get and calls the *registry* directly —
not itself over HTTP. What it does not own is the progress stream: that is
`GET /api/v1/solve/{id}/stream`, published in the contract and the same endpoint 5.3 will use,
because two implementations of one stream is what 4.7's D7 spent a decision preventing.

**Every generate goes through the pre-flight**, and *Solve it anyway* is still offered. The
checks are counting arguments: one that fails proves the real problem cannot be satisfied
either, so proceeding is offering to search for something already known not to exist. It is
offered because the search's answer is more useful than the arithmetic — an `infeasible`
ending carries the minimal conflicting set, and a shortfall carries one subtraction.
"""

from __future__ import annotations

import anyio.to_thread
from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api import targets
from tessera.api.console import timetables as timetables_console
from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db, Jobs
from tessera.api.jobs import SETTLED, AlreadySolvingError, Job
from tessera.api.routers.solving import infeasibility_report, preflight_report
from tessera.api.schemas import SolvePhase, SolveRequest, SolveStatus
from tessera.domain.constraints import TargetKind
from tessera.repository import calendar as calendar_repo
from tessera.repository import snapshot as snapshot_repo
from tessera.repository.errors import RepositoryError

#: What each phase means, in the words somebody watching needs rather than the words the
#: registry uses. Two of them are the ones this whole design exists for: `feasibility` reports
#: nothing for its whole duration on a real term, and a page that said only *queued* through it
#: would be describing a queue that does not exist (#305).
PHASES: dict[SolvePhase, tuple[str, str]] = {
    SolvePhase.QUEUED: (
        "Starting",
        "The engine is picking the term up.",
    ),
    SolvePhase.FEASIBILITY: (
        "Looking for any valid timetable",
        "Nothing is scored yet. The first job is to find an arrangement that breaks no hard "
        "rule, and on a department-sized term that takes several seconds and reports nothing "
        "at all while it runs.",
    ),
    SolvePhase.OPTIMISING: (
        "Improving it",
        "There is a valid timetable now, and everything from here is polish. Stop whenever "
        "the score is good enough — nothing is lost by stopping.",
    ),
    SolvePhase.INFEASIBLE: (
        "No valid timetable exists",
        "Not 'none found'. Something proved there is none, and the report says which "
        "requirements contradict each other.",
    ),
    SolvePhase.FAILED: (
        "The solve broke",
        "This is a defect rather than an answer about the term. The engine log carries the "
        "request id and the traceback.",
    ),
}


@router.post("/terms/{term_id}/generate", include_in_schema=False)
async def generate(
    request: Request,
    db: Db,
    jobs: Jobs,
    term_id: int,
    time_budget_seconds: int = Form(timetables_console.DEFAULT_BUDGET_SECONDS),
    seed_timetable_id: str = Form(""),
    anyway: str = Form(""),
) -> Response:
    """Check the term, then start solving it.

    `async` for the same reason `start_solve` is: the job outlives the request and
    `asyncio.create_task` needs a running loop, which a sync handler in Starlette's threadpool
    does not have. The term is read on a thread so the 27 to 37 ms it costs at department
    scale is not spent on the event loop.

    `seed_timetable_id` arrives as a string because an unselected `<select>` posts `""`.
    """
    wanted = SolveRequest(
        time_budget_seconds=max(1, min(time_budget_seconds, 3600)),
        seed_timetable_id=int(seed_timetable_id) if seed_timetable_id else None,
    )
    try:
        term = await anyio.to_thread.run_sync(
            lambda: snapshot_repo.load(
                db, term_id, seed_timetable_id=wanted.seed_timetable_id, respect_pins=True
            )
        )
    except RepositoryError as error:
        return timetables_console.render_list(request, db, term_id, problem=describe(error))

    if not term.sessions:
        # #307: `Solution` refuses a solved timetable with no placements on purpose, and an
        # empty term meets that invariant from the wrong side. Somebody making a term and
        # pressing Generate before adding teaching is an ordinary first day, not a failure.
        return timetables_console.render_list(
            request,
            db,
            term_id,
            problem="There is nothing to schedule yet. Offer a course and expand its weekly "
            "pattern first.",
        )

    if not anyway:
        report = preflight_report(term)
        if not report.can_solve:
            return page(
                request,
                "solve/preflight.html",
                term=calendar_repo.get_term(db, term_id),
                report=report,
                named=_naming(db, term_id),
                budget=wanted.time_budget_seconds,
            )

    try:
        job = jobs.start(term, term_id=term_id, wanted=wanted)
    except AlreadySolvingError as busy:
        # Watching the job that holds the engine is what somebody pressing Generate twice
        # actually wants. The API answers 409 and names it for the same reason.
        return redirect(f"/console/solve/{busy.job_id}")
    return redirect(f"/console/solve/{job.id}")


@router.get("/solve/{job_id}", include_in_schema=False)
def watch(request: Request, db: Db, jobs: Jobs, job_id: str) -> HTMLResponse:
    """Where the solve has got to."""
    job = jobs.get(job_id)
    if job is None:
        return page(request, "solve/gone.html", job_id=job_id)
    return _watching(request, db, job)


@router.post("/solve/{job_id}/stop", include_in_schema=False)
def stop(request: Request, db: Db, jobs: Jobs, job_id: str) -> Response:
    """Stop searching and keep whatever was found.

    Idempotent on a job that has already settled, exactly as the API's cancel is: pressing
    Stop a moment after the answer arrived is not a mistake worth an error page.
    """
    job = jobs.get(job_id)
    if job is None:
        return page(request, "solve/gone.html", job_id=job_id)
    jobs.cancel(job)
    return redirect(f"/console/solve/{job_id}")


@router.get("/solve/{job_id}/impossible", include_in_schema=False)
def impossible(request: Request, db: Db, jobs: Jobs, job_id: str) -> HTMLResponse:
    """Why there is no timetable — the requirement list, not *no solution found*.

    The differentiating feature (R3 §4), and until now nobody had read one outside a test.
    """
    job = jobs.get(job_id)
    if job is None:
        return page(request, "solve/gone.html", job_id=job_id)
    if job.status.phase is not SolvePhase.INFEASIBLE or job.explanation is None:
        return _watching(
            request,
            db,
            job,
            problem="Nothing was proven impossible about this solve, so there is no report.",
        )
    return page(
        request,
        "solve/impossible.html",
        term=calendar_repo.get_term(db, job.term_id),
        report=infeasibility_report(job.explanation),
        named=_naming(db, job.term_id),
    )


def _naming(db: Db, term_id: int) -> dict[str, dict[int, str]]:
    """Ids to names, for the one column of a report the engine deliberately leaves blank.

    `ConflictingRequirement.subject_kind` exists so *"instructor 4"* can be read as *"Prof.
    Sharma"* — the schema says in as many words that the engine holds ids and the client holds
    names. **The console is a client and it has the database**, so it does the naming, and it
    is the first thing in this project to do it at all.

    It does not reach inside the sentence beside it, which still says *group 1*: that string is
    composed in `Shortfall._resource` with the id already in it, so no client can honour the
    division the docstring there describes. Backlogged rather than fixed here — the wording
    lives in `tessera/solver/` and this phase does not open it.
    """
    names = targets.target_names(db, term_id=term_id)
    return {
        "instructor": names[TargetKind.INSTRUCTOR],
        "group": names[TargetKind.GROUP],
        "room": names[TargetKind.ROOM],
        "course": names[TargetKind.COURSE],
    }


def _watching(request: Request, db: Db, job: Job, problem: str | None = None) -> HTMLResponse:
    """One page, from **one** reading of the job.

    `job.status` is replaced by the worker thread, and loading it three times — once for the
    numbers, once for the sentences, once for whether it has finished — builds a page out of
    two different moments. That is not hypothetical: it turned `main` red. A solve settled
    between the first load and the third, so the page dropped the Stop button *and* the link
    to the timetable it had just written, while the log line beside it said `timetable=1`.

    #303 made the status safe to read concurrently by replacing it whole rather than editing
    it, so **one** load is always coherent. Taking several throws that away.
    """
    status = job.reading()
    headline, explanation = wording(status)
    return page(
        request,
        "solve/watch.html",
        term=calendar_repo.get_term(db, job.term_id),
        sessions=calendar_repo.term_session_count(db, job.term_id),
        status=status,
        settled=status.phase in SETTLED,
        impossible=status.phase is SolvePhase.INFEASIBLE,
        headline=headline,
        explanation=explanation,
        problem=problem,
    )


def _how_it_finished(status: SolveStatus) -> str:
    """Why a completed solve stopped, which is not always because the clock ran out.

    Found by watching a real one: 120 sessions reached **penalty 0 in 14 seconds** of a
    sixty-second budget, and the page said *"the budget ran out"* under a score nothing could
    improve. Offering to try again for longer is worse than useless there — it is advice to
    spend five minutes re-deriving an answer already known to be optimal.

    A penalty is a sum of non-negative costs, so zero is provably the best there is. Where the
    solver also reports a bound, a score equal to it is optimal for the same reason with the
    arithmetic done by CP-SAT rather than by inspection.
    """
    if status.penalty == 0:
        return (
            "Every preference this term states is satisfied. Nothing about this timetable can "
            "be improved by searching longer."
        )
    if status.lower_bound is not None and status.penalty == status.lower_bound:
        return (
            "This is provably the best arrangement the rules allow — the solver reached its "
            "own lower bound. A longer budget cannot beat it."
        )
    return (
        "The budget ran out and the best arrangement found is saved. Generating again with a "
        "longer budget, or starting from this one, will usually improve it."
    )


def wording(status: SolveStatus) -> tuple[str, str]:
    """The heading and the sentence under it, for the phase this reading is in.

    Takes a `SolveStatus` rather than a `Job` so a caller cannot accidentally load the job a
    second time: the worker replaces `job.status` mid-render, and a page assembled from two
    loads of it is what turned `main` red.

    Public because it is the one thing on this page worth asserting directly: *which* ending a
    search reaches is a fact about seconds, and #244 forbids a test being about those — so the
    words are checked against a constructed job and the plumbing is checked against a real one.

    The two endings that are not in `PHASES` are the ones whose meaning depends on whether a
    timetable was found, and saying *finished* over an empty result would be the worst kind of
    wrong: a search that ran out of time has proved nothing about the term.
    """
    if status.phase is SolvePhase.DONE:
        if status.timetable_id:
            return ("Finished", _how_it_finished(status))
        return (
            "Nothing was found in the time it had",
            "Which says nothing about whether a timetable exists — only that this search did "
            "not reach one. Try a longer budget before changing the data.",
        )
    if status.phase is SolvePhase.CANCELLED:
        if status.timetable_id:
            return ("Stopped", "The best arrangement found before you stopped is saved.")
        return (
            "Stopped before anything was found",
            "No valid arrangement had been reached yet, so there is nothing to save.",
        )
    return PHASES[status.phase]
