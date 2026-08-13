"""Applying a plan, and the two promises that make an import safe to press.

*"Malformed rows are rejected with precise messages and no partial write"* pulls in two
directions unless the halves are separated, and these tests are where that separation is
made honest:

* a row that fails **validation** is not part of the import, and the others still go in
* a **write** that fails takes the whole import with it, so nothing is ever half applied
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.importers.detect import detect
from tessera.importers.plan import Plan, build
from tessera.importers.sheet import read
from tessera.repository import groups as groups_repo
from tessera.repository import imports as repo
from tessera.repository import models as m
from tessera.repository import structure as structure_repo


@pytest.fixture
def campus(db: DbSession, institution: m.Institution) -> None:
    structure_repo.create_building(db, institution_id=institution.id, name="Block A")
    structure_repo.create_feature(db, institution_id=institution.id, name="projector")


def plan_for(db: DbSession, csv: bytes, term_id: int = 0) -> Plan:
    sheet = read(csv, "sheet.csv")
    found = detect(sheet.headers)
    assert found.kind is not None
    return build(sheet, found.kind, found.mapping, repo.catalogue_for(db, term_id))


class TestTheDryRun:
    def test_it_writes_nothing(self, db: DbSession, campus: None) -> None:
        plan = plan_for(db, b"Room,Seats,Block\nLH-201,150,Block A\n")

        outcome = repo.apply(db, plan, dry_run=True)

        assert outcome.written == 0
        assert structure_repo.list_rooms(db) == []

    def test_it_checks_everything_the_commit_would(self, db: DbSession, campus: None) -> None:
        """A dry run that checked less than the commit would be worse than none: it would
        turn "I checked" into confidence nobody had earned.

        The proof is that a name already taken — a rule only the *project* knows, not the
        file — is caught by the dry run rather than surfacing later.
        """
        structure_repo.create_room(db, name="LH-201", capacity=100)
        plan = plan_for(db, b"Room,Seats\nLH-201,150\n")

        outcome = repo.apply(db, plan, dry_run=True)

        assert outcome.rolled_back
        assert "already exists" in outcome.problems[0].message

    def test_a_dry_run_leaves_nothing_behind_for_the_next_one(
        self, db: DbSession, campus: None
    ) -> None:
        plan = plan_for(db, b"Room,Seats\nLH-201,150\n")

        repo.apply(db, plan, dry_run=True)
        second = repo.apply(db, plan, dry_run=True)

        assert not second.rolled_back or "already exists" not in str(second.problems)


class TestCommitting:
    def test_the_valid_rows_are_written(self, db: DbSession, campus: None) -> None:
        plan = plan_for(db, b"Room,Seats,Block\nLH-201,150,Block A\nLH-202,80,Block A\n")

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.written == 2
        assert len(structure_repo.list_rooms(db)) == 2

    def test_a_file_that_is_mostly_right_is_mostly_imported(
        self, db: DbSession, campus: None
    ) -> None:
        """Refusing 197 good rooms because three have typos is how an importer gets
        abandoned in favour of typing the data in by hand."""
        plan = plan_for(db, b"Room,Seats\nLH-201,150\nLH-202,forty\nLH-203,80\n")

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.written == 2
        assert len(plan.problems) == 1

    def test_a_write_failure_takes_the_whole_import_with_it(
        self, db: DbSession, campus: None
    ) -> None:
        """The other half of "no partial write". The first row is fine and the second
        collides with something already in the project; neither survives."""
        structure_repo.create_room(db, name="LH-202", capacity=100)
        plan = plan_for(db, b"Room,Seats\nLH-201,150\nLH-202,80\n")

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.written == 0
        assert outcome.rolled_back
        assert [room.name for room in structure_repo.list_rooms(db)] == ["LH-202"]

    def test_the_failure_names_the_row_that_caused_it(self, db: DbSession, campus: None) -> None:
        structure_repo.create_room(db, name="LH-203", capacity=100)
        plan = plan_for(db, b"Room,Seats\nLH-201,150\nLH-202,80\nLH-203,60\n")

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.problems[0].row == 4


class TestItGoesThroughTheRepository:
    def test_a_duplicate_unparented_room_is_still_refused(
        self, db: DbSession, campus: None
    ) -> None:
        """The case the backlog predicted for this phase.

        A room with no building cannot be caught by the unique constraint, because SQL
        treats each null as distinct. `create_room` is the only thing that catches it, so
        an importer doing bulk inserts would walk straight past — and this is the test
        that says it does not.
        """
        structure_repo.create_room(db, name="LH-201", capacity=100)
        plan = plan_for(db, b"Room,Seats\nLH-201,150\n")

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.rolled_back
        assert len(structure_repo.list_rooms(db)) == 1


class TestGroupsAndTheirParents:
    def test_a_parent_from_the_same_file_is_resolved(self, db: DbSession) -> None:
        """A sheet of groups almost always contains an intake and the batches beneath it.
        Resolving parents only against what already exists would reject every child."""
        plan = plan_for(
            db,
            b"Group,Students,Parent Group\n2024 Intake,0,\nA1,40,2024 Intake\nA2,40,2024 Intake\n",
        )

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.written == 3
        intake = next(g for g in groups_repo.list_groups(db) if g.name == "2024 Intake")
        children = [g for g in groups_repo.list_groups(db) if g.parent_id == intake.id]
        assert {child.name for child in children} == {"A1", "A2"}

    def test_a_child_listed_above_its_parent_still_works(self, db: DbSession) -> None:
        """Spreadsheets are not sorted for anyone's convenience."""
        plan = plan_for(db, b"Group,Students,Parent Group\nA1,40,2024 Intake\n2024 Intake,0,\n")

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.written == 2
        a1 = next(g for g in groups_repo.list_groups(db) if g.name == "A1")
        assert a1.parent_id is not None

    def test_a_parent_that_exists_in_the_project_is_used(self, db: DbSession) -> None:
        groups_repo.create_group(db, name="2024 Intake", size=0)
        plan = plan_for(db, b"Group,Students,Parent Group\nA1,40,2024 Intake\n")

        outcome = repo.apply(db, plan, dry_run=False)

        assert outcome.written == 1

    def test_a_headcount_is_derived_after_import(self, db: DbSession) -> None:
        """The point of getting the parents right: an intake entered with size 0 seats
        120 because its batches do."""
        plan = plan_for(
            db,
            b"Group,Students,Parent Group\n2024 Intake,0,\nA1,40,2024 Intake\n"
            b"A2,40,2024 Intake\nA3,40,2024 Intake\n",
        )
        repo.apply(db, plan, dry_run=False)

        known = groups_repo.group_set(db)
        intake = next(g for g in known.all if g.name == "2024 Intake")
        assert intake.id is not None
        assert known.headcount(intake.id) == 120


class TestTheCatalogue:
    def test_it_is_scoped_to_the_terms_institution(
        self, db: DbSession, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        """A project file can hold more than one institution, and `Block A` at one is not
        `Block A` at the other. Resolving across the whole file would attach a room to a
        building at a different university.
        """
        from tessera.repository import calendar as calendar_repo

        structure_repo.create_building(db, institution_id=institution.id, name="Block A")
        elsewhere = structure_repo.create_institution(db, name="Somewhere Else")
        assert elsewhere.id is not None
        structure_repo.create_building(db, institution_id=elsewhere.id, name="Annexe")
        term = calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2026-27",
            name="Autumn",
        )
        assert term.id is not None

        known = repo.catalogue_for(db, int(term.id))

        assert "Block A" in known.buildings
        assert "Annexe" not in known.buildings
