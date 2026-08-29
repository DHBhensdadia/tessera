"""Writing a mapped instance into a real project.

Against a real database rather than a mock, because everything that can go wrong here is a
rule only the database knows: a room name already taken, a term on another institution's
grid, a closure slot outside the week. A mock would agree with whatever this module believes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.importers.itc import Instance, read
from tessera.importers.itc.apply import mapped
from tessera.repository import calendar as calendar_repo
from tessera.repository import imports as imports_repo
from tessera.repository import models as m
from tessera.repository import people as people_repo
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as teaching_repo
from tessera.repository.errors import ConflictError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def instance() -> Instance:
    return read(FIXTURES / "bet-sum18.xml")


class TestApplying:
    def test_it_lands_as_its_own_institution_and_term(
        self, db: DbSession, instance: Instance
    ) -> None:
        """Its own, not merged into whatever the project holds. Two instances both name a
        room `Room 1` and mean different rooms."""
        outcome = imports_repo.apply_instance(db, mapped(instance), dry_run=False)

        assert outcome.institution_id
        term = calendar_repo.get_term(db, outcome.term_id)
        assert term.name == "bet-sum18"
        assert term.institution_id == outcome.institution_id

    def test_the_grid_is_the_one_the_mapping_chose(self, db: DbSession, instance: Instance) -> None:
        outcome = imports_repo.apply_instance(db, mapped(instance), dry_run=False)
        grid = calendar_repo.get_time_grid(db, outcome.grid_id)

        assert (grid.days, grid.slots_per_day, grid.slot_minutes) == (7, 53, 10)
        assert grid.day_start_minute == 8 * 60

    def test_the_rooms_and_courses_arrive(self, db: DbSession, instance: Instance) -> None:
        outcome = imports_repo.apply_instance(db, mapped(instance), dry_run=False)

        assert outcome.rooms == 46
        assert outcome.courses == 48
        assert len(structure_repo.list_rooms(db)) == 46
        assert len(teaching_repo.list_courses(db)) == 48

    def test_every_course_is_offered_in_the_term(self, db: DbSession, instance: Instance) -> None:
        """A course nobody offers is a catalogue entry, and the Offerings screen would be
        empty beside a Courses screen with 48 rows."""
        outcome = imports_repo.apply_instance(db, mapped(instance), dry_run=False)

        assert len(calendar_repo.list_offerings(db, term_id=outcome.term_id)) == 48

    def test_the_closures_are_blocked_against_the_right_rooms(
        self, db: DbSession, instance: Instance
    ) -> None:
        plan = mapped(instance)
        outcome = imports_repo.apply_instance(db, plan, dry_run=False)

        blocked = people_repo.list_unavailability(db, outcome.term_id, kind="room")
        assert blocked
        assert len(blocked) == sum(len(c.slots) for c in plan.closures)

    def test_every_blocked_slot_is_inside_the_week(self, db: DbSession, instance: Instance) -> None:
        """`block_slots` refuses a slot outside the term's grid, so this passing at all
        means the mapping and the grid agree. It is asserted anyway because the failure —
        a closure landing on the wrong day — is silent rather than loud."""
        outcome = imports_repo.apply_instance(db, mapped(instance), dry_run=False)
        grid = calendar_repo.get_time_grid(db, outcome.grid_id)

        for row in people_repo.list_unavailability(db, outcome.term_id, kind="room"):
            assert 0 <= row.slot < grid.slot_count


class TestTheDryRun:
    def test_it_keeps_nothing(self, db: DbSession, instance: Instance) -> None:
        outcome = imports_repo.apply_instance(db, mapped(instance), dry_run=True)

        assert outcome.rolled_back
        assert db.query(m.Room).count() == 0
        assert db.query(m.Course).count() == 0
        assert db.query(m.Institution).count() == 0

    def test_it_does_the_same_work(self, db: DbSession, instance: Instance) -> None:
        """A dry run that checked less than the commit would turn 'I checked' into
        confidence never earned. Running one and then a real one must succeed identically —
        if the dry run had skipped a constraint, the commit would be the first to find it.
        """
        imports_repo.apply_instance(db, mapped(instance), dry_run=True)
        outcome = imports_repo.apply_instance(db, mapped(instance), dry_run=False)

        assert outcome.rooms == 46

    def test_a_failure_leaves_nothing_behind(self, db: DbSession, instance: Instance) -> None:
        """The same instance twice would collide on the institution name. The point is not
        that it fails — it is that the second attempt leaves the first intact and adds
        nothing of its own.
        """
        first = imports_repo.apply_instance(db, mapped(instance), dry_run=False)
        db.flush()
        before = db.query(m.Room).count()

        with pytest.raises(ConflictError):
            imports_repo.apply_instance(db, mapped(instance), dry_run=False)

        assert db.query(m.Room).count() == before
        assert calendar_repo.get_term(db, first.term_id).name == "bet-sum18"
