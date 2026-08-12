"""Every failure uses one envelope.

A client that has to decode two different error shapes will eventually mishandle one,
so framework errors are routed through the same handler as the application's own.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_a_missing_route_is_a_problem_document(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404

    body = response.json()
    assert body["status"] == 404
    assert body["instance"] == "/api/v1/does-not-exist"
    assert response.headers["content-type"].startswith("application/problem+json")


def test_validation_failures_locate_each_bad_field(client: TestClient) -> None:
    """The reason RFC 9457 was chosen over FastAPI's default.

    A bare `{"detail": "..."}` cannot say *which* fields were wrong, which is exactly
    what an import of two hundred rows needs to report.
    """
    response = client.post(
        "/api/v1/timetables/1/validate-viewport",
        json={"session_id": 1, "room_ids": [], "period_from": -5, "period_to": 0},
    )
    assert response.status_code == 422

    body = response.json()
    assert body["type"].endswith("/validation-failed")
    assert len(body["errors"]) >= 2
    assert all("pointer" in error and "message" in error for error in body["errors"])

    pointers = {error["pointer"] for error in body["errors"]}
    assert any("room_ids" in pointer for pointer in pointers)
    assert any("period_from" in pointer for pointer in pointers)


def test_unimplemented_routes_name_the_phase(client: TestClient) -> None:
    response = client.post(
        "/api/v1/timetables/1/validate-move",
        json={"session_id": 1, "start_slot": 0, "room_id": 1},
    )
    assert response.status_code == 501
    assert "5.5" in response.json()["detail"]


def test_problem_documents_always_carry_the_same_keys(
    client: TestClient, unimplemented_route: str
) -> None:
    """One shape to decode, whatever went wrong."""
    required = {"type", "title", "status", "detail", "instance", "errors"}

    for method, path, payload in [
        ("get", "/api/v1/nope", None),
        ("get", unimplemented_route, None),
        ("post", "/api/v1/timetables/1/validate-move", {"session_id": "not-an-int"}),
    ]:
        response = getattr(client, method)(path, **({"json": payload} if payload else {}))
        assert required <= set(response.json()), f"{method} {path} returned a different shape"
