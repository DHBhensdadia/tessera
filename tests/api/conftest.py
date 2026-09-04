"""Fixtures for the routes that start a real solve.

**These use a file-backed project, and that is not fussiness.** The shared `engine` fixture is
`create_memory_engine`, which uses `StaticPool` — one connection shared by every session in the
process. A solve runs on its own thread and commits from there, and two sessions on one
connection are one transaction: 4.7 §2.3 measured a worker's commit capturing a request's
uncommitted row and making its rollback a no-op. Nothing would report that as itself; it would
surface as a phantom row in an unrelated assertion.

A file engine is what the product actually opens, with the pool and the isolation the product
gets. It costs a temporary directory per test.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from tessera.api import create_app
from tessera.repository import create_all, create_project_engine, session_factory
from tessera.repository import models as m
from tests.repository.authored import Term, term_with_sessions


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


@pytest.fixture
def solving_client(project: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine=project, configure_logs=False)) as client:
        yield client


def settled(client: TestClient, job_id: str, timeout: float = 60.0) -> dict[str, object]:
    """Poll a job until it stops moving, and fail loudly rather than hanging for ever."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        status = client.get(f"/api/v1/solve/{job_id}").json()
        if status["phase"] in {"done", "infeasible", "cancelled", "failed"}:
            return dict(status)
        time.sleep(0.05)
    raise AssertionError(
        f"job {job_id} never settled: {client.get(f'/api/v1/solve/{job_id}').json()}"
    )
