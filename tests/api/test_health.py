"""Health and metadata — the routes the client depends on before anything else works."""

from __future__ import annotations

from typing import ClassVar

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


class TestTheNativeApplicationHasParity:
    """3.4's exit test, as a guard rather than a memory.

    P5 sets it: *"Feature parity with the console for data entry."* The console's own
    navigation is the list of what that means, and it is enumerable — which is what makes
    the exit test checkable instead of arguable.

    Running it by hand at the end of 3.4 found three sections the console had offered since
    2.5 and the application had never had a screen for: institutions, teaching weeks and
    terms. Everything else had been built; those three were simply never noticed, because
    the project-creation sheet makes one of each and nothing afterwards asks for another.
    A second semester could be created in a browser and nowhere else.

    So the comparison lives here. A section added to the console now fails until the
    application answers it, or until the deferral is written down with the phase that owns
    it — which is a decision somebody makes, not a silence.
    """

    #: Sections that deliberately have no data-entry screen yet, and what owns them.
    DEFERRED: ClassVar[dict[str, str]] = {
        "constraints": "3.4b — sliders and rules, not CRUD (plan 3.4 D6)",
        "imports": "3.5 — the import UI",
    }

    def test_every_console_section_has_a_native_screen(self) -> None:
        import re
        from pathlib import Path

        from tessera.api.console.base import SECTIONS

        destination = (
            Path(__file__).resolve().parents[2] / "client/Sources/Tessera/Project/Destination.swift"
        )
        source = destination.read_text()
        body = source[source.index("enum Destination") : source.index("var id:")]
        cases = set(re.findall(r"^\s*case (\w+)$", body, re.MULTILINE))
        assert cases, "found no destinations — the scan is looking at the wrong thing"

        # The console's slug and the Swift case are the same word except where the noun
        # differs; map only the genuine renames, so a missing screen cannot hide behind one.
        renamed = {"student-groups": "groups", "time-grids": "grids"}

        missing = []
        for section in SECTIONS:
            if section.slug in self.DEFERRED:
                continue
            if renamed.get(section.slug, section.slug) not in cases:
                missing.append(section.slug)

        assert not missing, (
            f"the console offers {missing} and the application has no screen for them — "
            "either build it, or add it to DEFERRED with the phase that owns it"
        )

    def test_the_deferred_list_does_not_rot(self) -> None:
        """A deferral that has quietly been built is a note nobody will delete."""
        import re
        from pathlib import Path

        destination = (
            Path(__file__).resolve().parents[2] / "client/Sources/Tessera/Project/Destination.swift"
        )
        source = destination.read_text()
        body = source[source.index("enum Destination") : source.index("var id:")]
        cases = set(re.findall(r"^\s*case (\w+)$", body, re.MULTILINE))

        # `constraints` has a destination and no data-entry screen behind it yet, which is
        # exactly what 3.4b is for — so presence in the enum is not what settles this.
        built = {slug for slug in self.DEFERRED if slug in cases and slug != "constraints"}
        assert not built, f"{built} is listed as deferred and has a destination already"
