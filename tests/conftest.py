"""Shared fixtures.

The database fixtures build the schema with ``create_all`` rather than by running
migrations, because they are testing the models. Migrations get their own test that
exercises the real upgrade path — see ``tests/repository/test_migrations.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from tessera.repository import create_all, create_memory_engine, session_factory
from tessera.repository import models as m


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_memory_engine()
    create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[DbSession]:
    session = session_factory(engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def institution(db: DbSession) -> m.Institution:
    row = m.Institution(name="Sardar Patel University")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def grid(db: DbSession, institution: m.Institution) -> m.TimeGrid:
    """A plausible teaching week: Mon-Sat, 09:00-17:00, half-hour slots, lunch at 13:00."""
    row = m.TimeGrid(
        institution_id=institution.id,
        name="Standard",
        days=6,
        slots_per_day=16,
        slot_minutes=30,
        day_start_minute=9 * 60,
    )
    row.breaks = [m.TimeGridBreak(slot_of_day=8), m.TimeGridBreak(slot_of_day=9)]
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def term(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> m.Term:
    row = m.Term(
        institution_id=institution.id,
        time_grid_id=grid.id,
        academic_year="2026-27",
        name="Autumn",
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def features(db: DbSession, institution: m.Institution) -> dict[str, m.Feature]:
    rows = {
        name: m.Feature(institution_id=institution.id, name=name)
        for name in ("projector", "computers", "smartboard")
    }
    db.add_all(rows.values())
    db.commit()
    return rows
