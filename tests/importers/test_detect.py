"""Guessing what a sheet is, and which column is which.

Detection is allowed to be wrong — it is a guess, reported and overridable. What it is
not allowed to be is *confidently* wrong, so the tests here are mostly about the cases
where two shapes both nearly fit.
"""

from __future__ import annotations

from tessera.importers.detect import Kind, detect, suggest_column


class TestWhichKind:
    def test_a_room_sheet(self) -> None:
        found = detect(("Room Name", "Seats", "Block", "Equipment"))

        assert found.kind is Kind.ROOMS
        assert found.confident

    def test_an_instructor_sheet(self) -> None:
        found = detect(("Full Name", "E-mail", "Dept"))

        assert found.kind is Kind.INSTRUCTORS
        assert found.mapping == {"Full Name": "name", "E-mail": "email", "Dept": "department"}

    def test_a_course_sheet(self) -> None:
        found = detect(("Course Code", "Title", "Credits", "School"))

        assert found.kind is Kind.COURSES
        assert found.confident

    def test_a_group_sheet(self) -> None:
        found = detect(("Batch", "Students", "Parent Group"))

        assert found.kind is Kind.GROUPS
        assert found.mapping["Students"] == "size"

    def test_a_room_sheet_is_not_mistaken_for_a_course_sheet(self) -> None:
        """Both have a name and a department-ish column. Scoring by *required* fields
        first is what keeps them apart — a course must have a code, and this has none."""
        found = detect(("Name", "Seats", "Department"))

        assert found.kind is Kind.ROOMS


class TestHeadersPeopleActuallyWrite:
    def test_punctuation_and_case_do_not_matter(self) -> None:
        assert detect(("ROOM  NO.", "seats")).mapping == {"ROOM  NO.": "name", "seats": "capacity"}

    def test_underscores_are_spaces(self) -> None:
        assert detect(("room_name", "max")).mapping["room_name"] == "name"

    def test_a_numbered_column_feeds_a_repeatable_field(self) -> None:
        """A sheet with `Equipment 1` and `Equipment 2` is one field spread over two
        columns, and both should reach it."""
        found = detect(("Room", "Seats", "Equipment 1", "Equipment 2"))

        assert found.mapping["Equipment 1"] == "features"
        assert found.mapping["Equipment 2"] == "features"

    def test_a_numbered_column_does_not_feed_a_single_field(self) -> None:
        """`Seats 2` is not a second capacity; it is a column nobody has explained."""
        found = detect(("Room", "Seats", "Seats 2"))

        assert "Seats 2" in found.unmatched


class TestWhatItCannotWorkOut:
    def test_a_missing_required_column_is_named(self) -> None:
        found = detect(("Room Name", "Block"))

        assert found.kind is Kind.ROOMS
        assert found.missing == ("capacity",)
        assert not found.confident

    def test_columns_it_does_not_recognise_are_listed_not_dropped(self) -> None:
        found = detect(("Room", "Seats", "Cleaning rota"))

        assert "Cleaning rota" in found.unmatched

    def test_a_near_miss_gets_a_suggestion(self) -> None:
        assert suggest_column("Capasity", Kind.ROOMS) == "capacity"

    def test_something_genuinely_unrelated_gets_none(self) -> None:
        """Offering the nearest field for every stray column would turn a report into
        noise, and noise is what gets ignored."""
        assert suggest_column("Cleaning rota", Kind.ROOMS) == ""
