"""The command-line entry point.

Thin for now, but covered from the start: an entry point that has never been executed
in CI is the kind of thing that breaks silently and is only noticed by a user.
"""

from __future__ import annotations

import pytest

import tessera
from tessera.cli import main


def test_main_reports_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    assert tessera.__version__ in capsys.readouterr().out


def test_the_itc_command_is_reachable(capsys: pytest.CaptureFixture[str]) -> None:
    """`--help` exercises the subparser wiring, which is where a command silently stops
    existing — the parser is built at call time and nothing else references it."""
    with pytest.raises(SystemExit) as stopped:
        main(["itc", "--help"])

    assert stopped.value.code == 0
    assert "--into" in capsys.readouterr().out
