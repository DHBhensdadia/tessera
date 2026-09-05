"""Shared fixtures.

The database fixtures build the schema with ``create_all`` rather than by running
migrations, because they are testing the models. Migrations get their own test that
exercises the real upgrade path — see ``tests/repository/test_migrations.py``.

**The `project` fixtures below are file-backed, and that is not fussiness.** The shared
`engine` is `create_memory_engine`, which uses `StaticPool` — one connection shared by every
session in the process. A solve runs on its own thread and commits from there, and two
sessions on one connection are one transaction: 4.7 §2.3 measured a worker's commit capturing
a request's uncommitted row and making its rollback a no-op. Nothing would report that as
itself; it would surface as a phantom row in an unrelated assertion.

A file engine is what the product actually opens, with the pool and the isolation the product
gets. It costs a temporary directory per test, and two suites now solve — the API's routes and
the console's pages — so they share one definition.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from tessera.api import create_app
from tessera.repository import (
    create_all,
    create_memory_engine,
    create_project_engine,
    session_factory,
)
from tessera.repository import models as m
from tests.repository.authored import Term, refuted_term, term_with_sessions


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

    `base_url` is loopback because that is the only address the engine serves. It used to be
    httpx's default `testserver`, which meant the whole API suite addressed the application by
    a name no deployment answers to — invisible until 4.8 extended the rebinding guard past
    `/console` and every one of these went 403.
    """
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
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


@pytest.fixture
def project() -> Iterator[Engine]:
    """A project on disk, opened the way the engine opens one."""
    with TemporaryDirectory() as directory:
        engine = create_project_engine(Path(directory) / "test.tessera")
        create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def project_db(project: Engine) -> Iterator[DbSession]:
    session = session_factory(project)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def term_without_sessions(project_db: DbSession, campus: tuple[m.Institution, m.TimeGrid]) -> int:
    """A term somebody has just created and put nothing in — the state of every term on the
    first day, and the one no fixture in this project built until #307 was found by hand."""
    institution, grid = campus
    row = m.Term(
        institution_id=institution.id,
        time_grid_id=grid.id,
        academic_year="2026-27",
        name="Empty",
    )
    project_db.add(row)
    project_db.commit()
    return int(row.id or 0)


@pytest.fixture
def small_week(project_db: DbSession, campus: tuple[m.Institution, m.TimeGrid]) -> m.TimeGrid:
    """Two days of two hours. Small enough that a handful of sessions cannot fit in it."""
    institution, _ = campus
    grid = m.TimeGrid(
        institution_id=institution.id,
        name="Tiny",
        days=2,
        slots_per_day=2,
        slot_minutes=60,
        day_start_minute=9 * 60,
    )
    project_db.add(grid)
    project_db.commit()
    return grid


@pytest.fixture
def refuted(
    project_db: DbSession, campus: tuple[m.Institution, m.TimeGrid], small_week: m.TimeGrid
) -> Term:
    """A term arithmetic refutes: five one-hour sessions into a four-hour week."""
    institution, _ = campus
    return refuted_term(project_db, institution, small_week)


@pytest.fixture
def campus(project_db: DbSession) -> tuple[m.Institution, m.TimeGrid]:
    """One institution and one teaching week, for the terms below to hang off."""
    institution = m.Institution(name="Sardar Patel University")
    project_db.add(institution)
    project_db.commit()
    grid = m.TimeGrid(
        institution_id=institution.id,
        name="Standard",
        days=5,
        slots_per_day=8,
        slot_minutes=60,
        day_start_minute=9 * 60,
    )
    project_db.add(grid)
    project_db.commit()
    return institution, grid


@pytest.fixture
def solvable(project_db: DbSession, campus: tuple[m.Institution, m.TimeGrid]) -> Term:
    """A small term that solves in well under a second."""
    return term_with_sessions(project_db, *campus)


@pytest.fixture
def another_term(
    project_db: DbSession, campus: tuple[m.Institution, m.TimeGrid], solvable: Term
) -> Term:
    """A second term in the same project, for the guards that are about crossing between them."""
    return term_with_sessions(project_db, *campus, label="Spring")
