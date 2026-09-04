"""The six solving routes, end to end against a real project file.

The engine could not do any of this before 4.7: it had a solver, a scorer and an explainer,
and no way to point them at the project a person had open.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from tessera.repository import models as m
from tessera.repository import structure as structure_repo
from tests.api.conftest import settled
from tests.repository.authored import Term, term_with_sessions


class TestSolvingATerm:
    def test_a_solve_produces_a_timetable_that_can_be_read_back(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """The whole point of the phase, through HTTP for the first time."""
        started = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
        )
        assert started.status_code == 202
        job = started.json()
        assert job["phase"] == "queued"

        final = settled(solving_client, job["job_id"])

        assert final["phase"] == "done"
        assert final["timetable_id"] is not None
        read = solving_client.get(f"/api/v1/timetables/{final['timetable_id']}")
        assert read.status_code == 200
        assert read.json()["assignment_count"] == len(solvable.session_ids)

    def test_the_result_is_a_new_timetable_rather_than_an_overwritten_one(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """D5, and what `parent_id` was put in the first migration for."""
        first = settled(
            solving_client,
            solving_client.post(
                f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
            ).json()["job_id"],
        )
        again = settled(
            solving_client,
            solving_client.post(
                f"/api/v1/terms/{solvable.term_id}/solve",
                json={"time_budget_seconds": 20, "seed_timetable_id": first["timetable_id"]},
            ).json()["job_id"],
        )

        assert again["timetable_id"] != first["timetable_id"]
        both = solving_client.get(f"/api/v1/terms/{solvable.term_id}/timetables").json()
        assert both["total"] == 2
        newest = both["items"][0]
        assert newest["parent_id"] == first["timetable_id"]

    def test_two_solves_at_once_are_refused_by_name(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """D8. Two would contend for the same cores and make both slower than either, and the
        refusal names the job that holds the engine so a client can watch that one."""
        first = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 30}
        ).json()

        refused = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 30}
        )

        assert refused.status_code == 409
        assert first["job_id"] in refused.json()["detail"]

        solving_client.post(f"/api/v1/solve/{first['job_id']}/cancel")
        settled(solving_client, first["job_id"])

    def test_a_term_that_is_not_there(self, solving_client: TestClient) -> None:
        assert solving_client.post("/api/v1/terms/404/solve", json={}).status_code == 404

    def test_a_budget_outside_what_the_contract_allows(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        refused = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 0}
        )

        assert refused.status_code == 422


class TestStopping:
    def test_a_cancelled_solve_keeps_what_it_found(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """D4. Stopping is not discarding — P7 draws `[ Stop ] [ Keep Result ]`."""
        job = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 300}
        ).json()

        assert solving_client.post(f"/api/v1/solve/{job['job_id']}/cancel").status_code == 204
        final = settled(solving_client, job["job_id"])

        assert final["phase"] == "cancelled"

    def test_cancelling_twice_is_not_an_error(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        job = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 300}
        ).json()
        solving_client.post(f"/api/v1/solve/{job['job_id']}/cancel")
        settled(solving_client, job["job_id"])

        assert solving_client.post(f"/api/v1/solve/{job['job_id']}/cancel").status_code == 204

    def test_a_job_nobody_started(self, solving_client: TestClient) -> None:
        assert solving_client.get("/api/v1/solve/nosuchjob").status_code == 404
        assert solving_client.post("/api/v1/solve/nosuchjob/cancel").status_code == 404


class TestTheRefusal:
    def test_an_impossible_term_says_so_and_explains_itself(
        self, solving_client: TestClient, project_db: DbSession
    ) -> None:
        """The differentiator, over HTTP: not *no solution found* but which rule cannot hold."""
        institution = m.Institution(name="Sardar Patel University")
        project_db.add(institution)
        project_db.commit()
        grid = m.TimeGrid(
            institution_id=institution.id,
            name="Standard",
            days=5,
            slots_per_day=8,
            slot_minutes=60,
            day_start_minute=9 * 60,
        )
        project_db.add(grid)
        project_db.commit()
        term = term_with_sessions(project_db, institution, grid, capacity=5)

        job = solving_client.post(
            f"/api/v1/terms/{term.term_id}/solve", json={"time_budget_seconds": 20}
        ).json()
        final = settled(solving_client, job["job_id"])

        assert final["phase"] == "infeasible"
        assert final["timetable_id"] is None

        report = solving_client.get(f"/api/v1/solve/{job['job_id']}/result")
        assert report.status_code == 200
        body = report.json()
        assert body["summary"].startswith("No valid timetable exists")
        assert body["requirements"], "a refusal with nothing in it is 'no solution found'"

    def test_a_solved_term_has_no_report_to_give(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """409 rather than an empty report: nothing proved anything impossible."""
        job = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
        ).json()
        settled(solving_client, job["job_id"])

        refused = solving_client.get(f"/api/v1/solve/{job['job_id']}/result")

        assert refused.status_code == 409


class TestPreflight:
    def test_a_term_nothing_refutes(self, solving_client: TestClient, solvable: Term) -> None:
        answered = solving_client.post(f"/api/v1/terms/{solvable.term_id}/preflight")

        assert answered.status_code == 200
        body = answered.json()
        assert body["can_solve"] is True
        assert body["problems"] == []
        assert body["session_count"] == len(solvable.session_ids)

    def test_a_session_no_room_can_hold_is_named(
        self, solving_client: TestClient, project_db: DbSession, solvable: Term
    ) -> None:
        """P7 draws *"Show sessions"* beside every line, so a count with no way to see what it
        is counting would be the same unhelpfulness as "no solution found" with a number."""
        for room_id in solvable.room_ids:
            structure_repo.update_room(project_db, room_id, changes={"capacity": 5})
        project_db.commit()

        body = solving_client.post(f"/api/v1/terms/{solvable.term_id}/preflight").json()

        assert body["can_solve"] is False
        assert body["problems"]
        assert sorted(body["unplaceable_session_ids"]) == sorted(solvable.session_ids)
        assert body["problems"][0]["detail"], "the arithmetic is the point"

    def test_a_set_that_collides_names_no_session_in_particular(
        self, solving_client: TestClient, project_db: DbSession
    ) -> None:
        """The other half of the rule, and the one that distinguishes it.

        Twenty-five two-hour classes for one group in a forty-hour week is a shortage, not an
        absence: the rooms are open, every session could be placed on its own, and it is the
        *set* that does not fit. Listing them all as unplaceable would send somebody to look at
        sessions that are individually fine — so `problems` says what is wrong and
        `unplaceable_session_ids` stays empty.
        """
        institution = m.Institution(name="Sardar Patel University")
        project_db.add(institution)
        project_db.commit()
        grid = m.TimeGrid(
            institution_id=institution.id,
            name="Standard",
            days=5,
            slots_per_day=8,
            slot_minutes=60,
            day_start_minute=9 * 60,
        )
        project_db.add(grid)
        project_db.commit()
        crowded = term_with_sessions(project_db, institution, grid, per_week=25, rooms=3)

        body = solving_client.post(f"/api/v1/terms/{crowded.term_id}/preflight").json()

        assert body["can_solve"] is False
        assert body["problems"], "twenty-five classes do not fit in twenty hours"
        assert body["unplaceable_session_ids"] == []

    def test_a_term_that_is_not_there(self, solving_client: TestClient) -> None:
        assert solving_client.post("/api/v1/terms/404/preflight").status_code == 404
