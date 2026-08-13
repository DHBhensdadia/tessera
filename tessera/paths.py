"""Finding files that travel with the code but are not imported.

Two kinds of thing live inside the package and are read from disk at runtime rather than
imported: Alembic's migration scripts, and the console's Jinja2 templates. Neither is a
module, so neither is found by the import machinery, and both must be listed in
``packaging/tessera-engine.spec`` as ``datas``.

**PyInstaller unpacks that data under ``sys._MEIPASS``, not beside the source.** Resolving
relative to ``__file__`` therefore finds everything in development and nothing in a
shipped build — code that works perfectly until someone downloads the `.dmg`. That is the
failure mode `packaging/smoke-test.sh` exists to catch, and this module exists so there is
one place to get it right.
"""

from __future__ import annotations

import sys
from pathlib import Path


def bundled(*parts: str) -> Path:
    """A directory shipped as data, wherever it ended up.

    Looks under the PyInstaller bundle first and falls back to the source tree, so the
    same call works frozen and unfrozen.
    """
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen is not None:
        candidate = Path(frozen).joinpath(*parts)
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent.joinpath(*parts)


def migrations_directory() -> Path:
    """Where Alembic's migration scripts live, frozen or not."""
    return bundled("repository", "migrations")


def templates_directory() -> Path:
    """Where the console's Jinja2 templates live, frozen or not."""
    return bundled("templates")
