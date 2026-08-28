"""Rooms and their scaffolding, over HTTP.

The rules themselves are tested in `tests/repository/test_structure.py`. This checks
what only appears at the edge: status codes, the shape of the response, and that a
repository failure arrives as the right Problem rather than a 500.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def campus(client: TestClient) -> dict[str, int]:
    """A small institution, created through the API rather than the ORM.

    Deliberately not a database fixture: it exercises the create endpoints on the way to
    testing everything else, so a broken POST fails loudly here instead of quietly
    weakening every test that depends on it.
    """
    institution = client.post("/api/v1/institutions", json={"name": "Test University"}).json()
    building = client.post(
        "/api/v1/buildings", json={"institution_id": institution["id"], "name": "Block A"}
    ).json()
    projector = client.post(
        "/api/v1/features", json={"institution_id": institution["id"], "name": "projector"}
    ).json()
    computers = client.post(
        "/api/v1/features", json={"institution_id": institution["id"], "name": "computers"}
    ).json()
    return {
        "institution": institution["id"],
        "building": building["id"],
        "projector": projector["id"],
        "computers": computers["id"],
    }


class TestCreating:
    def test_a_room_comes_back_with_its_names_expanded(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """Ids alone would force a request per related record to draw one table."""
        response = client.post(
            "/api/v1/rooms",
            json={
                "name": "LH-201",
                "capacity": 120,
                "building_id": campus["building"],
                "feature_ids": [campus["projector"]],
            },
        )
        assert response.status_code == 201

        room = response.json()
        assert room["building"]["name"] == "Block A"
        assert [f["name"] for f in room["features"]] == ["projector"]

    def test_a_duplicate_name_is_a_conflict_not_a_crash(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        payload = {"name": "LH-201", "capacity": 120, "building_id": campus["building"]}
        assert client.post("/api/v1/rooms", json=payload).status_code == 201

        response = client.post("/api/v1/rooms", json=payload)
        assert response.status_code == 409
        assert response.json()["type"].endswith("/conflict")

    def test_an_unknown_feature_is_reported_against_the_field(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        response = client.post(
            "/api/v1/rooms", json={"name": "LH-9", "capacity": 10, "feature_ids": [999_999]}
        )
        assert response.status_code == 422
        assert response.json()["errors"][0]["pointer"] == "body/feature_ids"

    def test_a_negative_capacity_is_refused_by_the_schema(self, client: TestClient) -> None:
        response = client.post("/api/v1/rooms", json={"name": "LH-1", "capacity": -5})
        assert response.status_code == 422


class TestReading:
    def test_a_missing_room_is_404_not_500(self, client: TestClient) -> None:
        response = client.get("/api/v1/rooms/999999")
        assert response.status_code == 404
        assert response.json()["type"].endswith("/not-found")

    def test_filters_reach_the_query(self, client: TestClient, campus: dict[str, int]) -> None:
        client.post(
            "/api/v1/rooms",
            json={"name": "LH-201", "capacity": 120, "feature_ids": [campus["projector"]]},
        )
        client.post(
            "/api/v1/rooms",
            json={
                "name": "CL-01",
                "capacity": 40,
                "feature_ids": [campus["projector"], campus["computers"]],
            },
        )

        assert client.get("/api/v1/rooms").json()["total"] == 2
        assert client.get("/api/v1/rooms?min_capacity=100").json()["total"] == 1

        both = client.get(
            f"/api/v1/rooms?feature_id={campus['projector']}&feature_id={campus['computers']}"
        ).json()
        assert [r["name"] for r in both["items"]] == ["CL-01"]


class TestUpdating:
    def test_an_absent_field_is_left_alone(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        room = client.post(
            "/api/v1/rooms",
            json={"name": "LH-201", "capacity": 120, "building_id": campus["building"]},
        ).json()

        updated = client.patch(f"/api/v1/rooms/{room['id']}", json={"capacity": 150}).json()

        assert updated["capacity"] == 150
        assert updated["name"] == "LH-201"
        assert updated["building"]["name"] == "Block A"

    def test_an_explicit_null_clears_the_field(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        """The case a plain None check cannot distinguish from "not sent"."""
        room = client.post(
            "/api/v1/rooms",
            json={"name": "LH-201", "capacity": 120, "building_id": campus["building"]},
        ).json()

        updated = client.patch(f"/api/v1/rooms/{room['id']}", json={"building_id": None}).json()

        assert updated["building"] is None


class TestDeleting:
    def test_an_unused_room_is_removed(self, client: TestClient) -> None:
        room = client.post("/api/v1/rooms", json={"name": "LH-201", "capacity": 120}).json()
        assert client.delete(f"/api/v1/rooms/{room['id']}").status_code == 204
        assert client.get(f"/api/v1/rooms/{room['id']}").status_code == 404

    def test_a_feature_in_use_is_refused_and_says_what_uses_it(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        client.post(
            "/api/v1/rooms",
            json={"name": "CL-01", "capacity": 40, "feature_ids": [campus["projector"]]},
        )

        response = client.delete(f"/api/v1/features/{campus['projector']}")
        assert response.status_code == 409

        problem = response.json()
        assert problem["errors"][0]["pointer"] == "rooms"
        assert "1" in problem["errors"][0]["message"]


def test_unimplemented_neighbours_still_answer_501(
    client: TestClient, unimplemented_route: str
) -> None:
    """Turning some stubs into handlers must not disturb the ones left, or the frozen
    contract stops meaning what it says."""
    assert client.get(unimplemented_route).status_code == 501


class TestReferencesAreResolved:
    """That a declared relationship arrives with something in it.

    `InstructorRead.department` was `null` in every response from 2.2 until 3.4, for
    instructors that had a department and instructors that did not. The route built the
    model with `InstructorRead.model_validate(row)`, the row is a domain entity carrying
    `department_id` and no `department`, and the field's default is `None` — so the
    response validated, matched the published contract, and said nothing true.

    Nothing could have caught it. It surfaced when a screen finally displayed the field.
    """

    def test_an_instructor_reports_the_department_it_was_given(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        department = client.post(
            "/api/v1/departments",
            json={"institution_id": campus["institution"], "name": "Computer Science"},
        ).json()

        created = client.post(
            "/api/v1/instructors",
            json={"name": "Prof. Sharma", "department_id": department["id"]},
        ).json()
        assert created["department"] == {"id": department["id"], "name": "Computer Science"}

        # Every route that returns one, because only `create` was covered by the fix at
        # first and `list` is the one a screen actually calls.
        fetched = client.get(f"/api/v1/instructors/{created['id']}").json()
        assert fetched["department"]["name"] == "Computer Science"

        listed = client.get("/api/v1/instructors").json()["items"]
        assert [i["department"]["name"] for i in listed if i["id"] == created["id"]] == [
            "Computer Science"
        ]

        patched = client.patch(
            f"/api/v1/instructors/{created['id']}", json={"name": "Prof. R. Sharma"}
        ).json()
        assert patched["department"]["name"] == "Computer Science"

    def test_an_instructor_without_one_reports_nothing_rather_than_failing(
        self, client: TestClient, campus: dict[str, int]
    ) -> None:
        created = client.post("/api/v1/instructors", json={"name": "Visiting Lecturer"}).json()
        assert created["department"] is None

    def test_every_declared_reference_is_actually_resolved(self) -> None:
        """The class, not the instance.

        A `*Read` carrying a `Reference` has to be built by hand — the repository returns
        domain entities, which hold ids and not resolved objects, so validating one can only
        ever produce the field's default. `_course_read` and `_room_read` exist for exactly
        this, and the one model that skipped the helper is the one that was silently empty
        from 2.2 to 3.4.

        Read from the **syntax tree** rather than from the text. The first version searched
        the source for the offending call as a string and then failed on the sentence above
        describing it — a guard that reads prose is one that fires on documentation and gets
        switched off. `ast` sees calls and not comments.
        """
        import ast
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "tessera" / "api"

        validated: set[str] = set()
        for module in (root / "routers").glob("*.py"):
            for node in ast.walk(ast.parse(module.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "model_validate"
                    and isinstance(node.func.value, ast.Name)
                ):
                    validated.add(node.func.value.id)

        carries_reference = set()
        for schema in (root / "schemas").glob("*.py"):
            for match in re.finditer(
                r"class (\w+Read)\(Wire\):\n((?:    .*\n|\n)+?)(?=\n\nclass |\Z)",
                schema.read_text(),
            ):
                if "Reference" in match.group(2):
                    carries_reference.add(match.group(1))

        assert carries_reference, "found no models with reference fields — the scan is wrong"
        offenders = sorted(carries_reference & validated)
        assert not offenders, (
            f"{offenders} declare a Reference and are built by model_validate, "
            "which can only ever fill it with the field default"
        )
