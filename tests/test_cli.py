"""The command-line entry point.

Thin for now, but covered from the start: an entry point that has never been executed
in CI is the kind of thing that breaks silently and is only noticed by a user.
"""

from __future__ import annotations

import tessera
from tessera.cli import main


def test_main_reports_the_package_version(capsys):
    main()
    assert tessera.__version__ in capsys.readouterr().out
