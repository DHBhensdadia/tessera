"""Engine and session construction.

A Tessera project is a single SQLite file, so the connection details live here rather
than in configuration: there is nothing for a user to configure. The same models run on
PostgreSQL for server mode by passing a different URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from tessera.repository.models import Base


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    """Settings SQLite does not apply by default but that this application needs.

    ``foreign_keys`` is off in SQLite unless asked for, which would silently allow
    orphaned rows — a cascade delete that quietly does nothing is worse than one that
    fails. ``WAL`` lets a read proceed during a write, which matters once solving runs
    in the background while the interface is still being used.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_project_engine(path: Path | str, *, echo: bool = False) -> Engine:
    """Open (or create) a project file."""
    engine = create_engine(f"sqlite:///{path}", echo=echo, future=True)
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def create_memory_engine(*, echo: bool = False) -> Engine:
    """An in-memory project, for tests.

    ``StaticPool`` keeps every connection pointed at the same database; without it each
    connection would get its own empty one and nothing would persist between calls.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def create_all(engine: Engine) -> None:
    """Create the schema directly, bypassing migrations.

    For tests and throwaway databases only. A real project file is built and upgraded by
    Alembic, so that an existing file survives a schema change instead of being
    recreated.
    """
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """A transaction that commits on success and rolls back on failure."""
    factory = session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
