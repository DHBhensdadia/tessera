"""The rules page, and the phase's exit test performed the way a person would.

R1 §3's argument for storing weights as data is that exposing them *"turns 'your
algorithm is wrong' into 'move this slider'"*. That is only true if the slider exists, so
this is where the claim is checked.
"""

from __future__ import annotations

import re
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
def term(browser: TestClient) -> int:
    institution = browser.post("/api/v1/institutions", json={"name": "U"}).json()
    grid = browser.post(
        "/api/v1/time-grids",
        json={
            "institution_id": institution["id"],
            "days": 5,
            "slots_per_day": 6,
            "slot_minutes": 60,
            "day_start_minute": 540,
            "break_slots": [3],
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


@pytest.fixture
def shah(browser: TestClient, term: int) -> int:
    browser.post("/console/instructors", data={"name": "Prof. Shah", "email": ""})
    listed = browser.get("/api/v1/instructors").json()
    return int(listed["items"][0]["id"])


def rule_ids(markup: str) -> list[int]:
    return [int(i) for i in re.findall(r'action="/console/constraints/(\d+)"', markup)]


class TestThePage:
    def test_a_new_term_arrives_with_its_preferences(self, browser: TestClient, term: int) -> None:
        markup = browser.get(f"/console/constraints?term_id={term}").text
        # Was "…for everyone", which this page has shown since 2.5 and which is wrong for
        # the two preferences about courses. The word is per kind now.
        assert "Minimise idle gaps in the day for every group" in markup
        assert "Avoid teaching any course twice in one day" in markup
        assert len(rule_ids(markup)) == 7

    def test_it_says_so_when_there_is_no_term(self, browser: TestClient) -> None:
        assert "No terms exist yet" in browser.get("/console/constraints").text

    def test_the_section_is_in_the_menu(self, browser: TestClient) -> None:
        """A page reachable only by typing its URL is a page nobody uses."""
        assert '/console/constraints"' in browser.get("/console/").text

    def test_every_rule_carries_a_slider(self, browser: TestClient, term: int) -> None:
        markup = browser.get(f"/console/constraints?term_id={term}").text
        assert markup.count('type="range"') == 7

    def test_session_rules_are_not_offered_here(self, browser: TestClient, term: int) -> None:
        """They name sessions, which are generated rather than authored.

        Choosing two out of several hundred from a flat list would be worse than useless;
        that belongs to the timetable view, where a session can be pointed at.
        """
        markup = browser.get(f"/console/constraints?term_id={term}").text
        assert 'value="same_room"' not in markup
        assert 'value="min_gap"' not in markup


class TestTheSlider:
    def test_moving_it_sticks(self, browser: TestClient, term: int) -> None:
        first = rule_ids(browser.get(f"/console/constraints?term_id={term}").text)[0]

        browser.post(
            f"/console/constraints/{first}",
            data={"term_id": str(term), "weight": "17", "enabled": "true"},
        )

        listed = browser.get(f"/api/v1/terms/{term}/constraints").json()["items"]
        assert next(item for item in listed if item["id"] == first)["weight"] == 17

    def test_a_preference_can_be_switched_off(self, browser: TestClient, term: int) -> None:
        first = rule_ids(browser.get(f"/console/constraints?term_id={term}").text)[0]

        browser.post(f"/console/constraints/{first}", data={"term_id": str(term), "weight": "5"})

        listed = browser.get(f"/api/v1/terms/{term}/constraints").json()["items"]
        assert next(item for item in listed if item["id"] == first)["enabled"] is False


class TestAddingARule:
    def test_a_limit_on_one_instructor(self, browser: TestClient, term: int, shah: int) -> None:
        browser.post(
            "/console/constraints",
            data={
                "term_id": str(term),
                "kind": "limit_consecutive_slots",
                "target": [f"instructor:{shah}"],
                "slots": "3",
                "is_hard": "true",
            },
        )

        markup = browser.get(f"/console/constraints?term_id={term}").text
        assert "Give Prof. Shah at most 3 hour(s) in a row" in markup

    def test_a_rule_naming_nobody_cannot_be_a_requirement(
        self, browser: TestClient, term: int
    ) -> None:
        """Reported as a sentence beside the form, not as a JSON envelope."""
        response = browser.post(
            "/console/constraints",
            data={
                "term_id": str(term),
                "kind": "balance_daily_load",
                "is_hard": "true",
            },
        )
        assert response.status_code == 200
        assert "cannot be hard" in response.text
        assert response.headers["content-type"].startswith("text/html")
        assert "Add a rule" in response.text, "the form should still be there to correct"

    def test_a_missing_parameter_is_explained(self, browser: TestClient, term: int) -> None:
        response = browser.post(
            "/console/constraints",
            data={"term_id": str(term), "kind": "limit_consecutive_slots"},
        )
        assert "requires parameter" in response.text

    def test_a_rule_can_be_withdrawn(self, browser: TestClient, term: int) -> None:
        first = rule_ids(browser.get(f"/console/constraints?term_id={term}").text)[0]

        browser.post(f"/console/constraints/{first}/delete", data={"term_id": str(term)})

        assert browser.get(f"/api/v1/terms/{term}/constraints").json()["total"] == 6


class TestSafety:
    def test_a_name_is_escaped_rather_than_rendered(self, browser: TestClient, term: int) -> None:
        """The sentence embeds a target's name, which is user text."""
        browser.post("/console/instructors", data={"name": "<script>x</script>", "email": ""})
        instructor = browser.get("/api/v1/instructors").json()["items"][0]["id"]
        browser.post(
            "/console/constraints",
            data={
                "term_id": str(term),
                "kind": "minimise_instructor_gaps",
                "target": [f"instructor:{instructor}"],
            },
        )

        markup = browser.get(f"/console/constraints?term_id={term}").text
        assert "<script>x</script>" not in markup
        assert "&lt;script&gt;" in markup

    def test_the_page_refuses_a_foreign_host(self, engine: Engine) -> None:
        app = create_app(engine=engine, configure_logs=False)
        with TestClient(app, base_url="http://evil.example") as client:
            assert client.get("/console/constraints").status_code == 403


def test_the_exit_test(browser: TestClient, term: int, shah: int) -> None:
    """Phase 2.8, performed in a browser against the running engine.

    Create a per-instructor rule the 1.4 contract could not express, retune a default
    weight with the slider, mark an hour someone would rather not teach, and confirm all
    three are still there after everything is read back fresh.
    """
    browser.post(
        "/console/constraints",
        data={
            "term_id": str(term),
            "kind": "limit_consecutive_slots",
            "target": [f"instructor:{shah}"],
            "slots": "3",
            "is_hard": "true",
        },
    )
    gaps = next(
        item
        for item in browser.get(f"/api/v1/terms/{term}/constraints").json()["items"]
        if item["kind"] == "minimise_group_gaps"
    )
    browser.post(
        f"/console/constraints/{gaps['id']}",
        data={"term_id": str(term), "weight": "19", "enabled": "true"},
    )
    browser.post(
        f"/console/instructors/{shah}/availability",
        data={"term_id": str(term), "slot_4": "soft", "slot_5": "hard"},
    )

    rules = browser.get(f"/console/constraints?term_id={term}").text
    assert "Give Prof. Shah at most 3 hour(s) in a row" in rules
    assert 'value="19"' in rules

    week = browser.get(f"/console/instructors/{shah}/availability?term_id={term}").text
    assert "1 blocked, 1 discouraged" in week
