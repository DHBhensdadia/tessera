"""Reading a spreadsheet into rows, without deciding what any of it means.

pandas does the reading — encodings, byte-order marks, delimiter sniffing, workbooks with
several sheets — and is given no opportunity to do anything else.

**Everything is read as text.** Left to itself pandas infers types and turns whatever it
cannot parse into ``NaN``, which discards exactly the thing this phase exists to report:
a capacity of ``forty`` becomes "missing" rather than "says forty", a room genuinely
called ``NA`` becomes a blank, and one empty cell turns a column of room codes into
floats. ``dtype=str`` with ``keep_default_na=False`` stops all three.

**Row numbers are spreadsheet row numbers.** `row 14` has to mean row 14 in the file
somebody opens in Excel — one-based, header included — not pandas' zero-based index into
the data. Off by one here makes every message in the report quietly wrong.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd

#: The header occupies row 1, so the first row of data is row 2.
FIRST_DATA_ROW = 2


class UnreadableFileError(Exception):
    """The file could not be read at all — as opposed to read and found wanting.

    Kept separate from row problems because there is nothing to report per row: no
    columns were detected, no rows exist, and the only useful message is about the file.
    """


@dataclass(frozen=True)
class Row:
    """One line of the sheet, as text, with the number the user would see."""

    number: int
    cells: dict[str, str]

    def get(self, column: str) -> str:
        return self.cells.get(column, "").strip()


@dataclass(frozen=True)
class Sheet:
    headers: tuple[str, ...]
    rows: tuple[Row, ...]
    #: Headers that appeared more than once. pandas silently renames the second `Name` to
    #: `Name.1`, so without this the duplicate looks like a column nobody asked for.
    duplicate_headers: tuple[str, ...] = ()


def read(data: bytes, filename: str) -> Sheet:
    """Read a `.csv` or `.xlsx` into rows of text.

    Raises `UnreadableFileError` when there is nothing to work with; everything else is
    somebody's data and is handed on to be validated rather than rejected here.
    """
    if not data:
        raise UnreadableFileError("The file is empty.")

    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix in {"xlsx", "xlsm"}:
        frame = _read_excel(data)
    elif suffix in {"csv", "txt", "tsv"}:
        frame = _read_csv(data)
    else:
        raise UnreadableFileError(
            f"{filename!r} is not a spreadsheet. Save it as .csv or .xlsx and try again."
        )

    if frame.empty and not list(frame.columns):
        raise UnreadableFileError("No columns were found. Is the first row a header?")

    headers, duplicates = _headers(frame)
    rows = tuple(
        Row(
            number=FIRST_DATA_ROW + position,
            cells={header: _text(value) for header, value in zip(headers, values, strict=False)},
        )
        for position, values in enumerate(frame.itertuples(index=False, name=None))
    )
    return Sheet(headers=headers, rows=rows, duplicate_headers=duplicates)


def _read_csv(data: bytes) -> pd.DataFrame:
    try:
        return pd.read_csv(
            io.BytesIO(data),
            dtype=str,
            # `NA`, `null`, `None` and a dozen others are values pandas treats as missing
            # by default. In a room-name column they are room names. Either flag alone
            # stops it — `na_filter` disables the detection, `keep_default_na` empties the
            # list it detects against — and both are set because they say different halves
            # of the same intention and neither is load-bearing on its own.
            keep_default_na=False,
            na_filter=False,
            skip_blank_lines=False,  # a blank line is a row to report, not one to hide
            # "CSV UTF-8" is what Excel's save dialog offers, and it writes a byte-order
            # mark. Without this the first header is `﻿Name`, which matches no field
            # and makes an otherwise perfect file look like it has the wrong columns.
            # The codec reads plain UTF-8 unchanged, so there is no cost to always using it.
            encoding="utf-8-sig",
            encoding_errors="replace",
            engine="python",  # tolerates ragged rows and sniffs the delimiter
            sep=None,
        )
    except Exception as error:  # pandas raises a family of these; the cause is the same
        raise UnreadableFileError(
            f"The file could not be read as a spreadsheet: {error}"
        ) from error


def _read_excel(data: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(
            io.BytesIO(data),
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            engine="openpyxl",
        )
    except Exception as error:
        raise UnreadableFileError(f"The workbook could not be read: {error}") from error


def _headers(frame: pd.DataFrame) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Column names as written, and any that were duplicated.

    pandas renames a repeated `Name` to `Name.1` rather than complaining. That is a
    reasonable default and a terrible silence: two columns claiming to be the same field
    means one of them is being ignored, and the user should hear about it.
    """
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    headers: list[str] = []

    for column in frame.columns:
        name = str(column).strip()
        base = name.rsplit(".", 1)[0] if _looks_renamed(name) else name
        seen[base] = seen.get(base, 0) + 1
        if seen[base] == 2:
            duplicates.append(base)
        headers.append(name)

    return tuple(headers), tuple(duplicates)


def _looks_renamed(name: str) -> bool:
    """`Name.1` is pandas' work; `2.1` might be somebody's column."""
    stem, _, tail = name.rpartition(".")
    return bool(stem) and tail.isdigit() and not stem.replace(".", "").isdigit()


def _text(value: object) -> str:
    """Whatever the cell held, as the string the user would recognise.

    Numbers survive a round trip through Excel as floats often enough that `45.0` in a
    capacity column is common; it is shown as `45` because that is what was typed.

    `keep_default_na=False` stops pandas reading the *word* `NA` as missing, but a row
    with fewer fields than the header — a blank line, or a trailing comma nobody typed —
    is still padded with float `NaN`. Passing that through `str()` produces the string
    `"nan"`, which then reads as a room called nan, or a building nobody can find. It is
    a blank cell, and is treated as one.
    """
    if value is None or (isinstance(value, float) and value != value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        return text[:-2]
    return text
