"""The course catalogue, over HTTP.

The rules themselves are tested in `tests/repository/test_teaching.py`. This checks what
only appears at the edge: status codes, the shape of the response, and that a repository
refusal arrives as the right Problem rather than a 500.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def department(client: TestClient) -> int:
    """A department, created through the API rather than the ORM.

    Deliberately not a database fixture: it exercises the create endpoints on the way to
    testing everything else, so a broken POST fails loudly here instead of quietly
    weakening every test that depends on it.
    """
    institution = client.post("/api/v1/institutions", json={"name": "Test University"}).json()
    created = client.post(
        "/api/v1/departments",
        json={"institution_id": institution["id"], "name": "Computer Science"},
    ).json()
    return int(created["id"])


class TestCreating:
    def test_a_course_is_created_with_its_department_expanded(
        self, client: TestClient, department: int
    ) -> None:
        response = client.post(
            "/api/v1/courses",
            json={
                "department_id": department,
                "code": "CS101",
                "name": "Intro to Programming",
                "credits": 4,
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["code"] == "CS101"
        assert body["credits"] == 4
        assert body["department"] == {"id": department, "name": "Computer Science"}

    def test_a_course_needs_no_department(self, client: TestClient) -> None:
        """A syllabus committee creates courses before ownership is settled; refusing
        until then would push the work back into a spreadsheet."""
        response = client.post("/api/v1/courses", json={"code": "GEN101", "name": "Ethics"})

        assert response.status_code == 201
        assert response.json()["department"] is None

    def test_a_duplicate_code_is_a_409(self, client: TestClient, department: int) -> None:
        payload = {"department_id": department, "code": "CS101", "name": "Intro"}
        client.post("/api/v1/courses", json=payload)

        response = client.post("/api/v1/courses", json=payload)

        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_an_unknown_department_is_a_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/courses", json={"department_id": 999, "code": "CS101", "name": "Intro"}
        )

        assert response.status_code == 404

    def test_a_missing_code_is_a_422(self, client: TestClient) -> None:
        assert client.post("/api/v1/courses", json={"name": "Nameless"}).status_code == 422

    def test_an_empty_code_is_a_422(self, client: TestClient) -> None:
        response = client.post("/api/v1/courses", json={"code": "", "name": "Intro"})

        assert response.status_code == 422


class TestReadingAndEditing:
    def test_a_course_is_fetched_by_id(self, client: TestClient, department: int) -> None:
        created = client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS101", "name": "Intro"},
        ).json()

        response = client.get(f"/api/v1/courses/{created['id']}")

        assert response.status_code == 200
        assert response.json()["code"] == "CS101"

    def test_an_unknown_course_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/courses/999").status_code == 404

    def test_a_patch_leaves_absent_fields_alone(self, client: TestClient, department: int) -> None:
        """`exclude_unset` is what makes this a PATCH rather than a replace: the
        department is not in the payload, so it must survive."""
        created = client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS101", "name": "Intro", "credits": 4},
        ).json()

        response = client.patch(f"/api/v1/courses/{created['id']}", json={"credits": 3})

        assert response.status_code == 200
        body = response.json()
        assert body["credits"] == 3
        assert body["name"] == "Intro"
        assert body["department"]["id"] == department

    def test_a_course_can_be_detached_from_its_department(
        self, client: TestClient, department: int
    ) -> None:
        """An explicit null clears; an absent field would not. The two must stay
        distinguishable, which is the whole reason for `exclude_unset`."""
        created = client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS101", "name": "Intro"},
        ).json()

        response = client.patch(f"/api/v1/courses/{created['id']}", json={"department_id": None})

        assert response.status_code == 200
        assert response.json()["department"] is None

    def test_patching_into_a_collision_is_a_409(self, client: TestClient, department: int) -> None:
        client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS101", "name": "Intro"},
        )
        second = client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS102", "name": "Data"},
        ).json()

        response = client.patch(f"/api/v1/courses/{second['id']}", json={"code": "CS101"})

        assert response.status_code == 409


class TestListing:
    def test_listing_returns_a_page_envelope(self, client: TestClient, department: int) -> None:
        client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS101", "name": "Intro"},
        )

        body = client.get("/api/v1/courses").json()

        assert body["total"] == 1
        assert [c["code"] for c in body["items"]] == ["CS101"]

    def test_listing_filters_by_department(self, client: TestClient, department: int) -> None:
        client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS101", "name": "Intro"},
        )
        client.post("/api/v1/courses", json={"code": "GEN101", "name": "Ethics"})

        body = client.get("/api/v1/courses", params={"department_id": department}).json()

        assert [c["code"] for c in body["items"]] == ["CS101"]


class TestDeleting:
    def test_deleting_returns_204(self, client: TestClient, department: int) -> None:
        created = client.post(
            "/api/v1/courses",
            json={"department_id": department, "code": "CS101", "name": "Intro"},
        ).json()

        assert client.delete(f"/api/v1/courses/{created['id']}").status_code == 204
        assert client.get(f"/api/v1/courses/{created['id']}").status_code == 404

    def test_deleting_an_unknown_course_is_a_404(self, client: TestClient) -> None:
        assert client.delete("/api/v1/courses/999").status_code == 404
