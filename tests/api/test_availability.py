"""Instructors and availability over HTTP.

The rules are tested in `tests/repository/test_people.py`. This covers what only appears
at the edge: that the wire's (kind, subject_id) still maps onto the two columns
underneath, and that a range survives the round trip.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.repository import create_all, session_factory
from tessera.repository import models as m


@pytest.fixture
def term_id(engine: Engine) -> int:
    """A term to hang availability on, created directly so the API test starts from
    data rather than from six setup requests."""
    create_all(engine)
    with session_factory(engine)() as db:
        institution = m.Institution(name="Test University")
        db.add(institution)
        db.flush()
        grid = m.TimeGrid(
            institution_id=institution.id,
            days=5,
            slots_per_day=10,
            slot_minutes=60,
            day_start_minute=540,
        )
        db.add(grid)
        db.flush()
        term = m.Term(
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2026-27",
            name="Autumn",
        )
        db.add(term)
        db.commit()
        return int(term.id)


@pytest.fixture
def instructor_id(client: TestClient) -> int:
    response = client.post(
        "/api/v1/instructors", json={"name": "Prof. Sharma", "max_slots_per_day": 8}
    )
    assert response.status_code == 201
    return int(response.json()["id"])


class TestInstructors:
    def test_load_limits_survive_the_round_trip(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/instructors",
            json={"name": "Prof. Mehta", "max_slots_per_week": 30},
        ).json()

        fetched = client.get(f"/api/v1/instructors/{created['id']}").json()
        assert fetched["max_slots_per_week"] == 30
        assert fetched["max_slots_per_day"] is None

    def test_patch_leaves_unsent_fields_alone(self, client: TestClient, instructor_id: int) -> None:
        updated = client.patch(
            f"/api/v1/instructors/{instructor_id}", json={"email": "s@example.edu"}
        ).json()
        assert updated["email"] == "s@example.edu"
        assert updated["max_slots_per_day"] == 8

    def test_a_missing_instructor_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/instructors/999999").status_code == 404


class TestAvailability:
    def test_a_range_is_blocked_in_one_request(
        self, client: TestClient, term_id: int, instructor_id: int
    ) -> None:
        response = client.post(
            f"/api/v1/terms/{term_id}/unavailability",
            json={"kind": "instructor", "subject_id": instructor_id, "slots": [5, 6, 7]},
        )
        assert response.status_code == 201
        assert [x["slot"] for x in response.json()["items"]] == [5, 6, 7]

    def test_the_wire_shape_survives_the_storage_change(
        self, client: TestClient, term_id: int, instructor_id: int
    ) -> None:
        """`kind` and `subject_id` are derived now, not stored.

        The 1.3 corrective pass replaced them with two nullable columns. That the
        published contract did not move is the whole reason wire models are kept
        separate from domain models.
        """
        client.post(
            f"/api/v1/terms/{term_id}/unavailability",
            json={"kind": "instructor", "subject_id": instructor_id, "slots": [3]},
        )

        row = client.get(f"/api/v1/terms/{term_id}/unavailability").json()["items"][0]
        assert row["kind"] == "instructor"
        assert row["subject_id"] == instructor_id

    def test_releasing_part_of_a_range(
        self, client: TestClient, term_id: int, instructor_id: int
    ) -> None:
        client.post(
            f"/api/v1/terms/{term_id}/unavailability",
            json={"kind": "instructor", "subject_id": instructor_id, "slots": [5, 6, 7, 8]},
        )

        response = client.delete(
            f"/api/v1/terms/{term_id}/unavailability"
            f"?kind=instructor&subject_id={instructor_id}&slot=6&slot=7"
        )
        assert response.status_code == 204

        remaining = client.get(f"/api/v1/terms/{term_id}/unavailability").json()
        assert [x["slot"] for x in remaining["items"]] == [5, 8]

    def test_omitting_slots_clears_everything(
        self, client: TestClient, term_id: int, instructor_id: int
    ) -> None:
        """The endpoint's original meaning, unchanged by the new parameter."""
        client.post(
            f"/api/v1/terms/{term_id}/unavailability",
            json={"kind": "instructor", "subject_id": instructor_id, "slots": [5, 6, 7]},
        )

        client.delete(
            f"/api/v1/terms/{term_id}/unavailability?kind=instructor&subject_id={instructor_id}"
        )
        assert client.get(f"/api/v1/terms/{term_id}/unavailability").json()["total"] == 0

    def test_a_slot_beyond_the_grid_is_a_conflict(
        self, client: TestClient, term_id: int, instructor_id: int
    ) -> None:
        response = client.post(
            f"/api/v1/terms/{term_id}/unavailability",
            json={"kind": "instructor", "subject_id": instructor_id, "slots": [9999]},
        )
        assert response.status_code == 409
        assert "between 0 and 49" in response.json()["detail"]
