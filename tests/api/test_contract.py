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

import tessera

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


def response_models(spec: dict[str, Any]) -> dict[str, str]:
    """Every operation mapped to the schema its success response references."""
    found: dict[str, str] = {}
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method not in METHODS:
                continue
            for code, response in operation.get("responses", {}).items():
                if not code.startswith("2"):
                    continue
                schema = response.get("content", {}).get("application/json", {}).get("schema", {})
                if ref := schema.get("$ref"):
                    found[f"{method.upper()} {path}"] = str(ref).rsplit("/", 1)[-1]
    return found


def test_no_route_has_changed_what_it_answers_with(app: FastAPI, snapshot: dict[str, Any]) -> None:
    """The third thing this guard turned out not to cover.

    1.4 compared paths, methods and operation ids; 2.2 added parameters (#46); 2.8 added
    the fields inside a model (#83). A route can still keep its URL, its parameters and
    every model in the document, and answer with a *different* model — which is breaking,
    and passed silently. Found in 2.9 when `POST /terms/{id}/duplicate` was changed from
    `TermRead` to `TermDuplicated` and the guard said nothing.

    A change here is not always breaking — `TermDuplicated` extends `TermRead`, so that
    one was additive — but it is never something to discover afterwards. Regenerating the
    snapshot is the deliberate act that records the intent.
    """
    live = response_models(app.openapi())
    committed = response_models(snapshot)

    changed = sorted(
        f"{route}: {committed[route]} -> {live[route]}"
        for route in set(live) & set(committed)
        if committed[route] != live[route]
    )
    assert not changed, (
        f"routes now answer with a different model: {changed}\n"
        "If intended, regenerate the snapshot: uv run tessera-openapi"
    )


#: Routes with no error of their own to document.
#:
#: Each takes no parameters, reads no project, and describes the *build* rather than a
#: file — so there is no 404 to raise, no body to reject and no row to conflict with. The
#: only failure they can produce is the middleware's 401, which is declared once globally
#: as a security scheme (#133) rather than per route, exactly as it is for every other
#: route in the API.
#:
#: Named with the reason rather than kept as a bare list, because an exemption set that
#: grows by one every time the guard is inconvenient stops being a guard.
NO_ERRORS_OF_THEIR_OWN = {"/health", "/api/v1/meta", "/api/v1/constraint-catalogue"}


def test_every_route_documents_its_error_shape(app: FastAPI) -> None:
    """Errors are RFC 9457 everywhere, and the schema must say so.

    Without this the generated spec claims failures use FastAPI's default envelope, and
    a client built from it would decode them wrongly.
    """
    spec = app.openapi()
    missing: list[str] = []

    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method not in METHODS or path in NO_ERRORS_OF_THEIR_OWN:
                continue
            responses = operation.get("responses", {})
            if not any(code.startswith(("4", "5")) for code in responses):
                missing.append(f"{method.upper()} {path}")

    assert not missing, (
        f"routes with no documented error response: {missing}\n"
        "Add problem_responses(...) to the route, or — only if it genuinely has no error "
        "of its own — to NO_ERRORS_OF_THEIR_OWN with the reason."
    )


def test_the_exemptions_still_exist(app: FastAPI) -> None:
    """A route renamed out from under the exemption list leaves a hole nobody notices.

    The list would keep passing, the renamed route would go undocumented, and the guard
    would report success — which is the failure mode every exemption list has.
    """
    paths = set(app.openapi()["paths"])
    assert paths >= NO_ERRORS_OF_THEIR_OWN, (
        f"exempted routes that no longer exist: {NO_ERRORS_OF_THEIR_OWN - paths}"
    )


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


def test_every_operation_id_is_readable_and_unique(app: FastAPI) -> None:
    """The names a generated client turns into methods.

    FastAPI's default appends the path and the method, which is unique by construction and
    puts the URL inside the name — so a generated client hands every caller a method with
    the route baked into it, and moving a route renames a method at every call site.
    `operation_id` drops the path, which is only safe while the endpoint function names are
    distinct. That is the thing this checks.

    Read from the **generated document** rather than from `app.routes`. The first version
    walked the route objects looking for `APIRoute`, found none — this FastAPI keeps
    `_IncludedRouter` wrappers there — and passed on an empty list. It stayed green with
    the id function replaced by one returning raw `snake_case` names. The document is also
    the honest source: it is what a client generator actually reads.
    """
    ids = [
        operation["operationId"]
        for path in app.openapi()["paths"].values()
        for method, operation in path.items()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(ids) > 50, (
        f"only found {len(ids)} operations, so this check is passing on nothing — "
        "the document is not being read the way this test assumes"
    )

    duplicates = sorted({name for name in ids if ids.count(name) > 1})
    assert not duplicates, (
        "two routes share an operation id, so a generated client would lose one of them:\n"
        f"  {duplicates}\n"
        "Rename one of the endpoint functions — the id is derived from the function name."
    )

    malformed = sorted(name for name in ids if not name[0].islower() or not name.isalnum())
    assert not malformed, f"these are not lowerCamelCase: {malformed[:8]}"


def test_the_snapshot_is_not_stale(snapshot: dict[str, Any]) -> None:
    """The committed document describes the version it was generated from.

    Found by regenerating: the snapshot still said `0.1.0` long after `v0.2.0` shipped,
    because every other check compares *shape* and the version is not shape. A document
    published with a Docker image and a CLI that names the wrong version is wrong in the
    one field a consumer reads first.
    """
    assert snapshot["info"]["version"] == tessera.__version__, (
        f"the snapshot says {snapshot['info']['version']} and the package is "
        f"{tessera.__version__} — regenerate it: uv run tessera-openapi"
    )
