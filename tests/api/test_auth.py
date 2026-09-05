"""The engine token.

Covered in-process as well as through `tests/test_engine.py`, because those spawn a
subprocess that coverage cannot see into — a security control reporting as unmeasured is
a security control nobody notices going missing.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api import create_app

TOKEN = "test-token-that-is-long-enough-to-be-realistic"


@pytest.fixture
def guarded(engine: Engine) -> Iterator[TestClient]:
    with TestClient(
        create_app(engine=engine, token=TOKEN, configure_logs=False), base_url="http://127.0.0.1"
    ) as client:
        yield client


def test_a_correct_token_is_accepted(guarded: TestClient) -> None:
    response = guarded.get("/health", headers={"x-tessera-token": TOKEN})
    assert response.status_code == 200


def test_a_missing_token_is_refused(guarded: TestClient) -> None:
    response = guarded.get("/health")
    assert response.status_code == 401
    assert response.json()["type"].endswith("/unauthenticated")


def test_a_wrong_token_is_refused(guarded: TestClient) -> None:
    assert guarded.get("/health", headers={"x-tessera-token": "wrong"}).status_code == 401


def test_a_prefix_of_the_token_is_refused(guarded: TestClient) -> None:
    """Comparison is constant-time, so a partially correct token is worth no more than
    a wrong one."""
    assert guarded.get("/health", headers={"x-tessera-token": TOKEN[:-1]}).status_code == 401


def test_the_documentation_stays_open(guarded: TestClient) -> None:
    """The API shape is public knowledge; a project's data is not."""
    assert guarded.get("/openapi.json").status_code == 200
    assert guarded.get("/docs").status_code == 200


def test_data_endpoints_are_guarded(guarded: TestClient) -> None:
    """A stub answering 501 must still refuse an unauthenticated caller — otherwise the
    guard would appear only once handlers exist."""
    # An implemented route and an unimplemented one: both must refuse an
    # unauthenticated caller, or the guard would appear only once handlers exist.
    assert guarded.get("/api/v1/rooms").status_code == 401
    assert guarded.get("/api/v1/instructors").status_code == 401
    assert guarded.get("/api/v1/rooms", headers={"x-tessera-token": TOKEN}).status_code == 200
