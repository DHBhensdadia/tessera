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
from sqlalchemy import create_engine, inspect, text

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


# ---------------------------------------------------------------------------
# 2.7b: the migration that reshapes tables, run against rows
# ---------------------------------------------------------------------------

BEFORE_2_7B = "79c594049896"

# One row in each table the 2.7b revision rebuilds, plus the rows they depend on. Written
# as SQL rather than through the models on purpose: the models describe the schema *after*
# the migration, so using them here would build the new shape and prove nothing.
SEED = [
    "INSERT INTO institution (id, name) VALUES (1, 'Test University')",
    "INSERT INTO time_grid (id, institution_id, name, days, slots_per_day, slot_minutes,"
    " day_start_minute) VALUES (1, 1, 'Standard', 5, 8, 60, 540)",
    "INSERT INTO term (id, institution_id, time_grid_id, academic_year, name, starts_on,"
    " ends_on)"
    " VALUES (1, 1, 1, '2026-27', 'Autumn', '2026-07-01', '2026-11-30')",
    "INSERT INTO room (id, name, capacity) VALUES (1, 'Lab 1', 70)",
    "INSERT INTO feature (id, institution_id, name) VALUES (1, 1, 'computers')",
    "INSERT INTO room_feature (room_id, feature_id) VALUES (1, 1)",
    "INSERT INTO course (id, code, name, credits) VALUES (1, 'CS301', 'Operating Systems', 4)",
    "INSERT INTO offering (id, term_id, course_id) VALUES (1, 1, 1)",
    "INSERT INTO session_template (id, offering_id, kind, duration_slots, per_week,"
    " split_per_attendee) VALUES (1, 1, 'lab', 2, 1, 0)",
    "INSERT INTO template_feature (template_id, feature_id) VALUES (1, 1)",
    "INSERT INTO session (id, offering_id, term_id, template_id, kind, duration_slots,"
    " occurrence) VALUES (1, 1, 1, 1, 'lab', 2, 0)",
    "INSERT INTO session_feature (session_id, feature_id) VALUES (1, 1)",
    'INSERT INTO "constraint" (id, term_id, kind, is_hard, weight, params, enabled)'
    " VALUES (1, 1, 'min_gap', 1, 1, '{\"slots\": 4}', 1)",
    "INSERT INTO constraint_target (constraint_id, session_id) VALUES (1, 1)",
]


def rows(database_url: str, query: str) -> list[tuple[object, ...]]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return [tuple(row) for row in connection.execute(text(query))]
    finally:
        engine.dispose()


def seeded_at_previous_revision(database_url: str) -> Config:
    """A database at the revision before 2.7b, with data in every table it reshapes."""
    config = alembic_config(database_url)
    command.upgrade(config, BEFORE_2_7B)

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            for statement in SEED:
                connection.execute(text(statement))
    finally:
        engine.dispose()
    return config


def test_an_existing_constraint_target_becomes_a_session_target(database_url: str) -> None:
    """The whole reason this revision is hand-written.

    Autogenerate produced a version that dropped `session_id` and added `target_id`
    without moving anything between them. It passed every test above, because they all
    run against an empty database — and it would have silently emptied the constraint
    targets of every project already in existence.
    """
    config = seeded_at_previous_revision(database_url)
    command.upgrade(config, "head")

    assert rows(database_url, "SELECT target_kind, target_id FROM constraint_target") == [
        ("session", 1)
    ]


def test_rows_survive_the_tables_being_rebuilt(database_url: str) -> None:
    config = seeded_at_previous_revision(database_url)
    command.upgrade(config, "head")

    for table, owner in [
        ("room_feature", "room_id"),
        ("template_feature", "template_id"),
        ("session_feature", "session_id"),
    ]:
        assert rows(database_url, f"SELECT {owner}, feature_id, quantity FROM {table}") == [
            (1, 1, 0)
        ], f"{table} lost its row, or its new count did not default to zero"


def test_existing_rows_keep_the_meaning_they_had(database_url: str) -> None:
    """Every column added by this revision has to be a no-op for data already stored."""
    config = seeded_at_previous_revision(database_url)
    command.upgrade(config, "head")

    assert rows(database_url, "SELECT turnaround_slots FROM room") == [(0,)]
    assert rows(database_url, "SELECT week_pattern FROM session") == [("every_week",)]
    assert rows(database_url, "SELECT week_pattern FROM session_template") == [("every_week",)]


def test_the_revision_can_be_rolled_back_with_rows_present(database_url: str) -> None:
    """A migration is not reversible until it has been reversed over real rows.

    Going back is what happens when a user opens a project in an older build, so the old
    shape has to come back holding the data it held before.
    """
    config = seeded_at_previous_revision(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, BEFORE_2_7B)

    assert rows(database_url, "SELECT constraint_id, session_id FROM constraint_target") == [(1, 1)]
    assert rows(database_url, "SELECT room_id, feature_id FROM room_feature") == [(1, 1)]
    assert "turnaround_slots" not in {
        column["name"] for column in inspect(create_engine(database_url)).get_columns("room")
    }

    command.upgrade(config, "head")
    assert rows(database_url, "SELECT target_kind, target_id FROM constraint_target") == [
        ("session", 1)
    ]


def test_a_target_that_is_not_a_session_is_dropped_rather_than_mangled(
    database_url: str,
) -> None:
    """Downgrading cannot represent an instructor target, so it must lose it cleanly.

    Keeping the id and letting it land in `session_id` would point the constraint at
    whichever session happened to share that number — a wrong timetable rather than a
    missing rule.
    """
    config = seeded_at_previous_revision(database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO instructor (id, name, email) VALUES (7, 'Prof. Shah', '')")
            )
            connection.execute(
                text(
                    "INSERT INTO constraint_target (constraint_id, target_kind, target_id)"
                    " VALUES (1, 'instructor', 7)"
                )
            )
    finally:
        engine.dispose()

    command.downgrade(config, BEFORE_2_7B)
    assert rows(database_url, "SELECT constraint_id, session_id FROM constraint_target") == [(1, 1)]


def test_a_dangling_reference_fails_the_migration(database_url: str) -> None:
    """The other half of turning enforcement off while tables move.

    Deferring the check is only safe if the deferred check is real. This puts a row in
    pointing at a feature that does not exist — the exact thing enforcement-during-DDL
    was there to stop — and the upgrade has to refuse rather than quietly finish.
    """
    config = seeded_at_previous_revision(database_url)

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO room_feature (room_id, feature_id) VALUES (1, 404)")
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="dangling"):
        command.upgrade(config, "head")
