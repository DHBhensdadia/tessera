"""Save As, over HTTP — and the two project operations that deliberately do not exist.

The engine serves one project for its lifetime. Opening another is the client's job and
it does it by launching another engine, which is what the 1.5 handshake was designed
around. Saving needs nothing, because SQLite commits. What is left is copying, which the
client cannot do for itself while the database is open.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from tessera import project as project_module
from tessera.api.app import create_app
from tessera.repository.database import create_project_engine


@pytest.fixture
def on_disk(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    """An engine serving a real project package, not an in-memory database.

    Copying is about files, so the usual in-memory fixture would test nothing.
    """
    path = tmp_path / "Live.tessera"
    database = project_module.resolve(path)
    engine = create_project_engine(database)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE note (id INTEGER PRIMARY KEY, body TEXT)"))
        connection.execute(text("INSERT INTO note (body) VALUES ('real work')"))

    app: FastAPI = create_app(engine=engine, project_path=path, configure_logs=False)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, tmp_path
    finally:
        engine.dispose()


class TestSaveAs:
    def test_a_copy_is_written_and_can_be_opened(self, on_disk: tuple[TestClient, Path]) -> None:
        client, tmp_path = on_disk
        destination = tmp_path / "Copy.tessera"

        response = client.post("/api/v1/project/copy", json={"destination": str(destination)})

        assert response.status_code == 201, response.text
        assert response.json()["path"] == str(destination)
        assert project_module.database_path(destination).exists()

    def test_the_copy_holds_what_was_written_while_it_was_open(
        self, on_disk: tuple[TestClient, Path]
    ) -> None:
        """The reason this is an endpoint rather than a file copy in the client."""
        client, tmp_path = on_disk
        destination = tmp_path / "Copy.tessera"
        client.post("/api/v1/project/copy", json={"destination": str(destination)})

        engine = create_project_engine(project_module.database_path(destination))
        try:
            with engine.connect() as connection:
                assert connection.execute(text("SELECT body FROM note")).scalar() == "real work"
        finally:
            engine.dispose()

    def test_the_original_keeps_serving(self, on_disk: tuple[TestClient, Path]) -> None:
        client, tmp_path = on_disk
        client.post("/api/v1/project/copy", json={"destination": str(tmp_path / "A.tessera")})

        assert client.get("/health").status_code == 200

    def test_copying_onto_something_that_exists_is_refused(
        self, on_disk: tuple[TestClient, Path]
    ) -> None:
        client, tmp_path = on_disk
        occupied = tmp_path / "Taken.tessera"
        occupied.mkdir()

        response = client.post("/api/v1/project/copy", json={"destination": str(occupied)})

        assert response.status_code == 409, response.text
        assert "already exists" in response.text

    def test_a_destination_of_nothing_is_refused(self, on_disk: tuple[TestClient, Path]) -> None:
        client, _ = on_disk
        assert client.post("/api/v1/project/copy", json={"destination": ""}).status_code == 422


class TestWhatDoesNotExist:
    def test_there_is_no_way_to_open_another_project(self, client: TestClient) -> None:
        """One engine, one project. A route that swapped it would make the engine's
        identity mutable and invalidate every open session — the process boundary is
        what keeps two projects apart."""
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/project/open" not in paths

    def test_there_is_no_save_endpoint(self, client: TestClient) -> None:
        """P7 Act 12: everything is saved continuously; there is no Save button."""
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/project/save" not in paths

    def test_an_engine_with_no_project_on_disk_says_so(self, client: TestClient) -> None:
        """The in-memory case, which is what tests and the Docker image use."""
        response = client.post("/api/v1/project/copy", json={"destination": "/tmp/x.tessera"})
        assert response.status_code == 422
        assert "no project on disk" in response.text
