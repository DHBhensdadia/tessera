"""Generating a timetable from a browser, and being told why one is impossible.

These are the pages 4.8 exists for. The exit test's clauses about the pre-flight, about
stopping, and about the infeasibility report are all here — the ones that are about a *live*
score are part 2's, because nothing in this suite runs JavaScript.
"""

from __future__ import annotations

import time

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.console.solving import PHASES, _watching, wording
from tessera.api.jobs import Job
from tessera.api.schemas import SolvePhase, SolveStatus
from tessera.repository import session_factory
from tessera.solver import Stop
from tests.repository.authored import Term


def _a_request() -> Request:
    """The minimum a template render needs. `_watching` is called directly because the
    interleaving it guards against cannot be produced through the client."""
    return Request(
        {"type": "http", "method": "GET", "path": "/console/solve/j", "headers": [], "app": None}
    )


def watch_until_settled(client: TestClient, job_id: str, timeout: float = 60.0) -> str:
    """The watch page once its job stops moving.

    Reads the page rather than the API, because what is under test is the page: a job that
    settles while the template says it is running is exactly the defect this catches.
    """
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        page = client.get(f"/console/solve/{job_id}")
        assert page.status_code == 200
        if "Stop and keep" not in page.text:
            return str(page.text)
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never settled")


def generate(client: TestClient, term_id: int, **fields: str) -> str:
    """Press Generate and return where the browser was sent."""
    response = client.post(
        f"/console/terms/{term_id}/generate",
        data={"time_budget_seconds": "20", "seed_timetable_id": "", **fields},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:400]
    return str(response.headers["location"])


class TestGenerating:
    def test_a_browser_alone_produces_a_timetable(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        """Clause 1: no curl, no hand-written JSON — a form post and a link."""
        where = generate(solving_console, solvable.term_id)
        settled = watch_until_settled(solving_console, where.rsplit("/", 1)[-1])

        assert "/console/timetables/" in settled

    def test_the_result_is_valid_by_the_validator_rather_than_by_the_solver(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        """The page says zero hard violations, and that count is a second reading."""
        where = generate(solving_console, solvable.term_id)
        settled = watch_until_settled(solving_console, where.rsplit("/", 1)[-1])
        timetable = settled.split("/console/timetables/")[1].split('"')[0]

        report = solving_console.get(f"/api/v1/timetables/{timetable}/violations").json()

        assert report["is_feasible"] is True
        assert report["hard_violations"] == []

    def test_a_term_with_nothing_in_it_is_refused_beside_the_button(
        self, solving_console: TestClient, term_without_sessions: int
    ) -> None:
        """#307 through the console: an ordinary first day, not a traceback."""
        response = solving_console.post(
            f"/console/terms/{term_without_sessions}/generate",
            data={"time_budget_seconds": "20", "seed_timetable_id": ""},
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert "nothing to schedule" in response.text

    def test_a_seed_from_another_term_is_refused_beside_the_button(
        self, solving_console: TestClient, solvable: Term, another_term: Term
    ) -> None:
        """A warm start from a different term contributes no placements at all, silently —
        `Snapshot.of` drops assignments whose session is not in the term — so the repository
        refuses it and the console renders the refusal rather than a status code."""
        theirs = solving_console.post(
            f"/api/v1/terms/{another_term.term_id}/timetables", json={"name": "Theirs"}
        ).json()

        response = solving_console.post(
            f"/console/terms/{solvable.term_id}/generate",
            data={"time_budget_seconds": "20", "seed_timetable_id": str(theirs["id"])},
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert "belongs to term" in response.text

    def test_a_second_generate_watches_the_solve_that_is_already_running(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        """The API answers 409 and names the job; a browser wants to be taken to it."""
        first = generate(solving_console, solvable.term_id, time_budget_seconds="30")
        second = generate(solving_console, solvable.term_id, time_budget_seconds="30")

        assert second == first
        solving_console.post(f"{first}/stop")


class TestThePreflight:
    def test_a_term_the_counting_refutes_never_starts_a_search(
        self, solving_console: TestClient, refuted: Term
    ) -> None:
        """Clause 2. Failing after two minutes for something findable in fifty milliseconds
        is the behaviour this exists to prevent (#29)."""
        response = solving_console.post(
            f"/console/terms/{refuted.term_id}/generate",
            data={"time_budget_seconds": "20", "seed_timetable_id": ""},
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert "will prevent a valid timetable" in response.text

    def test_the_report_names_the_subject_rather_than_its_id(
        self, solving_console: TestClient, refuted: Term
    ) -> None:
        """The engine holds ids and `subject_kind` exists so a client can name them. The
        console is a client with the database, and it is the first one to do it."""
        response = solving_console.post(
            f"/console/terms/{refuted.term_id}/generate",
            data={"time_budget_seconds": "20", "seed_timetable_id": ""},
            follow_redirects=False,
        )

        assert "Prof. Rao" in response.text
        assert "One intake" in response.text

    def test_it_can_still_be_solved_anyway(
        self, solving_console: TestClient, refuted: Term
    ) -> None:
        """Offered on purpose: a shortfall carries one subtraction and the search's refusal
        carries the whole conflicting set, which is usually more use."""
        where = generate(solving_console, refuted.term_id, anyway="1")
        settled = watch_until_settled(solving_console, where.rsplit("/", 1)[-1])

        assert "No valid timetable exists" in settled


class TestBeingRefused:
    def test_the_requirement_list_reaches_a_person(
        self, solving_console: TestClient, refuted: Term
    ) -> None:
        """Clause 6. Every comparable tool prints *no solution found*; this does not."""
        where = generate(solving_console, refuted.term_id, anyway="1")
        job = where.rsplit("/", 1)[-1]
        watch_until_settled(solving_console, job)

        report = solving_console.get(f"/console/solve/{job}/impossible")

        assert report.status_code == 200
        assert "These requirements contradict each other" in report.text
        assert "no solution found" not in report.text.lower()

    def test_it_promises_only_what_was_proven(
        self, solving_console: TestClient, refuted: Term
    ) -> None:
        """#286: the page carries the corrected sentence and not the one that was false."""
        where = generate(solving_console, refuted.term_id, anyway="1")
        job = where.rsplit("/", 1)[-1]
        watch_until_settled(solving_console, job)

        report = solving_console.get(f"/console/solve/{job}/impossible").text

        assert "makes a timetable possible" not in report

    def test_asking_for_a_report_that_does_not_exist_shows_the_solve_instead(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        where = generate(solving_console, solvable.term_id)
        job = where.rsplit("/", 1)[-1]
        watch_until_settled(solving_console, job)

        response = solving_console.get(f"/console/solve/{job}/impossible")

        assert response.status_code == 200
        assert "Nothing was proven impossible" in response.text


class TestTheRefresh:
    """Clause 4. Part 1 has no script at all, so this is how the page moves — for everybody.

    Unconditional rather than inside `<noscript>`, because `<noscript>` content is ignored by
    a browser that *has* scripting enabled, and a page that only updated for people who had
    turned JavaScript off would be a strange thing to ship. Part 2 wraps it and lets an
    `EventSource` do the same job without discarding the page.
    """

    def test_a_running_solve_refreshes_itself(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        where = generate(solving_console, solvable.term_id, time_budget_seconds="30")

        page = solving_console.get(where)

        assert 'http-equiv="refresh"' in page.text
        solving_console.post(f"{where}/stop")

    def test_a_settled_one_stops_refreshing(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        """A finished page that kept reloading would poll a settled job for ever."""
        where = generate(solving_console, solvable.term_id)
        settled = watch_until_settled(solving_console, where.rsplit("/", 1)[-1])

        assert 'http-equiv="refresh"' not in settled


class TestStopping:
    def test_stop_returns_to_the_solve(self, solving_console: TestClient, solvable: Term) -> None:
        where = generate(solving_console, solvable.term_id, time_budget_seconds="30")
        job = where.rsplit("/", 1)[-1]

        response = solving_console.post(f"/console/solve/{job}/stop", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == f"/console/solve/{job}"

    def test_stopping_twice_is_not_an_error(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        """Pressing Stop a moment after the answer arrived is not a mistake worth a page."""
        where = generate(solving_console, solvable.term_id)
        job = where.rsplit("/", 1)[-1]
        watch_until_settled(solving_console, job)

        assert solving_console.post(f"/console/solve/{job}/stop").status_code == 200


class TestWhenTheJobIsGone:
    """Jobs do not survive a restart and only sixteen are remembered, so this is ordinary."""

    def test_watching_one_explains_rather_than_404s(self, solving_console: TestClient) -> None:
        response = solving_console.get("/console/solve/deadbeefdeadbeef")

        assert response.status_code == 200
        assert "no longer running" in response.text

    def test_stopping_one_explains_too(self, solving_console: TestClient) -> None:
        response = solving_console.post("/console/solve/deadbeefdeadbeef/stop")

        assert "no longer running" in response.text

    def test_asking_it_why_explains_too(self, solving_console: TestClient) -> None:
        response = solving_console.get("/console/solve/deadbeefdeadbeef/impossible")

        assert "no longer running" in response.text


class TestThePageIsOneReadingOfTheJob:
    """The defect that turned `main` red, as a test.

    `job.status` is replaced by the worker thread. `_watching` loaded it three times — for the
    numbers, for the sentences, and for whether the solve had finished — so a solve that
    settled between the first load and the third produced a page that was **settled by one
    reading and unfinished by another**: no Stop button, and no link to the timetable it had
    just written. The log line beside it said `timetable=1`.

    It passed locally twelve times running and on the phase branch's CI, and failed on
    `main`'s run of the same commit. Nothing about it is about how fast the machine is — it is
    about how many times the page looks. #303 made one look coherent; the fix is to take one.
    """

    def _interleaved(self, before: SolveStatus, after: SolveStatus) -> tuple[Job, list[int]]:
        """A job whose worker lands exactly once, right after the first read of `status`.

        Returns the reads counter too, because *how many times the render looked* is the rule
        and the missing link is only one shape of getting it wrong.
        """
        reads: list[int] = []

        class Interleaved(Job):
            @property
            def status(self) -> SolveStatus:
                reads.append(1)
                return before if len(reads) == 1 else after

            @status.setter
            def status(self, value: SolveStatus) -> None:
                pass

        return Interleaved(id="j", term_id=1, started=0.0, stop=Stop(), status=before), reads

    def test_a_solve_that_settles_mid_render_still_shows_its_timetable(
        self, solvable: Term, project: Engine
    ) -> None:
        running = SolveStatus(job_id="j", phase=SolvePhase.OPTIMISING, penalty=12)
        finished = SolveStatus(job_id="j", phase=SolvePhase.DONE, penalty=12, timetable_id=7)
        job, _ = self._interleaved(running, finished)

        with session_factory(project)() as db:
            rendered = bytes(_watching(_a_request(), db, job).body).decode()

        assert "Stop and keep" in rendered or "/console/timetables/7" in rendered, (
            "the page said the solve had finished and offered no way to reach its result — "
            "it was assembled from two different readings of the job"
        )

    def test_it_takes_exactly_one_reading(self, solvable: Term, project: Engine) -> None:
        """The rule rather than one of its symptoms. Anything that loads the status twice can
        describe two moments, and this is the cheapest way to say so."""
        status = SolveStatus(job_id="j", phase=SolvePhase.OPTIMISING, penalty=12)
        job, reads = self._interleaved(status, status)

        with session_factory(project)() as db:
            _watching(_a_request(), db, job)

        assert len(reads) == 1, f"the render loaded `job.status` {len(reads)} times"


class TestWhatEachEndingSays:
    """The two endings whose meaning depends on whether anything was found.

    Asserted against a constructed job rather than a real solve, because *which* ending a
    search reaches is a fact about seconds and #244 forbids a test being about those.
    """

    def _reading(
        self,
        phase: SolvePhase,
        timetable_id: int | None,
        penalty: int | None = None,
        lower_bound: int | None = None,
    ) -> SolveStatus:
        return SolveStatus(
            job_id="j",
            phase=phase,
            timetable_id=timetable_id,
            penalty=penalty,
            lower_bound=lower_bound,
        )

    def test_running_out_of_time_does_not_claim_the_term_is_impossible(self) -> None:
        headline, explanation = wording(self._reading(SolvePhase.DONE, None))

        assert "Nothing was found" in headline
        assert "says nothing about whether a timetable exists" in explanation

    def test_finishing_with_a_result_says_so(self) -> None:
        headline, _ = wording(self._reading(SolvePhase.DONE, 3, penalty=140))

        assert headline == "Finished"

    def test_running_out_of_time_offers_a_longer_budget(self) -> None:
        _, explanation = wording(self._reading(SolvePhase.DONE, 3, penalty=140))

        assert "longer budget" in explanation

    def test_a_score_of_zero_does_not_claim_the_clock_beat_it(self) -> None:
        """Found by watching a real solve: 120 sessions reached zero in 14 seconds of a
        sixty-second budget, under the sentence *the budget ran out*. Offering to try again
        for longer is advice to re-derive a provably optimal answer."""
        _, explanation = wording(self._reading(SolvePhase.DONE, 3, penalty=0))

        assert "longer budget" not in explanation
        assert "Nothing about this timetable can be improved" in explanation

    def test_reaching_the_lower_bound_says_it_is_proven(self) -> None:
        _, explanation = wording(self._reading(SolvePhase.DONE, 3, penalty=140, lower_bound=140))

        assert "provably the best" in explanation

    def test_stopping_after_a_result_keeps_it(self) -> None:
        headline, explanation = wording(self._reading(SolvePhase.CANCELLED, 3))

        assert headline == "Stopped"
        assert "saved" in explanation

    def test_stopping_before_one_says_there_is_nothing(self) -> None:
        headline, _ = wording(self._reading(SolvePhase.CANCELLED, None))

        assert "before anything was found" in headline

    def test_every_other_phase_has_a_sentence(self) -> None:
        """A phase with no entry would raise a KeyError on the page rather than say nothing."""
        unattributed = set(SolvePhase) - set(PHASES) - {SolvePhase.DONE, SolvePhase.CANCELLED}

        assert not unattributed
