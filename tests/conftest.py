"""Shared fixtures.

The database fixtures build the schema with ``create_all`` rather than by running
migrations, because they are testing the models. Migrations get their own test that
exercises the real upgrade path — see ``tests/repository/test_migrations.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from tessera.api import create_app
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


@pytest.fixture
def app(engine: Engine) -> FastAPI:
    return create_app(engine=engine, configure_logs=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A client with the lifespan actually run, so app.state.project exists.

    Instantiating TestClient without the context manager skips startup, which would
    leave every request failing on a missing project rather than on what is being
    tested.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unimplemented_route(client: TestClient) -> str:
    """A route that still answers 501, discovered rather than named.

    Tests needing *an* unimplemented endpoint kept hardcoding whichever one was handy,
    so every phase that implemented something broke unrelated tests — three in 2.1, two
    more in 2.2. Discovery makes them outlive the stubs.

    Widened in 2.4 part 2, which implemented the last two parameterless stubs — the
    fixture then found nothing and said so, which is the failure mode it was built to
    have. Routes with path parameters are now probed too, with an id substituted in: a
    stub raises before it looks anything up, so the id never needs to exist.
    """
    spec: dict[str, Any] = client.get("/openapi.json").json()
    candidates = sorted(spec["paths"], key=lambda p: ("{" in str(p), str(p)))

    for path in candidates:
        route = str(path)
        if "get" not in spec["paths"][path]:
            continue
        probe = re.sub(r"\{[^}]+\}", "1", route)
        if client.get(probe).status_code == 501:
            return probe
    raise AssertionError("no unimplemented GET route remains; these tests need updating")
