"""The structural scaffolding, over HTTP.

The rules are tested in `tests/repository/test_authoring.py`. This checks the edge: that
every structural entity can now be fetched, renamed and — where it has no dependants —
removed, and that the refusals arrive as Problems rather than 500s.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def campus(client: TestClient) -> dict[str, int]:
    institution = client.post("/api/v1/institutions", json={"name": "Test Univarsity"}).json()
    building = client.post(
        "/api/v1/buildings", json={"institution_id": institution["id"], "name": "Blok A"}
    ).json()
    feature = client.post(
        "/api/v1/features", json={"institution_id": institution["id"], "name": "projecter"}
    ).json()
    department = client.post(
        "/api/v1/departments", json={"institution_id": institution["id"], "name": "Compter Science"}
    ).json()
    program = client.post("/api/v1/programs", json={"name": "BTech CSE"}).json()
    return {
        "institution": institution["id"],
        "building": building["id"],
        "feature": feature["id"],
        "department": department["id"],
        "program": program["id"],
    }


class TestTheTyposCanNowBeFixed:
    """Every one of these names was mistyped on the way in. Before 2.4b none of them
    could be corrected without deleting and recreating — and two of them could not be
    deleted either."""

    def test_an_institution_is_renamed(self, client: TestClient, campus: dict[str, int]) -> None:
        response = client.patch(
            f"/api/v1/institutions/{campus['institution']}", json={"name": "Test University"}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Test University"

    def test_a_building_is_renamed(self, client: TestClient, campus: dict[str, int]) -> None:
        response = client.patch(f"/api/v1/buildings/{campus['building']}", json={"name": "Block A"})

        assert response.status_code == 200
        assert response.json()["name"] == "Block A"

    def test_a_feature_is_renamed(self, client: TestClient, campus: dict[str, int]) -> None:
        response = client.patch(f"/api/v1/features/{campus['feature']}", json={"name": "projector"})

        assert response.status_code == 200
        assert response.json()["name"] == "projector"

    def test_a_department_is_renamed_and_coded(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.patch(
            f"/api/v1/departments/{campus['department']}",
            json={"name": "Computer Science", "code": "CSE"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Computer Science"
        assert body["code"] == "CSE"

    def test_a_programme_is_renamed(self, client: TestClient, campus: dict[str, int]) -> None:
        response = client.patch(
            f"/api/v1/programs/{campus['program']}", json={"name": "B.Tech CSE"}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "B.Tech CSE"

    def test_renaming_onto_a_sibling_is_a_409(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        other = client.post(
            "/api/v1/buildings",
            json={"institution_id": campus["institution"], "name": "Block B"},
        ).json()

        response = client.patch(f"/api/v1/buildings/{other['id']}", json={"name": "Blok A"})

        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_an_empty_name_is_a_422(self, client: TestClient, campus: dict[str, int]) -> None:
        assert (
            client.patch(f"/api/v1/buildings/{campus['building']}", json={"name": ""}).status_code
            == 422
        )

    def test_patching_something_absent_is_a_404(self, client: TestClient) -> None:
        assert client.patch("/api/v1/buildings/999", json={"name": "Nowhere"}).status_code == 404


class TestFetchingOne:
    def test_each_entity_is_fetchable(self, client: TestClient, campus: dict[str, int]) -> None:
        for resource, key in (
            ("institutions", "institution"),
            ("buildings", "building"),
            ("features", "feature"),
            ("departments", "department"),
            ("programs", "program"),
        ):
            response = client.get(f"/api/v1/{resource}/{campus[key]}")
            assert response.status_code == 200, resource
            assert response.json()["id"] == campus[key]

    def test_an_absent_one_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/institutions/999").status_code == 404


class TestDeleting:
    def test_deleting_a_busy_institution_is_a_409(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.delete(f"/api/v1/institutions/{campus['institution']}")

        assert response.status_code == 409

    def test_an_empty_institution_is_deleted(self, client: TestClient) -> None:
        created = client.post("/api/v1/institutions", json={"name": "Doomed"}).json()

        assert client.delete(f"/api/v1/institutions/{created['id']}").status_code == 204
        assert client.get(f"/api/v1/institutions/{created['id']}").status_code == 404

    def test_a_department_holding_only_courses_is_deleted(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """The case most likely to be guarded wrongly by reflex: a course with no
        department is a state the catalogue is designed for."""
        course = client.post(
            "/api/v1/courses",
            json={"department_id": campus["department"], "code": "CS101", "name": "Intro"},
        ).json()

        assert client.delete(f"/api/v1/departments/{campus['department']}").status_code == 204
        assert client.get(f"/api/v1/courses/{course['id']}").json()["department"] is None

    def test_a_department_with_a_programme_is_a_409(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        client.post(
            "/api/v1/programs", json={"name": "MTech CSE", "department_id": campus["department"]}
        )

        assert client.delete(f"/api/v1/departments/{campus['department']}").status_code == 409


class TestOfferingsAndTemplatesAreFetchable:
    def test_an_offering_can_be_fetched_on_its_own(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        grid = client.post(
            "/api/v1/time-grids",
            json={
                "institution_id": campus["institution"],
                "days": 5,
                "slots_per_day": 16,
                "slot_minutes": 30,
                "day_start_minute": 540,
            },
        ).json()
        term = client.post(
            "/api/v1/terms",
            json={
                "institution_id": campus["institution"],
                "time_grid_id": grid["id"],
                "academic_year": "2026-27",
                "name": "Autumn",
            },
        ).json()
        course = client.post("/api/v1/courses", json={"code": "CS101", "name": "Intro"}).json()
        offering = client.post(
            f"/api/v1/terms/{term['id']}/offerings",
            json={"term_id": term["id"], "course_id": course["id"]},
        ).json()

        response = client.get(f"/api/v1/offerings/{offering['id']}")

        assert response.status_code == 200
        assert response.json()["course"]["name"] == "CS101 Intro"

    def test_an_absent_offering_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/offerings/999").status_code == 404
