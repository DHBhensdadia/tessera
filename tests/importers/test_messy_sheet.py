"""Two hundred rows of somebody else's spreadsheet.

The phase exit test is *"a messy 200-row spreadsheet imports; malformed rows are rejected
with precise messages and no partial write"*. Writing is part 2. What is provable here is
the half that decides whether the other half is worth having: that a file with realistic
damage in it produces a report naming every problem, against the right row, and lets
everything else through.

The damage is deliberate and each kind of it appears once, so a failure names its own
cause rather than "the messy sheet broke".
"""

from __future__ import annotations

import time

import pytest

from tessera.importers.detect import detect
from tessera.importers.plan import Catalogue, Plan, build
from tessera.importers.sheet import read

#: Row numbers are one-based with a header, so a row `n` here is line `n` in Excel.
DAMAGE = {
    14: "capacity is a word",
    27: "building is nothing like anything that exists",
    41: "equipment is misspelled",
    58: "no name at all",
    73: "capacity is negative",
    99: "blank line",
    150: "building is misspelled",
}


def messy_sheet() -> bytes:
    """A realistic file: mostly fine, damaged in seven places, one blank line."""
    lines = ["Room Name,Seats,Block,Equipment"]
    for number in range(2, 202):
        if number == 14:
            lines.append("LH-014,forty,Block A,projector")
        elif number == 27:
            lines.append("LH-027,60,Science Park,projector")
        elif number == 41:
            lines.append("LH-041,60,Block A,projecter")
        elif number == 58:
            lines.append(",60,Block A,projector")
        elif number == 73:
            lines.append("LH-073,-5,Block A,projector")
        elif number == 99:
            lines.append("")
        elif number == 150:
            lines.append("LH-150,60,Blok A,projector")
        else:
            lines.append(f"LH-{number:03d},{40 + number % 60},Block A,projector")
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def known() -> Catalogue:
    return Catalogue(buildings={"Block A": 1}, features={"projector": 1})


@pytest.fixture
def plan(known: Catalogue) -> Plan:
    sheet = read(messy_sheet(), "rooms.csv")
    found = detect(sheet.headers)
    assert found.kind is not None
    return build(sheet, found.kind, found.mapping, known)


class TestTheReport:
    def test_the_undamaged_rows_all_come_through(self, plan: Plan) -> None:
        """199 data rows, one of them blank, six of them broken. A file that is 97%
        correct should not be 0% imported."""
        assert plan.rows_total == 199
        assert plan.rows_ready == 199 - 6

    def test_every_damaged_row_is_reported(self, plan: Plan) -> None:
        damaged = {row for row in DAMAGE if row != 99}

        assert {problem.row for problem in plan.problems} == damaged

    def test_each_problem_names_the_row_the_user_would_open(self, plan: Plan) -> None:
        """The blank line at 99 shifts nothing: it is still a line in the file, and every
        row after it keeps the number Excel shows."""
        by_row = {problem.row: problem for problem in plan.problems}

        assert "'forty'" in by_row[14].message
        assert "Science Park" in by_row[27].message
        assert "projecter" in by_row[41].message
        assert by_row[58].column == "name"
        assert "greater than or equal to 0" in by_row[73].message

    def test_the_misspellings_get_suggestions_and_the_others_do_not(self, plan: Plan) -> None:
        by_row = {problem.row: problem for problem in plan.problems}

        assert by_row[41].suggestion == "projector"
        assert by_row[150].suggestion == "Block A"
        # "Science Park" resembles nothing in the project, so no hint is offered. A
        # near miss like "Blok A" gets one; a different name entirely gets silence,
        # because a suggestion for everything is a report nobody reads.
        assert by_row[27].suggestion == ""

    def test_nothing_is_silently_corrected(self, plan: Plan) -> None:
        """Six rows were damaged and six rows are missing. A suggestion is a sentence in
        a report, never an edit."""
        names = {getattr(prepared.entity, "name", "") for prepared in plan.ready}

        assert "LH-041" not in names
        assert "LH-150" not in names

    def test_the_blank_line_is_not_a_problem(self, plan: Plan) -> None:
        """A gap between blocks of a spreadsheet is formatting. Reporting it would train
        people to skim the report, which is how the real problems get missed."""
        assert 99 not in {problem.row for problem in plan.problems}


class TestItIsFastEnoughToBeInteractive:
    def test_two_hundred_rows_report_in_well_under_a_second(self, known: Catalogue) -> None:
        """Not an NFR — this phase has none — but the dry run is something a person waits
        for, and "upload, wait, read" is only tolerable at one of those speeds.
        """
        data = messy_sheet()

        started = time.perf_counter()
        sheet = read(data, "rooms.csv")
        found = detect(sheet.headers)
        assert found.kind is not None
        build(sheet, found.kind, found.mapping, known)
        elapsed = time.perf_counter() - started

        assert elapsed < 0.5, f"took {elapsed:.3f}s"
