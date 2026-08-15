"""Instructors, the availability grid, and the group tree.

The two sections that are not just a name and a parent, and so the two where the page
has to understand something: a week of integers, and a nesting.
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
    """A short teaching week — six one-hour slots with a break at index 3.

    Small on purpose: a 5x6 grid can be reasoned about in a test, and the break is there
    because a break column is the thing most likely to be rendered as a tickable hour.
    """
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


def blocked_count(markup: str) -> int:
    found = re.search(r"(\d+) blocked", markup)
    assert found is not None
    return int(found.group(1))


def discouraged_count(markup: str) -> int:
    found = re.search(r"(\d+) discouraged", markup)
    assert found is not None
    return int(found.group(1))


class TestInstructors:
    def test_an_instructor_is_added_and_listed(self, browser: TestClient) -> None:
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})

        assert "Prof. Sharma" in browser.get("/console/instructors").text

    def test_a_duplicate_name_is_refused_in_prose(self, browser: TestClient) -> None:
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})

        response = browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})

        assert "already exists" in response.text


class TestTheAvailabilityGrid:
    def test_it_says_so_when_there_is_no_term(self, browser: TestClient) -> None:
        """Availability is per term because a slot index only means a time by reference
        to a term's week. An empty grid with no explanation would look broken."""
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})

        response = browser.get("/console/instructors/1/availability")

        assert response.status_code == 200
        assert "No terms exist yet" in response.text

    def test_the_week_is_drawn_from_the_terms_own_grid(
        self, browser: TestClient, term: int
    ) -> None:
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})

        markup = browser.get("/console/instructors/1/availability").text

        assert re.findall(r"<th>(Mon|Tue|Wed|Thu|Fri)</th>", markup) == [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri",
        ]

    def test_break_slots_are_shown_but_not_tickable(self, browser: TestClient, term: int) -> None:
        """Five days with one break each: five cells that show the break and cannot be
        blocked, and 25 hours that can. Seeing lunch is how someone confirms the week is
        the one they meant to set up."""
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})

        markup = browser.get("/console/instructors/1/availability").text

        assert markup.count(">break<") == 5
        assert markup.count('<select name="slot_') == 25

    def test_blocking_hours_sticks(self, browser: TestClient, term: int) -> None:
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})

        browser.post(
            "/console/instructors/1/availability",
            data={"term_id": str(term), "slot_10": "hard", "slot_11": "hard"},
        )

        markup = browser.get("/console/instructors/1/availability").text
        assert blocked_count(markup) == 2

    def test_unticking_actually_frees_a_slot(self, browser: TestClient, term: int) -> None:
        """The case a partial update gets wrong.

        A control left at its default is indistinguishable from one that was never shown.
        Only clearing the term and re-applying what came back can tell them apart —
        anything else silently keeps the slot the user just freed.
        """
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})
        browser.post(
            "/console/instructors/1/availability",
            data={"term_id": str(term), "slot_10": "hard", "slot_11": "hard"},
        )

        browser.post(
            "/console/instructors/1/availability",
            data={"term_id": str(term), "slot_10": "hard", "slot_11": ""},
        )

        assert blocked_count(browser.get("/console/instructors/1/availability").text) == 1

    def test_clearing_everything_is_possible(self, browser: TestClient, term: int) -> None:
        """Submitting with nothing ticked must mean "available all week", not "no
        change" — the same absent-field problem at its extreme."""
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})
        browser.post(
            "/console/instructors/1/availability",
            data={"term_id": str(term), "slot_10": "hard", "slot_11": "hard"},
        )

        browser.post("/console/instructors/1/availability", data={"term_id": str(term)})

        assert blocked_count(browser.get("/console/instructors/1/availability").text) == 0

    def test_would_rather_not_is_kept_apart_from_cannot(
        self, browser: TestClient, term: int
    ) -> None:
        """Decision #78's middle state, which the grid could not express before 2.8.

        Storing both as blocked would hand the solver a preference dressed as a
        prohibition — an hour nobody may teach, from someone who only said they would
        prefer not to.
        """
        browser.post("/console/instructors", data={"name": "Prof. Sharma", "email": ""})
        browser.post(
            "/console/instructors/1/availability",
            data={"term_id": str(term), "slot_10": "hard", "slot_11": "soft"},
        )

        markup = browser.get("/console/instructors/1/availability").text
        assert blocked_count(markup) == 1
        assert discouraged_count(markup) == 1


class TestTheGroupTree:
    @pytest.fixture
    def intake(self, browser: TestClient) -> None:
        browser.post(
            "/console/student-groups",
            data={
                "name": "2024 Intake",
                "kind": "structural",
                "size": "0",
                "parent_id": "",
                "program_id": "",
            },
        )
        for batch in ("A1", "A2", "A3"):
            browser.post(
                "/console/student-groups",
                data={
                    "name": batch,
                    "kind": "structural",
                    "size": "40",
                    "parent_id": "1",
                    "program_id": "",
                },
            )

    def test_children_are_indented_under_their_parent(
        self, browser: TestClient, intake: None
    ) -> None:
        """The nesting is the only thing worth looking at on this page: it is why three
        labs can run in parallel and a lecture cannot run opposite any of them."""
        markup = browser.get("/console/student-groups").text

        indents = [float(x) for x in re.findall(r"padding-left: ([\d.]+)rem", markup)]
        assert indents[0] < indents[1]
        assert indents[1] == indents[2] == indents[3]

    def test_headcount_is_derived_not_typed(self, browser: TestClient, intake: None) -> None:
        """The intake was entered with size 0. 120 comes from the domain summing its
        leaves — the same answer the solver uses to decide whether a room fits."""
        markup = browser.get("/console/student-groups").text

        assert "120" in markup

    def test_the_page_says_who_clashes_with_whom(self, browser: TestClient, intake: None) -> None:
        markup = browser.get("/console/student-groups").text

        assert "2024 Intake" in markup
        assert markup.count("A1") >= 1

    def test_a_cycle_is_refused_in_prose(self, browser: TestClient, intake: None) -> None:
        """Rejected by `GroupSet`, not by anything in the console."""
        response = browser.post(
            "/console/student-groups",
            data={
                "name": "Loop",
                "kind": "structural",
                "size": "0",
                "parent_id": "999",
                "program_id": "",
            },
        )

        assert response.status_code == 200
        assert "unknown" in response.text.lower() or "does not exist" in response.text.lower()

    def test_a_structural_group_given_members_is_refused(self, browser: TestClient) -> None:
        """The domain rule that had never been provoked before 2.4b, now reachable from
        a form: `member_ids` is how a cohort names what it draws from, and a tree node
        takes its students through its parent instead."""
        browser.post(
            "/console/student-groups",
            data={
                "name": "Intake",
                "kind": "structural",
                "size": "10",
                "parent_id": "",
                "program_id": "",
            },
        )

        response = browser.post(
            "/console/student-groups",
            data={
                "name": "Wrong",
                "kind": "structural",
                "size": "0",
                "parent_id": "",
                "program_id": "",
                "member_ids": ["1"],
            },
        )

        assert "takes members through the tree" in response.text

    def test_deleting_a_parent_is_refused_with_counts(
        self, browser: TestClient, intake: None
    ) -> None:
        response = browser.post("/console/student-groups/1/delete")

        assert "3 sub groups" in response.text

    def test_a_size_can_be_corrected_in_place(self, browser: TestClient, intake: None) -> None:
        browser.post("/console/student-groups/2/resize", data={"size": "45"})

        assert "125" in browser.get("/console/student-groups").text
