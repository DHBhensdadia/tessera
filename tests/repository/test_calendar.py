"""Time grids, terms and offerings.

Repository-level, so the rules are tested without HTTP in the way. The same rules are
checked again through the API in `tests/api/test_calendar.py`.

The grid tests carry more weight than they look like they should. A grid is what gives
every stored slot index its meaning, so the rules here are the difference between a
timetable that is wrong and one that is *silently* wrong.
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.repository import calendar as repo
from tessera.repository import models as m
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as teaching_repo
from tessera.repository.errors import ConflictError, NotFoundError


class Week(TypedDict):
    """The four numbers that define a teaching week.

    A TypedDict rather than a plain dict so `**WEEK` keeps its field types when unpacked
    into a call whose parameters are not all ints.
    """

    days: int
    slots_per_day: int
    slot_minutes: int
    day_start_minute: int


WEEK: Week = {"days": 5, "slots_per_day": 16, "slot_minutes": 30, "day_start_minute": 9 * 60}


@pytest.fixture
def grid_id(db: DbSession, institution: m.Institution) -> int:
    created = repo.create_time_grid(db, institution_id=institution.id, name="Standard", **WEEK)
    assert created.id is not None
    return int(created.id)


class TestTimeGrids:
    def test_a_grid_is_created_with_its_breaks(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        grid = repo.create_time_grid(
            db, institution_id=institution.id, name="With lunch", break_slots=[8, 9], **WEEK
        )

        assert grid.break_slots == frozenset({8, 9})
        assert grid.slot_count == 80

    def test_slot_count_comes_from_the_domain(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        """Not recounted in the repository or the router.

        `slot_count` is `days * slots_per_day`, trivial enough that duplicating it looks
        harmless — and would then be a second definition of how long a week is.
        """
        grid = repo.create_time_grid(db, institution_id=institution.id, **WEEK)

        assert grid.slot_count == WEEK["days"] * WEEK["slots_per_day"]

    def test_a_break_outside_the_day_is_refused(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        """Rejected by the domain, surfaced as a conflict rather than an unhandled error."""
        with pytest.raises(ConflictError, match="outside a day"):
            repo.create_time_grid(db, institution_id=institution.id, break_slots=[99], **WEEK)

    def test_a_week_of_nothing_but_breaks_is_refused(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        with pytest.raises(ConflictError, match="nothing could be scheduled"):
            repo.create_time_grid(
                db,
                institution_id=institution.id,
                days=5,
                slots_per_day=3,
                slot_minutes=30,
                day_start_minute=540,
                break_slots=[0, 1, 2],
            )

    def test_there_is_no_way_to_edit_a_grid(self) -> None:
        """Decision #51, asserted as the absence of a function.

        Every stored slot index means what it means only by reference to the grid's
        shape. An `update_time_grid` would reinterpret every assignment and every blocked
        slot in every term using it, silently and without error. This test exists so that
        adding one is a deliberate act that breaks a build, not a convenience someone
        adds on a Tuesday.
        """
        assert not hasattr(repo, "update_time_grid")

    def test_grid_names_are_unique_per_institution(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        repo.create_time_grid(db, institution_id=institution.id, name="Standard", **WEEK)

        with pytest.raises(ConflictError):
            repo.create_time_grid(db, institution_id=institution.id, name="Standard", **WEEK)

    def test_an_unused_grid_is_deleted(self, db: DbSession, grid_id: int) -> None:
        repo.delete_time_grid(db, grid_id)

        assert repo.list_time_grids(db) == []

    def test_deleting_a_grid_a_term_uses_is_refused(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        """The guard proved by breaking the thing it guards.

        `time_grid_id` is RESTRICT so the database would refuse too — but with a message
        naming a constraint rather than the terms the user needs to go and look at.
        """
        repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid_id,
            academic_year="2026-27",
            name="Autumn",
        )

        with pytest.raises(ConflictError) as raised:
            repo.delete_time_grid(db, grid_id)

        assert raised.value.blockers == {"terms": 1}


class TestTerms:
    def test_a_term_is_created_against_a_grid(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        term = repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid_id,
            academic_year="2026-27",
            name="Autumn",
            starts_on=date(2026, 9, 1),
            ends_on=date(2026, 12, 18),
        )

        assert term.name == "Autumn"
        assert term.time_grid_id == grid_id

    def test_a_grid_from_another_institution_is_refused(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        """Two independent foreign keys, and nothing in the schema relating them.

        Without this a term could be built on another university's teaching week, and
        the mistake would surface much later as rooms and staff that do not exist.
        """
        other = structure_repo.create_institution(db, name="Somewhere Else")
        assert other.id is not None

        with pytest.raises(ConflictError, match="another institution"):
            repo.create_term(
                db,
                institution_id=other.id,
                time_grid_id=grid_id,
                academic_year="2026-27",
                name="Autumn",
            )

    def test_a_term_ending_before_it_starts_is_refused(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        """The domain has rejected this since 1.3 and nothing had ever asked it to."""
        with pytest.raises(ConflictError, match="ends before it starts"):
            repo.create_term(
                db,
                institution_id=institution.id,
                time_grid_id=grid_id,
                academic_year="2026-27",
                name="Autumn",
                starts_on=date(2026, 12, 18),
                ends_on=date(2026, 9, 1),
            )

    def test_a_name_may_repeat_across_years(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        """ "Autumn" every year is the normal case; twice in one year is a mistake."""
        for year in ("2026-27", "2027-28"):
            repo.create_term(
                db,
                institution_id=institution.id,
                time_grid_id=grid_id,
                academic_year=year,
                name="Autumn",
            )

        assert len(repo.list_terms(db)) == 2

    def test_a_name_may_not_repeat_within_a_year(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        def autumn() -> None:
            repo.create_term(
                db,
                institution_id=institution.id,
                time_grid_id=grid_id,
                academic_year="2026-27",
                name="Autumn",
            )

        autumn()

        with pytest.raises(ConflictError):
            autumn()

    def test_terms_are_listed_newest_year_first(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        for year in ("2025-26", "2027-28", "2026-27"):
            repo.create_term(
                db,
                institution_id=institution.id,
                time_grid_id=grid_id,
                academic_year=year,
                name="Autumn",
            )

        assert [t.academic_year for t in repo.list_terms(db)] == ["2027-28", "2026-27", "2025-26"]

    def test_renaming_into_a_collision_is_refused(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        def term(name: str) -> d.Term:
            return repo.create_term(
                db,
                institution_id=institution.id,
                time_grid_id=grid_id,
                academic_year="2026-27",
                name=name,
            )

        term("Autumn")
        spring = term("Spring")
        assert spring.id is not None

        with pytest.raises(ConflictError):
            repo.update_term(db, spring.id, changes={"name": "Autumn"})

    def test_a_term_keeps_its_own_name_when_edited(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        term = repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid_id,
            academic_year="2026-27",
            name="Autumn",
        )
        assert term.id is not None

        updated = repo.update_term(
            db, term.id, changes={"name": "Autumn", "starts_on": date(2026, 9, 1)}
        )

        assert updated.starts_on == date(2026, 9, 1)

    def test_editing_dates_into_the_wrong_order_is_refused(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        term = repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid_id,
            academic_year="2026-27",
            name="Autumn",
            starts_on=date(2026, 9, 1),
        )
        assert term.id is not None

        with pytest.raises(ConflictError, match="ends before it starts"):
            repo.update_term(db, term.id, changes={"ends_on": date(2026, 1, 1)})

    def test_a_term_cannot_be_repointed_at_another_grid(
        self, db: DbSession, institution: m.Institution, grid_id: int
    ) -> None:
        """The same hazard as editing a grid, reached through a different door.

        Repointing a term at a differently-shaped week would reinterpret every slot index
        already stored against it. `update_term` applies name and dates and nothing else,
        so a caller who asks for this is ignored rather than obeyed — and `TermUpdate`
        gives the request no way to arrive over HTTP at all.
        """
        narrower = repo.create_time_grid(
            db,
            institution_id=institution.id,
            name="Short week",
            days=4,
            slots_per_day=8,
            slot_minutes=30,
            day_start_minute=540,
        )
        term = repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid_id,
            academic_year="2026-27",
            name="Autumn",
        )
        assert term.id is not None

        updated = repo.update_term(db, term.id, changes={"time_grid_id": narrower.id})

        assert updated.time_grid_id == grid_id


class TestOfferings:
    @pytest.fixture
    def term_id(self, db: DbSession, institution: m.Institution, grid_id: int) -> int:
        created = repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid_id,
            academic_year="2026-27",
            name="Autumn",
        )
        assert created.id is not None
        return int(created.id)

    @pytest.fixture
    def course_id(self, db: DbSession) -> int:
        created = teaching_repo.create_course(db, code="CS101", name="Intro")
        assert created.id is not None
        return int(created.id)

    def test_a_course_is_offered_in_a_term(
        self, db: DbSession, term_id: int, course_id: int
    ) -> None:
        offering = repo.create_offering(db, term_id=term_id, course_id=course_id)

        assert offering.term_id == term_id
        assert offering.course_id == course_id

    def test_the_same_course_may_be_offered_in_two_terms(
        self, db: DbSession, institution: m.Institution, grid_id: int, term_id: int, course_id: int
    ) -> None:
        """The reason offerings exist at all: a course outlives any one semester."""
        spring = repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid_id,
            academic_year="2026-27",
            name="Spring",
        )
        assert spring.id is not None

        repo.create_offering(db, term_id=term_id, course_id=course_id)
        repo.create_offering(db, term_id=spring.id, course_id=course_id)

        assert len(repo.list_offerings(db, term_id=term_id)) == 1
        assert len(repo.list_offerings(db, term_id=spring.id)) == 1

    def test_the_same_course_twice_in_one_term_is_refused(
        self, db: DbSession, term_id: int, course_id: int
    ) -> None:
        repo.create_offering(db, term_id=term_id, course_id=course_id)

        with pytest.raises(ConflictError, match="already offered"):
            repo.create_offering(db, term_id=term_id, course_id=course_id)

    def test_offerings_are_ordered_by_course_code(self, db: DbSession, term_id: int) -> None:
        for code in ("CS201", "CS101", "CS301"):
            course = teaching_repo.create_course(db, code=code, name=code)
            assert course.id is not None
            repo.create_offering(db, term_id=term_id, course_id=course.id)

        found = repo.list_offerings(db, term_id=term_id)
        codes = [teaching_repo.get_course(db, int(o.course_id or 0)).code for o in found]
        assert codes == ["CS101", "CS201", "CS301"]

    def test_an_unknown_course_is_refused(self, db: DbSession, term_id: int) -> None:
        with pytest.raises(NotFoundError):
            repo.create_offering(db, term_id=term_id, course_id=999)

    def test_deleting_a_term_with_offerings_is_refused(
        self, db: DbSession, term_id: int, course_id: int
    ) -> None:
        """Deleting a term is "delete this semester and everything scheduled in it":
        offering cascades from term, session from offering, assignment from session."""
        repo.create_offering(db, term_id=term_id, course_id=course_id)

        with pytest.raises(ConflictError) as raised:
            repo.delete_term(db, term_id)

        assert raised.value.blockers == {"offerings": 1}

    def test_an_empty_offering_is_deleted(
        self, db: DbSession, term_id: int, course_id: int
    ) -> None:
        offering = repo.create_offering(db, term_id=term_id, course_id=course_id)
        assert offering.id is not None

        repo.delete_offering(db, offering.id)

        assert repo.list_offerings(db, term_id=term_id) == []

    def test_deleting_an_offering_with_sessions_is_refused(
        self, db: DbSession, term_id: int, course_id: int
    ) -> None:
        """The guard for a table part 3 will fill.

        The session is inserted through the ORM because no endpoint creates one yet.
        Waiting for part 3 would mean shipping a guard nobody has seen fire.
        """
        offering = repo.create_offering(db, term_id=term_id, course_id=course_id)
        assert offering.id is not None
        db.add(
            m.Session(offering_id=offering.id, term_id=term_id, kind="lecture", duration_slots=2)
        )
        db.flush()

        with pytest.raises(ConflictError) as raised:
            repo.delete_offering(db, offering.id)

        assert raised.value.blockers == {"sessions": 1}

    def test_the_session_survives_the_refusal(
        self, db: DbSession, term_id: int, course_id: int
    ) -> None:
        offering = repo.create_offering(db, term_id=term_id, course_id=course_id)
        assert offering.id is not None
        db.add(
            m.Session(offering_id=offering.id, term_id=term_id, kind="lecture", duration_slots=2)
        )
        db.flush()

        with pytest.raises(ConflictError):
            repo.delete_offering(db, offering.id)

        assert db.query(m.Session).count() == 1
        assert repo.session_count(db, offering.id) == 1

    def test_listing_offerings_for_an_unknown_term(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.list_offerings(db, term_id=999)
