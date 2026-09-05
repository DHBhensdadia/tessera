"""Waiting for a solve, in the one place both suites that start one can reach it.

A function rather than a fixture, and not in a `conftest`: two suites import it — the API's
routes and the console's pages — and a helper reached by importing a conftest is a helper in
the wrong file.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient


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
