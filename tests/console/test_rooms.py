"""Rooms in the browser — the shape every other section will copy.

The rules themselves belong to 2.1 and are tested in `tests/repository/test_structure.py`.
What is new here is the medium: a form that posts, a redirect that stops a refresh
resubmitting it, and a refusal that arrives as a sentence rather than a status code.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.app import create_app


@pytest.fixture
def browser(engine: Engine) -> Iterator[TestClient]:
    """An unauthenticated app, addressed as a browser on this machine would address it.

    No token, because these tests are about the pages rather than the way in — that is
    `test_shell.py`. The host still has to be local or the rebinding guard refuses.
    """
    app = create_app(engine=engine, configure_logs=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def add_room(browser: TestClient, **fields: str | int) -> None:
    form: dict[str, str] = {"building_id": "", **{k: str(v) for k, v in fields.items()}}
    browser.post("/console/rooms", data=form)


class TestBrowsing:
    def test_an_empty_project_says_so(self, browser: TestClient) -> None:
        """An empty table with no explanation is the commonest way a tool looks broken
        when it is working."""
        response = browser.get("/console/rooms")

        assert response.status_code == 200
        assert "No rooms yet" in response.text

    def test_a_room_appears_in_the_table(self, browser: TestClient) -> None:
        add_room(browser, name="LH-201", capacity=120)

        assert "LH-201" in browser.get("/console/rooms").text

    def test_ids_are_shown_as_names(self, browser: TestClient) -> None:
        """A table of foreign keys is not a tool anybody can use."""
        institution = browser.post("/api/v1/institutions", json={"name": "U"}).json()
        building = browser.post(
            "/api/v1/buildings", json={"institution_id": institution["id"], "name": "Block A"}
        ).json()
        projector = browser.post(
            "/api/v1/features", json={"institution_id": institution["id"], "name": "projector"}
        ).json()
        add_room(
            browser,
            name="LH-201",
            capacity=120,
            building_id=building["id"],
            feature_ids=projector["id"],
        )

        text = browser.get("/console/rooms").text

        assert "Block A" in text
        assert "projector" in text

    def test_the_overview_links_onward(self, browser: TestClient) -> None:
        assert "/console/rooms" in browser.get("/console/").text


class TestCreating:
    def test_a_successful_post_redirects(self, browser: TestClient) -> None:
        """Post-redirect-get. Without it, refreshing the page after adding a room adds
        a second one, which is the oldest bug in web forms."""
        response = browser.post(
            "/console/rooms",
            data={"name": "LH-201", "capacity": "120", "building_id": ""},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/console/rooms"

    def test_a_refusal_is_shown_as_a_sentence(self, browser: TestClient) -> None:
        """The API answers this with an RFC 9457 document. A person filling in a form
        needs prose, next to the form, with the form still on screen."""
        add_room(browser, name="LH-201", capacity=120)

        response = browser.post(
            "/console/rooms", data={"name": "LH-201", "capacity": "80", "building_id": ""}
        )

        assert response.status_code == 200
        assert "already exists" in response.text
        assert "Add a room" in response.text

    def test_what_was_typed_survives_a_refusal(self, browser: TestClient) -> None:
        """Retyping a form because one field was wrong is how a tool earns being
        abandoned."""
        add_room(browser, name="LH-201", capacity=120)

        response = browser.post(
            "/console/rooms", data={"name": "LH-201", "capacity": "80", "building_id": ""}
        )

        assert 'value="LH-201"' in response.text

    def test_an_unknown_feature_is_reported_against_its_field(self, browser: TestClient) -> None:
        response = browser.post(
            "/console/rooms",
            data={"name": "LH-201", "capacity": "80", "building_id": "", "feature_ids": "999"},
        )

        assert "feature_ids" in response.text


class TestDeleting:
    def test_a_room_can_be_removed(self, browser: TestClient) -> None:
        add_room(browser, name="LH-201", capacity=120)

        browser.post("/console/rooms/1/delete")

        assert "LH-201" not in browser.get("/console/rooms").text

    def test_a_blocked_delete_explains_itself(self, browser: TestClient) -> None:
        """Rooms cannot be deleted while a timetable places sessions in them. Nothing
        here can schedule anything yet, so this asserts the shape: a repository refusal
        reaches the page rather than becoming a 500."""
        response = browser.post("/console/rooms/999/delete")

        assert response.status_code == 200
        assert "no longer exists" in response.text
