"""Constraints.

Hard structural rules — one instructor in one place, capacity, features, availability —
never appear here. They are unconditional and are not stored, so there is nothing for a
client to configure. What is configurable is the weighted preferences and the targeted
distribution rules, which is exactly what these schemas carry.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from tessera.api.schemas.common import Wire
from tessera.domain.constraints import ConstraintKind, ConstraintScope, TargetKind


class TargetWire(Wire):
    """One thing a constraint applies to."""

    kind: TargetKind
    id: int = Field(ge=1)


class _HasTargets(Wire):
    """The two spellings of a target set, and the rule that only one may be used.

    ``target_ids`` came from the 1.4 contract, when a constraint could name sessions and
    nothing else. It is kept — removing a field breaks consumers, and it is still the
    shorter way to say the commonest thing — but it can only ever mean sessions.

    Sending both is refused rather than merged. They are two spellings of one field, and
    quietly unioning them makes "clear the targets" ambiguous: under PATCH an empty
    ``target_ids`` beside a populated ``targets`` has no single obvious reading.
    """

    @model_validator(mode="after")
    def _only_one_spelling(self) -> _HasTargets:
        sent = self.model_fields_set
        if "targets" in sent and "target_ids" in sent:
            raise ValueError("send either targets or target_ids, not both")
        return self


class ConstraintCreate(_HasTargets):
    kind: ConstraintKind
    is_hard: bool = Field(
        default=False,
        description="Only a rule that names its targets may be hard.",
    )
    weight: int = Field(default=1, ge=0, description="Cost per violation. Ignored when hard.")
    target_ids: list[int] = Field(
        default_factory=list,
        description="Sessions this applies to. Shorthand for targets of kind 'session'.",
    )
    targets: list[TargetWire] = Field(
        default_factory=list,
        description="What this applies to. Empty for a term-wide preference.",
    )
    params: dict[str, int] = Field(default_factory=dict)
    enabled: bool = True


class ConstraintUpdate(_HasTargets):
    weight: int | None = Field(default=None, ge=0)
    is_hard: bool | None = None
    target_ids: list[int] | None = None
    targets: list[TargetWire] | None = None
    params: dict[str, int] | None = None
    enabled: bool | None = None


class ConstraintRead(Wire):
    id: int
    term_id: int
    kind: ConstraintKind
    scope: ConstraintScope = Field(
        description="Derived from kind. 'global' may apply term-wide or be narrowed.",
    )
    is_hard: bool
    weight: int
    target_ids: list[int] = Field(
        default_factory=list, description="The session targets, for 1.4 consumers."
    )
    targets: list[TargetWire] = Field(default_factory=list)
    params: dict[str, int] = Field(default_factory=dict)
    enabled: bool
    summary: str = Field(description="The rule as a sentence, for display.")
