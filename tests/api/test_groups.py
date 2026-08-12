"""Groups over HTTP: the tree, the conflicts endpoint, and the two sizes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def campus(client: TestClient) -> dict[str, Any]:
    """An intake split three ways, plus an elective drawing from two of the labs.

    The shape every real timetable has, and the one where the tree alone is not enough.
    """
    program = client.post("/api/v1/programs", json={"name": "B.Tech CSE"}).json()
    batch = client.post(
        "/api/v1/student-groups",
        json={"name": "2024 CSE", "size": 0, "program_id": program["id"]},
    ).json()
    labs = [
        client.post(
            "/api/v1/student-groups",
            json={"name": f"Lab A{i}", "size": 40, "parent_id": batch["id"]},
        ).json()
        for i in (1, 2, 3)
    ]
    elective = client.post(
        "/api/v1/student-groups",
        json={
            "name": "Machine Learning",
            "kind": "cohort",
            "member_ids": [labs[0]["id"], labs[1]["id"]],
        },
    ).json()
    return {
        "program": program["id"],
        "batch": batch["id"],
        "labs": [x["id"] for x in labs],
        "elective": elective["id"],
    }


class TestTree:
    def test_structural_nesting_and_cohorts_side_by_side(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        """Cohorts appear as extra roots with no children.

        They have no parent by definition, and omitting them would hide exactly the
        groups most likely to cause conflicts. `kind` is what lets the interface render
        electives in their own section.
        """
        tree = client.get("/api/v1/student-groups/tree").json()

        by_name = {node["name"]: node for node in tree}
        assert set(by_name) == {"2024 CSE", "Machine Learning"}
        assert len(by_name["2024 CSE"]["children"]) == 3
        assert by_name["2024 CSE"]["kind"] == "structural"
        assert by_name["Machine Learning"]["kind"] == "cohort"
        assert by_name["Machine Learning"]["children"] == []

    def test_the_tree_is_resolved_by_the_engine(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        """Separate from the flat listing so the client never rebuilds the parent/child
        rules — a second implementation is a second place for them to be wrong."""
        flat = client.get("/api/v1/student-groups").json()
        assert flat["total"] == 5  # the tree above collapses these into 2 roots


class TestSizes:
    def test_an_intake_left_at_zero_seats_the_sum_of_its_labs(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        """`size` is what the user typed; `headcount` is what the solver must seat.

        A parent left at zero almost always means "nobody filled this in" rather than
        "this intake has no students", so the leaf sum is used instead of the zero.
        """
        batch = client.get(f"/api/v1/student-groups/{campus['batch']}").json()
        assert batch["size"] == 0
        assert batch["headcount"] == 120

    def test_an_explicit_size_is_respected(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        client.patch(f"/api/v1/student-groups/{campus['batch']}", json={"size": 118})
        batch = client.get(f"/api/v1/student-groups/{campus['batch']}").json()
        assert batch["size"] == 118
        assert batch["headcount"] == 118


class TestConflicts:
    def test_an_elective_clashes_with_what_it_draws_from(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        clashes = client.get(f"/api/v1/student-groups/{campus['elective']}/conflicts").json()

        assert campus["labs"][0] in clashes
        assert campus["labs"][1] in clashes
        assert campus["batch"] in clashes
        assert campus["labs"][2] not in clashes

    def test_parallel_labs_do_not_clash(self, client: TestClient, campus: dict[str, Any]) -> None:
        """Three labs at once is the reason a batch gets split at all."""
        clashes = client.get(f"/api/v1/student-groups/{campus['labs'][0]}/conflicts").json()
        assert campus["labs"][1] not in clashes
        assert campus["batch"] in clashes


class TestRefusals:
    def test_a_cycle_is_a_conflict_not_a_hang(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        """Left unchecked this would make leaf resolution loop forever."""
        response = client.patch(
            f"/api/v1/student-groups/{campus['batch']}",
            json={"parent_id": campus["labs"][0]},
        )
        assert response.status_code == 409
        assert "cycle" in response.json()["detail"]

    def test_deleting_an_intake_with_labs_is_refused(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        """`parent_id` cascades in the database, so without this a mis-click would take
        all three lab groups silently."""
        response = client.delete(f"/api/v1/student-groups/{campus['batch']}")
        assert response.status_code == 409
        assert any("3" in e["message"] for e in response.json()["errors"])

    def test_deleting_a_programme_with_groups_is_refused(
        self, client: TestClient, campus: dict[str, Any]
    ) -> None:
        """The delete added in 2.3 — the contract could create programmes and never
        remove one."""
        assert client.delete(f"/api/v1/programs/{campus['program']}").status_code == 409
