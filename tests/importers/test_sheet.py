"""Reading a file into rows of text.

The tests that matter here are the ones about *not* helping. pandas is very willing to
interpret a spreadsheet, and every interpretation it makes is information this phase
needed in order to tell somebody what is wrong with row 14.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from tessera.importers.sheet import UnreadableFileError, read


def workbook(rows: list[list[object]]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class TestRowNumbers:
    def test_the_first_data_row_is_row_two(self) -> None:
        """`row 14` has to mean row 14 in the file somebody opens in Excel.

        The header is row 1, so data starts at 2. Pandas counts its own rows from zero,
        and using that number would make every message in the report off by one — subtly
        wrong in a way nobody would notice until they went looking for the wrong line.
        """
        sheet = read(b"Name,Seats\nLH-201,150\nLH-202,80\n", "rooms.csv")

        assert [row.number for row in sheet.rows] == [2, 3]

    def test_a_blank_line_still_occupies_its_row(self) -> None:
        """Skipping blank lines silently would shift every number after them."""
        sheet = read(b"Name,Seats\nLH-201,150\n\nLH-203,60\n", "rooms.csv")

        assert [row.number for row in sheet.rows] == [2, 3, 4]
        assert sheet.rows[2].get("Name") == "LH-203"


class TestNothingIsInterpreted:
    def test_a_word_in_a_number_column_survives_as_a_word(self) -> None:
        """The whole value of this phase is being able to say "row 3 says 'forty'".

        Left to itself pandas turns that into NaN, and the only available message becomes
        "missing" — which is both wrong and impossible to act on.
        """
        sheet = read(b"Name,Seats\nLH-201,150\nLH-202,forty\n", "rooms.csv")

        assert sheet.rows[1].get("Seats") == "forty"

    def test_a_room_called_na_is_a_room_called_na(self) -> None:
        """`NA`, `N/A`, `null` and `None` are all values pandas treats as missing by
        default. In a room name column they are room names."""
        sheet = read(b"Name,Seats\nNA,30\nnull,40\n", "rooms.csv")

        assert [row.get("Name") for row in sheet.rows] == ["NA", "null"]

    def test_a_code_column_does_not_become_numbers(self) -> None:
        """One blank cell is enough to make pandas read a column of codes as floats,
        after which `0101` is `101.0` and no longer matches anything."""
        sheet = read(b"Name,Seats\n0101,30\n0102,40\n", "rooms.csv")

        assert [row.get("Name") for row in sheet.rows] == ["0101", "0102"]

    def test_a_number_round_tripped_through_excel_reads_as_typed(self) -> None:
        """Excel stores 45 as 45.0 often enough that a capacity column full of `45.0` is
        normal. It is shown as `45`, which is what was typed."""
        data = workbook([["Name", "Seats"], ["LH-201", 45]])

        sheet = read(data, "rooms.xlsx")

        assert sheet.rows[0].get("Seats") == "45"


class TestDuplicateHeaders:
    def test_a_repeated_header_is_reported(self) -> None:
        """pandas renames the second `Name` to `Name.1` and says nothing. That is a
        reasonable default and a bad silence: one of the two columns is being ignored."""
        sheet = read(b"Name,Seats,Name\nLH-201,150,Other\n", "rooms.csv")

        assert sheet.duplicate_headers == ("Name",)

    def test_a_column_genuinely_called_two_point_one_is_not_a_duplicate(self) -> None:
        sheet = read(b"2.1,Seats\nx,150\n", "rooms.csv")

        assert sheet.duplicate_headers == ()


class TestFilesThatCannotBeRead:
    def test_an_empty_file(self) -> None:
        with pytest.raises(UnreadableFileError, match="empty"):
            read(b"", "rooms.csv")

    def test_something_that_is_not_a_spreadsheet(self) -> None:
        with pytest.raises(UnreadableFileError, match="not a spreadsheet"):
            read(b"%PDF-1.4 ...", "timetable.pdf")

    def test_a_csv_with_no_header_row(self) -> None:
        with pytest.raises(UnreadableFileError):
            read(b"\n\n", "rooms.csv")

    def test_a_workbook_that_is_not_one(self) -> None:
        with pytest.raises(UnreadableFileError, match="could not be read"):
            read(b"this is not a zip archive", "rooms.xlsx")


class TestFormats:
    def test_an_xlsx_reads_like_a_csv(self) -> None:
        data = workbook([["Name", "Seats"], ["LH-201", 150], ["LH-202", 80]])

        sheet = read(data, "rooms.xlsx")

        assert sheet.headers == ("Name", "Seats")
        assert [row.get("Name") for row in sheet.rows] == ["LH-201", "LH-202"]

    def test_a_semicolon_separated_file_is_understood(self) -> None:
        """Excel writes these on any machine with a European locale, and users have no
        idea it happened."""
        sheet = read(b"Name;Seats\nLH-201;150\n", "rooms.csv")

        assert sheet.headers == ("Name", "Seats")
        assert sheet.rows[0].get("Seats") == "150"

    def test_a_byte_order_mark_is_not_part_of_the_first_header(self) -> None:
        """Excel's "CSV UTF-8" export writes one, and without handling it the first
        column is called `﻿Name` and matches nothing."""
        sheet = read("Name,Seats\nLH-201,150\n".encode("utf-8-sig"), "rooms.csv")

        assert sheet.headers[0] == "Name"


class TestShortRows:
    def test_a_row_with_fewer_cells_has_blanks_not_the_word_nan(self) -> None:
        """pandas pads a short row with float NaN. Stringifying that gives `"nan"`,
        which then reads as a building nobody can find rather than as an empty cell."""
        sheet = read(b"Name,Seats,Block\nLH-201,150\n", "rooms.csv")

        assert sheet.rows[0].get("Block") == ""

    def test_a_blank_line_has_no_content_at_all(self) -> None:
        sheet = read(b"Name,Seats\nLH-201,150\n\nLH-203,60\n", "rooms.csv")

        assert not any(sheet.rows[1].cells.values())
