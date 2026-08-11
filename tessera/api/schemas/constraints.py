"""Constraints.

Hard structural rules — one instructor in one place, capacity, features, availability —
never appear here. They are unconditional and are not stored, so there is nothing for a
client to configure. What is configurable is the weighted preferences and the targeted
distribution rules, which is exactly what these schemas carry.
"""

from __future__ import annotations

from pydantic import Field

from tessera.api.schemas.common import Wire
from tessera.domain.constraints import ConstraintKind, ConstraintScope


class ConstraintCreate(Wire):
    kind: ConstraintKind
    is_hard: bool = Field(
        default=False,
        description="Targeted constraints only; a global preference cannot be hard.",
    )
    weight: int = Field(default=1, ge=0, description="Cost per violation. Ignored when hard.")
    target_ids: list[int] = Field(
        default_factory=list,
        description="Sessions this applies to. Empty for global preferences.",
    )
    params: dict[str, int] = Field(default_factory=dict)
    enabled: bool = True


class ConstraintUpdate(Wire):
    weight: int | None = Field(default=None, ge=0)
    is_hard: bool | None = None
    target_ids: list[int] | None = None
    params: dict[str, int] | None = None
    enabled: bool | None = None


class ConstraintRead(Wire):
    id: int
    term_id: int
    kind: ConstraintKind
    scope: ConstraintScope = Field(description="Derived from kind; global rules take no targets.")
    is_hard: bool
    weight: int
    target_ids: list[int] = Field(default_factory=list)
    params: dict[str, int] = Field(default_factory=dict)
    enabled: bool
