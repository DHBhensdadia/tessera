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

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tessera.domain.ids import ConstraintId, SessionId, TermId


class ConstraintScope(StrEnum):
    """Whether a kind *may* apply term-wide, not whether it must.

    ``GLOBAL`` kinds take targets optionally: "minimise gaps" with no targets is the
    term-wide preference it always was, and the same kind naming Prof. Shah is that
    preference narrowed to one person. Making the narrowing a target rather than a
    separate kind is what R5 §3 F1 asked for — FET's palette is almost entirely
    per-resource, and three of ours could previously only apply to everybody or nobody.

    ``TARGETED`` kinds are meaningless without targets: "these two sessions must not
    overlap" needs to know which two.
    """

    GLOBAL = "global"
    TARGETED = "targeted"


class TargetKind(StrEnum):
    """What a constraint can be applied to.

    Until 2.7b a constraint could name **sessions and nothing else**, which meant
    "Prof. Shah teaches at most three consecutive hours" and "this division gets no more
    than two gaps a day" could not be written at all — the ordinary case in a department
    rather than an edge case.

    Adding a kind here is a handler in the solver, not a migration, which is what
    Decision #12 promised and could not deliver while the target table held one column.
    """

    SESSION = "session"
    INSTRUCTOR = "instructor"
    GROUP = "group"
    ROOM = "room"
    COURSE = "course"


class ConstraintTarget(BaseModel):
    """One thing a constraint applies to.

    A kind and an id rather than a foreign key, because no single key can point at five
    tables. The reference is checked by the repository, in the same place every other
    reference is checked.
    """

    model_config = ConfigDict(frozen=True)

    kind: TargetKind
    id: int = Field(ge=1)


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
    def spec(self) -> ConstraintSpec:
        """What this kind accepts. See :data:`SPECS`."""
        return SPECS[self]

    @property
    def scope(self) -> ConstraintScope:
        return self.spec.scope


class ParamSpec(BaseModel):
    """One parameter a kind takes, and the range it means anything over."""

    model_config = ConfigDict(frozen=True)

    label: str
    """How the interface asks for it — "at most how many hours in a row?"."""

    minimum: int = 1
    maximum: int = 100
    default: int = 1

    def check(self, value: int) -> str | None:
        if not self.minimum <= value <= self.maximum:
            return f"must be between {self.minimum} and {self.maximum}"
        return None


class ConstraintSpec(BaseModel):
    """Everything a constraint kind needs, except how to evaluate it.

    Evaluation belongs to the validator in Phase 4.1, which P5 requires be written as an
    *independent* reading of the rules — Phase 0.1 got zero cost mismatches across 21
    instances precisely because the solver model and the validator were two separate
    readings, and sharing logic would let one misreading hide inside both.

    So this is the other half: what a kind may be attached to, what it must be given, and
    how to say it in a sentence. It is what makes "adding a rule is a handler, not a
    migration" true rather than merely unfalsified — before 2.8 nothing checked anything
    about a kind, so adding one was easy only because nothing was required of it.
    """

    model_config = ConfigDict(frozen=True)

    scope: ConstraintScope
    targets: frozenset[TargetKind] = frozenset()
    """What it may be attached to. A kind with no targets listed is term-wide only."""

    params: Mapping[str, ParamSpec] = Field(default_factory=dict)
    summary: str
    """One sentence, with ``{param}`` placeholders and a ``{targets}`` slot.

    Here rather than in a template because the console needs a sentence per constraint
    and a second copy would drift from the rule it describes.
    """

    unnarrowed: str = "everyone"
    """What fills the ``{targets}`` slot when the constraint names none.

    Per kind rather than derived from :attr:`targets`, because the reading changes with the
    sentence: a rule about courses wants "any course" in one summary and "every course" in
    another, and no rule about target kinds produces both.

    It defaulted to "everyone" for every kind, which is right for the five about people and
    groups and wrong for the two about courses — "Avoid teaching **everyone** twice in one
    day" has been on the console page since 2.5 and on the wire since 2.8. Nobody noticed
    because nothing displayed the sentence beside the thing it describes until the native
    rules screen did.
    """

    def describe(self, params: Mapping[str, int], targets: str = "") -> str:
        filled = {name: params.get(name, spec.default) for name, spec in self.params.items()}
        return self.summary.format(**filled, targets=targets or self.unnarrowed).strip()


class Invariant(BaseModel):
    """A rule that is not stored, because it cannot be switched off.

    The module opens by saying these exist and until now that was the only place they were
    written down — as prose, in a docstring, in a language the client cannot read. So the
    interface had two choices: recite six sentences of its own, or say nothing. The first
    makes the client the authoritative statement of Tessera's hard rules, which is exactly
    backwards; the second leaves a person unable to find out what the solver will never do.

    They live here instead. Phase 4.1 writes the validator that *checks* them and attaches
    itself by ``key``; this is the half that can exist now, and having it means 4.1 inherits
    a list rather than inventing a second one.

    Deliberately prose-only. There is no handler, no id pretending to be one, and no
    weight — a weight on an invariant would suggest it could be traded away.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    """Stable across releases, so 4.1 can attach a checker and a report can name one."""

    statement: str
    """What is true of every valid timetable, in one sentence."""

    because: str
    """Why it is unconditional rather than a strong preference."""


INVARIANTS: tuple[Invariant, ...] = (
    Invariant(
        key="instructor_not_double_booked",
        statement="No instructor teaches two sessions at once",
        because="A person cannot be in two rooms, so a timetable that asks it is not worse — "
        "it is impossible to run.",
    ),
    Invariant(
        key="group_not_double_booked",
        statement="No student group attends two sessions at once",
        because="The same, from the students' side. A group split across two rooms means "
        "somebody misses a class.",
    ),
    Invariant(
        key="room_not_double_booked",
        statement="No room hosts two sessions at once",
        because="Two classes in one room is a collision somebody discovers at the door.",
    ),
    Invariant(
        key="room_fits_group",
        statement="A room must seat everyone assigned to it",
        because="Capacity is a fact about the building. Overfilling is not a cost to weigh "
        "against convenience.",
    ),
    Invariant(
        key="room_has_required_features",
        statement="A room must have every feature a session requires",
        because="A lab without computers cannot hold the lab, however well it scores on "
        "everything else.",
    ),
    Invariant(
        key="availability_respected",
        statement="Nothing is scheduled when a room or an instructor is unavailable",
        because="Unavailability is a statement about the world — a refurbishment, a person "
        "who is not there — rather than a preference to be balanced.",
    ),
    Invariant(
        key="breaks_protected",
        statement="Nothing is scheduled during a break, and no session runs through one",
        because="Breaks belong to the teaching week itself, so this is enforced by the grid "
        "before the solver ever sees a placement. P7 draws it as a slider; it is stronger "
        "than that, and a preference that can never be broken is a misleading control.",
    ),
)

#: The invariants by key, because everything that reports one has an id and needs a sentence.
#:
#: Derived rather than written a second time. 4.6's explainer names rules by key and must not
#: carry prose of its own — a rule whose wording lived in two places would be described one way
#: on the rules screen and another in the sentence saying why a term is impossible.
INVARIANT_BY_KEY: Mapping[str, Invariant] = {rule.key: rule for rule in INVARIANTS}


_PEOPLE_AND_GROUPS = frozenset({TargetKind.INSTRUCTOR, TargetKind.GROUP})
_SESSIONS = frozenset({TargetKind.SESSION})

SPECS: Mapping[ConstraintKind, ConstraintSpec] = {
    ConstraintKind.MINIMISE_GROUP_GAPS: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=frozenset({TargetKind.GROUP}),
        summary="Minimise idle gaps in the day for {targets}",
        unnarrowed="every group",
    ),
    ConstraintKind.MINIMISE_INSTRUCTOR_GAPS: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=frozenset({TargetKind.INSTRUCTOR}),
        summary="Minimise idle gaps in the day for {targets}",
        unnarrowed="every instructor",
    ),
    ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=frozenset({TargetKind.COURSE}),
        summary="Avoid teaching {targets} twice in one day",
        unnarrowed="any course",
    ),
    ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=frozenset({TargetKind.INSTRUCTOR}),
        summary="Respect the marked time preferences of {targets}",
        unnarrowed="every instructor",
    ),
    ConstraintKind.MINIMISE_BUILDING_CHANGES: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=_PEOPLE_AND_GROUPS,
        summary="Minimise moves between buildings for {targets}",
    ),
    ConstraintKind.BALANCE_DAILY_LOAD: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=_PEOPLE_AND_GROUPS,
        summary="Spread teaching evenly across the week for {targets}",
    ),
    ConstraintKind.PREFER_ROOM_STABILITY: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=frozenset({TargetKind.COURSE}),
        summary="Keep {targets} in the same room all week",
        unnarrowed="every course",
    ),
    ConstraintKind.LIMIT_CONSECUTIVE_SLOTS: ConstraintSpec(
        scope=ConstraintScope.GLOBAL,
        targets=_PEOPLE_AND_GROUPS,
        params={
            "slots": ParamSpec(label="Hours in a row", minimum=1, maximum=24, default=3),
        },
        summary="Give {targets} at most {slots} hour(s) in a row",
    ),
    ConstraintKind.SAME_TIME: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        summary="Start {targets} at the same time",
    ),
    ConstraintKind.SAME_ROOM: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        summary="Put {targets} in the same room",
    ),
    ConstraintKind.SAME_DAY: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        summary="Keep {targets} on the same day",
    ),
    ConstraintKind.DIFFERENT_DAY: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        summary="Keep {targets} on different days",
    ),
    ConstraintKind.PRECEDES: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        summary="Run {targets} in the order given",
    ),
    ConstraintKind.NOT_OVERLAP: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        summary="Never run {targets} at the same time",
    ),
    ConstraintKind.MIN_GAP: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        params={"slots": ParamSpec(label="Hours between", minimum=1, maximum=24, default=1)},
        summary="Leave at least {slots} hour(s) between {targets}",
    ),
    ConstraintKind.MAX_DAYS_BETWEEN: ConstraintSpec(
        scope=ConstraintScope.TARGETED,
        targets=_SESSIONS,
        params={"days": ParamSpec(label="Days apart at most", minimum=1, maximum=7, default=2)},
        summary="Keep {targets} within {days} day(s) of each other",
    ),
}
"""One entry per kind, and the enum is checked against it rather than trusted.

Adding a rule is an entry here plus an evaluator in 4.1 — no migration, no route, no
schema. ``test_every_kind_has_a_spec`` is what keeps that a fact.
"""


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

    targets: frozenset[ConstraintTarget] = frozenset()
    """What this applies to. Empty for a global preference."""

    params: dict[str, int] = Field(default_factory=dict)
    """Deliberately narrow: every parameter these kinds need is a count of slots or
    days. Widening it later is additive."""

    enabled: bool = True

    @property
    def target_ids(self) -> frozenset[SessionId]:
        """The sessions this applies to.

        Kept because the frozen API contract speaks in session ids, and because most
        distribution constraints are over sessions. Derived rather than stored, so there
        is one place a target lives and the two cannot disagree.
        """
        return frozenset(SessionId(t.id) for t in self.targets if t.kind is TargetKind.SESSION)

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> Constraint:
        spec = self.kind.spec

        if not self.targets:
            if spec.scope is ConstraintScope.TARGETED:
                raise ValueError(f"{self.kind} must name what it applies to")
            # A term-wide preference cannot be hard, because nothing satisfies "minimise
            # gaps" absolutely — there is no timetable it would accept. Narrowed to a
            # resource the same kind becomes a checkable rule ("Prof. Shah: at most 3
            # consecutive hours"), which an institution may well insist on, so the ban
            # applies to being untargeted rather than to the kind.
            if self.is_hard:
                raise ValueError(f"{self.kind} applies to the whole term and cannot be hard")

        wrong = sorted({t.kind for t in self.targets} - spec.targets)
        if wrong:
            allowed = ", ".join(sorted(spec.targets)) or "nothing"
            raise ValueError(f"{self.kind} applies to {allowed}, not {', '.join(wrong)}")

        missing = sorted(set(spec.params) - set(self.params))
        if missing:
            raise ValueError(f"{self.kind} requires parameter(s) {missing}")

        unknown = sorted(set(self.params) - set(spec.params))
        if unknown:
            raise ValueError(f"{self.kind} takes no parameter(s) {unknown}")

        for name, param in spec.params.items():
            complaint = param.check(self.params[name])
            if complaint is not None:
                raise ValueError(f"{name} {complaint}")
        return self

    def describe(self, targets: str = "") -> str:
        """This rule as a sentence, for the interface. See :class:`ConstraintSpec`.

        ``targets`` is the resolved names, which only a caller holding the database can
        supply. Without them a *targeted* rule falls back to naming kinds and ids rather
        than to "everyone" — which would be the opposite of true, and was: the API
        reported "Give everyone at most 3 hour(s) in a row" for a rule about one person.
        """
        if targets:
            return self.kind.spec.describe(self.params, targets)
        if not self.targets:
            return self.kind.spec.describe(self.params)
        listed = ", ".join(
            f"{t.kind.value} {t.id}"
            for t in sorted(self.targets, key=lambda t: (t.kind.value, t.id))
        )
        return self.kind.spec.describe(self.params, listed)

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
