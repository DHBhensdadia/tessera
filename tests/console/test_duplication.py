"""Duplicating a term in the browser, and Phase 2.9's exit test performed there.

P7 Act 11 is where the application earns its keep the second time. The page has one job
beyond the copy itself: explaining the four boxes it does not offer, because a checkbox
that cannot be false is worse than a sentence saying why.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.app import create_app


@pytest.fixture
def browser(engine: Engine) -> Iterator[TestClient]:
    app = create_app(engine=engine, configure_logs=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def autumn(browser: TestClient) -> int:
    institution = browser.post("/api/v1/institutions", json={"name": "U"}).json()
    grid = browser.post(
        "/api/v1/time-grids",
        json={
            "institution_id": institution["id"],
            "days": 5,
            "slots_per_day": 6,
            "slot_minutes": 60,
            "day_start_minute": 540,
        },
    ).json()
    created = browser.post(
        "/api/v1/terms",
        json={
            "institution_id": institution["id"],
            "time_grid_id": grid["id"],
            "academic_year": "2026-27",
            "name": "Autumn",
        },
    ).json()
    return int(created["id"])


class TestThePage:
    def test_it_is_reachable_from_the_term_list(self, browser: TestClient, autumn: int) -> None:
        assert f"/console/terms/{autumn}/duplicate" in browser.get("/console/terms").text

    def test_the_boxes_that_cannot_be_unticked_are_explained(
        self, browser: TestClient, autumn: int
    ) -> None:
        """Not rendered as disabled controls — as a sentence saying they are shared."""
        markup = browser.get(f"/console/terms/{autumn}/duplicate").text

        assert "shared across terms" in markup
        assert 'name="copy_groups"' not in markup
        assert 'name="copy_courses"' not in markup

    def test_it_says_assignments_are_not_carried(self, browser: TestClient, autumn: int) -> None:
        markup = browser.get(f"/console/terms/{autumn}/duplicate").text
        assert "not carried" in markup


class TestDuplicating:
    def test_a_new_term_appears(self, browser: TestClient, autumn: int) -> None:
        browser.post(
            f"/console/terms/{autumn}/duplicate",
            data={"name": "Spring", "academic_year": "2026-27"},
        )

        names = {t["name"] for t in browser.get("/api/v1/terms").json()["items"]}
        assert names == {"Autumn", "Spring"}

    def test_the_receipt_is_shown(self, browser: TestClient, autumn: int) -> None:
        """What was actually carried, not what was asked for."""
        response = browser.post(
            f"/console/terms/{autumn}/duplicate",
            data={
                "name": "Spring",
                "academic_year": "2026-27",
                "copy_constraints": "true",
            },
        )

        assert "Spring</strong> created" in response.text
        assert "constraints (7) carried" in response.text

    def test_a_clash_is_explained_beside_the_form(self, browser: TestClient, autumn: int) -> None:
        response = browser.post(
            f"/console/terms/{autumn}/duplicate",
            data={"name": "Autumn", "academic_year": "2026-27"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "already exists" in response.text
        assert "Create term" in response.text, "the form must still be there to correct"
        assert browser.get("/api/v1/terms").json()["total"] == 1

    def test_a_name_is_escaped_rather_than_rendered(self, browser: TestClient, autumn: int) -> None:
        response = browser.post(
            f"/console/terms/{autumn}/duplicate",
            data={"name": "<script>x</script>", "academic_year": "2026-27"},
        )
        assert "<script>x</script>" not in response.text

    def test_the_page_refuses_a_foreign_host(self, engine: Engine) -> None:
        app = create_app(engine=engine, configure_logs=False)
        with TestClient(app, base_url="http://evil.example") as client:
            assert client.get("/console/terms/1/duplicate").status_code == 403


def test_the_exit_test(browser: TestClient, autumn: int) -> None:
    """Phase 2.9, performed in a browser against the running engine.

    Retune a weight and mark an hour somebody would rather not teach, roll the term
    forward, and confirm both arrive in the new term with their meaning intact.
    """
    browser.post("/console/instructors", data={"name": "Prof. Shah", "email": ""})
    shah = browser.get("/api/v1/instructors").json()["items"][0]["id"]

    gaps = next(
        item
        for item in browser.get(f"/api/v1/terms/{autumn}/constraints").json()["items"]
        if item["kind"] == "minimise_group_gaps"
    )
    browser.post(
        f"/console/constraints/{gaps['id']}",
        data={"term_id": str(autumn), "weight": "19", "enabled": "true"},
    )
    browser.post(
        f"/console/instructors/{shah}/availability",
        data={"term_id": str(autumn), "slot_4": "soft", "slot_5": "hard"},
    )

    browser.post(
        f"/console/terms/{autumn}/duplicate",
        data={
            "name": "Spring",
            "academic_year": "2026-27",
            "copy_offerings": "true",
            "copy_constraints": "true",
            "copy_instructors": "true",
            "copy_rooms": "true",
        },
    )

    spring = next(t for t in browser.get("/api/v1/terms").json()["items"] if t["name"] == "Spring")
    carried = browser.get(f"/api/v1/terms/{spring['id']}/constraints").json()["items"]
    assert next(c for c in carried if c["kind"] == "minimise_group_gaps")["weight"] == 19

    week = browser.get(f"/console/instructors/{shah}/availability?term_id={spring['id']}").text
    assert "1 blocked, 1 discouraged" in week
