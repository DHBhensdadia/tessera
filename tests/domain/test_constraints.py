"""The constraint registry, and the rules it is there to enforce.

Before 2.8 nothing checked anything about a constraint kind: two parallel dicts a kind
could be absent from without complaint, and no statement anywhere of what a kind may be
attached to. So "adding a rule is a handler, not a migration" was true only because
nothing was required of a rule. These tests are what make the claim mean something.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tessera.domain.constraints import (
    SPECS,
    Constraint,
    ConstraintKind,
    ConstraintScope,
    ConstraintTarget,
    ParamSpec,
    TargetKind,
    default_constraints,
)
from tessera.domain.ids import TermId


class TestTheRegistryIsComplete:
    def test_every_kind_has_a_spec(self) -> None:
        """Iterating the enum, not the table — a kind added without one fails here."""
        missing = sorted(kind for kind in ConstraintKind if kind not in SPECS)
        assert missing == [], f"kinds with no specification: {missing}"

    def test_no_spec_describes_a_kind_that_does_not_exist(self) -> None:
        assert set(SPECS) <= set(ConstraintKind)

    def test_every_targeted_kind_accepts_something(self) -> None:
        """A targeted kind that accepts no target kind could never be constructed."""
        for kind, spec in SPECS.items():
            if spec.scope is ConstraintScope.TARGETED:
                assert spec.targets, f"{kind} must be targeted and accepts nothing"

    def test_every_summary_can_be_filled_in(self) -> None:
        """A placeholder with no parameter behind it would raise in the console."""
        for kind, spec in SPECS.items():
            sentence = spec.describe({}, targets="Prof. Shah")
            assert sentence and "{" not in sentence, f"{kind}: {sentence}"

    def test_the_defaults_are_all_global_preferences(self) -> None:
        for constraint in default_constraints(TermId(1)):
            assert constraint.kind.scope is ConstraintScope.GLOBAL
            assert not constraint.is_hard
            assert constraint.weight > 0


class TestAKindOnlyAcceptsItsOwnTargets:
    """The check that did not exist before 2.8.

    `RESPECT_INSTRUCTOR_PREFERENCES` over a *room* was accepted and stored, and would
    have reached the solver in Stage 4 as a rule about nothing.
    """

    def test_a_room_cannot_have_time_preferences(self) -> None:
        with pytest.raises(ValidationError, match="applies to instructor, not room"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES,
                targets=frozenset({ConstraintTarget(kind=TargetKind.ROOM, id=1)}),
            )

    def test_a_distribution_rule_is_about_sessions(self) -> None:
        with pytest.raises(ValidationError, match="applies to session, not instructor"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.SAME_ROOM,
                targets=frozenset({ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=1)}),
            )

    def test_a_kind_taking_two_target_kinds_takes_both(self) -> None:
        constraint = Constraint(
            term_id=TermId(1),
            kind=ConstraintKind.BALANCE_DAILY_LOAD,
            targets=frozenset(
                {
                    ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=1),
                    ConstraintTarget(kind=TargetKind.GROUP, id=2),
                }
            ),
        )
        assert len(constraint.targets) == 2

    def test_the_wrong_kinds_are_all_named_at_once(self) -> None:
        """Fixing one and being told about the next is how a form gets abandoned."""
        with pytest.raises(ValidationError, match="not course, room"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
                targets=frozenset(
                    {
                        ConstraintTarget(kind=TargetKind.ROOM, id=1),
                        ConstraintTarget(kind=TargetKind.COURSE, id=2),
                    }
                ),
            )


class TestParameters:
    def test_a_required_parameter_is_required(self) -> None:
        with pytest.raises(ValidationError, match=r"requires parameter\(s\) \['slots'\]"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.MIN_GAP,
                targets=frozenset({ConstraintTarget(kind=TargetKind.SESSION, id=1)}),
            )

    def test_a_parameter_the_kind_does_not_take_is_refused(self) -> None:
        """Silently ignoring it would let a typo look like a setting that took effect."""
        with pytest.raises(ValidationError, match=r"takes no parameter\(s\) \['days'\]"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.MIN_GAP,
                targets=frozenset({ConstraintTarget(kind=TargetKind.SESSION, id=1)}),
                params={"slots": 2, "days": 3},
            )

    def test_a_parameter_below_its_minimum_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="slots must be between 1 and 24"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.MIN_GAP,
                targets=frozenset({ConstraintTarget(kind=TargetKind.SESSION, id=1)}),
                params={"slots": 0},
            )

    def test_a_parameter_above_its_maximum_is_refused(self) -> None:
        """ "At most 900 days between" is a rule that does nothing, entered by mistake."""
        with pytest.raises(ValidationError, match="days must be between 1 and 7"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.MAX_DAYS_BETWEEN,
                targets=frozenset({ConstraintTarget(kind=TargetKind.SESSION, id=1)}),
                params={"days": 900},
            )

    def test_a_bound_is_inclusive_at_both_ends(self) -> None:
        for days in (1, 7):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.MAX_DAYS_BETWEEN,
                targets=frozenset({ConstraintTarget(kind=TargetKind.SESSION, id=1)}),
                params={"days": days},
            )


class TestSayingItInWords:
    def test_a_rule_reads_as_a_sentence(self) -> None:
        constraint = Constraint(
            term_id=TermId(1),
            kind=ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            targets=frozenset({ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=1)}),
            params={"slots": 3},
        )
        assert constraint.describe("Prof. Shah") == "Give Prof. Shah at most 3 hour(s) in a row"

    def test_an_untargeted_preference_names_what_it_applies_to(self) -> None:
        """It said "everyone" for every kind, and this test pinned that.

        Right for the five preferences about people and groups; wrong for the two about
        courses, which produced "Avoid teaching everyone twice in one day". The word is per
        kind now, because the reading changes with the sentence — one course rule wants
        "any course" and the other wants "every course", and no rule about target kinds
        yields both.
        """
        gaps = Constraint(term_id=TermId(1), kind=ConstraintKind.MINIMISE_GROUP_GAPS)
        assert gaps.describe() == "Minimise idle gaps in the day for every group"

        courses = Constraint(term_id=TermId(1), kind=ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY)
        assert courses.describe() == "Avoid teaching any course twice in one day"

    def test_no_preference_about_courses_describes_itself_as_being_about_people(self) -> None:
        """The property, rather than two more literals to keep in step."""
        for kind in ConstraintKind:
            spec = SPECS[kind]
            if spec.scope is ConstraintScope.GLOBAL and spec.targets == {TargetKind.COURSE}:
                assert "everyone" not in spec.describe({}), kind

    def test_a_targeted_rule_never_says_everyone(self) -> None:
        """It said exactly that, and the shipped build was the only place it showed.

        A caller with no names to substitute gets kinds and ids, which is uninformative;
        "everyone" is the opposite of true.
        """
        constraint = Constraint(
            term_id=TermId(1),
            kind=ConstraintKind.MINIMISE_GROUP_GAPS,
            targets=frozenset({ConstraintTarget(kind=TargetKind.GROUP, id=7)}),
        )
        assert constraint.describe() == "Minimise idle gaps in the day for group 7"

    def test_a_missing_parameter_falls_back_to_the_default(self) -> None:
        """`describe` is called on a half-filled form, so it cannot raise."""
        assert "3 hour(s)" in SPECS[ConstraintKind.LIMIT_CONSECUTIVE_SLOTS].describe({})


class TestScope:
    def test_a_term_wide_preference_cannot_be_hard(self) -> None:
        with pytest.raises(ValidationError, match="cannot be hard"):
            Constraint(term_id=TermId(1), kind=ConstraintKind.MINIMISE_GROUP_GAPS, is_hard=True)

    def test_the_same_preference_may_be_hard_once_it_names_someone(self) -> None:
        """Decision #80. "At most 3 in a row" is checkable; "minimise gaps" is not."""
        constraint = Constraint(
            term_id=TermId(1),
            kind=ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            targets=frozenset({ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=1)}),
            params={"slots": 3},
            is_hard=True,
        )
        assert constraint.is_hard
        assert constraint.effective_weight == 0

    def test_a_targeted_kind_must_name_something(self) -> None:
        with pytest.raises(ValidationError, match="must name what it applies to"):
            Constraint(term_id=TermId(1), kind=ConstraintKind.SAME_TIME)


def test_a_kind_is_unusable_without_its_registry_entry() -> None:
    """The "one entry" claim, shown by taking the entry away.

    Every rule a constraint is held to — what it may target, what it must be given, how
    it reads — is reached through the spec, so removing one makes its kind unusable
    rather than merely undescribed. That is what makes adding an entry the whole of the
    work, and it is why `test_every_kind_has_a_spec` is worth having.
    """
    removed = SPECS.pop(ConstraintKind.MIN_GAP)  # type: ignore[attr-defined]
    try:
        with pytest.raises(KeyError):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.MIN_GAP,
                targets=frozenset({ConstraintTarget(kind=TargetKind.SESSION, id=1)}),
                params={"slots": 2},
            )
    finally:
        SPECS[ConstraintKind.MIN_GAP] = removed  # type: ignore[index]


def test_a_new_kind_needs_no_change_beyond_its_entry() -> None:
    """Adding a rule, in full: one enum member and one spec.

    Modelled by giving an existing kind an entry it did not have — the same operation an
    author performs, minus the enum member, which pydantic checks separately. What
    matters is that nothing else is consulted: no migration, no route, no schema.
    """
    spec = SPECS[ConstraintKind.LIMIT_CONSECUTIVE_SLOTS].model_copy(
        update={
            "params": {"hour": ParamSpec(label="Start before hour", maximum=24, default=4)},
            "summary": "Start {targets} before hour {hour}",
        }
    )
    original = SPECS[ConstraintKind.PREFER_ROOM_STABILITY]
    SPECS[ConstraintKind.PREFER_ROOM_STABILITY] = spec  # type: ignore[index]
    try:
        constraint = Constraint(
            term_id=TermId(1),
            kind=ConstraintKind.PREFER_ROOM_STABILITY,
            targets=frozenset({ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=1)}),
            params={"hour": 9},
        )
        assert constraint.describe("Prof. Shah") == "Start Prof. Shah before hour 9"

        with pytest.raises(ValidationError, match="hour must be between 1 and 24"):
            Constraint(
                term_id=TermId(1),
                kind=ConstraintKind.PREFER_ROOM_STABILITY,
                targets=frozenset({ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=1)}),
                params={"hour": 99},
            )
    finally:
        SPECS[ConstraintKind.PREFER_ROOM_STABILITY] = original  # type: ignore[index]
