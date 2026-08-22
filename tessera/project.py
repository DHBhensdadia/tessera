"""What a `.tessera` project actually is on disk.

Decision #25 settled the document model in Stage 0: a project is **a real file the user
chose the location of**, not a hidden library entry, because timetables are emailed,
reviewed and archived by committees and a file uses habits people already have.

What #25 specified and Stage 1 did not build is that the file is a **package** — a
directory the Finder presents as a single item, holding the database and, in time, the
assets that belong with it: an institution's logo, the spreadsheets an import came from.

```
CSE Timetables.tessera/          <- what the user sees as one file
    project.db                   <- SQLite
    assets/                      <- room for them; created by whatever first needs one
```

A bare `.tessera` file — what `v0.1.0` shipped — is **converted in place** the first time
it is opened. That path exists precisely once in the product's life and it is cheap to
write now; retrofitting it after two shapes are in circulation is not, which is why this
lands before the client in 3.2 is written against whatever a project path means.

Nothing outside this module knows the layout. `--project` still takes one path and still
means "the project"; `resolve` turns it into the database inside.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

#: The database inside the package. A fixed name rather than a search, so a directory
#: with two databases in it is a corrupt project rather than an ambiguous one.
DATABASE_NAME = "project.db"


class NotAProjectError(Exception):
    """The path is a directory, but not one this application wrote."""


class ProjectMissingError(Exception):
    """A project that was supposed to already exist is not there.

    Raised only when the caller says it is *reopening* something. Creating what is
    missing is right for a new project and quietly destructive for a reopen: a stale
    entry in Recent Projects, or a window restored by macOS after the file was moved to
    another disk, would otherwise produce an empty project wearing a familiar name — and
    the person who notices is someone who believes they have lost a semester's work.

    The caller knows the intent and this module cannot infer it, which is why it is a
    parameter rather than a heuristic.
    """


def database_path(path: Path) -> Path:
    """Where the SQLite database lives inside a package."""
    return path / DATABASE_NAME


def resolve(path: Path, *, must_exist: bool = False) -> Path:
    """Turn what the user named into the database to open.

    Handles all four states a path can be in, because every one of them is reachable:
    a package that exists, a bare file from `v0.1.0`, a path that does not exist yet, and
    a directory that is not a project.

    Converting rather than refusing is deliberate. The alternative — telling someone
    their existing project is the wrong shape and asking them to do something about it —
    is a migration prompt for a change they neither asked for nor can act on.

    `must_exist` says the caller is reopening rather than creating. It turns the two
    states that would otherwise be *filled in* — a path that is not there, and an empty
    directory — into refusals. See `ProjectMissingError` for why that distinction is
    worth a parameter.
    """
    if path.is_dir():
        inside = database_path(path)
        if not inside.exists():
            if any(path.iterdir()):
                raise NotAProjectError(
                    f"{path} is a directory but does not contain {DATABASE_NAME}"
                )
            # An empty directory is indistinguishable from a project whose contents were
            # deleted, and treating it as a blank canvas is the same trap by another
            # route: the folder is still called "Autumn 2026" and it still opens.
            if must_exist:
                raise ProjectMissingError(f"{path} is empty — there is no project here")
        return inside

    if path.exists():
        return _convert(path)

    if must_exist:
        raise ProjectMissingError(f"{path} does not exist")

    path.mkdir(parents=True, exist_ok=True)
    return database_path(path)


def _convert(bare: Path) -> Path:
    """Turn a `v0.1.0` bare database into a package, keeping the same path.

    Done through a sibling directory and one rename so that a crash midway leaves either
    the original file or the finished package, never a half-built directory sitting where
    the project used to be.

    WAL sidecars are moved too. Leaving `-wal` behind would discard every committed
    transaction still in it — the database would open, and it would be older than the
    user's last edit, which is worse than failing.
    """
    staging = bare.with_name(bare.name + ".converting")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    for suffix in ("", "-wal", "-shm"):
        sidecar = bare.with_name(bare.name + suffix)
        if sidecar.exists():
            shutil.move(str(sidecar), str(staging / (DATABASE_NAME + suffix)))

    staging.rename(bare)
    return database_path(bare)


def copy_to(source_database: Path, destination: Path) -> Path:
    """Save a copy of an open project, safely, while it is being written to.

    Not `shutil.copy`. With WAL enabled the main file is not the whole database —
    committed pages may still be in `-wal` — so copying the bytes gives a database that
    opens and is quietly out of date, or one torn between two states.

    ``VACUUM INTO`` takes a consistent snapshot under a read lock and compacts it on the
    way out, in one statement. `sqlite3.Connection.backup()` would also be correct; the
    smaller output is the tiebreak, and this is an explicit user action rather than a hot
    path.
    """
    # `mkdir` without `exist_ok` is the refusal: a destination that already exists raises
    # rather than being written into. Deliberately not `exist_ok=True` — "save a copy"
    # onto an existing folder is how somebody loses the thing they were copying *to*.
    destination.mkdir(parents=True)
    target = database_path(destination)

    connection = sqlite3.connect(source_database)
    try:
        # A parameter, not an f-string: the path is user input and this is one of the
        # few places SQLite accepts a filename as a value.
        connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()
    return destination
