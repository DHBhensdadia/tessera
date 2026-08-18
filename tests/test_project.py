"""What a `.tessera` is on disk, and how a copy of one is taken safely.

Two things here are only true if they are tested against a real file: that a project
written by `v0.1.0` still opens after this change, and that copying an open database
produces one that is complete rather than merely openable.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from tessera import project
from tessera.repository.database import create_project_engine


def bare_database(path: Path, *, rows: int = 3) -> Path:
    """A `v0.1.0`-shaped project: one SQLite file, no package around it."""
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE note (id INTEGER PRIMARY KEY, body TEXT)")
    connection.executemany(
        "INSERT INTO note (body) VALUES (?)", [(f"row {i}",) for i in range(rows)]
    )
    connection.commit()
    connection.close()
    return path


def rows_in(database: Path) -> list[str]:
    connection = sqlite3.connect(database)
    try:
        return [body for (body,) in connection.execute("SELECT body FROM note ORDER BY id")]
    finally:
        connection.close()


class TestResolving:
    def test_a_path_that_does_not_exist_becomes_a_package(self, tmp_path: Path) -> None:
        wanted = tmp_path / "New.tessera"

        database = project.resolve(wanted)

        assert wanted.is_dir()
        assert database == wanted / project.DATABASE_NAME

    def test_an_existing_package_resolves_to_the_database_inside(self, tmp_path: Path) -> None:
        wanted = tmp_path / "Existing.tessera"
        project.resolve(wanted)
        bare_database(wanted / project.DATABASE_NAME)

        assert rows_in(project.resolve(wanted)) == ["row 0", "row 1", "row 2"]

    def test_a_directory_that_is_not_a_project_is_refused(self, tmp_path: Path) -> None:
        """Better than silently treating somebody's Documents folder as a project."""
        intruder = tmp_path / "Photos"
        intruder.mkdir()
        (intruder / "holiday.jpg").write_bytes(b"not a database")

        with pytest.raises(project.NotAProjectError, match="does not contain"):
            project.resolve(intruder)


class TestConvertingAV010Project:
    def test_a_bare_file_becomes_a_package_at_the_same_path(self, tmp_path: Path) -> None:
        """The upgrade path. It runs once per project and cannot be added later."""
        legacy = bare_database(tmp_path / "CSE Timetables.tessera")

        database = project.resolve(legacy)

        assert legacy.is_dir(), "the path the user knows must not move"
        assert database == legacy / project.DATABASE_NAME
        assert rows_in(database) == ["row 0", "row 1", "row 2"]

    def test_converting_twice_is_a_no_op(self, tmp_path: Path) -> None:
        legacy = bare_database(tmp_path / "Twice.tessera")

        first = project.resolve(legacy)
        second = project.resolve(legacy)

        assert first == second
        assert rows_in(second) == ["row 0", "row 1", "row 2"]

    def test_the_write_ahead_log_comes_with_it(self, tmp_path: Path) -> None:
        """The failure that would look like success.

        With WAL, committed rows can still be in the `-wal` sidecar. Moving only the main
        file gives a database that opens fine and is missing the user's last edits — worse
        than one that refuses to open, because nobody investigates a file that opened.
        """
        legacy = tmp_path / "Wal.tessera"
        connection = sqlite3.connect(legacy)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE note (id INTEGER PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO note (body) VALUES ('committed to the wal')")
        connection.commit()

        # The connection stays open on purpose. Closing the last one checkpoints the WAL
        # into the main file and deletes the sidecar — which is what made the first
        # version of this test pass with the sidecar handling removed. Asserting the
        # precondition is what keeps it honest.
        try:
            assert legacy.with_name(legacy.name + "-wal").exists(), "no -wal to lose"
            database = project.resolve(legacy)
        finally:
            connection.close()

        assert rows_in(database) == ["committed to the wal"]

    def test_nothing_is_left_beside_the_project(self, tmp_path: Path) -> None:
        bare_database(tmp_path / "Tidy.tessera")

        project.resolve(tmp_path / "Tidy.tessera")

        assert [p.name for p in tmp_path.iterdir()] == ["Tidy.tessera"]


class TestSavingACopy:
    def test_a_copy_of_an_open_project_is_complete(self, tmp_path: Path) -> None:
        """Taken while the database is open and has been written to.

        A `shutil.copy` here would produce a file that opens and is missing whatever is
        still in the WAL — which is why this is `VACUUM INTO` and why the test writes
        first and does not checkpoint.
        """
        source = tmp_path / "Live.tessera"
        database = project.resolve(source)
        engine = create_project_engine(database)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE note (id INTEGER PRIMARY KEY, body TEXT)"))
            connection.execute(text("INSERT INTO note (body) VALUES ('written while open')"))

        try:
            written = project.copy_to(database, tmp_path / "Copy.tessera")
            assert rows_in(project.database_path(written)) == ["written while open"]
        finally:
            engine.dispose()

    def test_the_copy_is_a_package_too(self, tmp_path: Path) -> None:
        source = tmp_path / "Live.tessera"
        database = project.resolve(source)
        bare_database(database)

        written = project.copy_to(database, tmp_path / "Copy.tessera")

        assert written.is_dir()
        assert project.database_path(written).exists()

    def test_the_original_is_untouched(self, tmp_path: Path) -> None:
        source = tmp_path / "Live.tessera"
        database = project.resolve(source)
        bare_database(database)

        project.copy_to(database, tmp_path / "Copy.tessera")

        assert rows_in(database) == ["row 0", "row 1", "row 2"]

    def test_writing_onto_something_that_exists_is_refused(self, tmp_path: Path) -> None:
        """Overwriting is how somebody loses the thing they were copying to.

        The contents are checked, not just the exception: `mkdir(exist_ok=True)` would
        still raise nothing and would write a database into somebody's existing folder,
        and an exception-only test would not notice.
        """
        source = tmp_path / "Live.tessera"
        database = project.resolve(source)
        bare_database(database)
        occupied = tmp_path / "Taken.tessera"
        occupied.mkdir()
        (occupied / "important.txt").write_text("somebody else's work")

        with pytest.raises(FileExistsError):
            project.copy_to(database, occupied)

        assert [p.name for p in occupied.iterdir()] == ["important.txt"]

    def test_the_copy_can_be_opened_and_written_to(self, tmp_path: Path) -> None:
        """A snapshot nobody can carry on working in is a backup, not a Save As."""
        source = tmp_path / "Live.tessera"
        database = project.resolve(source)
        bare_database(database)

        written = project.copy_to(database, tmp_path / "Copy.tessera")

        engine = create_project_engine(project.database_path(written))
        try:
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO note (body) VALUES ('and edited')"))
            assert rows_in(project.database_path(written))[-1] == "and edited"
        finally:
            engine.dispose()
