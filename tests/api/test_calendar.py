"""Time grids, terms and offerings, over HTTP.

The rules themselves are tested in `tests/repository/test_calendar.py`. This checks what
only appears at the edge: status codes, response shape, and that a repository refusal
arrives as the right Problem rather than a 500.

It also holds the guard for Decision #51, which is unusual in having no code to break —
see `TestTheGridCannotBeEdited`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

WEEK: dict[str, object] = {
    "days": 5,
    "slots_per_day": 16,
    "slot_minutes": 30,
    "day_start_minute": 540,
}


@pytest.fixture
def campus(client: TestClient) -> dict[str, int]:
    """An institution with a teaching week and a course, created through the API."""
    institution = client.post("/api/v1/institutions", json={"name": "Test University"}).json()
    grid = client.post(
        "/api/v1/time-grids",
        json={"institution_id": institution["id"], "name": "Standard", **WEEK},
    ).json()
    course = client.post("/api/v1/courses", json={"code": "CS101", "name": "Intro"}).json()
    return {"institution": institution["id"], "grid": grid["id"], "course": course["id"]}


@pytest.fixture
def term(client: TestClient, campus: dict[str, int]) -> int:
    created = client.post(
        "/api/v1/terms",
        json={
            "institution_id": campus["institution"],
            "time_grid_id": campus["grid"],
            "academic_year": "2026-27",
            "name": "Autumn",
        },
    ).json()
    return int(created["id"])


class TestTimeGrids:
    def test_a_grid_reports_its_slot_count(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.get(f"/api/v1/time-grids/{campus['grid']}")

        assert response.status_code == 200
        body = response.json()
        assert body["slot_count"] == 80
        assert body["break_slots"] == []

    def test_breaks_round_trip_in_order(self, client: TestClient, campus: dict[str, int]) -> None:
        response = client.post(
            "/api/v1/time-grids",
            json={
                "institution_id": campus["institution"],
                "name": "With lunch",
                "break_slots": [9, 8],
                **WEEK,
            },
        )

        assert response.status_code == 201
        assert response.json()["break_slots"] == [8, 9]

    def test_a_break_outside_the_day_is_a_409(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.post(
            "/api/v1/time-grids",
            json={"institution_id": campus["institution"], "break_slots": [99], **WEEK},
        )

        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_an_impossible_week_is_a_422(self, client: TestClient, campus: dict[str, int]) -> None:
        """Caught by the wire model before the domain sees it: `days` is bounded 1-7."""
        response = client.post(
            "/api/v1/time-grids",
            json={"institution_id": campus["institution"], **{**WEEK, "days": 0}},
        )

        assert response.status_code == 422

    def test_deleting_a_grid_in_use_is_a_409(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        response = client.delete(f"/api/v1/time-grids/{campus['grid']}")

        assert response.status_code == 409

    def test_an_unused_grid_is_deleted(self, client: TestClient, campus: dict[str, int]) -> None:
        assert client.delete(f"/api/v1/time-grids/{campus['grid']}").status_code == 204
        assert client.get(f"/api/v1/time-grids/{campus['grid']}").status_code == 404


class TestTheGridCannotBeEdited:
    """Decision #51, guarded at the published surface.

    Every stored slot index — every assignment, every blocked slot, every pinned
    placement — means what it means only by reference to its grid's shape. Editing a
    grid would reinterpret all of them at once, silently and without error.

    There is no code here to mutate, so the usual "break the guard and watch a test
    fail" does not apply. What can be checked is that the route does not exist, and
    that adding one fails a build rather than passing review as a small convenience.

    The first attempt at this walked `app.routes` and was **vacuous**: FastAPI stores
    included routers as opaque objects with no `path`, so the comprehension was always
    empty and the assertion always held. It was caught by adding the forbidden route and
    watching the test pass anyway. The spec is both the honest source and the one that
    matters, since it is what a generated client is built from.
    """

    def test_the_contract_offers_no_way_to_edit_a_grid(self, app: FastAPI) -> None:
        paths = app.openapi()["paths"]
        offending = sorted(
            f"{method.upper()} {path}"
            for path, operations in paths.items()
            if path.startswith("/api/v1/time-grids")
            for method in operations
            if method in {"patch", "put"}
        )

        assert not offending, (
            f"a time grid must not be editable — found {offending}. "
            "See Decision #51: editing a grid silently reinterprets every slot index "
            "stored against every term using it. Create a new grid instead."
        )

    def test_patching_a_grid_is_refused_by_the_router(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """The same fact from the caller's side: 405, not 200."""
        response = client.patch(f"/api/v1/time-grids/{campus['grid']}", json={"slots_per_day": 12})

        assert response.status_code == 405


class TestTerms:
    def test_a_term_expands_its_grid(self, client: TestClient, term: int) -> None:
        response = client.get(f"/api/v1/terms/{term}")

        assert response.status_code == 200
        assert response.json()["time_grid"]["name"] == "Standard"

    def test_a_grid_from_another_institution_is_a_409(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        other = client.post("/api/v1/institutions", json={"name": "Somewhere Else"}).json()

        response = client.post(
            "/api/v1/terms",
            json={
                "institution_id": other["id"],
                "time_grid_id": campus["grid"],
                "academic_year": "2026-27",
                "name": "Autumn",
            },
        )

        assert response.status_code == 409

    def test_dates_in_the_wrong_order_are_a_409(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.post(
            "/api/v1/terms",
            json={
                "institution_id": campus["institution"],
                "time_grid_id": campus["grid"],
                "academic_year": "2026-27",
                "name": "Autumn",
                "starts_on": "2026-12-18",
                "ends_on": "2026-09-01",
            },
        )

        assert response.status_code == 409

    def test_a_patch_leaves_absent_fields_alone(self, client: TestClient, term: int) -> None:
        response = client.patch(f"/api/v1/terms/{term}", json={"starts_on": "2026-09-01"})

        assert response.status_code == 200
        body = response.json()
        assert body["starts_on"] == "2026-09-01"
        assert body["name"] == "Autumn"
        assert body["time_grid"]["name"] == "Standard"

    def test_a_duplicate_term_is_a_409(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        response = client.post(
            "/api/v1/terms",
            json={
                "institution_id": campus["institution"],
                "time_grid_id": campus["grid"],
                "academic_year": "2026-27",
                "name": "Autumn",
            },
        )

        assert response.status_code == 409

    def test_an_unknown_term_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/terms/999").status_code == 404

    def test_an_empty_term_is_deleted(self, client: TestClient, term: int) -> None:
        assert client.delete(f"/api/v1/terms/{term}").status_code == 204


class TestOfferings:
    def test_a_course_is_offered_and_the_course_is_expanded(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        response = client.post(
            f"/api/v1/terms/{term}/offerings",
            json={"term_id": term, "course_id": campus["course"]},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["course"]["name"] == "CS101 Intro"
        assert body["session_count"] == 0

    def test_a_body_disagreeing_with_the_url_is_a_422(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        """Whichever term the caller meant, they believe the offering went somewhere it
        did not — and that belief surfaces later as a course missing from a timetable."""
        response = client.post(
            f"/api/v1/terms/{term}/offerings",
            json={"term_id": term + 1, "course_id": campus["course"]},
        )

        assert response.status_code == 422

    def test_offering_the_same_course_twice_is_a_409(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        payload = {"term_id": term, "course_id": campus["course"]}
        client.post(f"/api/v1/terms/{term}/offerings", json=payload)

        response = client.post(f"/api/v1/terms/{term}/offerings", json=payload)

        assert response.status_code == 409

    def test_listing_offerings_returns_a_page_envelope(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        client.post(
            f"/api/v1/terms/{term}/offerings",
            json={"term_id": term, "course_id": campus["course"]},
        )

        body = client.get(f"/api/v1/terms/{term}/offerings").json()

        assert body["total"] == 1
        assert body["items"][0]["term_id"] == term

    def test_deleting_a_term_with_offerings_is_a_409(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        client.post(
            f"/api/v1/terms/{term}/offerings",
            json={"term_id": term, "course_id": campus["course"]},
        )

        assert client.delete(f"/api/v1/terms/{term}").status_code == 409

    def test_deleting_an_offered_course_is_a_409(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        """The guard part 1 could only prove through the ORM, now reachable normally."""
        client.post(
            f"/api/v1/terms/{term}/offerings",
            json={"term_id": term, "course_id": campus["course"]},
        )

        assert client.delete(f"/api/v1/courses/{campus['course']}").status_code == 409

    def test_an_offering_is_deleted(
        self, client: TestClient, campus: dict[str, int], term: int
    ) -> None:
        created = client.post(
            f"/api/v1/terms/{term}/offerings",
            json={"term_id": term, "course_id": campus["course"]},
        ).json()

        assert client.delete(f"/api/v1/offerings/{created['id']}").status_code == 204
        assert client.get(f"/api/v1/terms/{term}/offerings").json()["total"] == 0
