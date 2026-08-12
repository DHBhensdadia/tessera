"""Programmes and groups, and the rules the domain enforces on their behalf.

The conflict relation itself is covered by property tests in
`tests/domain/test_groups_properties.py`. These check that writes reach the domain for
validation rather than being waved through, and that deletion refuses rather than
cascading silently.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain.groups import GroupKind
from tessera.repository import groups as repo
from tessera.repository.errors import ConflictError, NotFoundError


def ident(entity: object) -> int:
    value = getattr(entity, "id", None)
    assert value is not None
    return int(value)


@pytest.fixture
def batch(db: DbSession) -> int:
    """An intake with three lab sub-batches — the shape every timetable has."""
    parent = ident(repo.create_group(db, name="2024 CSE"))
    for i in (1, 2, 3):
        repo.create_group(db, name=f"Lab A{i}", size=40, parent_id=parent)
    return parent


class TestValidationReachesTheDomain:
    def test_a_group_cannot_become_its_own_ancestor(self, db: DbSession, batch: int) -> None:
        """The dangerous edit. Leaf resolution would loop forever.

        The check is not written in the repository — the prospective set is handed to
        `GroupSet`, which refuses it. This asserts that route is actually taken.
        """
        child = ident(repo.list_groups(db, program_id=None)[0])
        lab = next(g for g in repo.list_groups(db) if g.name == "Lab A1")

        with pytest.raises(ConflictError, match="cycle"):
            repo.update_group(db, batch, changes={"parent_id": ident(lab)})
        assert child  # silence the unused warning; the fixture shape matters

    def test_a_group_cannot_be_its_own_parent(self, db: DbSession, batch: int) -> None:
        with pytest.raises(ConflictError, match="cycle"):
            repo.update_group(db, batch, changes={"parent_id": batch})

    def test_an_unknown_parent_is_refused(self, db: DbSession) -> None:
        with pytest.raises(ConflictError, match="unknown parent"):
            repo.create_group(db, name="Orphan", parent_id=999_999)

    def test_a_cohort_may_not_draw_from_another_cohort(self, db: DbSession, batch: int) -> None:
        """Resolution must bottom out at real groups of students, or an elective drawing
        from an elective would double-count them."""
        lab = next(g for g in repo.list_groups(db) if g.name == "Lab A1")
        first = repo.create_group(db, name="ML", kind=GroupKind.COHORT, member_ids=[ident(lab)])

        with pytest.raises(ConflictError, match="structural"):
            repo.create_group(
                db, name="Advanced ML", kind=GroupKind.COHORT, member_ids=[ident(first)]
            )

    def test_an_unknown_member_is_refused(self, db: DbSession, batch: int) -> None:
        with pytest.raises(ConflictError, match="unknown member"):
            repo.create_group(db, name="ML", kind=GroupKind.COHORT, member_ids=[999_999])

    def test_a_rejected_write_leaves_nothing_behind(self, db: DbSession) -> None:
        """Validation happens before the insert, so a refusal does not consume an id or
        leave a half-written row to explain."""
        before = len(repo.list_groups(db))

        with pytest.raises(ConflictError):
            repo.create_group(db, name="Orphan", parent_id=999_999)

        assert len(repo.list_groups(db)) == before


class TestConflicts:
    def test_a_sub_batch_clashes_with_its_intake(self, db: DbSession, batch: int) -> None:
        lab = next(g for g in repo.list_groups(db) if g.name == "Lab A1")
        assert batch in repo.conflicts_of(db, ident(lab))

    def test_sibling_sub_batches_do_not_clash(self, db: DbSession, batch: int) -> None:
        """Three labs running in parallel is the entire point of splitting a batch."""
        labs = [g for g in repo.list_groups(db) if g.name.startswith("Lab")]
        assert ident(labs[1]) not in repo.conflicts_of(db, ident(labs[0]))

    def test_an_elective_clashes_with_what_it_draws_from(self, db: DbSession, batch: int) -> None:
        labs = sorted(
            (g for g in repo.list_groups(db) if g.name.startswith("Lab")), key=lambda g: g.name
        )
        elective = repo.create_group(
            db,
            name="Machine Learning",
            kind=GroupKind.COHORT,
            member_ids=[ident(labs[0]), ident(labs[1])],
        )

        clashes = repo.conflicts_of(db, ident(elective))
        assert ident(labs[0]) in clashes
        assert ident(labs[1]) in clashes
        assert batch in clashes  # shares students with the intake above them
        assert ident(labs[2]) not in clashes

    def test_conflicts_of_an_unknown_group(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.conflicts_of(db, 999_999)


class TestDeletion:
    def test_an_intake_with_sub_batches_is_refused(self, db: DbSession, batch: int) -> None:
        """`parent_id` is ON DELETE CASCADE, so without this check a mis-click would
        silently take all three lab groups with it."""
        with pytest.raises(ConflictError) as raised:
            repo.delete_group(db, batch)

        assert raised.value.blockers == {"sub_groups": 3}

    def test_a_group_an_elective_draws_from_is_refused(self, db: DbSession, batch: int) -> None:
        lab = next(g for g in repo.list_groups(db) if g.name == "Lab A1")
        repo.create_group(db, name="ML", kind=GroupKind.COHORT, member_ids=[ident(lab)])

        with pytest.raises(ConflictError) as raised:
            repo.delete_group(db, ident(lab))

        assert raised.value.blockers == {"cohorts": 1}

    def test_a_leaf_with_nothing_hanging_off_it_is_removed(self, db: DbSession, batch: int) -> None:
        lab = next(g for g in repo.list_groups(db) if g.name == "Lab A3")
        repo.delete_group(db, ident(lab))
        assert [g.name for g in repo.list_groups(db)] == ["2024 CSE", "Lab A1", "Lab A2"]

    def test_a_programme_with_groups_is_refused(self, db: DbSession) -> None:
        program = repo.create_program(db, name="B.Tech CSE")
        repo.create_group(db, name="2024 CSE", program_id=ident(program))

        with pytest.raises(ConflictError) as raised:
            repo.delete_program(db, ident(program))

        assert raised.value.blockers == {"student_groups": 1}

    def test_an_empty_programme_is_removed(self, db: DbSession) -> None:
        program = repo.create_program(db, name="B.Tech ECE")
        repo.delete_program(db, ident(program))
        assert repo.list_programs(db) == []


class TestNaming:
    def test_two_intakes_may_each_have_a_lab_a1(self, db: DbSession) -> None:
        """Names are scoped to the parent — every intake has a Lab A1."""
        first = ident(repo.create_group(db, name="2024 CSE"))
        second = ident(repo.create_group(db, name="2025 CSE"))

        repo.create_group(db, name="Lab A1", parent_id=first)
        repo.create_group(db, name="Lab A1", parent_id=second)

        assert len(repo.list_groups(db)) == 4

    def test_one_intake_may_not_have_two(self, db: DbSession, batch: int) -> None:
        with pytest.raises(ConflictError):
            repo.create_group(db, name="Lab A1", parent_id=batch)


def test_the_repository_does_not_reimplement_the_hierarchy() -> None:
    """The phase's central decision, asserted structurally.

    Cycle detection and leaf resolution live in `domain/groups.py`. Walking the tree in
    SQL here would be a second implementation, in a second language, obliged to agree
    with the first forever — and the two would drift.

    Parsed rather than grepped: a first attempt searched the text for "recursive" and
    tripped over the module docstring explaining why there is no recursive query. A
    guard that fires on its own documentation gets deleted rather than heeded.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "tessera/repository/groups.py").read_text()
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    leaked = called & {"cte", "union_all", "recursive"}
    assert not leaked, f"hierarchy logic leaked into SQL: {sorted(leaked)}"
