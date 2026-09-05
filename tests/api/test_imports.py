"""Importing over HTTP.

The rules are tested in `tests/importers/`. What only appears at the edge: that a dry run
is the default, that the two steps run the same code, that a mapping can be corrected and
sent back, and that an unusable file is a 400 rather than a stack trace.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.app import create_app

ROOMS = b"Room,Seats,Block,Equipment\nLH-201,150,Block A,projector\nLH-202,forty,Block A,\n"


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(
        create_app(engine=engine, configure_logs=False), base_url="http://127.0.0.1"
    ) as test_client:
        yield test_client


@pytest.fixture
def term(client: TestClient) -> int:
    institution = client.post("/api/v1/institutions", json={"name": "U"}).json()
    client.post("/api/v1/buildings", json={"institution_id": institution["id"], "name": "Block A"})
    client.post("/api/v1/features", json={"institution_id": institution["id"], "name": "projector"})
    grid = client.post(
        "/api/v1/time-grids",
        json={
            "institution_id": institution["id"],
            "days": 5,
            "slots_per_day": 8,
            "slot_minutes": 60,
            "day_start_minute": 540,
        },
    ).json()
    created = client.post(
        "/api/v1/terms",
        json={
            "institution_id": institution["id"],
            "time_grid_id": grid["id"],
            "academic_year": "2026-27",
            "name": "Autumn",
        },
    ).json()
    return int(created["id"])


def upload(
    client: TestClient, term: int, data: bytes, *, name: str = "rooms.csv", **params: object
) -> Any:
    files = {"file": (name, io.BytesIO(data), "text/csv")}
    # Every query parameter goes through `params`, including `term_id`. httpx *replaces*
    # a URL's query string with `params` rather than merging, so putting one in each is
    # how `term_id` silently disappears and every response becomes a 422.
    response = client.post(
        "/api/v1/imports/spreadsheet",
        files=files,
        params={"term_id": str(term), **{k: str(v) for k, v in params.items()}},
    )
    return {"status": response.status_code, **(response.json() if response.content else {})}


class TestTheDryRunIsTheDefault:
    def test_uploading_without_asking_writes_nothing(self, client: TestClient, term: int) -> None:
        """The safe thing has to be the thing that happens when nobody chose."""
        report = upload(client, term, ROOMS)

        assert report["committed"] is False
        assert client.get("/api/v1/rooms").json()["total"] == 0

    def test_it_reports_what_would_happen(self, client: TestClient, term: int) -> None:
        report = upload(client, term, ROOMS)

        assert report["detected_kind"] == "rooms"
        assert report["rows_total"] == 2
        assert report["rows_ready"] == 1
        assert "'forty'" in report["problems"][0]["message"]
        assert report["problems"][0]["row"] == 3

    def test_the_guessed_mapping_comes_back(self, client: TestClient, term: int) -> None:
        """It is returned so it can be corrected and sent again — which is what the
        `mapping` field on the request is for."""
        report = upload(client, term, ROOMS)

        assert report["column_mapping"]["Seats"] == "capacity"


class TestCommitting:
    def test_only_the_valid_rows_are_written(self, client: TestClient, term: int) -> None:
        report = upload(client, term, ROOMS, dry_run="false")

        assert report["committed"] is True
        assert client.get("/api/v1/rooms").json()["total"] == 1

    def test_the_same_file_twice_is_refused_whole(self, client: TestClient, term: int) -> None:
        """The second import collides with the first. Nothing is written rather than
        some of it, and the count from before is unchanged."""
        upload(client, term, ROOMS, dry_run="false")

        report = upload(client, term, ROOMS, dry_run="false")

        assert report["committed"] is False
        assert client.get("/api/v1/rooms").json()["total"] == 1

    def test_a_dry_run_after_a_commit_sees_the_collision(
        self, client: TestClient, term: int
    ) -> None:
        """The dry run and the commit run the same code, so the dry run knows everything
        the commit would — including rules that only the project can answer."""
        upload(client, term, ROOMS, dry_run="false")

        report = upload(client, term, ROOMS)

        assert any("already exists" in p["message"] for p in report["problems"])


class TestCorrectingTheMapping:
    def test_a_column_can_be_pointed_at_a_different_field(
        self, client: TestClient, term: int
    ) -> None:
        """A sheet whose header says something nobody guessed. Without this the only way
        to import it is to edit the spreadsheet — the manual work this phase removes."""
        odd = b"Room,Places Available\nLH-201,150\n"

        files = {"file": ("rooms.csv", io.BytesIO(odd), "text/csv")}
        response = client.post(
            f"/api/v1/imports/spreadsheet?term_id={term}&dry_run=false",
            files=files,
            data={"mapping": json.dumps({"Room": "name", "Places Available": "capacity"})},
        )

        assert response.json()["committed"] is True
        assert client.get("/api/v1/rooms").json()["items"][0]["capacity"] == 150

    def test_a_mapping_that_is_not_json_is_a_400(self, client: TestClient, term: int) -> None:
        files = {"file": ("rooms.csv", io.BytesIO(ROOMS), "text/csv")}
        response = client.post(
            f"/api/v1/imports/spreadsheet?term_id={term}",
            files=files,
            data={"mapping": "not json"},
        )

        assert response.status_code == 400


class TestFilesThatDoNotWork:
    def test_something_that_is_not_a_spreadsheet(self, client: TestClient, term: int) -> None:
        report = upload(client, term, b"%PDF-1.4", name="timetable.pdf")

        assert report["status"] == 400
        assert "not a spreadsheet" in report["detail"]

    def test_an_empty_file(self, client: TestClient, term: int) -> None:
        assert upload(client, term, b"")["status"] == 400

    def test_columns_that_resemble_nothing(self, client: TestClient, term: int) -> None:
        report = upload(client, term, b"Colour,Shape\nred,round\n")

        assert report["status"] == 400

    def test_a_missing_required_column_is_said_plainly(self, client: TestClient, term: int) -> None:
        """Detected as rooms — it has a room name — but with no capacity there is nothing
        to import, and "0 of 2 rows ready" alone would not explain why."""
        report = upload(client, term, b"Room,Block\nLH-201,Block A\n")

        assert any("No column was found for" in p["message"] for p in report["problems"])


class TestTheReportCanBeFetchedAgain:
    def test_a_report_is_retrievable_by_id(self, client: TestClient, term: int) -> None:
        report = upload(client, term, ROOMS)

        fetched = client.get(f"/api/v1/imports/{report['import_id']}")

        assert fetched.status_code == 200
        assert fetched.json()["rows_total"] == 2

    def test_an_unknown_id_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/imports/nothing").status_code == 404


class TestTheMappingTable:
    """What a column mapping table needs, and where it has to come from.

    P7 draws a sample beside every row — *"Room No → [ Name ⌄ ] LH-201"* — because nobody
    recognises a column called `Blk` by its name and everybody recognises it by seeing
    `Academic Block A` next to it. And a dropdown needs to know what a column *may* be
    mapped to.

    Both come from the engine. The sample because the client cannot read the file: a `.csv`
    it could parse, but an `.xlsx` is a zip of XML, and a second spreadsheet reader in Swift
    to show one cell would be a second answer to what the file says. The field list because
    the alternative is the four kinds' fields written out again in Swift, which is the second
    statement of a rule that drifts the first time a field is added here.
    """

    def test_every_column_is_described_in_order(self, client: TestClient, term: int) -> None:
        report = _post(
            client,
            term,
            b"Room Name,Seats,Block,Floor\nLH-201,120,Block A,2\n",
        )
        assert [c["header"] for c in report["columns"]] == [
            "Room Name",
            "Seats",
            "Block",
            "Floor",
        ]

    def test_each_column_carries_a_sample(self, client: TestClient, term: int) -> None:
        report = _post(client, term, b"Room Name,Seats,Block\nLH-201,120,Block A\n")
        samples = {c["header"]: c["sample"] for c in report["columns"]}
        assert samples == {"Room Name": "LH-201", "Seats": "120", "Block": "Block A"}

    def test_the_sample_is_the_first_value_that_exists(self, client: TestClient, term: int) -> None:
        """A blank first cell must not leave the column somebody most needs to identify
        showing nothing."""
        report = _post(
            client,
            term,
            b"Room Name,Seats,Block\nLH-201,120,\nLH-202,80,Block A\n",
        )
        samples = {c["header"]: c["sample"] for c in report["columns"]}
        assert samples["Block"] == "Block A"

    def test_an_ignored_column_says_so(self, client: TestClient, term: int) -> None:
        report = _post(client, term, b"Room Name,Seats,Floor\nLH-201,120,2\n")
        described = {c["header"]: c["maps_to"] for c in report["columns"]}
        assert described["Room Name"] == "name"
        assert described["Floor"] == "", "an unmapped column is ignored, not omitted"

    def test_the_table_and_the_round_trip_form_agree(self, client: TestClient, term: int) -> None:
        """`columns` is what a table draws and `column_mapping` is what gets sent back. Two
        shapes of one fact, so the only thing worth testing is that they cannot disagree."""
        report = _post(client, term, b"Room Name,Seats,Block,Floor\nLH-201,120,Block A,2\n")
        from_table = {c["header"]: c["maps_to"] for c in report["columns"] if c["maps_to"]}
        assert from_table == report["column_mapping"]

    def test_the_fields_offered_are_the_detected_kind_s(
        self, client: TestClient, term: int
    ) -> None:
        report = _post(client, term, b"Room Name,Seats,Block\nLH-201,120,Block A\n")
        assert report["detected_kind"] == "rooms"
        assert [f["name"] for f in report["fields"]] == [
            "name",
            "capacity",
            "building",
            "features",
        ]
        required = {f["name"] for f in report["fields"] if f["required"]}
        assert required == {"name", "capacity"}

    def test_a_corrected_mapping_is_honoured(self, client: TestClient, term: int) -> None:
        """The whole point of making the table editable: a column guessed wrong makes every
        row fail, and correcting it must change what the next dry run reports."""
        sheet = b"Label,Seats,Block\nLH-201,120,Block A\n"

        guessed = _post(client, term, sheet)
        corrected = _post(
            client,
            term,
            sheet,
            mapping={"Label": "name", "Seats": "capacity", "Block": "building"},
        )

        assert corrected["rows_ready"] >= guessed["rows_ready"]
        assert {c["header"]: c["maps_to"] for c in corrected["columns"]}["Label"] == "name"


def _post(
    client: TestClient,
    term: int,
    sheet: bytes,
    mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = {"mapping": json.dumps(mapping)} if mapping else {}
    response = client.post(
        f"/api/v1/imports/spreadsheet?term_id={term}&dry_run=true",
        files={"file": ("rooms.csv", sheet, "text/csv")},
        data=data,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body
