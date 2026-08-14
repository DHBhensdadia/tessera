"""Alembic environment.

The database URL is supplied by the caller rather than read from ``alembic.ini``,
because a Tessera project is a file the user chose the location of — there is no single
configured database to point at. The application passes one in through
``config.attributes``; the command line falls back to ``TESSERA_DATABASE_URL``.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from tessera.repository.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    supplied = config.attributes.get("database_url")
    if supplied:
        return str(supplied)
    from_env = os.environ.get("TESSERA_DATABASE_URL")
    if from_env:
        return from_env
    configured = config.get_main_option("sqlalchemy.url", "")
    if configured:
        return configured
    raise RuntimeError(
        "no database to migrate: pass database_url in config.attributes, or set "
        "TESSERA_DATABASE_URL"
    )


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things. Batch mode rebuilds the table around the
        # change instead, which is what makes a schema migration possible at all on a
        # user's existing project file rather than only on a fresh one.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Emit SQL without connecting, for review."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)

    if connectable is not None:
        _configure(connectable)
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
        # Required, and easy to miss. SQLite reports non-transactional DDL, so Alembic
        # does not open a transaction of its own: the CREATE TABLEs autocommit, but the
        # INSERT that stamps alembic_version does not. Without this the schema is built
        # and the database still claims to be at base — so the next downgrade does
        # nothing and the next upgrade fails on tables that already exist.
        connection.commit()
        if sqlite:
            _check_foreign_keys(connection)


def _check_foreign_keys(connection: Connection) -> None:
    """Verify integrity *after* migrating, having not enforced it during.

    Enforcing foreign keys while migrating looks like the careful choice and is the
    opposite of one. SQLite has no ALTER for a primary key, so any real change means
    rebuilding the table — and with ``foreign_keys=ON`` a ``DROP TABLE`` performs an
    implicit ``DELETE FROM`` first, which fires ``ON DELETE CASCADE`` into every child.

    That is not hypothetical. Adding one nullable column to ``room`` silently emptied
    ``room_feature``: batch mode rebuilt ``room``, the drop cascaded, and the migration
    reported success having deleted every room's equipment. It is caught by
    ``test_rows_survive_the_tables_being_rebuilt``.

    So enforcement is off while tables move, and the whole database is checked once at
    the end — which is SQLite's own documented procedure, and a stronger guarantee: it
    inspects every row that exists rather than only the ones a statement touched.
    """
    dangling = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if dangling:
        broken = sorted({(row[0], row[2]) for row in dangling})
        raise RuntimeError(
            "migration left dangling references: "
            + ", ".join(f"{table} → {parent}" for table, parent in broken)
        )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
