"""The registry's bookkeeping: what it remembers, and what it promises a reader.

The concurrency is tested where it happens — `tests/api/test_solving.py` starts real solves
against a real project file, because an inline registry would exercise the bookkeeping and not
the thing most likely to be wrong (4.7 D9).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.deps import ProjectState
from tessera.api.jobs import REMEMBERED, Job, Registry, _settled_as, advance
from tessera.api.schemas import SolvePhase, SolveRequest, SolveStatus
from tessera.domain.groups import GroupSet
from tessera.domain.ids import RoomId, SessionId
from tessera.domain.time_grid import TimeGrid
from tessera.domain.validation import Snapshot
from tessera.repository import session_factory
from tessera.solver import Outcome, Placed, Progress, Solution, Stop
from tests.repository.authored import Term
from tests.solving import settled


@pytest.fixture
def registry(project: Engine) -> Registry:
    return Registry(
        ProjectState(engine=project, path=Path("test.tessera"), sessions=session_factory(project))
    )


def a_job(phase: SolvePhase = SolvePhase.FEASIBILITY) -> Job:
    return Job(
        id=f"job{time.perf_counter_ns()}",
        term_id=1,
        started=time.perf_counter(),
        stop=Stop(),
        status=SolveStatus(job_id="j", phase=phase),
    )


class TestAReadingIsCoherent:
    def test_the_status_is_replaced_rather_than_edited(self) -> None:
        """The promise the whole design rests on.

        A stream reads `job.status` from the event loop while the solver writes it from a
        worker thread. Replacing the object is one reference swap, so a reader sees either the
        old reading or the new one; editing fields in place would let it see a penalty from one
        solution beside a bound from another and draw a point that never existed.
        """
        job = a_job()
        before = job.status

        advance(job, Progress(phase="optimising", seconds=1.0, penalty=10))

        assert job.status is not before
        assert before.penalty is None, "the reading a client already had changed underneath it"
        assert job.status.penalty == 10

    def test_the_clock_is_read_rather_than_stored(self) -> None:
        """So a panel keeps counting through a phase the solver says nothing during — which is
        most of the first ten seconds on a real term."""
        job = a_job()

        first = job.reading().elapsed_seconds
        time.sleep(0.05)
        second = job.reading().elapsed_seconds

        assert second > first
        assert job.status.elapsed_seconds == 0.0, "the stored reading holds no clock"


class TestWhatAJobSaysWhileItRuns:
    def test_the_phase_is_named_before_the_search_starts(
        self, registry: Registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`queued` means waiting for a turn, and nothing here ever waits for one.

        The solver's first progress event is the feasibility pass *finishing*, which at five
        hundred sessions is seven seconds in — so a job that took its phase from that event
        reported `queued` through seven seconds of hard work. Found by running the real engine
        and reading the stream, and asserted here rather than end to end because a term small
        enough to build in a fixture finishes before anything could look at it.
        """
        seen: list[SolvePhase] = []

        def watched(self: Registry, job: Job, snapshot: object, wanted: object) -> Solution:
            seen.append(job.status.phase)
            return Solution(outcome=Outcome.OUT_OF_TIME)

        monkeypatch.setattr(Registry, "_solve", watched)

        async def run_one() -> None:
            job = registry.start(_nothing_to_solve(), term_id=1, wanted=SolveRequest())
            assert job.task is not None
            await job.task

        asyncio.run(run_one())

        assert seen == [SolvePhase.FEASIBILITY], (
            "a panel reading 'queued' is describing a queue that does not exist"
        )

    def test_a_job_that_fails_unexpectedly_says_failed_and_does_not_go_quiet(
        self, registry: Registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one branch that must never swallow anything.

        The solver already turns a broken CP-SAT into an answer (#301), so anything reaching
        here is a defect in this file — and a job that simply stopped updating would be the
        worst way to learn about it. The phase says `failed`, the exception still propagates so
        the task carries it, and it is logged on the way past.
        """

        def broken(self: Registry, job: Job, snapshot: object, wanted: object) -> Solution:
            raise RuntimeError("something nobody planned for")

        monkeypatch.setattr(Registry, "_solve", broken)

        async def run_one() -> Job:
            job = registry.start(_nothing_to_solve(), term_id=1, wanted=SolveRequest())
            assert job.task is not None
            with pytest.raises(RuntimeError, match="nobody planned for"):
                await job.task
            return job

        job = asyncio.run(run_one())

        assert job.status.phase is SolvePhase.FAILED
        assert job.settled, "a failed job that never settles is a spinner for ever"


def _nothing_to_solve() -> Snapshot:
    """An empty term. `_solve` is patched out, so nothing looks at it."""
    return Snapshot.of(
        grid=TimeGrid(days=1, slots_per_day=2, slot_minutes=60, day_start_minute=9 * 60),
        sessions=[],
        rooms=[],
        groups=GroupSet([]),
    )


class TestHowAnEndingIsNamed:
    @pytest.mark.parametrize(
        ("found", "expected"),
        [
            (
                Solution(
                    outcome=Outcome.SOLVED,
                    placements=(Placed(SessionId(1), 0, RoomId(1)),),
                ),
                SolvePhase.DONE,
            ),
            (
                Solution(
                    outcome=Outcome.SOLVED,
                    placements=(Placed(SessionId(1), 0, RoomId(1)),),
                    stopped=True,
                ),
                SolvePhase.CANCELLED,
            ),
            (Solution(outcome=Outcome.OUT_OF_TIME), SolvePhase.DONE),
            (
                Solution(outcome=Outcome.OUT_OF_TIME, search_failed="IndexError: x"),
                SolvePhase.FAILED,
            ),
        ],
        ids=["solved", "cancelled", "ran out", "the solver broke"],
    )
    def test_each_ending_has_its_own_name(self, found: Solution, expected: SolvePhase) -> None:
        assert _settled_as(found) is expected

    def test_running_out_of_time_is_not_called_impossible(self) -> None:
        """#205 on the wire. `infeasible` is reserved for a term something has **proven** has
        no timetable; a solve that simply did not find one settles as `done` with nothing
        against it, and only the first is a reason to change the data."""
        assert _settled_as(Solution(outcome=Outcome.OUT_OF_TIME)) is not SolvePhase.INFEASIBLE


class TestWhatIsRemembered:
    def test_a_finished_job_stays_readable(self, registry: Registry) -> None:
        """A client that reconnects after the end still learns what happened."""
        job = a_job(SolvePhase.DONE)
        registry._jobs[job.id] = job

        assert registry.get(job.id) is job
        assert registry.running is None

    def test_but_not_for_ever(self, registry: Registry) -> None:
        """Unbounded memory in a process that runs for days is a leak with a nice name.
        Forgetting the oldest answers 404, which is what a restart answers too."""
        for _ in range(REMEMBERED + 5):
            registry._forget_the_oldest()
            job = a_job(SolvePhase.DONE)
            registry._jobs[job.id] = job

        assert len(registry._jobs) <= REMEMBERED


@pytest.mark.slow
class TestNothingIsLeftRunning:
    def test_solving_repeatedly_does_not_accumulate_threads(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """P5's exit test asks for *no orphan threads*, and this is where that is checkable.

        **Not "no thread survives a solve"** — the first version asserted that and failed, on a
        thread named `AnyIO worker thread`. It is a *pooled* worker waiting for the next task,
        which is the design rather than a leak, and a test that called it one would have been
        demanding that the threadpool stop being a pool.

        What a leak would actually look like is accumulation: a job whose thread never returned
        would leave one behind every time. So six solves must not cost more threads than three.
        """

        def solve_once() -> None:
            job = solving_client.post(
                f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
            ).json()
            settled(solving_client, job["job_id"])

        for _ in range(3):
            solve_once()
        after_three = Counter(thread.name for thread in threading.enumerate())

        for _ in range(3):
            solve_once()
        after_six = Counter(thread.name for thread in threading.enumerate())

        grew = {
            name: (after_three[name], count)
            for name, count in after_six.items()
            if count > after_three[name]
        }
        assert not grew, f"threads accumulated across solves: {grew}"


@pytest.mark.slow
class TestAgainstTheRealThing:
    def test_the_engine_runs_one_solve_at_a_time_and_then_the_next(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """Sequentially is fine; concurrently is refused. The second POST only succeeds once
        the first has settled, which is what makes the 409 a queue signal rather than a wall."""
        first = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
        ).json()
        settled(solving_client, first["job_id"])

        second = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
        )

        assert second.status_code == 202
        assert second.json()["job_id"] != first["job_id"]
        settled(solving_client, second.json()["job_id"])
