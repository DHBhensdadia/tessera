"""Reading a generated timetable in a browser.

The console knew nothing about timetables before 4.8 — no grid, no score, no violation count
— so everything here is new ground rather than a change to an existing page.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from tessera.domain.timetable import Assignment
from tessera.repository import models as m
from tessera.repository import session_factory
from tessera.repository import snapshot as snapshot_repo
from tessera.repository import structure as structure_repo
from tessera.repository import timetables as timetables_repo
from tests.console.test_solving import generate, watch_until_settled
from tests.repository.authored import Term


def _stacked_on_monday(project: Engine, term: Term) -> int:
    """A timetable placed by hand so that it is valid and wasteful.

    Every session on Monday with an hour idle between them, which is what the default
    preferences price. A *solved* timetable scores zero, so it cannot show what a breakdown
    looks like.
    """
    with session_factory(project)() as db:
        loaded = snapshot_repo.load(db, term.term_id)
        room = min(loaded.rooms)
        stored = timetables_repo.record(
            db,
            term_id=term.term_id,
            placements=[
                Assignment(session_id=one, start_slot=slot, room_id=room)
                for slot, one in zip(range(0, 99, 3), sorted(loaded.sessions), strict=False)
            ],
            name="Wasteful",
        )
        db.commit()
        return int(stored.id or 0)


#: Clause 7. A page draws *cells*, most of them empty, so its size follows the grid and the
#: number of subjects rather than the number of placements — 4.8 measured every room of a
#: 500-room institution at 1.7 MiB. One subject at a time is what keeps this true.
PAGE_CEILING_BYTES = 50 * 1024


@pytest.fixture
def generated(solving_console: TestClient, solvable: Term) -> int:
    """A term solved through the console, and the timetable it produced."""
    where = generate(solving_console, solvable.term_id)
    settled = watch_until_settled(solving_console, where.rsplit("/", 1)[-1])
    return int(settled.split("/console/timetables/")[1].split('"')[0])


class TestTheTermsTimetables:
    def test_the_list_offers_a_generate_form(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        page = solving_console.get(f"/console/terms/{solvable.term_id}/timetables")

        assert page.status_code == 200
        assert 'name="time_budget_seconds"' in page.text
        assert 'name="seed_timetable_id"' in page.text

    def test_a_generated_timetable_appears_on_it(
        self, solving_console: TestClient, solvable: Term, generated: int
    ) -> None:
        page = solving_console.get(f"/console/terms/{solvable.term_id}/timetables")

        assert f"/console/timetables/{generated}" in page.text

    def test_it_can_be_offered_as_a_warm_start(
        self, solving_console: TestClient, solvable: Term, generated: int
    ) -> None:
        """D9. `seed_timetable_id` has existed since 4.7 and nothing outside a test had ever
        reached it — this select is the only way a person can."""
        page = solving_console.get(f"/console/terms/{solvable.term_id}/timetables")

        assert f'<option value="{generated}"' in page.text

    def test_solving_from_one_produces_another_rather_than_replacing_it(
        self, solving_console: TestClient, solvable: Term, generated: int
    ) -> None:
        where = generate(solving_console, solvable.term_id, seed_timetable_id=str(generated))
        settled = watch_until_settled(solving_console, where.rsplit("/", 1)[-1])
        second = int(settled.split("/console/timetables/")[1].split('"')[0])

        assert second != generated
        assert solving_console.get(f"/console/timetables/{generated}").status_code == 200

    def test_one_can_be_thrown_away(
        self, solving_console: TestClient, solvable: Term, generated: int
    ) -> None:
        response = solving_console.post(
            f"/console/timetables/{generated}/delete", follow_redirects=False
        )

        assert response.status_code == 303
        listing = solving_console.get(f"/console/terms/{solvable.term_id}/timetables")
        assert f"/console/timetables/{generated}" not in listing.text


class TestReadingIt:
    def test_all_three_pivots_render(self, solving_console: TestClient, generated: int) -> None:
        for pivot in ("group", "instructor", "room"):
            page = solving_console.get(f"/console/timetables/{generated}?pivot={pivot}")

            assert page.status_code == 200, pivot
            assert 'class="week"' in page.text, pivot

    def test_it_opens_on_a_subject_with_teaching_in_it(
        self, solving_console: TestClient, generated: int
    ) -> None:
        """A room estate sorts LH-1 first and a solver may have used only LH-2. Opening on an
        empty week reads as a broken grid rather than as a free room."""
        page = solving_console.get(f"/console/timetables/{generated}?pivot=room")

        assert 'class="taught"' in page.text

    def test_the_subject_asked_for_is_the_one_drawn(
        self, solving_console: TestClient, generated: int
    ) -> None:
        """The ordinary path through the selector, and the one the fallbacks exist around."""
        view = solving_console.get(f"/api/v1/timetables/{generated}/grid?pivot=room").json()
        empty = next(column["subject"] for column in view["columns"] if not column["cells"])

        page = solving_console.get(
            f"/console/timetables/{generated}?pivot=room&subject={empty['id']}"
        )

        assert f">{empty['name']}</h1>" in page.text

    def test_an_unknown_subject_falls_back_rather_than_failing(
        self, solving_console: TestClient, generated: int
    ) -> None:
        """Changing the pivot posts the *old* pivot's subject id — the two selects are one
        form — so an id that means nothing here is ordinary, not an error page."""
        page = solving_console.get(f"/console/timetables/{generated}?pivot=room&subject=99999")

        assert page.status_code == 200
        assert 'class="week"' in page.text

    def test_an_unknown_pivot_falls_back_too(
        self, solving_console: TestClient, generated: int
    ) -> None:
        page = solving_console.get(f"/console/timetables/{generated}?pivot=nonsense")

        assert page.status_code == 200

    def test_the_violation_count_is_the_validators_and_not_the_solvers(
        self, solving_console: TestClient, generated: int
    ) -> None:
        """`Timetable.penalty` is what the search said its own answer cost. The count on this
        page is a second, independently written reading of the same placements."""
        page = solving_console.get(f"/console/timetables/{generated}")

        assert "hard violations" in page.text

    def test_the_score_is_broken_down_by_rule(
        self, solving_console: TestClient, project: Engine, solvable: Term
    ) -> None:
        """On a timetable that costs something, which a solved one does not.

        The first version of this asserted that the word *penalty* appeared on the page. It
        does, in a caption, whatever the table below it says — a test that could not fail,
        which ②b caught by breaking the table and watching it pass.
        """
        stored = _stacked_on_monday(project, solvable)

        page = solving_console.get(f"/console/timetables/{stored}")
        reported = solving_console.get(f"/api/v1/timetables/{stored}/violations").json()

        assert reported["penalty_breakdown"], "the fixture must cost something to be a test"
        for rule, cost in reported["penalty_breakdown"].items():
            assert rule.replace("_", " ").capitalize() in page.text
            assert f"<td>{cost}</td>" in page.text


class TestWhenThereIsNothingToRead:
    def test_a_timetable_with_no_placements_still_opens(
        self, solving_console: TestClient, solvable: Term
    ) -> None:
        """Somebody makes a candidate by hand and looks at it before filling it in. Every
        room is still a subject — an empty week is what *this room is free* looks like."""
        made = solving_console.post(
            f"/api/v1/terms/{solvable.term_id}/timetables", json={"name": "Blank"}
        ).json()

        page = solving_console.get(f"/console/timetables/{made['id']}?pivot=room")

        assert page.status_code == 200
        assert "Nothing is scheduled here" in page.text

    def test_a_term_with_no_teaching_has_no_subjects_at_all(
        self, solving_console: TestClient, term_without_sessions: int
    ) -> None:
        """No sessions means no groups and no instructors to pivot on, and the page says so
        rather than drawing an empty table with no heading."""
        made = solving_console.post(
            f"/api/v1/terms/{term_without_sessions}/timetables", json={"name": "Blank"}
        ).json()

        page = solving_console.get(f"/console/timetables/{made['id']}?pivot=group")

        assert page.status_code == 200
        assert "nothing in it to read" in page.text

    def test_one_an_institution_is_running_is_not_deleted_quietly(
        self, solving_console: TestClient, solvable: Term, generated: int
    ) -> None:
        """The refusal belongs beside the button, which is the one thing the console does
        not share with the API."""
        solving_console.patch(f"/api/v1/timetables/{generated}", json={"status": "published"})

        response = solving_console.post(f"/console/timetables/{generated}/delete")

        assert response.status_code == 200
        assert "archive it before deleting" in response.text


class TestTheSizeOfThePage:
    """Clause 7, and the reason the page has a subject selector at all."""

    @pytest.fixture
    def many_rooms(
        self, project_db: DbSession, campus: tuple[m.Institution, m.TimeGrid], solvable: Term
    ) -> int:
        """A department's worth of rooms, most of them empty, so the page has plenty it could
        draw and must not."""
        institution, _ = campus
        building = structure_repo.create_building(
            project_db, institution_id=institution.id, name="Overflow"
        )
        assert building.id is not None
        for number in range(40):
            structure_repo.create_room(
                project_db, building_id=int(building.id), name=f"X-{number:03d}", capacity=60
            )
        project_db.commit()
        return len(solvable.room_ids) + 40

    def test_one_subject_is_drawn_however_many_there_are(
        self, solving_console: TestClient, generated: int, many_rooms: int
    ) -> None:
        page = solving_console.get(f"/console/timetables/{generated}?pivot=room")

        assert page.text.count('class="week"') == 1, (
            f"{many_rooms} subjects exist and the page must draw one of them"
        )

    def test_the_page_stays_small(
        self, solving_console: TestClient, generated: int, many_rooms: int
    ) -> None:
        page = solving_console.get(f"/console/timetables/{generated}?pivot=room")

        assert len(page.content) < PAGE_CEILING_BYTES, (
            f"{len(page.content):,} bytes for one subject out of {many_rooms} — the selector "
            "is what keeps this from following the size of the estate"
        )

    def test_every_room_is_still_offered(
        self, solving_console: TestClient, generated: int, many_rooms: int
    ) -> None:
        """Small because one week is drawn, not because subjects were hidden."""
        page = solving_console.get(f"/console/timetables/{generated}?pivot=room")

        assert page.text.count("<option ") >= many_rooms
