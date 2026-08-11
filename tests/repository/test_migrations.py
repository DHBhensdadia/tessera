"""Migrations.

A migration that only ever runs forwards on a fresh database is not known to work. The
tests here run it against a real file, roll it back, and run it again, because that is
what happens on a user's existing project when they update the application.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from tessera.repository.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'project.tessera'}"


def table_names(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_the_whole_schema(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
    created = table_names(database_url)

    expected = set(Base.metadata.tables)
    assert expected <= created, f"missing: {sorted(expected - created)}"
    assert "alembic_version" in created


def test_downgrade_removes_everything_it_created(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    remaining = table_names(database_url) - {"alembic_version"}
    assert remaining == set(), f"downgrade left {sorted(remaining)} behind"


def test_the_cycle_can_be_repeated(database_url: str) -> None:
    """Regression: the version stamp must be committed.

    SQLite reports non-transactional DDL, so Alembic opens no transaction of its own.
    The CREATE TABLEs autocommit but the alembic_version INSERT does not, and without an
    explicit commit the schema exists while the database still claims to be at base —
    which makes the next downgrade a no-op and the next upgrade fail on tables that
    already exist. Caught by this exact sequence.
    """
    config = alembic_config(database_url)
    for _ in range(2):
        command.upgrade(config, "head")
        assert len(table_names(database_url)) > 1
        command.downgrade(config, "base")
        assert table_names(database_url) - {"alembic_version"} == set()


def test_version_is_recorded_after_upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() is not None
    finally:
        engine.dispose()


def test_models_and_migrations_have_not_drifted(database_url: str) -> None:
    """The models must be exactly what the migrations build.

    Changing a model and forgetting the migration is the easiest mistake in this layer
    to make and the hardest to notice: everything passes locally, because the test
    database was built from the models rather than from the migrations.
    """
    command.upgrade(alembic_config(database_url), "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "target_metadata": Base.metadata}
            )
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert differences == [], (
        "models and migrations disagree — run: uv run alembic revision --autogenerate\n"
        f"{differences}"
    )
