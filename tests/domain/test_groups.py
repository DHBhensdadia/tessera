"""Student groups and the conflict relation.

The conflict relation decides whether two sessions may share a slot, so an error here
produces timetables that look valid and are not. It is checked against a deliberately
slow reference implementation over generated trees, on the same principle the Phase 0.1
spike established: agreement between two independent readings is evidence, one reading
passing its own test is not.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from tessera.domain import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import StudentGroupId


def gid(value: int) -> StudentGroupId:
    return StudentGroupId(value)


def group(
    value: int,
    *,
    parent: int | None = None,
    size: int = 0,
    members: set[int] | None = None,
) -> StudentGroup:
    return StudentGroup(
        id=gid(value),
        name=f"g{value}",
        size=size,
        kind=GroupKind.COHORT if members else GroupKind.STRUCTURAL,
        parent_id=gid(parent) if parent is not None else None,
        member_ids=frozenset(gid(m) for m in (members or set())),
    )


@pytest.fixture
def department() -> GroupSet:
    """A realistic shape: one intake split into two lab batches, plus a second intake,
    and an elective drawing from both."""
    return GroupSet(
        [
            group(1, size=0),  # B.Tech CSE
            group(2, parent=1, size=0),  # 2024 intake
            group(3, parent=2, size=40),  # lab batch A1
            group(4, parent=2, size=40),  # lab batch A2
            group(5, parent=1, size=0),  # 2025 intake
            group(6, parent=5, size=35),  # lab batch B1
            group(7, members={2, 5}),  # elective across both intakes
        ]
    )


class TestStructure:
    def test_leaves_resolve_through_the_tree(self, department: GroupSet) -> None:
        assert department.leaves_of(gid(2)) == {gid(3), gid(4)}
        assert department.leaves_of(gid(1)) == {gid(3), gid(4), gid(6)}

    def test_a_leaf_contains_itself(self, department: GroupSet) -> None:
        assert department.leaves_of(gid(3)) == {gid(3)}

    def test_a_cohort_resolves_through_its_members(self, department: GroupSet) -> None:
        assert department.leaves_of(gid(7)) == {gid(3), gid(4), gid(6)}

    def test_ancestors_walk_to_the_root(self, department: GroupSet) -> None:
        assert department.ancestors_of(gid(3)) == (gid(2), gid(1))

    def test_headcount_falls_back_to_the_leaf_sum(self, department: GroupSet) -> None:
        """A parent left at zero means unfilled, not empty."""
        assert department.headcount(gid(2)) == 80
        assert department.headcount(gid(3)) == 40


class TestConflicts:
    def test_a_parent_conflicts_with_its_child(self, department: GroupSet) -> None:
        assert department.conflicts(gid(2), gid(3))

    def test_siblings_do_not_conflict(self, department: GroupSet) -> None:
        """The whole point of splitting a batch: two lab groups run in parallel."""
        assert not department.conflicts(gid(3), gid(4))

    def test_unrelated_branches_do_not_conflict(self, department: GroupSet) -> None:
        assert not department.conflicts(gid(3), gid(6))

    def test_a_cohort_conflicts_with_everything_it_draws_from(self, department: GroupSet) -> None:
        """An elective cannot be taught opposite a lecture its students must attend —
        the case a plain tree cannot express."""
        assert department.conflicts(gid(7), gid(2))
        assert department.conflicts(gid(7), gid(3))
        assert department.conflicts(gid(7), gid(6))

    def test_a_group_conflicts_with_itself(self, department: GroupSet) -> None:
        assert department.conflicts(gid(3), gid(3))

    def test_conflict_map_agrees_with_pairwise_checks(self, department: GroupSet) -> None:
        for a in department.all:
            for b in department.all:
                assert a.id is not None and b.id is not None
                assert (b.id in department.conflict_map[a.id]) == department.conflicts(a.id, b.id)


class TestRejectsBadData:
    def test_unknown_parent(self) -> None:
        with pytest.raises(ValueError, match="unknown parent"):
            GroupSet([group(1, parent=99)])

    def test_unknown_member(self) -> None:
        with pytest.raises(ValueError, match="unknown member"):
            GroupSet([group(1, members={99})])

    def test_a_cycle_is_caught_rather_than_hanging(self) -> None:
        with pytest.raises(ValueError, match="cycle"):
            GroupSet([group(1, parent=2), group(2, parent=1)])

    def test_duplicate_ids(self) -> None:
        with pytest.raises(ValueError, match="duplicate group id"):
            GroupSet([group(1), group(1)])

    def test_unpersisted_groups(self) -> None:
        with pytest.raises(ValueError, match="must be persisted"):
            GroupSet([StudentGroup(name="nameless", size=1)])

    def test_a_cohort_may_not_have_a_parent(self) -> None:
        with pytest.raises(ValidationError, match="cannot have a parent"):
            StudentGroup(
                id=gid(1),
                name="x",
                size=0,
                kind=GroupKind.COHORT,
                parent_id=gid(2),
                member_ids=frozenset({gid(3)}),
            )

    def test_a_cohort_must_name_members(self) -> None:
        with pytest.raises(ValidationError, match="must name its member groups"):
            StudentGroup(id=gid(1), name="x", size=0, kind=GroupKind.COHORT)

    def test_a_structural_group_may_not_list_members(self) -> None:
        with pytest.raises(ValidationError, match="through the tree"):
            StudentGroup(
                id=gid(1),
                name="x",
                size=0,
                member_ids=frozenset({gid(2)}),
                kind=GroupKind.STRUCTURAL,
            )

    def test_a_cohort_may_not_draw_from_another_cohort(self) -> None:
        with pytest.raises(ValueError, match="only draw from structural"):
            GroupSet([group(1, size=1), group(2, members={1}), group(3, members={2})])


class TestAgainstAReferenceImplementation:
    @staticmethod
    def _reference_conflicts(groups: list[StudentGroup], a: int, b: int) -> bool:
        """Deliberately naive: walk ancestry both ways rather than compare leaf sets.

        Only valid for pure trees, which is why the generated cases below build trees
        rather than cohorts.
        """
        by_id = {int(g.id): g for g in groups if g.id is not None}

        def ancestry(start: int) -> set[int]:
            chain = {start}
            node = by_id[start]
            while node.parent_id is not None:
                chain.add(int(node.parent_id))
                node = by_id[int(node.parent_id)]
            return chain

        return a in ancestry(b) or b in ancestry(a)

    @given(
        parents=st.lists(st.integers(-1, 8), min_size=2, max_size=9),
        pair=st.tuples(st.integers(0, 8), st.integers(0, 8)),
    )
    def test_leaf_sets_match_ancestry_walking_on_trees(
        self, parents: list[int], pair: tuple[int, int]
    ) -> None:
        # Parent index must be strictly smaller, which makes cycles impossible and
        # keeps the generated structure a forest.
        groups = [
            group(i, parent=(parents[i] if 0 <= parents[i] < i else None), size=1)
            for i in range(len(parents))
        ]
        a, b = pair
        if a >= len(groups) or b >= len(groups):
            return

        group_set = GroupSet(groups)
        assert group_set.conflicts(gid(a), gid(b)) == self._reference_conflicts(groups, a, b)
