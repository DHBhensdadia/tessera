"""Student groups and the conflict relation derived from them.

A programme's groups form a tree — programme, intake, lab sub-batch — and a lecture for
an intake conflicts with a lab for one of its sub-batches, because the same students sit
in both. A flat list of groups cannot express that and breaks at the first lab split.

Electives break the tree, though: "Machine Learning" draws students from three intakes
at once and is nobody's child. Modelling that as another tree node would be a lie, so
cross-cutting groups are a separate kind that names its members explicitly.

Both cases reduce to the same question — *do these two groups share any students?* —
which is answered by comparing leaf sets:

    conflict(a, b)  <=>  leaves(a) & leaves(b) != {}

Ancestry falls out of this for free: an intake's leaf set contains its sub-batches'.

See R1 §2.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tessera.domain.ids import ProgramId, StudentGroupId


class GroupKind(StrEnum):
    """How a group gets its members."""

    STRUCTURAL = "structural"
    """A node in the programme tree: a programme, an intake, a lab sub-batch."""

    COHORT = "cohort"
    """A cross-cutting set — an elective — that names its constituent groups."""


class StudentGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: StudentGroupId | None = None
    program_id: ProgramId | None = None
    name: str = Field(min_length=1)
    kind: GroupKind = GroupKind.STRUCTURAL
    size: int = Field(ge=0)

    parent_id: StudentGroupId | None = None
    """Structural groups only. ``None`` marks a root."""

    member_ids: frozenset[StudentGroupId] = frozenset()
    """Cohort groups only: the structural groups it draws students from."""

    @model_validator(mode="after")
    def _kind_and_links_agree(self) -> StudentGroup:
        if self.kind is GroupKind.COHORT:
            if self.parent_id is not None:
                raise ValueError(f"cohort group {self.name!r} cannot have a parent")
            if not self.member_ids:
                raise ValueError(f"cohort group {self.name!r} must name its member groups")
        elif self.member_ids:
            raise ValueError(
                f"structural group {self.name!r} takes members through the tree, "
                "not an explicit list"
            )
        return self


class GroupSet:
    """All groups in a term, with the conflict relation resolved once.

    Built at load time and treated as immutable. Every clash check the solver and the
    validator perform goes through :meth:`conflicts`, so it must be a lookup rather than
    a traversal.
    """

    def __init__(self, groups: list[StudentGroup]) -> None:
        missing = [g.name for g in groups if g.id is None]
        if missing:
            raise ValueError(f"groups must be persisted before use: {missing}")

        self._by_id: dict[StudentGroupId, StudentGroup] = {}
        for group in groups:
            assert group.id is not None  # narrowed by the check above
            if group.id in self._by_id:
                raise ValueError(f"duplicate group id {group.id}")
            self._by_id[group.id] = group

        self._validate_references()
        self._reject_cycles()

    # -- construction checks -----------------------------------------------------

    def _validate_references(self) -> None:
        for group in self._by_id.values():
            if group.parent_id is not None and group.parent_id not in self._by_id:
                raise ValueError(f"{group.name!r} names unknown parent {group.parent_id}")
            for member in group.member_ids:
                if member not in self._by_id:
                    raise ValueError(f"{group.name!r} names unknown member {member}")
                if self._by_id[member].kind is not GroupKind.STRUCTURAL:
                    raise ValueError(
                        f"cohort {group.name!r} may only draw from structural groups, "
                        f"but {self._by_id[member].name!r} is a cohort"
                    )

    def _reject_cycles(self) -> None:
        """A parent chain that loops would make leaf resolution non-terminating."""
        for start in self._by_id.values():
            seen: set[StudentGroupId] = set()
            current = start
            while current.parent_id is not None:
                assert current.id is not None
                seen.add(current.id)
                if current.parent_id in seen:
                    raise ValueError(f"group hierarchy contains a cycle at {start.name!r}")
                current = self._by_id[current.parent_id]

    # -- structure ---------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, group_id: StudentGroupId) -> bool:
        return group_id in self._by_id

    def get(self, group_id: StudentGroupId) -> StudentGroup:
        return self._by_id[group_id]

    @property
    def all(self) -> tuple[StudentGroup, ...]:
        return tuple(self._by_id.values())

    @cached_property
    def _children(self) -> dict[StudentGroupId, list[StudentGroupId]]:
        children: dict[StudentGroupId, list[StudentGroupId]] = {gid: [] for gid in self._by_id}
        for group in self._by_id.values():
            if group.parent_id is not None:
                assert group.id is not None
                children[group.parent_id].append(group.id)
        return children

    def children_of(self, group_id: StudentGroupId) -> tuple[StudentGroupId, ...]:
        return tuple(self._children[group_id])

    def ancestors_of(self, group_id: StudentGroupId) -> tuple[StudentGroupId, ...]:
        chain: list[StudentGroupId] = []
        current = self._by_id[group_id]
        while current.parent_id is not None:
            chain.append(current.parent_id)
            current = self._by_id[current.parent_id]
        return tuple(chain)

    # -- the part everything else depends on --------------------------------------

    @cached_property
    def _leaves(self) -> dict[StudentGroupId, frozenset[StudentGroupId]]:
        """The structural leaf groups each group ultimately contains.

        Computed iteratively rather than recursively: a deep programme hierarchy is
        unlikely to blow the stack, but the tree comes from user data and it costs
        nothing to be certain.
        """
        resolved: dict[StudentGroupId, frozenset[StudentGroupId]] = {}

        def structural_leaves(gid: StudentGroupId) -> frozenset[StudentGroupId]:
            if gid in resolved:
                return resolved[gid]
            stack = [gid]
            found: set[StudentGroupId] = set()
            while stack:
                current = stack.pop()
                kids = self._children[current]
                if kids:
                    stack.extend(kids)
                else:
                    found.add(current)
            resolved[gid] = frozenset(found)
            return resolved[gid]

        leaves: dict[StudentGroupId, frozenset[StudentGroupId]] = {}
        for gid, group in self._by_id.items():
            if group.kind is GroupKind.COHORT:
                leaves[gid] = frozenset().union(*(structural_leaves(m) for m in group.member_ids))
            else:
                leaves[gid] = structural_leaves(gid)
        return leaves

    def leaves_of(self, group_id: StudentGroupId) -> frozenset[StudentGroupId]:
        return self._leaves[group_id]

    def conflicts(self, a: StudentGroupId, b: StudentGroupId) -> bool:
        """Whether two groups share students and so cannot be taught at once."""
        if a == b:
            return True
        return bool(self._leaves[a] & self._leaves[b])

    @cached_property
    def conflict_map(self) -> dict[StudentGroupId, frozenset[StudentGroupId]]:
        """Every group mapped to those it clashes with, including itself.

        Materialised once so the solver builds constraints from lookups rather than
        recomputing intersections inside its inner loop.
        """
        ids = list(self._by_id)
        result: dict[StudentGroupId, set[StudentGroupId]] = {gid: {gid} for gid in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if self._leaves[a] & self._leaves[b]:
                    result[a].add(b)
                    result[b].add(a)
        return {gid: frozenset(peers) for gid, peers in result.items()}

    def headcount(self, group_id: StudentGroupId) -> int:
        """Students to seat: a group's own size, or the sum of its leaves if unset.

        Sizes are recorded per group, but a parent left at zero is far more likely to
        mean "nobody filled this in" than "this intake has no students", so the leaf
        sum is used instead of trusting the zero.
        """
        group = self._by_id[group_id]
        if group.size:
            return group.size
        return sum(self._by_id[leaf].size for leaf in self._leaves[group_id])
