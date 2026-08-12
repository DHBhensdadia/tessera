"""Properties of the conflict relation, over randomly generated hierarchies.

The exit test for Phase 2.3, and the phase Hypothesis was chosen for back in P3.

Example-based tests can only assert what someone thought to write down. The space of
tree shapes here is large — depth, branching, which groups an elective draws from — and
the relation has to hold across all of it, because the solver builds one constraint per
conflicting pair and a single wrong answer is either a clash it permits or a timetable
it wrongly calls impossible.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import StudentGroupId


@st.composite
def hierarchies(draw: st.DrawFn) -> GroupSet:
    """A random but legal set of groups.

    Every group after the first may take any earlier group as its parent, which produces
    trees of varying depth and width while making cycles impossible by construction —
    the point is to explore *legal* shapes, since cycle rejection is tested directly.
    """
    size = draw(st.integers(min_value=1, max_value=12))
    groups: list[StudentGroup] = []

    for index in range(size):
        parent = None
        if index and draw(st.booleans()):
            parent = StudentGroupId(draw(st.integers(min_value=1, max_value=index)))
        groups.append(
            StudentGroup(
                id=StudentGroupId(index + 1),
                name=f"g{index + 1}",
                kind=GroupKind.STRUCTURAL,
                size=draw(st.integers(min_value=0, max_value=200)),
                parent_id=parent,
            )
        )

    # Optionally add an elective drawing from a few of them, since cohorts are where the
    # relation stops being pure containment.
    if size >= 2 and draw(st.booleans()):
        members = draw(
            st.lists(
                st.integers(min_value=1, max_value=size), min_size=1, max_size=size, unique=True
            )
        )
        groups.append(
            StudentGroup(
                id=StudentGroupId(size + 1),
                name="elective",
                kind=GroupKind.COHORT,
                size=0,  # a cohort's headcount comes from its members
                member_ids=frozenset(StudentGroupId(i) for i in members),
            )
        )

    return GroupSet(groups)


@settings(max_examples=250)
@given(hierarchies())
def test_a_group_always_conflicts_with_itself(groups: GroupSet) -> None:
    """Reflexive: nothing can be taught opposite itself."""
    for group in groups.all:
        assert group.id is not None
        assert groups.conflicts(group.id, group.id)


@settings(max_examples=250)
@given(hierarchies())
def test_the_relation_is_symmetric(groups: GroupSet) -> None:
    """If A cannot be taught opposite B, B cannot be taught opposite A.

    The solver builds one constraint per pair and does not care which way round it
    reads them; an asymmetric relation would mean the answer depended on iteration
    order.
    """
    ids = [g.id for g in groups.all if g.id is not None]
    for a in ids:
        for b in ids:
            assert groups.conflicts(a, b) == groups.conflicts(b, a)


@settings(max_examples=250)
@given(hierarchies())
def test_ancestors_always_conflict_with_their_descendants(groups: GroupSet) -> None:
    """A lecture for the whole intake clashes with anything scheduled for a sub-batch
    inside it — the original reason groups are a tree at all."""
    for group in groups.all:
        assert group.id is not None
        for ancestor in groups.ancestors_of(group.id):
            assert groups.conflicts(group.id, ancestor)


@settings(max_examples=250)
@given(hierarchies())
def test_conflict_is_exactly_shared_leaves(groups: GroupSet) -> None:
    """The whole relation, restated independently.

    `conflicts` is defined as intersecting leaf sets; this recomputes that from
    `leaves_of` and requires the two to agree. If the implementation ever grows a
    special case — for cohorts, say — this notices.
    """
    ids = [g.id for g in groups.all if g.id is not None]
    for a in ids:
        for b in ids:
            expected = a == b or bool(groups.leaves_of(a) & groups.leaves_of(b))
            assert groups.conflicts(a, b) == expected


@settings(max_examples=250)
@given(hierarchies())
def test_the_conflict_map_agrees_with_the_pairwise_answer(groups: GroupSet) -> None:
    """The map is materialised once so the solver reads lookups instead of recomputing
    intersections in its inner loop. It must say the same thing."""
    ids = [g.id for g in groups.all if g.id is not None]
    for a in ids:
        assert groups.conflict_map[a] == frozenset(b for b in ids if groups.conflicts(a, b))


@settings(max_examples=250)
@given(hierarchies())
def test_headcount_is_never_less_than_a_leaf(groups: GroupSet) -> None:
    """A parent must seat at least as many students as any single group inside it.

    Catches the failure that matters: a headcount too small would let the solver put an
    intake in a room that cannot hold it.
    """
    for group in groups.all:
        assert group.id is not None
        leaves = groups.leaves_of(group.id)
        if group.size == 0 and leaves:
            assert groups.headcount(group.id) == sum(groups.get(leaf).size for leaf in leaves)


@settings(max_examples=200)
@given(hierarchies())
def test_leaves_are_always_structural(groups: GroupSet) -> None:
    """Resolution bottoms out at real groups of students.

    A cohort resolving to another cohort would double-count, and an elective drawing
    from an elective is rejected at construction — this is the invariant that rejection
    protects.
    """
    for group in groups.all:
        assert group.id is not None
        for leaf in groups.leaves_of(group.id):
            assert groups.get(leaf).kind is GroupKind.STRUCTURAL
