"""Expansion over HTTP — P7's weekly-pattern screen, end to end.

The reconciliation rules are tested in `tests/repository/test_expansion.py`. This is the
journey a user actually takes: author a pattern, press expand, see the sessions, change
the pattern, press expand again.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

WEEK = {
    "days": 5,
    "slots_per_day": 16,
    "slot_minutes": 30,
    "day_start_minute": 540,
    "break_slots": [8, 9],
}


@pytest.fixture
def campus(client: TestClient) -> dict[str, int]:
    institution = client.post("/api/v1/institutions", json={"name": "Test University"}).json()
    grid = client.post(
        "/api/v1/time-grids", json={"institution_id": institution["id"], **WEEK}
    ).json()
    term = client.post(
        "/api/v1/terms",
        json={
            "institution_id": institution["id"],
            "time_grid_id": grid["id"],
            "academic_year": "2026-27",
            "name": "Autumn",
        },
    ).json()
    course = client.post(
        "/api/v1/courses", json={"code": "CS301", "name": "Operating Systems"}
    ).json()
    offering = client.post(
        f"/api/v1/terms/{term['id']}/offerings",
        json={"term_id": term["id"], "course_id": course["id"]},
    ).json()
    intake = client.post("/api/v1/student-groups", json={"name": "2024 Intake", "size": 120}).json()
    batches = [
        client.post(
            "/api/v1/student-groups", json={"name": n, "size": 40, "parent_id": intake["id"]}
        ).json()["id"]
        for n in ("A1", "A2", "A3")
    ]
    return {
        "term": term["id"],
        "offering": offering["id"],
        "intake": intake["id"],
        "a1": batches[0],
        "a2": batches[1],
        "a3": batches[2],
    }


def add_lectures(client: TestClient, campus: dict[str, int], per_week: int = 3) -> int:
    created = client.post(
        f"/api/v1/offerings/{campus['offering']}/templates",
        json={
            "offering_id": campus["offering"],
            "kind": "lecture",
            "duration_slots": 2,
            "per_week": per_week,
            "attendee_ids": [campus["intake"]],
        },
    ).json()
    return int(created["id"])


def add_labs(client: TestClient, campus: dict[str, int]) -> int:
    created = client.post(
        f"/api/v1/offerings/{campus['offering']}/templates",
        json={
            "offering_id": campus["offering"],
            "kind": "lab",
            "duration_slots": 4,
            "per_week": 1,
            "split_per_attendee": True,
            "attendee_ids": [campus["a1"], campus["a2"], campus["a3"]],
        },
    ).json()
    return int(created["id"])


class TestExpanding:
    def test_the_journey_from_pattern_to_six_sessions(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """P7's weekly-pattern screen: three lectures to the whole batch, plus one lab
        per sub-batch, which the interface labels "generates 3 sessions"."""
        add_lectures(client, campus)
        add_labs(client, campus)

        response = client.post(f"/api/v1/offerings/{campus['offering']}/expand")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 6
        assert sum(1 for s in body["items"] if s["kind"] == "lab") == 3
        assert all(s["course"]["name"] == "CS301 Operating Systems" for s in body["items"])

    def test_a_lab_session_seats_only_its_own_batch(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """The split is the point: three parallel labs of 40, not one of 120."""
        add_labs(client, campus)

        body = client.post(f"/api/v1/offerings/{campus['offering']}/expand").json()

        assert {s["headcount"] for s in body["items"]} == {40}

    def test_the_template_reports_what_it_generated(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        add_lectures(client, campus)
        client.post(f"/api/v1/offerings/{campus['offering']}/expand")

        body = client.get(f"/api/v1/offerings/{campus['offering']}/templates").json()

        assert body["items"][0]["session_count"] == 3

    def test_the_offering_reports_its_session_count(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        add_lectures(client, campus)
        client.post(f"/api/v1/offerings/{campus['offering']}/expand")

        body = client.get(f"/api/v1/terms/{campus['term']}/offerings").json()

        assert body["items"][0]["session_count"] == 3

    def test_expanding_twice_is_a_no_op(self, client: TestClient, campus: dict[str, int]) -> None:
        add_lectures(client, campus)
        first = client.post(f"/api/v1/offerings/{campus['offering']}/expand").json()

        second = client.post(f"/api/v1/offerings/{campus['offering']}/expand").json()

        assert [s["id"] for s in first["items"]] == [s["id"] for s in second["items"]]

    def test_expanding_an_unknown_offering_is_a_404(self, client: TestClient) -> None:
        assert client.post("/api/v1/offerings/999/expand").status_code == 404


class TestEditingThePattern:
    def test_growing_the_pattern_adds_one_session(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        template = add_lectures(client, campus)
        before = client.post(f"/api/v1/offerings/{campus['offering']}/expand").json()

        client.patch(f"/api/v1/templates/{template}", json={"per_week": 4})
        after = client.post(f"/api/v1/offerings/{campus['offering']}/expand").json()

        assert after["total"] == 4
        assert {s["id"] for s in before["items"]} < {s["id"] for s in after["items"]}

    def test_the_shape_of_a_component_cannot_be_edited(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """`duration_slots` is absent from `SessionTemplateUpdate` deliberately: it is
        copied into each session so a session can diverge, and there is no honest way to
        propagate a change afterwards. Pydantic ignores the unknown field rather than
        applying it."""
        template = add_lectures(client, campus)

        response = client.patch(f"/api/v1/templates/{template}", json={"duration_slots": 8})

        assert response.status_code == 200
        assert response.json()["duration_slots"] == 2

    def test_narrowing_a_split_drops_that_batch(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        template = add_labs(client, campus)
        client.post(f"/api/v1/offerings/{campus['offering']}/expand")

        client.patch(
            f"/api/v1/templates/{template}",
            json={"attendee_ids": [campus["a1"], campus["a2"]]},
        )
        after = client.post(f"/api/v1/offerings/{campus['offering']}/expand").json()

        assert after["total"] == 2

    def test_an_empty_attendee_list_is_a_422(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        template = add_lectures(client, campus)

        response = client.patch(f"/api/v1/templates/{template}", json={"attendee_ids": []})

        assert response.status_code == 422

    def test_patching_an_unknown_template_is_a_404(self, client: TestClient) -> None:
        assert client.patch("/api/v1/templates/999", json={"per_week": 2}).status_code == 404
