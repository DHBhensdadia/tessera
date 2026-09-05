"""The two routes 4.8 took off `pending`: the pivoted grid, and the violation report.

P5 gives both to later phases — the grid to 5.1 and the violations to 5.8 — and 4.8 needs
both to put a timetable in front of somebody. Building them here rather than leaving the
console a private projection is Decision #5 applied one level down: the drift this project
keeps finding (#133, #147, #151, #154, #168) is always two readings of one thing that agreed
by convention until a second consumer appeared.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api import targets
from tessera.domain.timetable import Assignment
from tessera.export import grid
from tessera.repository import session_factory
from tessera.repository import snapshot as snapshot_repo
from tessera.repository import timetables as timetables_repo
from tests.repository.authored import Term
from tests.solving import settled


@pytest.fixture
def solved(solving_client: TestClient, solvable: Term) -> int:
    started = solving_client.post(
        f"/api/v1/terms/{solvable.term_id}/solve", json={"time_budget_seconds": 20}
    )
    assert started.status_code == 202, started.text
    ended = settled(solving_client, str(started.json()["job_id"]))
    assert ended["timetable_id"], ended
    return int(str(ended["timetable_id"]))


class TestTheGrid:
    def test_all_three_pivots_answer(self, solving_client: TestClient, solved: int) -> None:
        for pivot in ("group", "instructor", "room"):
            view = solving_client.get(f"/api/v1/timetables/{solved}/grid?pivot={pivot}")

            assert view.status_code == 200, pivot
            assert view.json()["pivot"] == pivot

    def test_a_pivot_that_is_not_one_is_refused(
        self, solving_client: TestClient, solved: int
    ) -> None:
        assert (
            solving_client.get(f"/api/v1/timetables/{solved}/grid?pivot=colour").status_code == 422
        )

    def test_every_placement_appears_exactly_once_per_pivot(
        self, solving_client: TestClient, solved: int, solvable: Term
    ) -> None:
        """By room, each session is in one room. The other two can legitimately repeat one —
        a lecture is on every attending batch's week — so this is the pivot that counts."""
        view = solving_client.get(f"/api/v1/timetables/{solved}/grid?pivot=room").json()
        placed = [cell["session_id"] for column in view["columns"] for cell in column["cells"]]

        assert sorted(placed) == sorted(solvable.session_ids)

    def test_it_carries_the_shape_of_the_week(
        self, solving_client: TestClient, solved: int
    ) -> None:
        view = solving_client.get(f"/api/v1/timetables/{solved}/grid").json()

        assert view["days"] == 5
        assert view["slots_per_day"] == 8

    def test_subject_ids_narrows_it(self, solving_client: TestClient, solved: int) -> None:
        everything = solving_client.get(f"/api/v1/timetables/{solved}/grid?pivot=room").json()
        wanted = everything["columns"][0]["subject"]["id"]

        narrowed = solving_client.get(
            f"/api/v1/timetables/{solved}/grid?pivot=room&subject_ids={wanted}"
        ).json()

        assert [column["subject"]["id"] for column in narrowed["columns"]] == [wanted]

    def test_a_cell_names_its_room_rather_than_only_its_id(
        self, solving_client: TestClient, solved: int
    ) -> None:
        """Bare ids would force a client to fetch every related name to draw one screen."""
        view = solving_client.get(f"/api/v1/timetables/{solved}/grid?pivot=room").json()
        cells = [cell for column in view["columns"] for cell in column["cells"]]

        assert all(cell["room"]["name"] for cell in cells)
        assert all(cell["label"] for cell in cells)

    def test_an_unknown_timetable_is_404(self, solving_client: TestClient) -> None:
        assert solving_client.get("/api/v1/timetables/9999/grid").status_code == 404


class TestTheyAgree:
    """Clause 8. One projection, two presentations — asserted rather than assumed."""

    def test_the_route_and_the_projection_place_the_same_sessions(
        self, solving_client: TestClient, solved: int, solvable: Term, project: Engine
    ) -> None:
        view = solving_client.get(f"/api/v1/timetables/{solved}/grid?pivot=room").json()
        over_the_wire = {
            (column["subject"]["id"], cell["session_id"], cell["start_slot"])
            for column in view["columns"]
            for cell in column["cells"]
        }

        with session_factory(project)() as db:
            term = snapshot_repo.load(db, solvable.term_id, seed_timetable_id=solved)
            labels = targets.labels(db, term_id=solvable.term_id)
            in_the_projection = {
                (week.subject.id, cell.block.session_id, cell.block.start_slot)
                for week in grid.weeks(term, labels, grid.Pivot.ROOM)
                for row in week.rows
                for cell in row.cells
                if cell.block is not None
            }

        assert over_the_wire == in_the_projection


class TestTheViolations:
    def test_a_solved_timetable_is_clean(self, solving_client: TestClient, solved: int) -> None:
        """And this is the validator saying so, not the solver repeating itself."""
        report = solving_client.get(f"/api/v1/timetables/{solved}/violations").json()

        assert report["is_feasible"] is True
        assert report["hard_violations"] == []

    def test_the_score_matches_what_was_stored(
        self, solving_client: TestClient, solved: int
    ) -> None:
        """Two independent readings of one timetable. Agreement is the evidence 4.1 was
        written separately to provide; this is where the two meet over HTTP."""
        report = solving_client.get(f"/api/v1/timetables/{solved}/violations").json()
        stored = solving_client.get(f"/api/v1/timetables/{solved}").json()

        assert report["penalty"] == stored["penalty"]
        assert report["penalty_breakdown"] == stored["penalty_breakdown"]

    def test_it_reads_the_placements_rather_than_repeating_the_stored_number(
        self, solving_client: TestClient, project: Engine, solvable: Term
    ) -> None:
        """The guard the test above cannot be.

        A solved term scores **zero**, so *the two readings agree* compares nothing with
        nothing — the shape 4.3 part 1 already shipped once and #249 recorded. So a timetable
        is stored with a penalty nobody computed, and the route must contradict it.
        """
        with session_factory(project)() as db:
            term = snapshot_repo.load(db, solvable.term_id)
            first = min(term.grid.teaching_slots)
            room = next(iter(term.rooms))
            stored = timetables_repo.record(
                db,
                term_id=solvable.term_id,
                placements=[
                    Assignment(session_id=one, start_slot=first, room_id=room)
                    for one in term.sessions
                ],
                name="Everything at once",
                penalty=4321,
                penalty_breakdown={"invented": 4321},
            )
            db.commit()

        report = solving_client.get(f"/api/v1/timetables/{stored.id}/violations").json()

        assert report["penalty"] != 4321
        assert report["is_feasible"] is False, "every session in one room at one time"
        assert {one["session_id"] for one in report["hard_violations"]} == set(solvable.session_ids)

    def test_an_empty_timetable_is_feasible_and_incomplete(
        self, solving_client: TestClient, solvable: Term
    ) -> None:
        """`is_feasible` says nothing about completeness on purpose (4.1 D6): a half-built
        timetable is the normal state while somebody is working on one."""
        made = solving_client.post(
            f"/api/v1/terms/{solvable.term_id}/timetables", json={"name": "Empty"}
        ).json()

        report = solving_client.get(f"/api/v1/timetables/{made['id']}/violations").json()

        assert report["is_feasible"] is True
        assert report["hard_violations"] == []

    def test_a_violation_says_which_session_is_in_trouble(
        self, solving_client: TestClient, solved: int
    ) -> None:
        """Until 4.8 the wire model had no `session_id`, so a whole-timetable report was a
        list nothing could attribute to a cell."""
        fields = solving_client.get("/openapi.json").json()["components"]["schemas"]["Violation"]

        assert "session_id" in fields["properties"]

    def test_an_unknown_timetable_is_404(self, solving_client: TestClient) -> None:
        assert solving_client.get("/api/v1/timetables/9999/violations").status_code == 404
