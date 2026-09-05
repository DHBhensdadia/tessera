"""Solving as a job: one at a time, watched from outside, and stoppable.

A solve takes seconds to minutes, so it cannot be an HTTP request that returns when it is
done — [ADR-0008](../../docs/adr/0008-in-process-jobs.md) settled the shape in August and
P2 §6 fixed the routes. What that ADR could not settle, because there was no solver yet, is
how the three hard parts actually work.

**The solve runs on a thread, and that is measured rather than hoped.** OR-Tools releases the
GIL, so an asyncio loop beside a running solve ticks at 1.046 ms against 1.023 ms idle; the
Python that builds each round's model does not release it, and even at five hundred sessions
the loop's worst stall is 27.5 ms. A subprocess would buy nothing and cost a second copy of a
67 MB library, `freeze_support` under PyInstaller, and a `Snapshot` that has to be pickled.

**The stream ticks rather than being pushed to.** The job holds one `SolveStatus` and the
worker thread *replaces* it — never edits it field by field — so a reader always sees a
coherent set of numbers rather than a penalty from one solution beside a bound from another.
That makes the fan-out free: every connected stream reads the same attribute on its own
schedule, and nothing needs a queue, a lock, or `call_soon_threadsafe`.

**Cancelling is `Stop`**, which reaches into CP-SAT rather than waiting for the current solve
to end on its own. The route sets it and returns; the worker unwinds by itself.

Jobs do not survive an engine restart, which ADR-0008 accepts: a solve is minutes and the
timetable it started from is already on disk.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio.to_thread
import structlog

from tessera.api.schemas import SolvePhase, SolveRequest, SolveStatus
from tessera.domain.timetable import Assignment
from tessera.repository import timetables as timetables_repo
from tessera.repository.database import session_scope
from tessera.solver import Budget, Outcome, Progress, Solution, Stop, solve

if TYPE_CHECKING:
    from tessera.api.deps import ProjectState
    from tessera.domain.validation import Snapshot
    from tessera.solver.result import Explanation

logger = structlog.get_logger(__name__)

#: How often a connected stream looks at the job and says where it has got to.
#:
#: Four times a second, which is faster than a person reads and slower than the solver can
#: report: CP-SAT found 24 improving solutions inside one second on a small term (4.7 §2.2),
#: and forwarding each would be a wire that changes faster than a panel can draw. A fixed
#: cadence puts a ceiling on the rate and a floor under the silence, which is the half that
#: matters — on two of three real terms the solver says nothing for its whole first phase.
TICK_SECONDS = 0.25

#: How many finished jobs stay readable. Beyond this the oldest is forgotten, and asking for
#: it answers 404 — the same answer it gives after a restart.
REMEMBERED = 16

#: The phases from which nothing further happens.
SETTLED = frozenset(
    {SolvePhase.DONE, SolvePhase.INFEASIBLE, SolvePhase.CANCELLED, SolvePhase.FAILED}
)


@dataclass
class Job:
    """One solve, and everything anybody is allowed to ask about it while it runs."""

    id: str
    term_id: int
    started: float
    stop: Stop
    status: SolveStatus
    """The latest reading. **Replaced, never edited** — see the module docstring."""

    explanation: Explanation | None = None
    """Why there is no timetable, kept for `GET /solve/{id}/result`."""

    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def settled(self) -> bool:
        return self.status.phase in SETTLED

    def reading(self) -> SolveStatus:
        """The status as of now, with the clock filled in.

        Elapsed time is computed here rather than stored, so a panel showing *0:42* keeps
        counting through a phase where the solver has nothing to report — which is most of
        the first ten seconds on a real term.
        """
        elapsed = time.perf_counter() - self.started
        return self.status.model_copy(update={"elapsed_seconds": round(elapsed, 2)})


class AlreadySolvingError(Exception):
    """A solve is already running. Carries the job that holds the engine."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"solve {job_id} is already running")
        self.job_id = job_id


def events(job: Job) -> AsyncIterator[dict[str, str]]:
    """What a connected client is told, from now until the job settles.

    A function rather than a method because it needs nothing but the job: the registry owns
    which jobs exist, and a stream owns none of that. Several clients can read the same job at
    once and each gets its own schedule, because all any of them does is look at an attribute.

    The first event carries the whole current status, so a client that attaches late — or
    reconnects — starts from where things are rather than from nothing.
    """

    async def stream() -> AsyncIterator[dict[str, str]]:
        # One reading per tick, and every event on that tick is built from it. The status is
        # replaced whole so a single load is always coherent — taking four per iteration gave
        # that away, and could announce a phase from one moment beside numbers from another.
        # Latent here, because no client reads the `phase` event; the same pattern on the
        # console's page was not, and turned `main` red.
        reading = job.reading()
        phase = reading.phase
        yield {"event": "status", "data": reading.model_dump_json()}

        while reading.phase not in SETTLED:
            await asyncio.sleep(TICK_SECONDS)
            reading = job.reading()
            if reading.phase is not phase:
                phase = reading.phase
                yield {"event": "phase", "data": phase.value}
            yield {"event": "status", "data": reading.model_dump_json()}

        yield {"event": "done", "data": reading.model_dump_json()}

    return stream()


def advance(job: Job, event: Progress) -> None:
    """One reading from the solver, replacing the last.

    Called on the worker thread, and a function rather than a method for the same reason
    `events` is: it needs the job and nothing else. Assigning the attribute is a single
    reference swap, so a stream reading it concurrently sees either the old status or the new
    one and never half of each — which is why the status is rebuilt rather than edited.
    """
    job.status = job.status.model_copy(
        update={
            "phase": SolvePhase.FEASIBILITY
            if event.phase == "feasibility"
            else SolvePhase.OPTIMISING,
            "penalty": event.penalty,
            "penalty_breakdown": dict(event.penalty_breakdown),
            "lower_bound": event.lower_bound,
            "solutions_found": event.solutions,
        }
    )


class Registry:
    """Every solve this engine has run since it started, and the one it is running now.

    One per application, held on `app.state` beside the open project — the engine serves one
    file, so a registry that outlived it would be a registry pointed at nothing.
    """

    def __init__(self, project: ProjectState) -> None:
        self._project = project
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    @property
    def running(self) -> Job | None:
        return next((job for job in self._jobs.values() if not job.settled), None)

    def start(self, snapshot: Snapshot, *, term_id: int, wanted: SolveRequest) -> Job:
        """Take a loaded term and begin solving it.

        **One at a time** (D8). Two solves would contend for the same cores and make both
        slower than either, and this engine serves one person with one file open. The
        refusal names the job that holds it, so a client can watch that one instead of
        guessing.

        The snapshot arrives already built, because loading it is 27 to 37 ms at department
        scale and doing it on the request thread is what lets a term that cannot be loaded
        fail as a 404 rather than as a job that starts and immediately dies.
        """
        if (busy := self.running) is not None:
            raise AlreadySolvingError(busy.id)

        job = Job(
            id=uuid.uuid4().hex[:16],
            term_id=term_id,
            started=time.perf_counter(),
            stop=Stop(),
            status=SolveStatus(job_id="", phase=SolvePhase.QUEUED),
        )
        job.status = job.status.model_copy(update={"job_id": job.id})
        self._forget_the_oldest()
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, snapshot, wanted))
        logger.info("solve_started", job=job.id, term=term_id, budget=wanted.time_budget_seconds)
        return job

    def cancel(self, job: Job) -> None:
        """Ask the search to stop. Returns as soon as CP-SAT has been told.

        Idempotent, including on a job that has already finished: a client pressing *Stop* a
        moment after the answer arrived has not made a mistake worth an error about.
        """
        job.stop.request()

    # -- the worker ---------------------------------------------------------------

    async def _run(self, job: Job, snapshot: Snapshot, wanted: SolveRequest) -> None:
        """Solve on a thread, then write what came back, then settle the job."""
        # Said before the search starts, not after it finishes. The solver's first progress
        # event is the feasibility pass *completing*, which at five hundred sessions is seven
        # seconds in — and a panel reading `queued` for seven seconds is describing a queue
        # that does not exist. Found by running the real engine and watching it (4.7 §9).
        job.status = job.status.model_copy(update={"phase": SolvePhase.FEASIBILITY})
        try:
            found = await anyio.to_thread.run_sync(lambda: self._solve(job, snapshot, wanted))
        except Exception:
            # Nothing here is expected: the solver already turns a broken CP-SAT into an
            # answer (#301), so anything reaching this is a defect and must be visible
            # rather than a job that stops updating and never says why.
            logger.exception("solve_failed", job=job.id, term=job.term_id)
            job.status = job.status.model_copy(update={"phase": SolvePhase.FAILED})
            raise

        job.explanation = found.explanation
        job.status = job.status.model_copy(update={"phase": _settled_as(found)})
        logger.info(
            "solve_finished",
            job=job.id,
            phase=job.status.phase.value,
            penalty=job.status.penalty,
            timetable=job.status.timetable_id,
        )

    def _solve(self, job: Job, snapshot: Snapshot, wanted: SolveRequest) -> Solution:
        """The blocking half, on its own thread: search, then store what was found.

        Storing happens here rather than back on the event loop so the whole of the slow
        work is on one thread and the database session never crosses one. It is also the
        only write: a result goes in once, at the end (D5), rather than on every improvement.
        """
        found = solve(
            snapshot,
            Budget(seconds=wanted.time_budget_seconds),
            on_progress=lambda event: advance(job, event),
            stop=job.stop,
        )
        if found.placements:
            with session_scope(self._project.engine) as db:
                stored = timetables_repo.record(
                    db,
                    term_id=job.term_id,
                    placements=[
                        Assignment(
                            session_id=placed.session,
                            start_slot=placed.start_slot,
                            room_id=placed.room,
                            is_pinned=placed.is_pinned,
                        )
                        for placed in found.placements
                    ],
                    name="Generated",
                    parent_id=wanted.seed_timetable_id,
                    penalty=found.penalty,
                    penalty_breakdown=found.penalty_breakdown,
                )
            job.status = job.status.model_copy(update={"timetable_id": stored.id})
        return found

    def _forget_the_oldest(self) -> None:
        settled = [job_id for job_id, job in self._jobs.items() if job.settled]
        for job_id in settled[: max(len(settled) - REMEMBERED + 1, 0)]:
            del self._jobs[job_id]


def _settled_as(found: Solution) -> SolvePhase:
    """Which ending this was.

    `INFEASIBLE` is reserved for a term something has **proven** has no timetable, which is
    #205's distinction carried onto the wire: running out of time and being impossible are
    different sentences and only the second is a reason to change the data. A solve that
    found nothing in the time it had settles as `done` with no timetable against it.
    """
    if found.search_failed:
        return SolvePhase.FAILED
    if found.stopped:
        return SolvePhase.CANCELLED
    if found.outcome is Outcome.IMPOSSIBLE:
        return SolvePhase.INFEASIBLE
    return SolvePhase.DONE
