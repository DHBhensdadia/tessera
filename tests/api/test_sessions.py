"""Weekly patterns and sessions, over HTTP.

The rules are tested in `tests/repository/test_sessions.py`. This checks what only
appears at the edge: status codes, the expanded references a client needs to render a
row without a second request, and that a refusal arrives as the right Problem.

Sessions cannot be created over HTTP — there is no `POST /sessions`, by design — so the
few tests that need one reach past the API to make it. Part 4 makes them properly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from tessera.repository import models as m

# Lunch at slots 8 and 9 is not decoration: it splits the day into two runs of eight, so
# the longest placeable block is 8 rather than 16. Without it a "too long" test would
# have to use an absurd number, and would stop exercising the interesting case — a block
# that fits in the day but cannot avoid the break.
WEEK = {
    "days": 5,
    "slots_per_day": 16,
    "slot_minutes": 30,
    "day_start_minute": 540,
    "break_slots": [8, 9],
}


@pytest.fixture
def campus(client: TestClient) -> dict[str, int]:
    """An offering with an intake, three sub-batches, an instructor and a feature."""
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
            "/api/v1/student-groups",
            json={"name": name, "size": 40, "parent_id": intake["id"]},
        ).json()["id"]
        for name in ("A1", "A2", "A3")
    ]
    teacher = client.post("/api/v1/instructors", json={"name": "Prof. Sharma"}).json()
    projector = client.post(
        "/api/v1/features", json={"institution_id": institution["id"], "name": "projector"}
    ).json()
    return {
        "term": term["id"],
        "offering": offering["id"],
        "intake": intake["id"],
        "a1": batches[0],
        "a2": batches[1],
        "a3": batches[2],
        "instructor": teacher["id"],
        "projector": projector["id"],
    }


def generated_session(engine: Engine, campus: dict[str, int], *, duration: int = 2) -> int:
    """A session made past the API, since nothing over HTTP creates one."""
    with DbSession(engine) as db:
        offering = db.get(m.Offering, campus["offering"])
        assert offering is not None
        row = m.Session(
            offering_id=offering.id,
            term_id=offering.term_id,
            kind="lecture",
            duration_slots=duration,
        )
        row.attendees = [db.get(m.StudentGroup, campus["intake"])]  # type: ignore[list-item]
        db.add(row)
        db.commit()
        return int(row.id)


class TestTemplates:
    def test_a_template_expands_its_references(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.post(
            f"/api/v1/offerings/{campus['offering']}/templates",
            json={
                "offering_id": campus["offering"],
                "kind": "lab",
                "duration_slots": 4,
                "per_week": 1,
                "split_per_attendee": True,
                "attendee_ids": [campus["a1"], campus["a2"], campus["a3"]],
                "instructor_ids": [campus["instructor"]],
                "required_feature_ids": [campus["projector"]],
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["kind"] == "lab"
        assert {a["name"] for a in body["attendees"]} == {"A1", "A2", "A3"}
        assert [i["name"] for i in body["instructors"]] == ["Prof. Sharma"]
        assert [f["name"] for f in body["required_features"]] == ["projector"]
        assert body["session_count"] == 0

    def test_a_body_disagreeing_with_the_url_is_a_422(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.post(
            f"/api/v1/offerings/{campus['offering']}/templates",
            json={
                "offering_id": campus["offering"] + 99,
                "duration_slots": 2,
                "per_week": 1,
                "attendee_ids": [campus["intake"]],
            },
        )

        assert response.status_code == 422

    def test_a_template_with_no_attendees_is_a_422(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """Caught by the wire model: `attendee_ids` has `min_length=1`, so this never
        reaches the domain rule that says the same thing."""
        response = client.post(
            f"/api/v1/offerings/{campus['offering']}/templates",
            json={
                "offering_id": campus["offering"],
                "duration_slots": 2,
                "per_week": 1,
                "attendee_ids": [],
            },
        )

        assert response.status_code == 422

    def test_a_component_longer_than_the_day_is_a_409(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.post(
            f"/api/v1/offerings/{campus['offering']}/templates",
            json={
                "offering_id": campus["offering"],
                "duration_slots": 12,
                "per_week": 1,
                "attendee_ids": [campus["intake"]],
            },
        )

        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_an_unknown_attendee_is_a_422_naming_the_field(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.post(
            f"/api/v1/offerings/{campus['offering']}/templates",
            json={
                "offering_id": campus["offering"],
                "duration_slots": 2,
                "per_week": 1,
                "attendee_ids": [999],
            },
        )

        assert response.status_code == 422
        assert "attendee_ids" in response.text

    def test_listing_returns_a_page_envelope(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        client.post(
            f"/api/v1/offerings/{campus['offering']}/templates",
            json={
                "offering_id": campus["offering"],
                "duration_slots": 2,
                "per_week": 3,
                "attendee_ids": [campus["intake"]],
            },
        )

        body = client.get(f"/api/v1/offerings/{campus['offering']}/templates").json()

        assert body["total"] == 1
        assert body["items"][0]["per_week"] == 3

    def test_a_template_is_deleted(self, client: TestClient, campus: dict[str, int]) -> None:
        created = client.post(
            f"/api/v1/offerings/{campus['offering']}/templates",
            json={
                "offering_id": campus["offering"],
                "duration_slots": 2,
                "per_week": 1,
                "attendee_ids": [campus["intake"]],
            },
        ).json()

        assert client.delete(f"/api/v1/templates/{created['id']}").status_code == 204
        assert client.get(f"/api/v1/offerings/{campus['offering']}/templates").json()["total"] == 0

    def test_deleting_an_unknown_template_is_a_404(self, client: TestClient) -> None:
        assert client.delete("/api/v1/templates/999").status_code == 404


class TestSessions:
    def test_a_session_carries_what_a_row_needs_to_render(
        self, client: TestClient, engine: Engine, campus: dict[str, int]
    ) -> None:
        """Course, attendees and headcount in one response.

        A client drawing a week needs all three per session; bare ids would make it
        hundreds of round trips for one screen.
        """
        created = generated_session(engine, campus)

        body = client.get(f"/api/v1/sessions/{created}").json()

        assert body["course"]["name"] == "CS301 Operating Systems"
        assert [a["name"] for a in body["attendees"]] == ["2024 Intake"]
        assert body["headcount"] == 120

    def test_sessions_are_listed_for_a_term(
        self, client: TestClient, engine: Engine, campus: dict[str, int]
    ) -> None:
        generated_session(engine, campus)

        body = client.get(f"/api/v1/terms/{campus['term']}/sessions").json()

        assert body["total"] == 1

    def test_the_group_filter_narrows(
        self, client: TestClient, engine: Engine, campus: dict[str, int]
    ) -> None:
        generated_session(engine, campus)

        body = client.get(
            f"/api/v1/terms/{campus['term']}/sessions", params={"group_id": campus["a1"]}
        ).json()

        assert body["total"] == 0

    def test_a_session_can_be_lengthened(
        self, client: TestClient, engine: Engine, campus: dict[str, int]
    ) -> None:
        created = generated_session(engine, campus)

        response = client.patch(f"/api/v1/sessions/{created}", json={"duration_slots": 4})

        assert response.status_code == 200
        assert response.json()["duration_slots"] == 4

    def test_lengthening_beyond_the_day_is_a_409(
        self, client: TestClient, engine: Engine, campus: dict[str, int]
    ) -> None:
        created = generated_session(engine, campus)

        response = client.patch(f"/api/v1/sessions/{created}", json={"duration_slots": 12})

        assert response.status_code == 409

    def test_an_unknown_session_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/sessions/999").status_code == 404

    def test_deleting_an_offering_with_sessions_is_a_409(
        self, client: TestClient, engine: Engine, campus: dict[str, int]
    ) -> None:
        """The guard part 2 could only prove through the ORM, now reachable normally."""
        generated_session(engine, campus)

        assert client.delete(f"/api/v1/offerings/{campus['offering']}").status_code == 409
