"""Each of the sixteen kinds, shown to respond to the thing it measures.

Same discipline as the invariants: a rule that never fires is indistinguishable from one that
works, so each is given a timetable built to break it and a timetable that satisfies it. The
second half matters as much as the first — a rule that fires on everything is no more useful
than one that fires on nothing, and only asserting the failure would not tell them apart.

Nothing is in force by default. Every test names the rule it is about, which keeps the
invariant suite's baseline clean and makes each rule's cost attributable to the rule.
"""

from __future__ import annotations

import pytest

from tessera.domain.constraints import (
    Constraint,
    ConstraintKind,
    ConstraintTarget,
    TargetKind,
)
from tessera.domain.entities import Unavailability
from tessera.domain.ids import InstructorId
from tessera.domain.validation import Report, validate, validate_move
from tessera.domain.validation.rules import EVALUATORS, ON_A_MOVE
from tests.domain.validation.institution import (
    BATCH_B,
    COMPUTING,
    LAB,
    LAB_A,
    LAB_B,
    LECTURE,
    STUDIO,
    TUTORIAL,
    Institution,
)


def rule(
    kind: ConstraintKind, *sessions: int, weight: int = 1, hard: bool = False, **params: int
) -> Constraint:
    return Constraint(
        kind=kind,
        is_hard=hard,
        weight=weight,
        targets=frozenset(ConstraintTarget(kind=TargetKind.SESSION, id=s) for s in sessions),
        params=params,
    )


def over(
    kind: ConstraintKind, target: TargetKind, *ids: int, weight: int = 1, **params: int
) -> Constraint:
    """A global preference narrowed to particular instructors, groups or courses."""
    return Constraint(
        kind=kind,
        weight=weight,
        targets=frozenset(ConstraintTarget(kind=target, id=i) for i in ids),
        params=params,
    )


def fired(report: Report) -> set[str]:
    return {v.rule for v in report.violations}


@pytest.fixture
def good() -> Institution:
    return Institution()


class TestTheCatalogue:
    def test_every_kind_has_an_evaluator(self) -> None:
        """`SPECS` promised this in 1.3: *"adding a rule is an entry here plus an evaluator
        in 4.1 — no migration, no route, no schema."* A kind with no evaluator is a rule an
        institution can set, see on the rules screen, and have silently ignored."""
        assert set(EVALUATORS) == set(ConstraintKind)

    def test_only_session_rules_are_checked_on_a_move(self) -> None:
        """A global preference is a property of a day, not of one placement, so it cannot
        refuse a drop. The eight that name sessions can."""
        assert set(ON_A_MOVE) == {
            ConstraintKind.SAME_TIME,
            ConstraintKind.SAME_ROOM,
            ConstraintKind.SAME_DAY,
            ConstraintKind.DIFFERENT_DAY,
            ConstraintKind.NOT_OVERLAP,
            ConstraintKind.PRECEDES,
            ConstraintKind.MIN_GAP,
            ConstraintKind.MAX_DAYS_BETWEEN,
        }


class TestRulesOverNamedSessions:
    def test_same_time(self, good: Institution) -> None:
        """The two labs are at 11:00 and 14:00."""
        assert fired(
            validate(good.ruled(rule(ConstraintKind.SAME_TIME, LAB_A, LAB_B)).snapshot())
        ) == {"same_time"}
        together = good.moved(LAB_B, at=2 + 8)  # same hour, next day
        assert (
            validate(
                together.ruled(rule(ConstraintKind.SAME_TIME, LAB_A, LAB_B)).snapshot()
            ).violations
            == ()
        )

    def test_same_room(self, good: Institution) -> None:
        assert fired(
            validate(good.ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL)).snapshot())
        ) == {"same_room"}
        assert (
            validate(good.ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, LAB_B)).snapshot()).violations
            == ()
        )

    def test_same_day(self, good: Institution) -> None:
        elsewhere = good.moved(LAB_B, at=2 + 8)
        assert fired(
            validate(elsewhere.ruled(rule(ConstraintKind.SAME_DAY, LAB_A, LAB_B)).snapshot())
        ) == {"same_day"}
        assert (
            validate(good.ruled(rule(ConstraintKind.SAME_DAY, LAB_A, LAB_B)).snapshot()).violations
            == ()
        )

    def test_different_day(self, good: Institution) -> None:
        assert fired(
            validate(good.ruled(rule(ConstraintKind.DIFFERENT_DAY, LAB_A, LAB_B)).snapshot())
        ) == {"different_day"}
        elsewhere = good.moved(LAB_B, at=2 + 8)
        assert (
            validate(
                elsewhere.ruled(rule(ConstraintKind.DIFFERENT_DAY, LAB_A, LAB_B)).snapshot()
            ).violations
            == ()
        )

    def test_not_overlap(self, good: Institution) -> None:
        """Distinct from the room and instructor invariants: an institution may want two
        sessions kept apart that share neither — a lab and the tutorial about it.

        Isolated by *difference* rather than by building a pair that breaks nothing else.
        Every pair in this small institution shares something — the two labs need the one
        room with workstations, the tutorial shares an instructor with one of them — so what
        is asserted is what the rule itself contributed.
        """
        overlapping = good.moved(TUTORIAL, at=5, to=STUDIO)
        without = fired(validate(overlapping.snapshot()))
        with_rule = fired(
            validate(
                overlapping.ruled(rule(ConstraintKind.NOT_OVERLAP, LAB_B, TUTORIAL)).snapshot()
            )
        )

        assert with_rule - without == {"not_overlap"}
        assert (
            validate(
                good.ruled(rule(ConstraintKind.NOT_OVERLAP, LAB_B, TUTORIAL)).snapshot()
            ).violations
            == ()
        )

    def test_precedes(self, good: Institution) -> None:
        """Lower session id first, which is the only order the stored set can offer."""
        backwards = good.moved(LAB_A, at=7)  # after the lab that should follow it
        assert fired(
            validate(backwards.ruled(rule(ConstraintKind.PRECEDES, LAB_A, LAB_B)).snapshot())
        ) == {"precedes"}
        assert (
            validate(good.ruled(rule(ConstraintKind.PRECEDES, LAB_A, LAB_B)).snapshot()).violations
            == ()
        )

    def test_min_gap(self, good: Institution) -> None:
        """The labs are at 11:00 and 14:00 — two free hours between them."""
        close = good.ruled(rule(ConstraintKind.MIN_GAP, LAB_A, LAB_B, slots=4))
        assert fired(validate(close.snapshot())) == {"min_gap"}
        assert (
            validate(
                good.ruled(rule(ConstraintKind.MIN_GAP, LAB_A, LAB_B, slots=2)).snapshot()
            ).violations
            == ()
        )

    def test_max_days_between(self, good: Institution) -> None:
        apart = good.moved(LAB_B, at=2 + 8 * 3)  # three days later
        assert fired(
            validate(
                apart.ruled(rule(ConstraintKind.MAX_DAYS_BETWEEN, LAB_A, LAB_B, days=1)).snapshot()
            )
        ) == {"max_days_between"}
        assert (
            validate(
                good.ruled(rule(ConstraintKind.MAX_DAYS_BETWEEN, LAB_A, LAB_B, days=1)).snapshot()
            ).violations
            == ()
        )


class TestPreferencesOverTheTerm:
    def test_group_gaps(self, good: Institution) -> None:
        """Batch B is in the lecture until 11:00 and the lab at 14:00 — two idle hours,
        because 13:00 is lunch and lunch is not somebody waiting around."""
        report = validate(
            good.ruled(over(ConstraintKind.MINIMISE_GROUP_GAPS, TargetKind.GROUP)).snapshot()
        )

        assert "minimise_group_gaps" in fired(report)
        assert report.penalty_breakdown["minimise_group_gaps"] > 0

    def test_a_break_is_not_a_gap(self, good: Institution) -> None:
        """The one thing this rule must not do. Counting lunch would give every full day the
        same cost and tell an institution nothing about any of them."""
        report = validate(
            good.moved(LECTURE, at=2)
            .moved(LAB_A, at=5)
            .ruled(over(ConstraintKind.MINIMISE_GROUP_GAPS, TargetKind.GROUP))
            .snapshot()
        )
        gaps = [v for v in report.violations if v.rule == "minimise_group_gaps"]

        # 11:00-13:00 lecture, 14:00 lab: only the break sits between them.
        assert all(v.units > 0 for v in gaps)
        assert not any("2 idle" in v.message for v in gaps)

    def test_instructor_gaps(self, good: Institution) -> None:
        away = good.moved(TUTORIAL, at=7, to=STUDIO)  # instructor 2 at 11:00 and 16:00
        report = validate(
            away.ruled(
                over(ConstraintKind.MINIMISE_INSTRUCTOR_GAPS, TargetKind.INSTRUCTOR)
            ).snapshot()
        )

        assert "minimise_instructor_gaps" in fired(report)

    def test_the_same_course_twice_a_day(self, good: Institution) -> None:
        """Computing runs three times on the Monday."""
        report = validate(
            good.ruled(
                over(ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY, TargetKind.COURSE, COMPUTING)
            ).snapshot()
        )
        found = next(v for v in report.violations if v.rule == "avoid_same_course_twice_a_day")

        assert found.units == 2  # three sessions, two more than wanted

    def test_instructor_preferences(self, good: Institution) -> None:
        """A soft unavailability, which the invariants pass over entirely."""
        report = validate(
            good.closed(
                Unavailability(instructor_id=InstructorId(2), slot=2, is_hard=False, weight=3)
            )
            .ruled(over(ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES, TargetKind.INSTRUCTOR))
            .snapshot()
        )
        found = next(v for v in report.violations if v.rule == "respect_instructor_preferences")

        assert found.units == 3  # the weight the row carried
        assert report.is_feasible  # a preference is not an impossibility

    def test_building_changes(self, good: Institution) -> None:
        with_buildings = good.model_rooms({LAB: 1, STUDIO: 2}).ruled(
            over(ConstraintKind.MINIMISE_BUILDING_CHANGES, TargetKind.INSTRUCTOR)
        )
        report = validate(with_buildings.snapshot())

        assert "minimise_building_changes" in fired(report)

    def test_daily_load(self, good: Institution) -> None:
        """Everything is on the Monday, so every day but one is empty."""
        report = validate(
            good.ruled(over(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.GROUP)).snapshot()
        )

        assert "balance_daily_load" in fired(report)

    def test_an_even_week_costs_nothing(self, good: Institution) -> None:
        """The half of the rule that keeps it meaningful: it must be reachable.

        Measured against an even share rather than the lightest day, so a subject that
        cannot fill five days is not charged a floor no weight could reduce.
        """
        spread = good.moved(LAB_B, at=2 + 8).moved(TUTORIAL, at=2 + 16, to=STUDIO)
        report = validate(
            spread.ruled(
                over(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.GROUP, BATCH_B)
            ).snapshot()
        )

        assert "balance_daily_load" not in fired(report)

    def test_room_stability(self, good: Institution) -> None:
        """Computing runs in the lab twice and the studio once."""
        report = validate(
            good.ruled(
                over(ConstraintKind.PREFER_ROOM_STABILITY, TargetKind.COURSE, COMPUTING)
            ).snapshot()
        )
        found = next(v for v in report.violations if v.rule == "prefer_room_stability")

        assert found.units == 1  # one room more than it needed

    def test_consecutive_slots(self, good: Institution) -> None:
        """Batch B: lecture 09:00-11:00 then a lab at 11:00 is three hours in a row."""
        packed = good.moved(LAB_B, at=2, to=STUDIO)
        report = validate(
            packed.ruled(
                over(ConstraintKind.LIMIT_CONSECUTIVE_SLOTS, TargetKind.GROUP, slots=2)
            ).snapshot()
        )

        assert "limit_consecutive_slots" in fired(report)

    def test_a_preference_narrowed_to_somebody_else_is_silent(self, good: Institution) -> None:
        """Narrowing is what 3.5 fixed on the rules screen — *"Give everyone at most 3
        hour(s) in a row"* was being said about a rule for one person. It has to mean
        something here too, or the sentence and the behaviour disagree."""
        packed = good.moved(LAB_B, at=2, to=STUDIO)
        report = validate(
            packed.ruled(
                over(ConstraintKind.LIMIT_CONSECUTIVE_SLOTS, TargetKind.INSTRUCTOR, 99, slots=1)
            ).snapshot()
        )

        assert "limit_consecutive_slots" not in fired(report)


class TestWhatItCosts:
    def test_a_soft_violation_is_priced_not_refused(self, good: Institution) -> None:
        report = validate(
            good.ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=7)).snapshot()
        )

        assert report.is_feasible  # worse, not invalid
        assert report.penalty == 7
        assert report.penalty_breakdown == {"same_room": 7}

    def test_a_hard_targeted_rule_is_refused_not_priced(self, good: Institution) -> None:
        """A targeted rule may be hard — *"these two never clash"* is a thing an institution
        insists on. It then costs nothing, because it is not a trade."""
        report = validate(
            good.ruled(
                rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=7, hard=True)
            ).snapshot()
        )

        assert not report.is_feasible
        assert report.penalty == 0
        assert report.hard

    def test_weight_multiplies_units(self, good: Institution) -> None:
        """Three sessions of one course on a Monday is two units over; at weight five that
        is ten. The two numbers are kept apart so 4.3 can raise a weight and see the score
        move without the violation count changing."""
        report = validate(
            good.ruled(
                over(
                    ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY,
                    TargetKind.COURSE,
                    COMPUTING,
                    weight=5,
                )
            ).snapshot()
        )

        assert report.penalty == 10

    def test_a_disabled_rule_does_nothing(self, good: Institution) -> None:
        """Switched off on the rules screen means switched off here. Filtered once when the
        snapshot is built, so no evaluator has to remember — and one that forgot would
        enforce something an institution had deliberately turned off."""
        off = rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL).model_copy(update={"enabled": False})
        report = validate(good.ruled(off).snapshot())

        assert report.violations == ()

    def test_the_breakdown_is_by_kind_not_by_rule(self, good: Institution) -> None:
        """Two narrowed rules of one kind report as that kind. An institution wants to know
        what gaps cost it, not what rule 14 cost it — and 4.3 reports its objective the same
        way, which is how the two can be compared at all."""
        report = validate(
            good.ruled(
                rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=2),
                rule(ConstraintKind.SAME_ROOM, LAB_B, TUTORIAL, weight=3),
            ).snapshot()
        )

        assert report.penalty_breakdown == {"same_room": 5}

    def test_an_empty_timetable_costs_nothing(self, good: Institution) -> None:
        """Every rule must be silent about sessions nobody has placed, or a term would open
        showing hundreds of violations before anybody had done anything."""
        empty = Institution(assignments=())
        report = validate(
            empty.ruled(
                *(
                    over(kind, next(iter(kind.spec.targets)), **dict.fromkeys(kind.spec.params, 1))
                    for kind in ConstraintKind
                    if kind.spec.targets != frozenset({TargetKind.SESSION})
                )
            ).snapshot()
        )

        assert report.violations == ()
        assert report.penalty == 0


class TestOnAMove:
    """A hard targeted rule has to refuse a drop, or the interface permits what the solver
    forbids — which is the drift Decision #5 exists to prevent, arriving one level down.

    Only the rules naming the moved session are re-checked, through the
    `constraints_of_session` index: a drag consults a handful of rules rather than the term's
    whole rulebook, for the same reason every occupancy check is a lookup.
    """

    def test_a_hard_targeted_rule_refuses_a_drop(self, good: Institution) -> None:
        term = good.ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, hard=True))

        # The tutorial is in the studio and the lab is in the lab, so the rule is already
        # broken where they sit — moving the tutorial into the lab is what satisfies it.
        assert not validate_move(term.snapshot(), TUTORIAL, 3, STUDIO).legal
        assert validate_move(term.snapshot(), TUTORIAL, 7, LAB).legal

    def test_the_refusal_names_the_rule(self, good: Institution) -> None:
        term = good.ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, hard=True))
        verdict = validate_move(term.snapshot(), TUTORIAL, 3, STUDIO)

        assert {v.rule for v in verdict.violations} == {"same_room"}

    def test_a_soft_rule_does_not_refuse_a_drop(self, good: Institution) -> None:
        """A preference makes a timetable worse, not impossible. The verdict a drag reads is
        about legality, and the frozen `MoveVerdict` has nowhere to put a cost — so a soft
        rule is scored on the whole timetable and silent here."""
        term = good.ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=9))

        assert validate_move(term.snapshot(), TUTORIAL, 3, STUDIO).legal

    def test_a_rule_naming_other_sessions_is_not_consulted(self, good: Institution) -> None:
        """The index earns its place here: a rule about two other sessions cannot make this
        move illegal, and a move that evaluated the whole rulebook would say otherwise as
        soon as any rule anywhere was broken."""
        term = good.ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, LAB_B, hard=True))

        assert validate_move(term.snapshot(), TUTORIAL, 3, STUDIO).legal

    def test_the_move_is_judged_where_it_would_land(self, good: Institution) -> None:
        """Not where the session currently sits. The lens redirects one lookup rather than
        rebuilding the placements — copying five thousand entries per drag would be correct
        and would cost the flatness the design is for.
        """
        term = good.ruled(rule(ConstraintKind.SAME_DAY, LAB_A, TUTORIAL, hard=True))

        assert validate_move(term.snapshot(), TUTORIAL, 3, STUDIO).legal  # still Monday
        assert not validate_move(term.snapshot(), TUTORIAL, 3 + 8, STUDIO).legal  # Tuesday


class TestRulesWithTooLittleToJudge:
    def test_a_rule_over_one_placed_session_is_silent(self, good: Institution) -> None:
        """`MAX_DAYS_BETWEEN` over a pair where only one is placed has nothing to compare."""
        term = Institution(assignments=good.assignments[:2]).ruled(
            rule(ConstraintKind.MAX_DAYS_BETWEEN, LAB_A, LAB_B, days=1)
        )

        assert validate(term.snapshot()).violations == ()

    def test_a_preference_about_a_subject_with_nothing_placed_is_silent(
        self, good: Institution
    ) -> None:
        term = Institution(assignments=()).ruled(
            over(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.GROUP)
        )

        assert validate(term.snapshot()).violations == ()


class TestTheEndOfTheWeek:
    def test_a_session_overrunning_the_week_does_not_count_phantom_hours(
        self, good: Institution
    ) -> None:
        """A two-hour tutorial starting in the last hour of Friday.

        It runs off the end of the week, which is its own violation. What it must *not* do is
        contribute an hour that does not exist to a rule about hours in a row — and it did:
        `Lens.span` computed the raw range while `Snapshot.teaching` clipped at the last slot,
        so the two disagreed about a session nobody could schedule anyway.

        Found by the property test in part 3, not by anything here: no test had a session
        both overrunning the week and subject to a consecutive-hours rule.
        """
        # Four hours from three slots before the end: three are real, the fourth is past
        # the end of the week. Three in a row is allowed — which is what Batch A already has
        # on the Monday — so only the phantom hour could tip this over.
        start = good.grid.slot_count - 3
        overrunning = good.lasting(TUTORIAL, 4).moved(TUTORIAL, at=start, to=STUDIO)
        report = validate(
            overrunning.ruled(
                over(ConstraintKind.LIMIT_CONSECUTIVE_SLOTS, TargetKind.GROUP, slots=3)
            ).snapshot()
        )

        assert "breaks_protected" in fired(report)  # it does run off the end
        assert "limit_consecutive_slots" not in fired(report)  # but only for real hours
