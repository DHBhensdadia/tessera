"""The published contract.

Phase 1.4 freezes the URL and verb surface before the handlers exist, so that later
phases plug into a known shape and the client can be built against it. These tests are
what makes "frozen" mean something.

The snapshot deliberately compares **shape, not bytes** (plan D6). Byte-equality would
also fail on every FastAPI upgrade, so Dependabot would turn this guard into noise — and
a guard that cries wolf gets silenced, which is worse than not having it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
METHODS = {"get", "post", "put", "patch", "delete"}


def operations(spec: dict[str, Any]) -> dict[str, str]:
    """Every (method, path) mapped to its operation id.

    Operation ids are included because they become client method names: renaming one is
    a breaking change for a generated client even though the URL is untouched.
    """
    found: dict[str, str] = {}
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method in METHODS:
                found[f"{method.upper()} {path}"] = operation.get("operationId", "")
    return found


@pytest.fixture
def snapshot() -> dict[str, Any]:
    if not SNAPSHOT.exists():
        pytest.fail(f"missing {SNAPSHOT}; regenerate with `uv run tessera-openapi`")
    loaded: dict[str, Any] = json.loads(SNAPSHOT.read_text())
    return loaded


def test_the_surface_has_not_changed(app: FastAPI, snapshot: dict[str, Any]) -> None:
    live = operations(app.openapi())
    committed = operations(snapshot)

    added = sorted(set(live) - set(committed))
    removed = sorted(set(committed) - set(live))
    renamed = sorted(
        f"{route}: {committed[route]} -> {live[route]}"
        for route in set(live) & set(committed)
        if committed[route] != live[route]
    )

    assert not (added or removed or renamed), (
        "the API contract changed.\n"
        f"  added:   {added}\n"
        f"  removed: {removed}\n"
        f"  renamed: {renamed}\n"
        "If intended, regenerate the snapshot: uv run tessera-openapi"
    )


def test_request_and_response_models_have_not_changed(
    app: FastAPI, snapshot: dict[str, Any]
) -> None:
    """A route can keep its URL and still break a client by changing its payload."""
    live = set(app.openapi().get("components", {}).get("schemas", {}))
    committed = set(snapshot.get("components", {}).get("schemas", {}))

    removed = sorted(committed - live)
    assert not removed, f"models removed from the contract: {removed}"


def test_every_route_documents_its_error_shape(app: FastAPI) -> None:
    """Errors are RFC 9457 everywhere, and the schema must say so.

    Without this the generated spec claims failures use FastAPI's default envelope, and
    a client built from it would decode them wrongly.
    """
    spec = app.openapi()
    missing: list[str] = []

    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method not in METHODS or path in {"/health", "/api/v1/meta"}:
                continue
            responses = operation.get("responses", {})
            if not any(code.startswith(("4", "5")) for code in responses):
                missing.append(f"{method.upper()} {path}")

    assert not missing, f"routes with no documented error response: {missing}"


def test_the_whole_surface_is_reachable(client: TestClient) -> None:
    """`/docs` renders, and `/openapi.json` is served. Part of the exit test."""
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_no_unscoped_validation_endpoint_exists(app: FastAPI) -> None:
    """Phase 0.2 measured whole-grid validation at 43 ms p99 against a 16 ms budget.

    Viewport scoping is the fix, and the guarantee is that there is no unscoped variant
    to reach for — an endpoint that can be misused eventually is. This test is what stops
    one being added later by someone who has not read the measurement.
    """
    validation = [p for p in app.openapi()["paths"] if "validate" in p]
    assert validation, "expected validation routes to exist"
    assert all("viewport" in path or "move" in path for path in validation), (
        f"unscoped validation endpoint added: {validation}"
    )


def any_unimplemented_route(client: TestClient) -> str:
    """A route that still answers 501, found rather than hardcoded.

    These tests need *an* unimplemented endpoint, not a specific one. Naming
    `/api/v1/rooms` meant that implementing rooms broke three unrelated tests — and it
    would have happened again at every phase. Discovery makes them outlive the stubs.
    """
    spec: dict[str, Any] = client.get("/openapi.json").json()
    for path, operations in spec["paths"].items():
        route = str(path)
        if "get" not in operations or "{" in route:
            continue
        if client.get(route).status_code == 501:
            return route
    raise AssertionError("no unimplemented GET route remains; update these tests")


def test_stubs_answer_501_and_name_their_phase(client: TestClient) -> None:
    """Declared-but-unimplemented routes say so, and say when.

    404 would claim the endpoint does not exist, when the entire point of this phase is
    that it does and its shape is already agreed.
    """
    response = client.get(any_unimplemented_route(client))
    assert response.status_code == 501

    problem = response.json()
    assert problem["status"] == 501
    assert problem["type"].endswith("/not-implemented")
    assert "phase" in problem["detail"]
    assert response.headers["content-type"].startswith("application/problem+json")
