"""`tessera itc` end to end, against a project on disk.

The one test that exercises every piece at once — parse, map, create the project, run the
migrations, write, and print the ledger. Each part is tested on its own elsewhere; what only
this can catch is the wiring between them, which is exactly what the exit test for this phase
turned out to depend on.

Marked slow because it runs the real migrations against a real file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from tessera.cli import itc, main
from tessera.repository import models as m
from tessera.repository.database import create_project_engine, session_factory

pytestmark = pytest.mark.slow

FIXTURE = Path(__file__).parent / "fixtures" / "bet-sum18.xml"


def _run(*arguments: str) -> int:
    """The command, parsed the way the real entry point parses it."""
    parser = argparse.ArgumentParser()
    itc.add_arguments(parser)
    return itc.run(parser.parse_args(list(arguments)))


class TestTheCommand:
    def test_it_writes_a_project_that_can_be_opened(self, tmp_path: Path) -> None:
        into = tmp_path / "ITC.tessera"

        assert _run(str(FIXTURE), "--into", str(into)) == 0

        # A package, not a bare file — the shape `project.resolve` creates.
        assert (into / "project.db").exists()
        with session_factory(create_project_engine(into / "project.db"))() as db:
            assert db.query(m.Room).count() == 46
            assert db.query(m.Course).count() == 48
            assert db.query(m.Term).one().name == "bet-sum18"

    def test_it_says_what_was_lost(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An import that reports only what arrived has told you the flattering half."""
        _run(str(FIXTURE), "--into", str(tmp_path / "p.tessera"))
        printed = capsys.readouterr().out

        assert "carried" in printed
        assert "dropped" in printed
        assert "127  classes" in printed
        assert "10 minutes from 08:00" in printed

    def test_a_dry_run_keeps_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        into = tmp_path / "ITC.tessera"

        assert _run(str(FIXTURE), "--into", str(into), "--dry-run") == 0

        with session_factory(create_project_engine(into / "project.db"))() as db:
            assert db.query(m.Room).count() == 0
        assert "nothing kept" in capsys.readouterr().out

    def test_a_file_that_is_not_an_instance_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        not_xml = tmp_path / "rooms.csv"
        not_xml.write_text("name,capacity\nLH-201,120\n")

        assert _run(str(not_xml), "--into", str(tmp_path / "p.tessera")) == 1
        assert "cannot read" in capsys.readouterr().out

    def test_a_file_that_is_not_there(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(str(tmp_path / "gone.xml"), "--into", str(tmp_path / "p.tessera")) == 1
        assert "cannot read" in capsys.readouterr().out

    def test_it_is_reachable_through_the_entry_point(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Through `main`, which is what the installed `tessera` command runs. The parser
        wiring is built at call time and has nothing else referencing it."""
        main(["itc", str(FIXTURE), "--into", str(tmp_path / "p.tessera")])

        assert "bet-sum18" in capsys.readouterr().out

