"""Courses, the calendar, and the weekly pattern — including the phase exit test.

The exit test is the reason this phase exists: a complete small department entered
through the browser with no API client and no Swift. Everything before it in this file
is one of the pieces that has to work for that to be true.
"""

from __future__ import annotations

import html
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


def form(browser: TestClient, path: str, **fields: object) -> str:
    """Post a form the way a browser does, and hand back whatever came out.

    Repeated fields — several attendees, several break slots — are a list *value* rather
    than repeated keys, which is what httpx wants. Passing a list of pairs instead posts
    nothing at all and every field comes back "required", which looks exactly like a
    broken handler.
    """
    payload: dict[str, str | list[str]] = {}
    for key, value in fields.items():
        payload[key] = [str(item) for item in value] if isinstance(value, list) else str(value)
    return str(browser.post(path, data=payload).text)


def problem(markup: str) -> str:
    """The refusal shown to the user, with entities turned back into characters.

    Unescaped here because escaping is a rendering detail and the message is what is
    being asserted — an apostrophe reaching the page as `&#39;` is Jinja doing its job,
    which `test_a_name_is_escaped_not_executed` checks on purpose.
    """
    found = re.search(r'class="problem">([^<]+)', markup)
    return html.unescape(found.group(1).strip()) if found else ""


@pytest.fixture
def campus(browser: TestClient) -> None:
    """Everything a term needs, entered through forms only."""
    form(browser, "/console/institutions", name="Test University")
    form(browser, "/console/departments", name="Computer Science", code="CSE", parent_id=1)
    form(browser, "/console/features", name="computers", parent_id=1)
    form(browser, "/console/instructors", name="Prof. Sharma", email="")
    form(
        browser,
        "/console/student-groups",
        name="2024 Intake",
        kind="structural",
        size=0,
        parent_id="",
        program_id="",
    )
    for batch in ("A1", "A2", "A3"):
        form(
            browser,
            "/console/student-groups",
            name=batch,
            kind="structural",
            size=40,
            parent_id=1,
            program_id="",
        )
    form(
        browser,
        "/console/time-grids",
        institution_id=1,
        name="Standard",
        days=5,
        slots_per_day=16,
        slot_minutes=30,
        day_start_minute=540,
        break_slots=[8, 9],
    )
    form(
        browser,
        "/console/terms",
        institution_id=1,
        time_grid_id=1,
        academic_year="2026-27",
        name="Autumn",
        starts_on="",
        ends_on="",
    )
    form(
        browser,
        "/console/courses",
        code="CS301",
        name="Operating Systems",
        credits=4,
        department_id=1,
    )


class TestTheTeachingWeek:
    def test_a_week_reports_its_longest_placeable_block(
        self, browser: TestClient, campus: None
    ) -> None:
        """16 slots a day with lunch at 8 and 9 leaves two runs of eight.

        Nobody thinks to check this until a solve fails, so the page states it: a
        four-hour lab cannot go in a week whose longest unbroken run is three.
        """
        markup = browser.get("/console/time-grids").text

        assert "8 slots" in markup

    def test_there_is_no_way_to_edit_a_week(self, browser: TestClient, campus: None) -> None:
        """Decision #51 has no edit form because it must not have one. The page says why,
        because an absence with no explanation gets 'fixed' by the next person."""
        markup = browser.get("/console/time-grids").text

        assert "cannot be edited" in markup
        assert "/console/time-grids/1/rename" not in markup

    def test_a_week_in_use_cannot_be_deleted(self, browser: TestClient, campus: None) -> None:
        assert "cannot be deleted" in form(browser, "/console/time-grids/1/delete")


class TestTerms:
    def test_a_term_needs_a_week_and_says_so(self, browser: TestClient) -> None:
        browser.post("/console/institutions", data={"name": "Test University"})

        markup = browser.get("/console/terms").text

        assert "Create a teaching week first" in markup

    def test_dates_are_optional(self, browser: TestClient, campus: None) -> None:
        """A department starts next year's timetable long before the calendar is
        confirmed, and nothing in the scheduler reads these."""
        assert "Autumn" in browser.get("/console/terms").text

    def test_dates_the_wrong_way_round_are_refused(self, browser: TestClient, campus: None) -> None:
        markup = form(
            browser,
            "/console/terms",
            institution_id=1,
            time_grid_id=1,
            academic_year="2027-28",
            name="Spring",
            starts_on="2027-12-18",
            ends_on="2027-09-01",
        )

        assert "ends before it starts" in problem(markup)


class TestOfferings:
    def test_a_course_is_offered_in_a_term(self, browser: TestClient, campus: None) -> None:
        form(browser, "/console/terms/1/offerings", course_id=1)

        assert "CS301" in browser.get("/console/terms/1/offerings").text

    def test_an_already_offered_course_is_not_in_the_menu(
        self, browser: TestClient, campus: None
    ) -> None:
        """The rule is one offering per course per term. A menu that offers a choice it
        will then refuse explains the rule worse than a menu that does not."""
        form(browser, "/console/terms/1/offerings", course_id=1)

        markup = browser.get("/console/terms/1/offerings").text

        assert "Every course is already offered" in markup


class TestTheWeeklyPattern:
    @pytest.fixture
    def offering(self, browser: TestClient, campus: None) -> None:
        form(browser, "/console/terms/1/offerings", course_id=1)

    def test_a_component_states_what_it_will_generate(
        self, browser: TestClient, offering: None
    ) -> None:
        """ "→ generates 3 sessions" is doing real teaching work: it makes the
        lecture/lab-split model visible without anyone reading documentation."""
        form(
            browser,
            "/console/offerings/1/templates",
            kind="lecture",
            per_week=3,
            duration_slots=2,
            attendee_ids=1,
            instructor_ids=1,
        )

        markup = browser.get("/console/offerings/1/templates").text

        assert "→ 3 sessions" in markup

    def test_a_split_component_generates_one_per_group(
        self, browser: TestClient, offering: None
    ) -> None:
        form(
            browser,
            "/console/offerings/1/templates",
            kind="lab",
            per_week=1,
            duration_slots=4,
            attendee_ids=[2, 3, 4],
            split_per_attendee="true",
        )

        assert "→ 3 sessions" in browser.get("/console/offerings/1/templates").text

    def test_a_block_longer_than_the_day_allows_is_refused(
        self, browser: TestClient, offering: None
    ) -> None:
        """The check that turns a solve-time failure into an authoring-time sentence."""
        markup = form(
            browser,
            "/console/offerings/1/templates",
            kind="lab",
            per_week=1,
            duration_slots=12,
            attendee_ids=1,
        )

        assert "fits in this term's teaching week" in problem(markup)

    def test_editing_the_pattern_does_not_touch_sessions_until_expanded(
        self, browser: TestClient, offering: None
    ) -> None:
        """Separating the edit from the reconciliation is what lets someone see what a
        change would cost before paying for it."""
        form(
            browser,
            "/console/offerings/1/templates",
            kind="lecture",
            per_week=3,
            duration_slots=2,
            attendee_ids=1,
        )
        form(browser, "/console/offerings/1/expand")

        form(browser, "/console/templates/1/repeat", per_week=4)
        markup = browser.get("/console/offerings/1/templates").text

        assert "→ 4 sessions" in markup
        assert "(3 now — expand to reconcile)" in markup


class TestExpanding:
    @pytest.fixture
    def pattern(self, browser: TestClient, campus: None) -> None:
        form(browser, "/console/terms/1/offerings", course_id=1)
        form(
            browser,
            "/console/offerings/1/templates",
            kind="lecture",
            per_week=3,
            duration_slots=2,
            attendee_ids=1,
            instructor_ids=1,
        )
        form(
            browser,
            "/console/offerings/1/templates",
            kind="lab",
            per_week=1,
            duration_slots=4,
            attendee_ids=[2, 3, 4],
            split_per_attendee="true",
            instructor_ids=1,
            required_feature_ids=1,
        )

    def test_the_exit_test(self, browser: TestClient, pattern: None) -> None:
        """**Phase 2.5's exit test.**

        A complete small department, entered through the browser with no API client and
        no Swift, expanding to exactly the six sessions P5 named: three lectures to the
        whole intake and one lab for each of three sub-batches.
        """
        form(browser, "/console/offerings/1/expand")

        markup = browser.get("/console/offerings/1/templates").text
        rows = re.findall(
            r"<td>(lecture|lab)</td>\s*<td class=\"empty\">(\d+) of its group</td>"
            r"\s*<td>(\d+) slots?</td>\s*<td>([^<]+)</td>\s*<td>(\d+)</td>",
            markup,
        )

        assert len(rows) == 6
        lectures = [r for r in rows if r[0] == "lecture"]
        labs = [r for r in rows if r[0] == "lab"]

        assert len(lectures) == 3
        assert {r[2] for r in lectures} == {"2"}
        assert {r[4] for r in lectures} == {"120"}

        assert len(labs) == 3
        assert {r[2] for r in labs} == {"4"}
        assert {r[3].strip() for r in labs} == {"A1", "A2", "A3"}
        assert {r[4] for r in labs} == {"40"}

    def test_expanding_twice_changes_nothing(self, browser: TestClient, pattern: None) -> None:
        """Idempotence is what makes it safe to offer as a button."""
        form(browser, "/console/offerings/1/expand")
        first = browser.get("/console/offerings/1/templates").text.count("of its group")

        form(browser, "/console/offerings/1/expand")

        assert browser.get("/console/offerings/1/templates").text.count("of its group") == first

    def test_growing_the_pattern_then_expanding_adds_one(
        self, browser: TestClient, pattern: None
    ) -> None:
        form(browser, "/console/offerings/1/expand")

        form(browser, "/console/templates/1/repeat", per_week=4)
        form(browser, "/console/offerings/1/expand")

        assert browser.get("/console/offerings/1/templates").text.count("of its group") == 7

    def test_an_offering_with_sessions_cannot_be_withdrawn(
        self, browser: TestClient, pattern: None
    ) -> None:
        form(browser, "/console/offerings/1/expand")

        assert "cannot be deleted" in problem(form(browser, "/console/offerings/1/delete"))

    def test_removing_a_component_takes_its_sessions(
        self, browser: TestClient, pattern: None
    ) -> None:
        form(browser, "/console/offerings/1/expand")

        form(browser, "/console/templates/2/delete")

        assert browser.get("/console/offerings/1/templates").text.count("of its group") == 3


class TestWhatTheBrowserIsToldToRender:
    def test_a_name_is_escaped_not_executed(self, browser: TestClient, campus: None) -> None:
        """The console renders user text into HTML, so it is worth proving once that the
        text is data rather than markup.

        A project file is emailed between people — that is the whole point of the
        document model — so "nobody would type that" is not an argument available here.
        """
        form(
            browser,
            "/console/courses",
            code="X1",
            name="<script>alert(1)</script>",
            credits=0,
            department_id="",
        )

        markup = browser.get("/console/courses").text

        assert "<script>alert(1)</script>" not in markup
        assert "&lt;script&gt;" in markup
