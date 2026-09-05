"""What a person watching a solve is sent, and how often.

4.7 §1a is why this route does not simply forward `on_improvement`: on two real terms out of
three that callback fires **once or not at all** inside thirty seconds, so a panel fed by it
draws nothing while the solver works and returns a good timetable. The stream ticks instead.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.jobs import TICK_SECONDS, Job, events
from tessera.api.schemas import SolvePhase, SolveStatus
from tessera.solver import Stop
from tests.repository.authored import Term
from tests.solving import settled


def frames(client: TestClient, job_id: str, most: int = 12) -> Iterator[tuple[str, str]]:
    """Read up to `most` server-sent events off the wire, as (event, data) pairs."""
    with client.stream("GET", f"/api/v1/solve/{job_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        event = ""
        seen = 0
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                yield event, line.removeprefix("data:").strip()
                seen += 1
                if seen >= most or event == "done":
                    return


@pytest.fixture
def running(solving_client: TestClient, solvable: Term) -> Iterator[str]:
    """A solve with a budget long enough that the stream can be watched, cancelled after."""
    job = solving_client.post(
        f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 300}
    ).json()
    yield str(job["job_id"])
    solving_client.post(f"/api/v1/solve/{job['job_id']}/cancel")
    settled(solving_client, job["job_id"])


class TestTheCadence:
    """The tick itself, against a job that does not finish.

    A real solve of a term small enough to build in a fixture is over in a fifth of a second —
    it proves an optimum and stops, which is correct and leaves nothing to tick about. So the
    cadence is asserted here, where the job's lifetime is controlled, and the wiring is
    asserted end to end below. The same split the cancellation tests arrived at.
    """

    def test_it_keeps_saying_something_while_the_solver_is_quiet(self, project: Engine) -> None:
        """The finding of §1a, as a test. A stream fed only by accepted rounds would send one
        event here, or none — and *is it working?* is what a progress panel answers."""
        seen = asyncio.run(_listen(_a_job_that_runs(), wanted=5))

        assert len(seen) == 5
        assert {event for event, _ in seen} == {"status"}

    def test_the_clock_moves_even_when_the_score_does_not(self, project: Engine) -> None:
        seen = asyncio.run(_listen(_a_job_that_runs(), wanted=4))

        elapsed = [json.loads(data)["elapsed_seconds"] for _, data in seen]
        assert elapsed == sorted(elapsed)
        assert elapsed[-1] > elapsed[0], "a panel showing 0:00 for ever is the bug this catches"

    def test_a_phase_change_is_announced_as_one(self, project: Engine) -> None:
        """So a client can draw *"Feasible solution found"* as its own line, which is what P7
        does, without inferring it from a score that happens to have appeared."""
        job = _a_job_that_runs()

        async def move_on() -> list[tuple[str, str]]:
            listening = asyncio.create_task(_collect(job, wanted=4))
            await asyncio.sleep(TICK_SECONDS * 1.5)
            job.status = job.status.model_copy(update={"phase": SolvePhase.OPTIMISING})
            return await listening

        assert "phase" in {event for event, _ in asyncio.run(move_on())}

    def test_and_the_last_thing_said_is_that_it_is_over(self, project: Engine) -> None:
        job = _a_job_that_runs()

        async def finish() -> list[tuple[str, str]]:
            listening = asyncio.create_task(_collect(job, wanted=20))
            await asyncio.sleep(TICK_SECONDS * 1.5)
            job.status = job.status.model_copy(update={"phase": SolvePhase.DONE})
            return await listening

        seen = asyncio.run(finish())
        assert seen[-1][0] == "done"


def _a_job_that_runs() -> Job:
    """A job in flight, with no solver behind it. The stream cannot tell the difference."""
    return Job(
        id="watched",
        term_id=1,
        started=time.perf_counter(),
        stop=Stop(),
        status=SolveStatus(job_id="watched", phase=SolvePhase.FEASIBILITY),
    )


async def _collect(job: Job, *, wanted: int) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    async for event in events(job):
        seen.append((str(event["event"]), str(event["data"])))
        if len(seen) >= wanted or event["event"] == "done":
            break
    return seen


async def _listen(job: Job, *, wanted: int) -> list[tuple[str, str]]:
    return await asyncio.wait_for(_collect(job, wanted=wanted), timeout=wanted * TICK_SECONDS + 5)


class TestOneTickIsOneReading:
    """Every event on a tick is built from the same load of `job.status`.

    The status is replaced whole by the worker thread precisely so that **one** load is
    coherent (#303). The stream used to take four an iteration — for whether the job had
    settled, twice for the phase, and once for the numbers — which can announce a phase from
    one moment beside a score from another.

    Latent, because no client reads the `phase` event: the console's page and 5.3 both read
    `status.phase`. The same pattern on the page was **not** latent and turned `main` red
    (#327), and this went out with that fix and without a guard until now.
    """

    def test_a_tick_loads_the_status_once(self, project: Engine) -> None:
        reads: list[int] = []
        moving = _a_job_that_runs()

        class Counted(Job):
            @property
            def status(self) -> SolveStatus:
                reads.append(1)
                return moving.status

            @status.setter
            def status(self, value: SolveStatus) -> None:
                pass

        job = Counted(
            id="j", term_id=1, started=time.perf_counter(), stop=Stop(), status=moving.status
        )
        ticks = 4
        asyncio.run(_listen(job, wanted=ticks))

        # One for the first event before the loop, then one per tick.
        assert len(reads) == ticks, f"{len(reads)} loads across {ticks} events"

    def test_the_phase_it_announces_is_the_phase_it_then_reports(self, project: Engine) -> None:
        """The user-visible shape of the same rule, for whichever client reads that event
        first — a `phase` event naming something the `status` beside it contradicts."""
        job = _a_job_that_runs()

        async def move_on() -> list[tuple[str, str]]:
            listening = asyncio.create_task(_collect(job, wanted=6))
            await asyncio.sleep(TICK_SECONDS * 1.5)
            job.status = job.status.model_copy(update={"phase": SolvePhase.OPTIMISING})
            return await listening

        seen = asyncio.run(move_on())
        announced = [data for event, data in seen if event == "phase"]
        assert announced, "the phase change was never announced"

        after = seen[[event for event, _ in seen].index("phase") + 1]
        assert after[0] == "status"
        assert json.loads(after[1])["phase"] == announced[-1]


class TestWhatComesDownTheWire:
    def test_the_first_event_carries_the_whole_status(
        self, solving_client: TestClient, running: str
    ) -> None:
        """So attaching late — or reconnecting — starts from where things are, not from
        nothing, and no replay machinery is needed."""
        event, data = next(iter(frames(solving_client, running, most=1)))

        assert event == "status"
        body = json.loads(data)
        assert body["job_id"] == running
        assert set(body) >= {"phase", "elapsed_seconds", "penalty", "solutions_found"}

    def test_a_settled_job_still_answers_and_then_closes(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """Attaching after the end is ordinary: a client reconnecting has no way to know."""
        job = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
        ).json()
        settled(solving_client, job["job_id"])

        seen = list(frames(solving_client, job["job_id"]))

        assert seen[0][0] == "status"
        assert seen[-1][0] == "done"
        assert json.loads(seen[-1][1])["phase"] == "done"

    def test_the_stream_ends_with_the_answer(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """`done` is last and carries the terminal status, so a client that reads only the end
        still learns what happened."""
        job = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
        ).json()

        seen = list(frames(solving_client, job["job_id"], most=400))

        assert seen[-1][0] == "done"
        final = json.loads(seen[-1][1])
        assert final["phase"] == "done"
        assert final["timetable_id"] is not None

    def test_a_job_nobody_started(self, solving_client: TestClient) -> None:
        assert solving_client.get("/api/v1/solve/nosuchjob/stream").status_code == 404
