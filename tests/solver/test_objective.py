"""Each of the eight terms, on a timetable nailed down so the number can be read by hand.

**Pinned on purpose.** Every session is fixed, so the model has exactly one solution and the
objective is arithmetic rather than a search result. A term that is subtly wrong then shows up
as a wrong integer instead of as a slightly different timetable nobody can argue with.

Each rule is tested twice: once on an arrangement that breaks it and once on one that does
not. The second half is what stops a term that always returning 1 from passing, and it is
half of D6's question — *can this kind reach zero at all?*

The other half is at the bottom of this file, and it is the half that matters. A pinned zero
shows a **person** can build an arrangement costing nothing. `TestEveryKindCanReachZero` shows
the **solver** can find one and prove it is the best there is, which is what P5's exit test
needs to mean anything: a weight that cannot be satisfied is one you can raise for ever and
measure nothing (#196).

The agreement with the validator is `test_agreement.py`. This file is about whether the
arithmetic says what the rule says.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from ortools.sat.python import cp_model

from tessera.domain.constraints import (
    Constraint,
    ConstraintKind,
    ConstraintTarget,
    TargetKind,
)
from tessera.domain.entities import Unavailability, WeekPattern
from tessera.domain.ids import InstructorId, RoomId, SessionId
from tessera.domain.validation import validate
from tessera.solver import Budget, Outcome, Solution, solve
from tessera.solver.model import build
from tessera.solver.objective import TERMS, NotScorableError, add, bounds
from tests.domain.validation.institution import (
    BATCH_A,
    BATCH_B,
    COMPUTING,
    CUPBOARD,
    HALL,
    LAB,
    LAB_A,
    LAB_B,
    LECTURE,
    MATHS,
    STUDIO,
    TUTORIAL,
    Institution,
)

#: Long enough that a pinned term is never the thing that runs out of time, short enough
#: that a mistake fails the suite rather than hanging it.
BUDGET = Budget(seconds=20)


def rule(
    kind: ConstraintKind,
    *targets: SessionId,
    weight: int = 1,
    is_hard: bool = False,
    **params: int,
) -> Constraint:
    """One rule over named sessions. Weights are deliberately never 1 by default in the
    tests below, so a term that ignored `Constraint.weight` and counted units would fail."""
    return Constraint(
        kind=kind,
        weight=weight,
        is_hard=is_hard,
        targets=frozenset(ConstraintTarget(kind=TargetKind.SESSION, id=t) for t in targets),
        params=params,
    )


def about(
    kind: ConstraintKind,
    target_kind: TargetKind,
    *targets: int,
    weight: int = 1,
    **params: int,
) -> Constraint:
    """A preference, narrowed to instructors, groups or courses — or to nobody, meaning all.

    Narrowing is how each of these is tested twice. Most of them cost something on the
    known-good timetable for one subject and nothing for another, so pointing the same rule
    at each in turn gives the broken case and the clean one without moving anything.
    """
    return Constraint(
        kind=kind,
        weight=weight,
        targets=frozenset(ConstraintTarget(kind=target_kind, id=t) for t in targets),
        params=params,
    )


#: The hall and the lab on one site, the seminar room and the studio on another.
TWO_SITES = {HALL: 1, LAB: 1, CUPBOARD: 2, STUDIO: 2}


def laid_out(
    *,
    lecture: tuple[int, RoomId] = (0, HALL),
    lab_a: tuple[int, RoomId] = (2, LAB),
    lab_b: tuple[int, RoomId] = (5, LAB),
    tutorial: tuple[int, RoomId] = (6, STUDIO),
) -> Institution:
    """The known-good timetable, every session pinned, and any of them moved by keyword."""
    institution = Institution(assignments=())
    for session_id, (slot, room) in (
        (LECTURE, lecture),
        (LAB_A, lab_a),
        (LAB_B, lab_b),
        (TUTORIAL, tutorial),
    ):
        institution = institution.pinned_to(session_id, at=slot, room=room)
    return institution


def scored(institution: Institution) -> Solution:
    """Solve a pinned term, and check the validator calls the result a valid timetable.

    The second half matters: a term whose pins are impossible would otherwise fail with a
    confusing message about a penalty when the real answer is that the layout is wrong.
    """
    snapshot = institution.snapshot()
    report = validate(snapshot)
    assert report.is_feasible, f"the pinned layout is not valid: {report.hard}"

    found = solve(snapshot, BUDGET)
    assert found.solved
    return found


def costs(institution: Institution, kind: ConstraintKind, expected: int) -> None:
    """The objective scores this arrangement of this rule at exactly `expected`.

    And so does the validator. The generated agreement test covers this far more widely, but
    a hand-worked number that both implementations produce is the one place a *shared*
    misreading would show — the two agreeing with each other says nothing about either being
    right, and only a number worked out by a person on paper does.
    """
    found = scored(institution)
    report = validate(institution.snapshot())

    assert found.penalty == expected
    assert report.penalty == expected
    assert found.penalty_breakdown == ({kind.value: expected} if expected else {})
    assert found.penalty_breakdown == report.penalty_breakdown
    # Nothing is left to search once every session is pinned, so anything else would mean
    # the bound is not tracking the objective it was derived from.
    assert found.is_optimal


class TestTheEightRulesOverNamedSessions:
    """One arrangement that breaks each rule, and one that does not."""

    def test_same_time_counts_the_hours_that_disagree(self) -> None:
        """Slot *of day*, not the week-absolute slot: the lab moved to the same hour on
        another day satisfies it, which is what makes `SAME_DAY` a separate rule."""
        broken = laid_out().ruled(rule(ConstraintKind.SAME_TIME, LECTURE, LAB_A, weight=3))
        costs(broken, ConstraintKind.SAME_TIME, 3)

        kept = laid_out(lab_a=(8, LAB)).ruled(
            rule(ConstraintKind.SAME_TIME, LECTURE, LAB_A, weight=3)
        )
        costs(kept, ConstraintKind.SAME_TIME, 0)

    def test_same_room_counts_the_rooms_that_disagree(self) -> None:
        broken = laid_out().ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=2))
        costs(broken, ConstraintKind.SAME_ROOM, 2)

        kept = laid_out(tutorial=(7, LAB)).ruled(
            rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=2)
        )
        costs(kept, ConstraintKind.SAME_ROOM, 0)

    def test_same_day_counts_the_days_that_disagree(self) -> None:
        kept = laid_out().ruled(rule(ConstraintKind.SAME_DAY, LECTURE, TUTORIAL, weight=5))
        costs(kept, ConstraintKind.SAME_DAY, 0)

        broken = laid_out(tutorial=(14, STUDIO)).ruled(
            rule(ConstraintKind.SAME_DAY, LECTURE, TUTORIAL, weight=5)
        )
        costs(broken, ConstraintKind.SAME_DAY, 5)

    def test_different_day_counts_the_pairs_sharing_one(self) -> None:
        broken = laid_out().ruled(rule(ConstraintKind.DIFFERENT_DAY, LECTURE, TUTORIAL, weight=4))
        costs(broken, ConstraintKind.DIFFERENT_DAY, 4)

        kept = laid_out(tutorial=(14, STUDIO)).ruled(
            rule(ConstraintKind.DIFFERENT_DAY, LECTURE, TUTORIAL, weight=4)
        )
        costs(kept, ConstraintKind.DIFFERENT_DAY, 0)

    def test_not_overlap_counts_the_pairs_running_together(self) -> None:
        """Two labs in one room at one hour, one in odd weeks and one in even.

        The only pair in this institution that *can* share an hour — everything else shares a
        room, an instructor or a group, and the invariants would refuse it. So this is also
        the case that pins down an asymmetry worth knowing about: the occupancy rules skip
        pairs whose weeks never meet, and `NOT_OVERLAP` does not. The validator is the
        authority for what a timetable costs, so the objective matches it rather than
        arguing; the backlog carries the question.
        """
        fortnightly = (
            laid_out(lab_b=(2, LAB))
            .patterned(LAB_A, WeekPattern.ODD_WEEKS)
            .patterned(LAB_B, WeekPattern.EVEN_WEEKS)
        )
        broken = fortnightly.ruled(rule(ConstraintKind.NOT_OVERLAP, LAB_A, LAB_B, weight=7))
        costs(broken, ConstraintKind.NOT_OVERLAP, 7)

        apart = (
            laid_out()
            .patterned(LAB_A, WeekPattern.ODD_WEEKS)
            .patterned(LAB_B, WeekPattern.EVEN_WEEKS)
            .ruled(rule(ConstraintKind.NOT_OVERLAP, LAB_A, LAB_B, weight=7))
        )
        costs(apart, ConstraintKind.NOT_OVERLAP, 0)

    def test_min_gap_counts_the_pairs_that_are_too_close(self) -> None:
        """The lecture ends at slot 1; a tutorial at slot 3 leaves one hour, not two."""
        broken = laid_out(tutorial=(3, STUDIO)).ruled(
            rule(ConstraintKind.MIN_GAP, LECTURE, TUTORIAL, weight=6, slots=2)
        )
        costs(broken, ConstraintKind.MIN_GAP, 6)

        kept = laid_out().ruled(rule(ConstraintKind.MIN_GAP, LECTURE, TUTORIAL, weight=6, slots=2))
        costs(kept, ConstraintKind.MIN_GAP, 0)

    def test_precedes_counts_the_pairs_in_the_wrong_order(self) -> None:
        """Ascending session id, because the order somebody gave is not stored — see the
        rule for why that is a gap rather than a design. What matters here is that the
        objective reads it the same way the validator does."""
        kept = laid_out().ruled(rule(ConstraintKind.PRECEDES, LAB_A, LAB_B, weight=9))
        costs(kept, ConstraintKind.PRECEDES, 0)

        broken = laid_out(lab_a=(5, LAB), lab_b=(2, LAB)).ruled(
            rule(ConstraintKind.PRECEDES, LAB_A, LAB_B, weight=9)
        )
        costs(broken, ConstraintKind.PRECEDES, 9)

    def test_max_days_between_counts_the_days_over_the_allowance(self) -> None:
        """Three days apart where one is allowed is two units, not one violation."""
        kept = laid_out().ruled(
            rule(ConstraintKind.MAX_DAYS_BETWEEN, LECTURE, LAB_A, weight=2, days=1)
        )
        costs(kept, ConstraintKind.MAX_DAYS_BETWEEN, 0)

        broken = laid_out(lab_a=(24, LAB)).ruled(
            rule(ConstraintKind.MAX_DAYS_BETWEEN, LECTURE, LAB_A, weight=2, days=1)
        )
        costs(broken, ConstraintKind.MAX_DAYS_BETWEEN, 4)


#: One arrangement per kind that breaks it, for the mutation test below. The layouts are the
#: ones the eight tests above use; each entry is re-checked to actually violate before it is
#: silenced, so an entry that drifted into a clean layout fails rather than passing quietly.
BREAKS: dict[ConstraintKind, tuple[Institution, Constraint]] = {
    ConstraintKind.SAME_TIME: (
        laid_out(),
        rule(ConstraintKind.SAME_TIME, LECTURE, LAB_A, weight=3),
    ),
    ConstraintKind.SAME_ROOM: (
        laid_out(),
        rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=2),
    ),
    ConstraintKind.SAME_DAY: (
        laid_out(tutorial=(14, STUDIO)),
        rule(ConstraintKind.SAME_DAY, LECTURE, TUTORIAL, weight=5),
    ),
    ConstraintKind.DIFFERENT_DAY: (
        laid_out(),
        rule(ConstraintKind.DIFFERENT_DAY, LECTURE, TUTORIAL, weight=4),
    ),
    ConstraintKind.NOT_OVERLAP: (
        laid_out(lab_b=(2, LAB))
        .patterned(LAB_A, WeekPattern.ODD_WEEKS)
        .patterned(LAB_B, WeekPattern.EVEN_WEEKS),
        rule(ConstraintKind.NOT_OVERLAP, LAB_A, LAB_B, weight=7),
    ),
    ConstraintKind.MIN_GAP: (
        laid_out(tutorial=(3, STUDIO)),
        rule(ConstraintKind.MIN_GAP, LECTURE, TUTORIAL, weight=6, slots=2),
    ),
    ConstraintKind.PRECEDES: (
        laid_out(lab_a=(5, LAB), lab_b=(2, LAB)),
        rule(ConstraintKind.PRECEDES, LAB_A, LAB_B, weight=9),
    ),
    ConstraintKind.MAX_DAYS_BETWEEN: (
        laid_out(lab_a=(24, LAB)),
        rule(ConstraintKind.MAX_DAYS_BETWEEN, LECTURE, LAB_A, weight=2, days=1),
    ),
    ConstraintKind.MINIMISE_GROUP_GAPS: (
        laid_out(),
        about(ConstraintKind.MINIMISE_GROUP_GAPS, TargetKind.GROUP, BATCH_B, weight=3),
    ),
    ConstraintKind.MINIMISE_INSTRUCTOR_GAPS: (
        laid_out(),
        about(ConstraintKind.MINIMISE_INSTRUCTOR_GAPS, TargetKind.INSTRUCTOR, 2),
    ),
    ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY: (
        laid_out(),
        about(ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY, TargetKind.COURSE, COMPUTING, weight=4),
    ),
    ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES: (
        laid_out().closed(
            Unavailability(instructor_id=InstructorId(2), slot=6, is_hard=False, weight=5)
        ),
        about(ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES, TargetKind.INSTRUCTOR, 2, weight=2),
    ),
    ConstraintKind.MINIMISE_BUILDING_CHANGES: (
        laid_out().model_rooms(TWO_SITES),
        about(ConstraintKind.MINIMISE_BUILDING_CHANGES, TargetKind.INSTRUCTOR, weight=3),
    ),
    ConstraintKind.BALANCE_DAILY_LOAD: (
        laid_out(),
        about(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.INSTRUCTOR, 2, weight=7),
    ),
    ConstraintKind.PREFER_ROOM_STABILITY: (
        laid_out(),
        about(ConstraintKind.PREFER_ROOM_STABILITY, TargetKind.COURSE, COMPUTING, weight=5),
    ),
    ConstraintKind.LIMIT_CONSECUTIVE_SLOTS: (
        laid_out(),
        about(
            ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            TargetKind.GROUP,
            BATCH_A,
            weight=6,
            slots=2,
        ),
    ),
}


class TestEveryTermIsWatchedToFail:
    """Silence each term in turn, and check something notices.

    4.1 ran this discipline on its sixteen evaluators and it caught a rule that had quietly
    stopped running — the suite was green, and the rule was dead. The failure it guards
    against here is the same shape and easier to reach: a term that returns no violation
    counts costs nothing, breaks no test that only checks feasibility, and leaves the solver
    optimising a rulebook with a rule missing from it.
    """

    def test_every_scored_kind_has_an_arrangement_that_breaks_it(self) -> None:
        assert set(BREAKS) == set(TERMS)

    @pytest.mark.parametrize("kind", sorted(TERMS))
    def test_a_term_that_stops_counting_disagrees_with_the_validator(
        self, kind: ConstraintKind, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        institution, constraint = BREAKS[kind]
        ruled = institution.ruled(constraint)

        assert scored(ruled).penalty > 0, "this layout does not break the rule any more"

        monkeypatch.setitem(TERMS, kind, lambda terms, constraint: [])
        silenced = solve(ruled.snapshot(), BUDGET)

        assert silenced.penalty == 0
        assert silenced.penalty != validate(ruled.snapshot()).penalty


#: The known-good timetable, for reference while reading the numbers below.
#:
#:      day 0    0     1     2     3     4      5      6     7
#:      LECTURE  |-- hall --|                                       year 1, instructor 1
#:      LAB_A                |lab|                                  batch A, instructor 2
#:      LAB_B                             |lab|                     batch B, instructor 3
#:      TUTORIAL                                 |studio|           batch B, instructor 2
#:                                 lunch
BASELINE = laid_out()


class TestTheGapsInSomebodysDay:
    """Idle hours between the first and last thing of the day, breaks excepted."""

    def test_a_group_with_a_solid_morning_has_none(self) -> None:
        """Batch A is taught 0-1 and then 2. Nothing to wait through."""
        costs(
            BASELINE.ruled(about(ConstraintKind.MINIMISE_GROUP_GAPS, TargetKind.GROUP, BATCH_A)),
            ConstraintKind.MINIMISE_GROUP_GAPS,
            0,
        )

    def test_a_group_waiting_between_classes_pays_for_each_hour(self) -> None:
        """Batch B is taught 0-1, then 5, then 6. Hours 2 and 3 are idle; hour 4 is lunch,
        which is the timetable working rather than somebody waiting."""
        costs(
            BASELINE.ruled(
                about(ConstraintKind.MINIMISE_GROUP_GAPS, TargetKind.GROUP, BATCH_B, weight=3)
            ),
            ConstraintKind.MINIMISE_GROUP_GAPS,
            6,
        )

    def test_the_same_question_asked_about_instructors(self) -> None:
        """Instructor 2 teaches at 2 and again at 6: hours 3 and 5 idle, 4 is lunch."""
        costs(
            BASELINE.ruled(
                about(ConstraintKind.MINIMISE_INSTRUCTOR_GAPS, TargetKind.INSTRUCTOR, 2)
            ),
            ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
            2,
        )

    def test_an_instructor_with_one_class_has_no_day_to_speak_of(self) -> None:
        costs(
            BASELINE.ruled(
                about(ConstraintKind.MINIMISE_INSTRUCTOR_GAPS, TargetKind.INSTRUCTOR, 1)
            ),
            ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
            0,
        )


class TestACourseTaughtTwiceInOneDay:
    def test_the_second_and_third_teaching_both_cost(self) -> None:
        """Computing is taught three times on day 0 — one is free, two are not."""
        costs(
            BASELINE.ruled(
                about(
                    ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY,
                    TargetKind.COURSE,
                    COMPUTING,
                    weight=4,
                )
            ),
            ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY,
            8,
        )

    def test_a_course_taught_once_costs_nothing(self) -> None:
        costs(
            BASELINE.ruled(
                about(ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY, TargetKind.COURSE, MATHS)
            ),
            ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY,
            0,
        )


class TestKeepingACourseInOneRoom:
    def test_a_course_spread_over_two_rooms_pays_for_the_second(self) -> None:
        costs(
            BASELINE.ruled(
                about(ConstraintKind.PREFER_ROOM_STABILITY, TargetKind.COURSE, COMPUTING, weight=5)
            ),
            ConstraintKind.PREFER_ROOM_STABILITY,
            5,
        )

    def test_a_course_that_never_leaves_its_room_costs_nothing(self) -> None:
        """The tutorial moved into the lab, which is free at hour 7."""
        costs(
            laid_out(tutorial=(7, LAB)).ruled(
                about(ConstraintKind.PREFER_ROOM_STABILITY, TargetKind.COURSE, COMPUTING, weight=5)
            ),
            ConstraintKind.PREFER_ROOM_STABILITY,
            0,
        )


class TestHoursSomebodyWouldRatherNotTeach:
    """Soft unavailability — the data 2.7b added, and the reason this kind stopped being a
    rule with nothing behind it."""

    def test_teaching_at_a_disliked_hour_costs_what_they_said_it_would(self) -> None:
        reluctant = BASELINE.closed(
            Unavailability(instructor_id=InstructorId(2), slot=6, is_hard=False, weight=5)
        ).ruled(
            about(ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES, TargetKind.INSTRUCTOR, 2, weight=2)
        )
        costs(reluctant, ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES, 10)

    def test_a_preference_about_an_hour_nobody_uses_costs_nothing(self) -> None:
        content = BASELINE.closed(
            Unavailability(instructor_id=InstructorId(2), slot=30, is_hard=False, weight=5)
        ).ruled(about(ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES, TargetKind.INSTRUCTOR, 2))
        costs(content, ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES, 0)

    def test_a_hard_row_is_not_a_preference_and_is_not_priced(self) -> None:
        """*Would rather not* is not *cannot*. A hard row narrows the solver's domain instead,
        so the session simply never goes there and there is nothing to charge for."""
        shut = BASELINE.closed(
            Unavailability(instructor_id=InstructorId(2), slot=6, is_hard=True)
        ).ruled(about(ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES, TargetKind.INSTRUCTOR, 2))
        assert solve(shut.snapshot(), BUDGET).outcome is Outcome.IMPOSSIBLE


class TestWalkingBetweenBuildings:
    """Nothing in the fixture is in a building until a test puts it in one."""

    def test_a_move_is_counted_once_for_each_person_who_makes_it(self) -> None:
        """Instructor 2 goes lab to studio; batch B goes hall, lab, then studio. Two moves,
        by two different people, over the same walk."""
        costs(
            BASELINE.model_rooms(TWO_SITES).ruled(
                about(ConstraintKind.MINIMISE_BUILDING_CHANGES, TargetKind.INSTRUCTOR, weight=3)
            ),
            ConstraintKind.MINIMISE_BUILDING_CHANGES,
            6,
        )

    def test_a_day_spent_on_one_site_costs_nothing(self) -> None:
        costs(
            BASELINE.model_rooms({HALL: 1, LAB: 1, CUPBOARD: 1, STUDIO: 1}).ruled(
                about(ConstraintKind.MINIMISE_BUILDING_CHANGES, TargetKind.INSTRUCTOR)
            ),
            ConstraintKind.MINIMISE_BUILDING_CHANGES,
            0,
        )

    def test_rooms_nobody_has_put_on_a_map_are_not_two_buildings_apart(self) -> None:
        """Every room in the fixture has no building at all, which is the state a term is in
        before anybody fills that in. It must not read as a move on every hop."""
        costs(
            BASELINE.ruled(about(ConstraintKind.MINIMISE_BUILDING_CHANGES, TargetKind.INSTRUCTOR)),
            ConstraintKind.MINIMISE_BUILDING_CHANGES,
            0,
        )


class TestSpreadingTheWeekEvenly:
    def test_a_day_heavier_than_anyone_could_avoid_costs_the_difference(self) -> None:
        """Instructor 2 teaches two single hours, both on day 0. One of them could have been
        somewhere else, so one hour is charged for."""
        costs(
            BASELINE.ruled(
                about(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.INSTRUCTOR, 2, weight=7)
            ),
            ConstraintKind.BALANCE_DAILY_LOAD,
            7,
        )

    def test_a_week_that_could_not_be_flatter_costs_nothing(self) -> None:
        """Instructor 1 teaches one two-hour lecture. It has to sit somewhere, so the day it
        sits on is not heavy — it is the only day there is. #196: measured against the even
        share *or* the longest session, whichever is larger, so this can reach zero."""
        costs(
            BASELINE.ruled(about(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.INSTRUCTOR, 1)),
            ConstraintKind.BALANCE_DAILY_LOAD,
            0,
        )


class TestHoursInARow:
    def test_a_run_longer_than_allowed_costs_each_hour_over(self) -> None:
        """Batch A is taught 0, 1 and 2 without a break — three in a row where two are
        allowed."""
        costs(
            BASELINE.ruled(
                about(
                    ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
                    TargetKind.GROUP,
                    BATCH_A,
                    weight=6,
                    slots=2,
                )
            ),
            ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            6,
        )

    def test_a_run_exactly_as_long_as_allowed_costs_nothing(self) -> None:
        costs(
            BASELINE.ruled(
                about(
                    ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
                    TargetKind.GROUP,
                    BATCH_B,
                    weight=6,
                    slots=2,
                )
            ),
            ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            0,
        )


class TestNarrowingARule:
    def test_a_rule_narrowed_to_nothing_of_its_kind_covers_nobody(self) -> None:
        """Four kinds apply to instructors *and* groups, and ask for each in turn. Falling
        back to "everyone" per kind made a rule aimed at one instructor also charge every
        group in the term — the opposite of narrowing, and silent (#198)."""
        costs(
            BASELINE.ruled(
                about(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.INSTRUCTOR, 1, weight=9)
            ),
            ConstraintKind.BALANCE_DAILY_LOAD,
            0,
        )

    def test_an_unnarrowed_rule_covers_the_whole_term(self) -> None:
        """Instructor 2 costs 1, batch A costs 1, batch B costs 2 — instructors then groups,
        which is the order the validator visits them in and the set it visits."""
        costs(
            BASELINE.ruled(about(ConstraintKind.BALANCE_DAILY_LOAD, TargetKind.INSTRUCTOR)),
            ConstraintKind.BALANCE_DAILY_LOAD,
            4,
        )


class TestTheWeightsComeFromTheConstraint:
    """D3. 2.8 put a weight on `Constraint` and 3.5 put a slider on the rules screen; an
    objective with constants would make those sliders decorative."""

    @pytest.mark.parametrize("weight", [0, 1, 3, 50])
    def test_the_same_violation_costs_what_the_rule_says(self, weight: int) -> None:
        broken = laid_out().ruled(
            rule(ConstraintKind.DIFFERENT_DAY, LECTURE, TUTORIAL, weight=weight)
        )
        assert scored(broken).penalty == weight

    def test_two_rules_of_one_kind_are_reported_together(self) -> None:
        """Per kind, not per constraint — `Report.penalty_breakdown`'s shape, and the reason
        it has that shape: an institution wants to know what gaps cost it, not what rule 14
        cost it."""
        broken = laid_out().ruled(
            rule(ConstraintKind.DIFFERENT_DAY, LECTURE, TUTORIAL, weight=4),
            rule(ConstraintKind.DIFFERENT_DAY, LAB_A, LAB_B, weight=10),
        )
        found = scored(broken)
        assert found.penalty_breakdown == {ConstraintKind.DIFFERENT_DAY.value: 14}

    def test_a_disabled_rule_costs_nothing(self) -> None:
        """The snapshot filters them out before any of this runs, which is why no term has
        to remember to check — but a term is exactly where forgetting would be silent."""
        off = laid_out().ruled(
            rule(ConstraintKind.DIFFERENT_DAY, LECTURE, TUTORIAL, weight=4).model_copy(
                update={"enabled": False}
            )
        )
        assert scored(off).penalty == 0


class TestAHardRuleIsRefusedRatherThanPriced:
    """D3's other half — and a gap 4.2 left, since its model never read `snapshot.constraints`
    at all. A hard distribution rule was neither enforced nor scored: the solver could return
    a timetable the validator called invalid, and nothing in the phase noticed because the
    generated instances carried no rules."""

    def test_a_layout_that_breaks_a_hard_rule_has_no_solution(self) -> None:
        impossible = laid_out().ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, is_hard=True))
        found = solve(impossible.snapshot(), BUDGET)
        assert found.outcome is Outcome.IMPOSSIBLE

    def test_the_same_rule_kept_is_solved_and_costs_nothing(self) -> None:
        """A hard rule carries no weight, so obeying it is worth zero rather than worth
        something — a price on an inviolable rule would suggest it could be traded away."""
        fine = laid_out(tutorial=(7, LAB)).ruled(
            rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, is_hard=True)
        )
        found = scored(fine)
        assert found.penalty == 0
        assert found.penalty_breakdown == {}

    def test_the_same_violation_made_soft_is_priced_instead(self) -> None:
        priced = laid_out().ruled(rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=2))
        assert scored(priced).penalty == 2


class TestNoTermCanGoNegative:
    """D2, and the bug this phase exists not to repeat. Phase 0.1 wrote room stability as
    `sum(uses_room) - 1`, a course in one room contributed minus nothing, and the solver
    reported cost 5 with a lower bound of -7 — then burned the full 60 s unable to prove what
    it had found at 3.41 s."""

    def test_every_violation_count_has_a_floor_of_zero(self) -> None:
        institution = laid_out().ruled(
            rule(ConstraintKind.SAME_TIME, LECTURE, LAB_A, weight=3),
            rule(ConstraintKind.SAME_ROOM, LAB_A, TUTORIAL, weight=2),
            rule(ConstraintKind.MAX_DAYS_BETWEEN, LECTURE, LAB_A, weight=2, days=1),
            rule(ConstraintKind.MIN_GAP, LECTURE, TUTORIAL, weight=6, slots=2),
            rule(ConstraintKind.PRECEDES, LAB_A, LAB_B, weight=9),
        )
        snapshot = institution.snapshot()
        objective = add(build(snapshot), snapshot)

        assert objective is not None
        assert objective.units, "no terms were built, so this proves nothing"
        assert set(objective.floors()) == {0}

    def test_a_variables_ceiling_is_read_correctly(self) -> None:
        """The guard on an API that answers rather than refuses.

        A CP-SAT variable's domain comes back as a native `repeated_scalar_int64_t`, which
        does not implement negative indexing: `domain[-1]` returns `domain[0]`. Every
        boolean's ceiling read as 0, every cost variable got the domain `[0, 0]`, and each
        soft rule silently became a hard one — the pinned terms above all reported infeasible
        while the validator called the same timetable fine. Nothing raised.
        """
        model = cp_model.CpModel()
        assert bounds(model.new_bool_var("b")) == (0, 1)
        assert bounds(model.new_int_var(2, 9, "i")) == (2, 9)
        assert bounds(
            model.new_int_var_from_domain(cp_model.Domain.from_values([0, 3, 7]), "d")
        ) == (0, 7)

    def test_the_bound_is_never_reported_below_zero(self) -> None:
        with pytest.raises(ValueError, match="unsound"):
            Solution(outcome=Outcome.OUT_OF_TIME, lower_bound=-7)

    def test_a_bound_above_the_best_solution_is_not_a_bound(self) -> None:
        with pytest.raises(ValueError, match="not a bound"):
            Solution(
                outcome=Outcome.SOLVED,
                placements=scored(laid_out()).placements,
                penalty=3,
                penalty_breakdown={"same_time": 3},
                lower_bound=4,
            )

    def test_a_breakdown_that_does_not_sum_to_the_penalty_is_refused(self) -> None:
        with pytest.raises(ValueError, match="counted in one place"):
            Solution(
                outcome=Outcome.SOLVED,
                placements=scored(laid_out()).placements,
                penalty=3,
                penalty_breakdown={"same_time": 2},
            )

    def test_a_failed_solve_carries_no_score(self) -> None:
        with pytest.raises(ValueError, match="no timetable"):
            Solution(outcome=Outcome.OUT_OF_TIME, penalty=5)

    def test_a_negative_penalty_is_not_a_cost(self) -> None:
        """The guard for the other half of 0.1's bug. Its *bound* went negative; a term that
        could go negative would take the reported score with it."""
        with pytest.raises(ValueError, match="not a cost"):
            Solution(
                outcome=Outcome.SOLVED,
                placements=scored(laid_out()).placements,
                penalty=-1,
            )


class TestARuleWithTooFewSessionsToBreak:
    """Silence on both sides, which is the only answer that keeps them equal.

    `Lens.placed` drops targets that are not placed and every `_agree_on` rule needs more than
    one before it says anything. A term cannot see whether a session is placed — the solver
    places all of them — but it can see whether the session is *in the term at all*, and a
    rule naming one session, or naming sessions that were deleted, has nothing to compare.
    """

    @pytest.mark.parametrize(
        "constraint",
        [
            rule(ConstraintKind.SAME_DAY, LECTURE, weight=5),
            rule(ConstraintKind.SAME_TIME, LECTURE, weight=5),
            rule(ConstraintKind.SAME_ROOM, LECTURE, weight=5),
            rule(ConstraintKind.MAX_DAYS_BETWEEN, LECTURE, weight=5, days=1),
        ],
        ids=lambda c: str(c.kind.value),
    )
    def test_one_session_cannot_disagree_with_itself(self, constraint: Constraint) -> None:
        institution = laid_out().ruled(constraint)
        assert scored(institution).penalty == 0
        assert validate(institution.snapshot()).penalty == 0

    def test_a_rule_naming_sessions_the_term_does_not_have_says_nothing(self) -> None:
        """The validator drops them silently, so the objective must too. A term that counted
        them would price a rule about a session somebody deleted."""
        gone = SessionId(99)
        institution = laid_out().ruled(
            rule(ConstraintKind.SAME_DAY, LECTURE, gone, weight=5),
            rule(ConstraintKind.MAX_DAYS_BETWEEN, LAB_A, gone, weight=5, days=1),
        )
        assert scored(institution).penalty == 0
        assert validate(institution.snapshot()).penalty == 0


class TestTwoRulesAboutTheSameSession:
    def test_they_share_the_channelling_and_still_agree(self) -> None:
        """Asking twice whether the lecture is on Tuesday should build one boolean, not two.

        The saving is real — a term with several distribution rules over one set would
        otherwise carry a duplicate channelling network per rule — but what is asserted here
        is the part that could go wrong: sharing a variable between two rules must not make
        either of them read differently.
        """
        institution = laid_out(tutorial=(14, STUDIO)).ruled(
            rule(ConstraintKind.SAME_DAY, LECTURE, TUTORIAL, weight=5),
            rule(ConstraintKind.SAME_DAY, LECTURE, LAB_A, TUTORIAL, weight=2),
        )
        found = scored(institution)

        assert found.penalty == validate(institution.snapshot()).penalty
        assert found.penalty_breakdown == validate(institution.snapshot()).penalty_breakdown


class TestNothingIsQuietlyUnscored:
    """D4. A partial objective silently ignores whichever slider a user moved, which is the
    worst kind of interface defect because it looks like it works."""

    def test_every_kind_has_a_term(self) -> None:
        """The enum is checked against the registry rather than trusted — the discipline
        `SPECS` and `EVALUATORS` are both held to. Adding a seventeenth kind is a term here,
        and this is what says so."""
        assert set(TERMS) == set(ConstraintKind)

    def test_a_kind_with_no_term_stops_the_solve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loud rather than quiet. Scoring the kinds we have and omitting the rest produces a
        timetable optimised against a rulebook nobody wrote down, and a penalty that does not
        answer for the difference."""
        monkeypatch.delitem(TERMS, ConstraintKind.MINIMISE_GROUP_GAPS)

        with pytest.raises(NotScorableError, match="minimise_group_gaps"):
            solve(
                laid_out()
                .ruled(Constraint(kind=ConstraintKind.MINIMISE_GROUP_GAPS, weight=3))
                .snapshot(),
                BUDGET,
            )


class TestATermWithNoPreferences:
    def test_nothing_is_minimised_at_all(self) -> None:
        """Not a constant objective — none. `minimize(0)` turns a satisfaction problem into
        an optimisation problem CP-SAT will then go on to prove optimal, which would quietly
        change every feasibility time 4.2 measured."""
        snapshot = Institution(assignments=()).snapshot()
        assert add(build(snapshot), snapshot) is None

    def test_the_solution_says_zero_rather_than_nothing(self) -> None:
        found = solve(Institution(assignments=()).snapshot(), BUDGET)
        assert found.solved
        assert found.penalty == 0
        assert found.penalty_breakdown == {}
        assert found.lower_bound == 0


class TestEveryKindCanReachZero:
    """D6. A kind whose cost no arrangement can remove is a bug in the term, not a strict rule.

    #196 found exactly that: `BALANCE_DAILY_LOAD` measured against the *lightest* day charged
    a floor nothing could clear, so an institution could raise its weight to fifty and watch
    the timetable not move. The rule looked like it worked, and the slider did nothing.

    Every rule in `BREAKS` is one that costs something on the pinned timetable. Here the pins
    come off and the same rule is handed to the solver, which must find an arrangement costing
    **nothing** and prove no cheaper one exists. That is the precondition for the weight tests
    in `test_weights.py`, and it is cheap to check.
    """

    @pytest.mark.parametrize("kind", sorted(BREAKS, key=str), ids=str)
    def test_the_solver_finds_an_arrangement_this_rule_costs_nothing_on(
        self, kind: ConstraintKind
    ) -> None:
        institution, constraint = BREAKS[kind]
        free = replace(institution, assignments=()).ruled(constraint)

        found = solve(free.snapshot(), BUDGET)

        assert found.solved, f"{kind.value}: no timetable at all"
        assert found.penalty == 0, (
            f"{kind.value} costs {found.penalty} even when the solver is free to arrange "
            "the term however it likes — so the weight on it cannot be traded against "
            "anything, and raising it would move nothing"
        )
        assert found.is_optimal, f"{kind.value}: zero found but not proven"
