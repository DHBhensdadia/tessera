"""Duplicating a term over HTTP.

What only appears at the edge: the receipt. `TermDuplicate` was frozen in 1.4 offering
seven checkboxes, four of which name things that live above a term and therefore cannot be
copied or withheld — so the response has to describe what happened rather than echo what
was asked.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.repository import calendar as calendar_repo
from tessera.repository import create_all, session_factory
from tessera.repository import models as m


@pytest.fixture
def term_id(engine: Engine) -> int:
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
        created = calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2026-27",
            name="Autumn",
        )
        db.commit()
        return int(created.id or 0)


def duplicate(client: TestClient, term_id: int, **flags: object) -> dict[str, object]:
    body: dict[str, object] = {"name": "Spring", "academic_year": "2026-27"}
    body.update(flags)
    response = client.post(f"/api/v1/terms/{term_id}/duplicate", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


class TestTheResponseIsStillATerm:
    def test_a_1_4_client_reading_a_term_keeps_working(
        self, client: TestClient, term_id: int
    ) -> None:
        """The route was frozen answering with a term, so the receipt is a superset.

        Nesting the term one level down would have been tidier and would have broken
        every reader written against the contract.
        """
        body = duplicate(client, term_id)

        assert body["name"] == "Spring"
        assert body["academic_year"] == "2026-27"
        assert isinstance(body["id"], int)
        assert body["time_grid"] is not None

    def test_the_new_term_is_listed(self, client: TestClient, term_id: int) -> None:
        duplicate(client, term_id)
        names = {t["name"] for t in client.get("/api/v1/terms").json()["items"]}
        assert names == {"Autumn", "Spring"}


class TestTheReceipt:
    def test_things_above_a_term_are_reported_as_shared(
        self, client: TestClient, term_id: int
    ) -> None:
        carried = duplicate(client, term_id)["carried"]
        assert isinstance(carried, dict)
        for name in ("rooms", "instructors", "groups", "courses"):
            assert carried[name] == "shared", f"{name} is not term-scoped and cannot be copied"

    def test_what_was_copied_says_copied(self, client: TestClient, term_id: int) -> None:
        body = duplicate(client, term_id)
        carried = body["carried"]
        counts = body["counts"]
        assert isinstance(carried, dict) and isinstance(counts, dict)

        assert carried["constraints"] == "copied"
        assert counts["constraints"] == 7

    def test_assignments_are_reported_as_skipped(self, client: TestClient, term_id: int) -> None:
        carried = duplicate(client, term_id)["carried"]
        assert isinstance(carried, dict)
        assert carried["assignments"] == "skipped"

    def test_unticking_something_shared_says_skipped_rather_than_shared(
        self, client: TestClient, term_id: int
    ) -> None:
        carried = duplicate(client, term_id, copy_courses=False)["carried"]
        assert isinstance(carried, dict)
        assert carried["courses"] == "skipped"


class TestRefusals:
    def test_duplicating_into_a_name_that_already_exists(
        self, client: TestClient, term_id: int
    ) -> None:
        response = client.post(
            f"/api/v1/terms/{term_id}/duplicate",
            json={"name": "Autumn", "academic_year": "2026-27"},
        )
        assert response.status_code == 409, response.text

    def test_assignments_without_offerings(self, client: TestClient, term_id: int) -> None:
        response = client.post(
            f"/api/v1/terms/{term_id}/duplicate",
            json={
                "name": "Spring",
                "academic_year": "2026-27",
                "copy_offerings": False,
                "copy_assignments": True,
            },
        )
        assert response.status_code == 422
        assert "without the offerings" in response.text

    def test_a_term_that_does_not_exist(self, client: TestClient, term_id: int) -> None:
        response = client.post(
            "/api/v1/terms/999/duplicate",
            json={"name": "Spring", "academic_year": "2026-27"},
        )
        assert response.status_code == 404

    def test_a_nameless_term_is_refused_before_anything_is_written(
        self, client: TestClient, term_id: int
    ) -> None:
        response = client.post(
            f"/api/v1/terms/{term_id}/duplicate",
            json={"name": "", "academic_year": "2026-27"},
        )
        assert response.status_code == 422
        assert client.get("/api/v1/terms").json()["total"] == 1
