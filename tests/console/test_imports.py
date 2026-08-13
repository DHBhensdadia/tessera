"""Importing a spreadsheet in a browser — and the phase exit test.

*"A messy 200-row spreadsheet imports; malformed rows are rejected with precise messages
and no partial write."* Everything here is either that sentence or one of the things that
has to work for it to be true.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.app import create_app
from tests.importers.test_messy_sheet import DAMAGE, messy_sheet

ROOMS = b"Room,Seats,Block\nLH-201,150,Block A\nLH-202,forty,Block A\n"


@pytest.fixture
def browser(engine: Engine) -> Iterator[TestClient]:
    app = create_app(engine=engine, configure_logs=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def term(browser: TestClient) -> int:
    institution = browser.post("/api/v1/institutions", json={"name": "U"}).json()
    browser.post("/api/v1/buildings", json={"institution_id": institution["id"], "name": "Block A"})
    browser.post(
        "/api/v1/features", json={"institution_id": institution["id"], "name": "projector"}
    )
    grid = browser.post(
        "/api/v1/time-grids",
        json={
            "institution_id": institution["id"],
            "days": 5,
            "slots_per_day": 8,
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


def upload(browser: TestClient, term: int, data: bytes, name: str = "rooms.csv") -> str:
    response = browser.post(
        "/console/imports",
        data={"term_id": str(term)},
        files={"file": (name, io.BytesIO(data), "text/csv")},
    )
    return str(response.text)


def token_in(markup: str) -> str:
    found = re.search(r"/console/imports/([a-f0-9]+)/check", markup)
    assert found is not None, "no upload token on the page"
    return found.group(1)


def rooms(browser: TestClient) -> int:
    total: int = browser.get("/api/v1/rooms").json()["total"]
    return total


class TestCheckingBeforeWriting:
    def test_uploading_writes_nothing(self, browser: TestClient, term: int) -> None:
        """An importer that writes on upload and explains afterwards is one people stop
        trusting the first time it is wrong about a file they cared about."""
        upload(browser, term, ROOMS)

        assert rooms(browser) == 0

    def test_the_report_says_how_much_would_go_in(self, browser: TestClient, term: int) -> None:
        markup = upload(browser, term, ROOMS)

        assert "1 of 2 rows would be imported" in " ".join(markup.split())

    def test_a_problem_names_its_row_and_column(self, browser: TestClient, term: int) -> None:
        markup = upload(browser, term, ROOMS)

        assert "forty" in markup
        assert ">3</td>" in markup

    def test_an_unreadable_file_is_explained_not_thrown(
        self, browser: TestClient, term: int
    ) -> None:
        markup = upload(browser, term, b"%PDF-1.4", name="timetable.pdf")

        assert "not a spreadsheet" in markup

    def test_columns_that_resemble_nothing_are_explained(
        self, browser: TestClient, term: int
    ) -> None:
        markup = upload(browser, term, b"Colour,Shape\nred,round\n")

        assert "do not look like" in markup


class TestCorrectingTheMapping:
    def test_a_column_nobody_guessed_can_be_pointed_at_a_field(
        self, browser: TestClient, term: int
    ) -> None:
        """Without this the only way to import a sheet whose header says something
        unexpected is to edit the spreadsheet — the manual work this page removes."""
        markup = upload(browser, term, b"Room,Places Available\nLH-201,150\n")
        token = token_in(markup)

        rechecked = browser.post(
            f"/console/imports/{token}/check",
            data={"column:Room": "name", "column:Places Available": "capacity"},
        ).text

        assert "1 of 1 row would be imported" in " ".join(rechecked.split())

    def test_the_unrecognised_column_is_offered_a_guess(
        self, browser: TestClient, term: int
    ) -> None:
        markup = upload(browser, term, b"Room,Seats,Capasity\nLH-201,150,x\n")

        assert "looks like capacity" in markup

    def test_rechecking_still_writes_nothing(self, browser: TestClient, term: int) -> None:
        """The mapping sent here is **complete**, so a row genuinely could be written.

        An earlier version of this test sent only one column, which left capacity
        unmapped — every row then failed validation and there was nothing to write, so the
        test passed whether or not the dry run held. It was proving the mapping was
        broken, not that nothing was written.
        """
        token = token_in(upload(browser, term, ROOMS))

        rechecked = browser.post(
            f"/console/imports/{token}/check",
            data={"column:Room": "name", "column:Seats": "capacity", "column:Block": "building"},
        ).text

        assert "1 of 2 rows would be imported" in " ".join(rechecked.split())
        assert rooms(browser) == 0


class TestCommitting:
    def test_the_valid_rows_go_in_and_the_page_moves_on(
        self, browser: TestClient, term: int
    ) -> None:
        """Landing on the rooms page rather than a success message: the result should be
        visible rather than asserted."""
        token = token_in(upload(browser, term, ROOMS))

        response = browser.post(f"/console/imports/{token}/commit", data={}, follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/console/rooms"
        assert rooms(browser) == 1

    def test_an_expired_upload_says_so(self, browser: TestClient, term: int) -> None:
        markup = browser.post("/console/imports/nosuchtoken/commit", data={}).text

        assert "expired" in markup

    def test_importing_the_same_file_twice_writes_nothing_the_second_time(
        self, browser: TestClient, term: int
    ) -> None:
        """Every row collides. Nothing is written rather than some of it."""
        token = token_in(upload(browser, term, ROOMS))
        browser.post(f"/console/imports/{token}/commit", data={})

        second = token_in(upload(browser, term, ROOMS))
        browser.post(f"/console/imports/{second}/commit", data={})

        assert rooms(browser) == 1


class TestTheExitTest:
    def test_a_messy_two_hundred_row_spreadsheet(self, browser: TestClient, term: int) -> None:
        """**Phase 2.6's exit test**, performed the way a person would.

        199 rows with six kinds of damage in them: a word where a number belongs, a
        building that does not exist, a misspelled one that does, a missing name, a
        negative capacity, and a blank line. Every problem is reported against the row
        the file shows, and the 193 rows that are fine go in.
        """
        markup = upload(browser, term, messy_sheet())
        token = token_in(markup)

        assert "193 of 199 rows would be imported" in " ".join(markup.split())
        assert rooms(browser) == 0

        reported = {int(row) for row in re.findall(r"<tr>\s*<td>(\d+)</td>", markup)}
        assert reported == {row for row in DAMAGE if row != 99}

        browser.post(f"/console/imports/{token}/commit", data={})

        assert rooms(browser) == 193

    def test_the_damaged_rows_are_the_ones_missing(self, browser: TestClient, term: int) -> None:
        """Six rows were rejected and six rooms are absent — and each absent room is one
        the report named, rather than a coincidence of counting."""
        token = token_in(upload(browser, term, messy_sheet()))
        browser.post(f"/console/imports/{token}/commit", data={})

        names = {room["name"] for room in browser.get("/api/v1/rooms").json()["items"]}

        for row in (14, 27, 41, 73, 150):
            assert f"LH-{row:03d}" not in names
        assert "LH-100" in names

    def test_a_suggestion_was_offered_and_not_taken(self, browser: TestClient, term: int) -> None:
        markup = upload(browser, term, messy_sheet())

        assert "Did you mean" in markup
        assert "projector" in markup
