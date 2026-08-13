"""The five sections that are the same form five times.

Declared from a table rather than written out, so what is worth testing is that the
declaration is right for each one — the parent a thing hangs from, whether it has a code,
and that the shared rename cannot collide a record with itself.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.app import create_app
from tessera.api.console.places import KINDS


@pytest.fixture
def browser(engine: Engine) -> Iterator[TestClient]:
    app = create_app(engine=engine, configure_logs=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def university(browser: TestClient) -> int:
    browser.post("/console/institutions", data={"name": "Test University"})
    return 1


class TestTheSectionsExist:
    def test_every_declared_kind_renders(self, browser: TestClient) -> None:
        """A section that is declared but unreachable is the failure a table makes
        possible, so every slug is fetched rather than a representative one."""
        for kind in KINDS:
            response = browser.get(f"/console/{kind.slug}")
            assert response.status_code == 200, kind.slug
            assert kind.title in response.text

    def test_every_declared_kind_is_in_the_navigation(self, browser: TestClient) -> None:
        """The reason the section list is data: a page nobody can navigate to is a page
        that does not exist."""
        markup = browser.get("/console/").text

        for kind in KINDS:
            assert f"/console/{kind.slug}" in markup, kind.slug

    def test_an_unknown_section_is_a_plain_404(self, browser: TestClient) -> None:
        """Each kind is registered at its own path rather than behind a `/{slug}`
        catch-all, so an unknown slug matches nothing at all. The catch-all would also
        have had to be registered after every bespoke section, making route matching
        depend on import order — which a formatter is entitled to rearrange."""
        assert browser.get("/console/nonsense").status_code == 404


class TestCreating:
    def test_a_thing_with_no_parent(self, browser: TestClient) -> None:
        browser.post("/console/institutions", data={"name": "Test University"})

        assert "Test University" in browser.get("/console/institutions").text

    def test_a_thing_hanging_from_a_parent(self, browser: TestClient, university: int) -> None:
        browser.post("/console/buildings", data={"name": "Block A", "parent_id": str(university)})

        assert "Block A" in browser.get("/console/buildings").text

    def test_a_thing_with_a_code(self, browser: TestClient, university: int) -> None:
        browser.post(
            "/console/departments",
            data={"name": "Computer Science", "code": "CSE", "parent_id": str(university)},
        )

        markup = browser.get("/console/departments").text
        assert "Computer Science" in markup
        assert "CSE" in markup

    def test_an_optional_parent_may_be_left_empty(self, browser: TestClient) -> None:
        """A programme need not belong to a department; every other parent here must."""
        browser.post("/console/programs", data={"name": "BTech CSE", "code": "", "parent_id": ""})

        assert "BTech CSE" in browser.get("/console/programs").text

    def test_a_missing_required_parent_is_explained(self, browser: TestClient) -> None:
        """Rather than a 500 from a repository call missing an argument."""
        response = browser.post("/console/buildings", data={"name": "Block A", "parent_id": ""})

        assert response.status_code == 200
        assert "required" in response.text.lower()

    def test_a_duplicate_is_refused_in_prose(self, browser: TestClient) -> None:
        browser.post("/console/institutions", data={"name": "Test University"})

        response = browser.post("/console/institutions", data={"name": "Test University"})

        assert "already exists" in response.text


class TestRenaming:
    def test_a_typo_can_be_corrected(self, browser: TestClient) -> None:
        """The whole reason 2.4b existed. Until then this was impossible."""
        browser.post("/console/institutions", data={"name": "Test Univarsity"})

        browser.post("/console/institutions/1/rename", data={"name": "Test University"})

        assert "Test University" in browser.get("/console/institutions").text

    def test_renaming_to_its_own_name_is_not_a_collision(self, browser: TestClient) -> None:
        """`exclude_id` in the shared helper. Written out five times this would have
        been five chances to forget it."""
        browser.post("/console/institutions", data={"name": "Test University"})

        response = browser.post(
            "/console/institutions/1/rename",
            data={"name": "Test University"},
            follow_redirects=False,
        )

        assert response.status_code == 303

    def test_renaming_onto_a_sibling_is_refused(self, browser: TestClient, university: int) -> None:
        browser.post("/console/buildings", data={"name": "Block A", "parent_id": "1"})
        browser.post("/console/buildings", data={"name": "Block B", "parent_id": "1"})

        response = browser.post("/console/buildings/2/rename", data={"name": "Block A"})

        assert "already exists" in response.text


class TestDeleting:
    def test_an_unused_thing_goes(self, browser: TestClient) -> None:
        browser.post("/console/institutions", data={"name": "Doomed"})

        browser.post("/console/institutions/1/delete")

        assert "Doomed" not in browser.get("/console/institutions").text

    def test_a_busy_one_explains_what_is_in_the_way(
        self, browser: TestClient, university: int
    ) -> None:
        browser.post("/console/buildings", data={"name": "Block A", "parent_id": "1"})

        response = browser.post("/console/institutions/1/delete")

        assert "still has dependants" in response.text
        assert "1 buildings" in response.text
