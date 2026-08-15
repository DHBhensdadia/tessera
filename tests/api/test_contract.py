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


def parameters(spec: dict[str, Any]) -> dict[str, set[str]]:
    """Every operation mapped to the names of the parameters it accepts."""
    found: dict[str, set[str]] = {}
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method in METHODS:
                found[f"{method.upper()} {path}"] = {
                    str(p["name"]) for p in operation.get("parameters", [])
                }
    return found


def test_no_parameter_has_been_removed(app: FastAPI, snapshot: dict[str, Any]) -> None:
    """Routes can keep their path and method and still break a client.

    Added in 2.2 after noticing the surface test compared only paths, methods and
    operation ids — so dropping a required query parameter, which is unambiguously
    breaking, passed silently. The guard had been trusted since 1.4 and covered less
    than it appeared to.

    Only *removals* fail. Adding a parameter is additive and safe, and that is how the
    selective unavailability delete arrived.
    """
    live = parameters(app.openapi())
    committed = parameters(snapshot)

    lost = {
        route: sorted(names - live.get(route, set()))
        for route, names in committed.items()
        if route in live and names - live[route]
    }
    assert not lost, (
        f"parameters removed from the contract: {lost}\n"
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


def fields(spec: dict[str, Any]) -> dict[str, tuple[set[str], set[str]]]:
    """Every model mapped to the fields it has, and the subset a caller must send."""
    found: dict[str, tuple[set[str], set[str]]] = {}
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        found[name] = (set(schema.get("properties", {})), set(schema.get("required", [])))
    return found


def test_no_field_has_been_removed_or_newly_required(
    app: FastAPI, snapshot: dict[str, Any]
) -> None:
    """The third time this guard has been found to cover less than it appeared to.

    1.4 compared paths, methods and operation ids. 2.2 found that a removed query
    parameter passed silently and added `test_no_parameter_has_been_removed` (#46). 2.8
    found the same one level further down: the model test compares schema *names*, so
    deleting a field from a response model — unambiguously breaking for every client —
    passed. Caught by deleting `ConstraintRead.target_ids` and watching the suite stay
    green.

    Removals fail, and so does making an optional request field required, because both
    break a caller that was written against the old shape. Additions pass: that is how
    `targets` was added here without breaking the 1.4 surface.
    """
    live = fields(app.openapi())
    committed = fields(snapshot)

    lost = {
        name: sorted(properties - live[name][0])
        for name, (properties, _) in committed.items()
        if name in live and properties - live[name][0]
    }
    tightened = {
        name: sorted(live[name][1] - required)
        for name, (_, required) in committed.items()
        if name in live and live[name][1] - required
    }
    assert not (lost or tightened), (
        f"fields removed from the contract: {lost}\n"
        f"fields newly required: {tightened}\n"
        "If intended, regenerate the snapshot: uv run tessera-openapi"
    )


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


def test_stubs_answer_501_and_name_their_phase(
    client: TestClient, unimplemented_route: str
) -> None:
    """Declared-but-unimplemented routes say so, and say when.

    404 would claim the endpoint does not exist, when the entire point of this phase is
    that it does and its shape is already agreed.
    """
    response = client.get(unimplemented_route)
    assert response.status_code == 501

    problem = response.json()
    assert problem["status"] == 501
    assert problem["type"].endswith("/not-implemented")
    assert "phase" in problem["detail"]
    assert response.headers["content-type"].startswith("application/problem+json")
