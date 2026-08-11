"""Student groups.

The tree and the cohort kind both appear on the wire, because the client renders an
outline and needs to distinguish "a sub-batch of this intake" from "an elective drawing
from three intakes" — they look the same in a flat list and behave differently.
"""

from __future__ import annotations

from pydantic import Field

from tessera.api.schemas.common import Wire
from tessera.domain.groups import GroupKind


class StudentGroupCreate(Wire):
    program_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    kind: GroupKind = GroupKind.STRUCTURAL
    size: int = Field(default=0, ge=0)
    parent_id: int | None = Field(
        default=None, description="Structural groups only. Null marks a root."
    )
    member_ids: list[int] = Field(
        default_factory=list,
        description="Cohort groups only: the structural groups it draws students from.",
    )


class StudentGroupUpdate(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    size: int | None = Field(default=None, ge=0)
    parent_id: int | None = None
    member_ids: list[int] | None = None


class StudentGroupRead(Wire):
    id: int
    name: str
    kind: GroupKind
    size: int
    parent_id: int | None
    member_ids: list[int] = Field(default_factory=list)
    headcount: int = Field(
        default=0,
        description="Students to seat: the group's own size, or the sum of its leaves when unset.",
    )


class StudentGroupTree(Wire):
    """A node in the resolved hierarchy, for the outline view."""

    id: int
    name: str
    kind: GroupKind
    size: int
    headcount: int = 0
    children: list[StudentGroupTree] = Field(default_factory=list)
