"""Constraints, as data rather than code.

The rules that make a timetable *valid* — no instructor in two rooms at once, capacity,
required features, availability — are not stored. They are unconditional, and a
timetable violating one is not a worse timetable but an invalid one. They live in the
validator and the solver model.

Everything else is a row. Following the ITC-2019 formulation, a constraint is a
discriminator, an optional set of target sessions, a hard/soft flag and a weight. That
generality is what allows a new rule to arrive as a new handler rather than a schema
migration — and it is why institutional quirks could safely be deferred out of the
schema design (open question D).

A *global* constraint expresses a preference over the whole term and names no targets;
"minimise gaps in a student's day" is one. A *targeted* constraint applies to a specific
set of sessions; "the CS301 lab must follow its lecture" is one.

See R1 §3.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tessera.domain.ids import ConstraintId, SessionId, TermId


class ConstraintScope(StrEnum):
    GLOBAL = "global"
    TARGETED = "targeted"


class ConstraintKind(StrEnum):
    """Every rule that can be expressed as data.

    Kinds are grouped by scope. Adding one means writing a handler in the solver and
    the validator; it does not mean touching the schema.
    """

    # -- global preferences, weighted ------------------------------------------
    MINIMISE_GROUP_GAPS = "minimise_group_gaps"
    MINIMISE_INSTRUCTOR_GAPS = "minimise_instructor_gaps"
    AVOID_SAME_COURSE_TWICE_A_DAY = "avoid_same_course_twice_a_day"
    RESPECT_INSTRUCTOR_PREFERENCES = "respect_instructor_preferences"
    MINIMISE_BUILDING_CHANGES = "minimise_building_changes"
    BALANCE_DAILY_LOAD = "balance_daily_load"
    PREFER_ROOM_STABILITY = "prefer_room_stability"
    LIMIT_CONSECUTIVE_SLOTS = "limit_consecutive_slots"

    # -- distribution constraints over a set of sessions ------------------------
    SAME_TIME = "same_time"
    SAME_ROOM = "same_room"
    SAME_DAY = "same_day"
    DIFFERENT_DAY = "different_day"
    PRECEDES = "precedes"
    NOT_OVERLAP = "not_overlap"
    MIN_GAP = "min_gap"
    MAX_DAYS_BETWEEN = "max_days_between"

    @property
    def scope(self) -> ConstraintScope:
        return ConstraintScope.GLOBAL if self in _GLOBAL_KINDS else ConstraintScope.TARGETED


_GLOBAL_KINDS = frozenset(
    {
        ConstraintKind.MINIMISE_GROUP_GAPS,
        ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
        ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY,
        ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES,
        ConstraintKind.MINIMISE_BUILDING_CHANGES,
        ConstraintKind.BALANCE_DAILY_LOAD,
        ConstraintKind.PREFER_ROOM_STABILITY,
        ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
    }
)

_REQUIRED_PARAMS: dict[ConstraintKind, tuple[str, ...]] = {
    ConstraintKind.LIMIT_CONSECUTIVE_SLOTS: ("slots",),
    ConstraintKind.MIN_GAP: ("slots",),
    ConstraintKind.MAX_DAYS_BETWEEN: ("days",),
}


class Constraint(BaseModel):
    """One rule, with the strength the institution assigned it."""

    model_config = ConfigDict(frozen=True)

    id: ConstraintId | None = None
    term_id: TermId | None = None
    kind: ConstraintKind

    is_hard: bool = False
    """Hard constraints are inviolable and carry no weight; a timetable breaking one is
    rejected rather than penalised. Global preferences are always soft."""

    weight: int = Field(default=1, ge=0)
    """Cost per violation. Ignored when ``is_hard``. Surfaced as a slider, because
    institutions genuinely disagree about the relative importance of these and the
    argument should be settled by the user rather than by us."""

    target_ids: frozenset[SessionId] = frozenset()
    params: dict[str, int] = Field(default_factory=dict)
    """Deliberately narrow: every parameter these kinds need is a count of slots or
    days. Widening it later is additive."""

    enabled: bool = True

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> Constraint:
        if self.kind.scope is ConstraintScope.GLOBAL:
            if self.target_ids:
                raise ValueError(f"{self.kind} applies to the whole term and takes no targets")
            if self.is_hard:
                raise ValueError(f"{self.kind} is a preference and cannot be hard")
        elif not self.target_ids:
            raise ValueError(f"{self.kind} must name the sessions it applies to")

        missing = [p for p in _REQUIRED_PARAMS.get(self.kind, ()) if p not in self.params]
        if missing:
            raise ValueError(f"{self.kind} requires parameter(s) {missing}")
        return self

    @property
    def effective_weight(self) -> int:
        """What a violation costs. Hard constraints are not costed — they are refused."""
        return 0 if self.is_hard else self.weight


def default_constraints(term_id: TermId | None = None) -> list[Constraint]:
    """The preference set a new term starts with.

    Weights follow the emphasis in R1 §3: student time is protected more strongly than
    staff convenience, and cosmetic preferences start low so they break ties rather than
    drive the solution.
    """
    weights: dict[ConstraintKind, int] = {
        ConstraintKind.MINIMISE_GROUP_GAPS: 8,
        ConstraintKind.MINIMISE_INSTRUCTOR_GAPS: 5,
        ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY: 4,
        ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES: 4,
        ConstraintKind.MINIMISE_BUILDING_CHANGES: 3,
        ConstraintKind.BALANCE_DAILY_LOAD: 2,
        ConstraintKind.PREFER_ROOM_STABILITY: 1,
    }
    return [
        Constraint(term_id=term_id, kind=kind, weight=weight) for kind, weight in weights.items()
    ]
