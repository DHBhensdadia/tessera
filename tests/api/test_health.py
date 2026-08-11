"""Health and metadata — the routes the client depends on before anything else works."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import tessera


def test_health_reports_a_reachable_project(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert body["version"] == tessera.__version__
    assert body["pid"] > 0


def test_health_reports_degraded_rather_than_failing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A health check that raises tells the client nothing.

    The engine polls this after spawning; if the database is unreachable it needs a
    diagnosis, not a stack trace or a hang. Patched rather than genuinely broken, so
    the engine survives to be torn down.
    """

    def refuse(*_: object, **__: object) -> None:
        raise OSError("database file is locked")

    monkeypatch.setattr(Engine, "connect", refuse)

    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "degraded"
    assert "OSError" in body["database"]


def test_meta_reports_the_api_version(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert body["api_version"] == "v1"
    assert body["version"] == tessera.__version__


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    """Echoed back so a user reporting a problem can quote something that appears in
    the engine log."""
    response = client.get("/health")
    assert response.headers["x-request-id"]


def test_a_supplied_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
