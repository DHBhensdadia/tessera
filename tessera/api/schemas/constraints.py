"""Constraints, and the catalogue that describes what one may be.

Hard structural rules — one instructor in one place, capacity, features, availability —
are never *stored*. They are unconditional, so there is nothing for a client to configure.
They do appear here, on the catalogue, because an interface that cannot say what the solver
will never do is hiding half the model from the person using it.

What is configurable is the weighted preferences and the targeted distribution rules, which
is what the rest of these schemas carry.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from tessera.api.schemas.common import Wire
from tessera.domain.constraints import (
    INVARIANTS,
    SPECS,
    ConstraintKind,
    ConstraintScope,
    Invariant,
    TargetKind,
)


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


# -- the catalogue ------------------------------------------------------------------
#
# Everything below describes what a constraint *may be*, rather than one that exists.
#
# It is published because `SPECS` lives in the domain and the console reads it by importing
# it — which works only because the console runs inside the engine. A native client had no
# way to learn which kinds exist, what each may be attached to, or what parameters it takes,
# so it could not offer to create one without a hand-written copy of `SPECS` in Swift.
#
# That copy is what Decision #5 forbids and what `ConstraintSpec` warns about in its own
# docstring: "a second copy would drift from the rule it describes." So the catalogue is
# *derived* from `SPECS` in `of()` below rather than restated, and a test asserts the two
# agree — adding a kind publishes it, and there is nothing to keep in step by hand.


class ParamRead(Wire):
    """One parameter a kind takes, and the range it means anything over."""

    name: str
    label: str = Field(description="How to ask for it — 'Hours in a row'.")
    minimum: int
    maximum: int
    default: int


class ConstraintKindRead(Wire):
    """One rule that could be created, and everything needed to offer it."""

    kind: ConstraintKind
    scope: ConstraintScope = Field(
        description="'global' may apply term-wide or be narrowed to named targets; "
        "'targeted' is meaningless without them.",
    )
    targets: list[TargetKind] = Field(
        description="What it may be attached to. Empty means term-wide only.",
    )
    params: list[ParamRead] = Field(default_factory=list)
    summary_template: str = Field(
        description="The rule as a sentence, with {name} placeholders for each parameter "
        "and {targets} for what it applies to. Placeholders are bare — no format specs — "
        "so a client can fill them in as a form is typed rather than asking per keystroke.",
    )
    example: str = Field(
        description="The template filled with defaults, for a menu of kinds to read.",
    )

    @classmethod
    def of(cls, kind: ConstraintKind) -> ConstraintKindRead:
        spec = SPECS[kind]
        return cls(
            kind=kind,
            scope=spec.scope,
            # Sorted so the wire order is stable: `targets` is a frozenset, whose iteration
            # order is not, and a contract snapshot that reshuffles between runs is a guard
            # that fails for no reason.
            targets=sorted(spec.targets, key=lambda t: t.value),
            params=[
                ParamRead(
                    name=name,
                    label=param.label,
                    minimum=param.minimum,
                    maximum=param.maximum,
                    default=param.default,
                )
                for name, param in sorted(spec.params.items())
            ],
            summary_template=spec.summary,
            example=spec.describe({}, "…"),
        )


class InvariantRead(Wire):
    """A rule that cannot be switched off."""

    key: str
    statement: str
    because: str

    @classmethod
    def of(cls, invariant: Invariant) -> InvariantRead:
        return cls(key=invariant.key, statement=invariant.statement, because=invariant.because)


class ConstraintCatalogue(Wire):
    """What a constraint may be, and what is true regardless.

    Both halves in one response because they are one screen and one question — *what can I
    change, and what can I not?* — and answering it in two round trips would let an
    interface render half of it.
    """

    kinds: list[ConstraintKindRead]
    invariants: list[InvariantRead] = Field(
        description="Never stored and never configurable. Listed so an interface can "
        "explain what the solver will always do.",
    )

    @classmethod
    def build(cls) -> ConstraintCatalogue:
        return cls(
            kinds=[ConstraintKindRead.of(kind) for kind in ConstraintKind],
            invariants=[InvariantRead.of(i) for i in INVARIANTS],
        )
