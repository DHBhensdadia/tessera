"""Renaming and removing the structural scaffolding.

The 1.4 freeze gave institutions, departments, buildings, features and programmes `list`
and `create` and nothing else. Later phases noticed the missing deletes one at a time and
nobody noticed the missing edits at all, so until 2.4b a mistyped name was permanent.

These are the rules that arrive with the fix.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.repository import calendar as calendar_repo
from tessera.repository import groups as groups_repo
from tessera.repository import models as m
from tessera.repository import structure as repo
from tessera.repository import teaching as teaching_repo
from tessera.repository.errors import ConflictError, NotFoundError


class TestRenaming:
    def test_a_building_can_be_renamed(self, db: DbSession, institution: m.Institution) -> None:
        building = repo.create_building(db, institution_id=institution.id, name="Blok A")
        assert building.id is not None

        renamed = repo.update_building(db, building.id, changes={"name": "Block A"})

        assert renamed.name == "Block A"

    def test_renaming_onto_a_sibling_is_refused(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        repo.create_building(db, institution_id=institution.id, name="Block A")
        second = repo.create_building(db, institution_id=institution.id, name="Block B")
        assert second.id is not None

        with pytest.raises(ConflictError):
            repo.update_building(db, second.id, changes={"name": "Block A"})

    def test_renaming_to_its_own_name_is_not_a_collision(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        """`exclude_id` is what makes this a no-op rather than a collision with itself.

        The bug found in 2.1, and one that would have returned five times over if each
        of these entities had got its own copy of the rename.
        """
        building = repo.create_building(db, institution_id=institution.id, name="Block A")
        assert building.id is not None

        unchanged = repo.update_building(db, building.id, changes={"name": "Block A"})

        assert unchanged.name == "Block A"

    def test_the_same_name_is_free_in_another_institution(self, db: DbSession) -> None:
        first = repo.create_institution(db, name="One University")
        second = repo.create_institution(db, name="Two University")
        assert first.id is not None and second.id is not None
        repo.create_building(db, institution_id=first.id, name="Block A")
        theirs = repo.create_building(db, institution_id=second.id, name="Annexe")
        assert theirs.id is not None

        renamed = repo.update_building(db, theirs.id, changes={"name": "Block A"})

        assert renamed.name == "Block A"

    def test_a_department_code_can_be_set_without_touching_its_name(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        department = repo.create_department(db, institution_id=institution.id, name="Physics")
        assert department.id is not None

        updated = repo.update_department(db, department.id, changes={"code": "PHY"})

        assert updated.code == "PHY"
        assert updated.name == "Physics"

    def test_features_and_programmes_rename_the_same_way(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        feature = repo.create_feature(db, institution_id=institution.id, name="projecter")
        program = groups_repo.create_program(db, name="BTech CSE")
        assert feature.id is not None and program.id is not None

        assert (
            repo.update_feature(db, feature.id, changes={"name": "projector"}).name == "projector"
        )
        assert (
            groups_repo.update_program(db, program.id, changes={"name": "B.Tech CSE"}).name
            == "B.Tech CSE"
        )

    def test_renaming_something_that_is_not_there(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.update_building(db, 999, changes={"name": "Nowhere"})


class TestDeletingAnInstitution:
    def test_an_empty_institution_is_deleted(self, db: DbSession) -> None:
        created = repo.create_institution(db, name="Doomed University")
        assert created.id is not None

        repo.delete_institution(db, created.id)

        assert repo.list_institutions(db) == []

    def test_deleting_one_with_a_term_is_refused(
        self, db: DbSession, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        """The guard proved by breaking the thing it guards.

        An institution is the root of five cascade chains; a term reaches sessions and
        assignments beyond that. Without this, one dialog empties a project.
        """
        calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2026-27",
            name="Autumn",
        )

        with pytest.raises(ConflictError) as raised:
            repo.delete_institution(db, institution.id)

        assert raised.value.blockers["terms"] == 1
        assert raised.value.blockers["time_grids"] == 1

    def test_every_kind_of_dependant_is_counted(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        repo.create_building(db, institution_id=institution.id, name="Block A")
        repo.create_department(db, institution_id=institution.id, name="Physics")
        repo.create_feature(db, institution_id=institution.id, name="projector")

        with pytest.raises(ConflictError) as raised:
            repo.delete_institution(db, institution.id)

        assert raised.value.blockers == {"buildings": 1, "departments": 1, "features": 1}

    def test_nothing_is_destroyed_by_the_refusal(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        repo.create_building(db, institution_id=institution.id, name="Block A")

        with pytest.raises(ConflictError):
            repo.delete_institution(db, institution.id)

        assert len(repo.list_buildings(db)) == 1
        assert repo.get_institution(db, institution.id).name == institution.name


class TestDeletingADepartment:
    def test_an_empty_department_is_deleted(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        department = repo.create_department(db, institution_id=institution.id, name="Physics")
        assert department.id is not None

        repo.delete_department(db, department.id)

        assert repo.list_departments(db) == []

    def test_a_department_with_programmes_is_refused(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        department = repo.create_department(db, institution_id=institution.id, name="CSE")
        assert department.id is not None
        groups_repo.create_program(db, name="BTech CSE", department_id=department.id)

        with pytest.raises(ConflictError) as raised:
            repo.delete_department(db, department.id)

        assert raised.value.blockers == {"programs": 1}

    def test_courses_do_not_block_it_and_survive_without_it(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        """The case most likely to be guarded wrongly by reflex.

        `course.department_id` is ON DELETE SET NULL, and a course with no department is
        a state the catalogue is *designed* for — Decision #50 exists because a syllabus
        committee creates courses before ownership is settled. Blocking here would make
        that design unreachable.
        """
        department = repo.create_department(db, institution_id=institution.id, name="CSE")
        assert department.id is not None
        course = teaching_repo.create_course(
            db, code="CS101", name="Intro", department_id=department.id
        )
        assert course.id is not None

        repo.delete_department(db, department.id)

        survivor = teaching_repo.get_course(db, course.id)
        assert survivor.code == "CS101"
        assert survivor.department_id is None


class TestFetchingOneOfEach:
    def test_each_entity_can_be_fetched_by_id(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        building = repo.create_building(db, institution_id=institution.id, name="Block A")
        feature = repo.create_feature(db, institution_id=institution.id, name="projector")
        department = repo.create_department(db, institution_id=institution.id, name="CSE")
        program = groups_repo.create_program(db, name="BTech CSE")
        assert building.id and feature.id and department.id and program.id

        assert repo.get_institution(db, institution.id).name == institution.name
        assert repo.get_building(db, building.id).name == "Block A"
        assert repo.get_feature(db, feature.id).name == "projector"
        assert repo.get_department(db, department.id).name == "CSE"
        assert groups_repo.get_program(db, program.id).name == "BTech CSE"

    def test_fetching_something_that_is_not_there(self, db: DbSession) -> None:
        for fetch in (repo.get_institution, repo.get_building, repo.get_feature):
            with pytest.raises(NotFoundError):
                fetch(db, 999)
