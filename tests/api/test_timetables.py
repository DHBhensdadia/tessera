"""The five timetable routes Decision #94 moved to 4.7.

They were stubbed in 1.4 and pointed here because this is *"the first phase in which a
timetable can exist at all"* — the solver produces one. The repository behind them is tested
in `tests/repository/test_timetables.py`; these are about the surface, and about the two
refusals that only mean anything over HTTP.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.repository.authored import Term


def a_timetable(client: TestClient, term: Term, name: str = "Draft A") -> dict[str, object]:
    made = client.post(f"/api/v1/terms/{term.term_id}/timetables", json={"name": name})
    assert made.status_code == 201, made.text
    return dict(made.json())


class TestTheOrdinaryLife:
    def test_a_term_starts_with_none(self, solving_client: TestClient, solvable: Term) -> None:
        listed = solving_client.get(f"/api/v1/terms/{solvable.term_id}/timetables")

        assert listed.status_code == 200
        assert listed.json() == {"items": [], "total": 0}

    def test_created_empty_and_read_back(self, solving_client: TestClient, solvable: Term) -> None:
        made = a_timetable(solving_client, solvable)

        assert made["status"] == "draft"
        assert made["penalty"] is None, "never solved is not the same as costing nothing"
        assert made["assignment_count"] == 0
        assert made["is_editable"] is True

        read = solving_client.get(f"/api/v1/timetables/{made['id']}")
        assert read.status_code == 200
        assert read.json() == made

    def test_listed_newest_first(self, solving_client: TestClient, solvable: Term) -> None:
        first = a_timetable(solving_client, solvable, "Draft A")
        second = a_timetable(solving_client, solvable, "Draft B")

        listed = solving_client.get(f"/api/v1/terms/{solvable.term_id}/timetables").json()

        assert [item["id"] for item in listed["items"]] == [second["id"], first["id"]]
        assert listed["total"] == 2

    def test_narrowed_by_status(self, solving_client: TestClient, solvable: Term) -> None:
        made = a_timetable(solving_client, solvable)
        solving_client.patch(f"/api/v1/timetables/{made['id']}", json={"status": "archived"})

        drafts = solving_client.get(
            f"/api/v1/terms/{solvable.term_id}/timetables", params={"status_filter": "draft"}
        ).json()
        archived = solving_client.get(
            f"/api/v1/terms/{solvable.term_id}/timetables", params={"status_filter": "archived"}
        ).json()

        assert drafts["total"] == 0
        assert archived["total"] == 1

    def test_renamed(self, solving_client: TestClient, solvable: Term) -> None:
        made = a_timetable(solving_client, solvable)

        renamed = solving_client.patch(
            f"/api/v1/timetables/{made['id']}", json={"name": "What we ran"}
        )

        assert renamed.status_code == 200
        assert renamed.json()["name"] == "What we ran"
        assert renamed.json()["status"] == "draft", "renaming is not publishing"

    def test_published_and_then_no_longer_editable(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        made = a_timetable(solving_client, solvable)

        published = solving_client.patch(
            f"/api/v1/timetables/{made['id']}", json={"status": "published"}
        ).json()

        assert published["published_at"] is not None
        assert published["is_editable"] is False

    def test_deleted(self, solving_client: TestClient, solvable: Term) -> None:
        made = a_timetable(solving_client, solvable)

        assert solving_client.delete(f"/api/v1/timetables/{made['id']}").status_code == 204
        assert solving_client.get(f"/api/v1/timetables/{made['id']}").status_code == 404


class TestWhatItRefuses:
    def test_a_timetable_that_is_not_there(self, solving_client: TestClient) -> None:
        assert solving_client.get("/api/v1/timetables/404").status_code == 404
        assert solving_client.patch("/api/v1/timetables/404", json={"name": "x"}).status_code == 404
        assert solving_client.delete("/api/v1/timetables/404").status_code == 404

    def test_a_term_that_is_not_there(self, solving_client: TestClient) -> None:
        assert solving_client.get("/api/v1/terms/404/timetables").status_code == 404
        assert solving_client.post("/api/v1/terms/404/timetables", json={}).status_code == 404

    def test_an_empty_name(self, solving_client: TestClient, solvable: Term) -> None:
        refused = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/timetables", json={"name": ""}
        )

        assert refused.status_code == 422

    def test_deleting_something_an_institution_is_running(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """A published timetable is what they are actually running, and a delete that quietly
        took it out is not something to discover afterwards. 6.5 owns the way back to draft."""
        made = a_timetable(solving_client, solvable)
        solving_client.patch(f"/api/v1/timetables/{made['id']}", json={"status": "published"})

        refused = solving_client.delete(f"/api/v1/timetables/{made['id']}")

        assert refused.status_code == 409

    def test_a_lineage_that_crosses_terms(
        self, solving_client: TestClient, solvable: Term, another_term: Term
    ) -> None:
        """A comparison drawing two timetables of different terms side by side compares
        nothing, and `parent_id` is a plain foreign key with nothing to stop it."""
        theirs = a_timetable(solving_client, another_term)

        refused = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/timetables",
            json={"name": "Forked", "parent_id": theirs["id"]},
        )

        assert refused.status_code == 409
