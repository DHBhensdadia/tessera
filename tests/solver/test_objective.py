"""Each of the eight terms, on a timetable nailed down so the number can be read by hand.

**Pinned on purpose.** Every session is fixed, so the model has exactly one solution and the
objective is arithmetic rather than a search result. A term that is subtly wrong then shows up
as a wrong integer instead of as a slightly different timetable nobody can argue with.

Each rule is tested twice: once on an arrangement that breaks it and once on one that does
not. The second half is what stops a term that always returns 1 from passing, and it is D6's
question — *can this kind reach zero at all?* — asked early for the eight kinds that have it.

The agreement with the validator is `test_agreement.py`. This file is about whether the
arithmetic says what the rule says.
"""

from __future__ import annotations

import pytest
from ortools.sat.python import cp_model

from tessera.domain.constraints import (
    Constraint,
    ConstraintKind,
    ConstraintTarget,
    TargetKind,
)
from tessera.domain.entities import WeekPattern
from tessera.domain.ids import RoomId, SessionId
from tessera.domain.validation import validate
from tessera.solver import Budget, Outcome, Solution, solve
from tessera.solver.model import build
from tessera.solver.objective import PENDING, TERMS, NotScorableError, _bounds, add
from tests.domain.validation.institution import (
    HALL,
    LAB,
    LAB_A,
    LAB_B,
    LECTURE,
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
    """The objective scores this arrangement of this rule at exactly `expected`."""
    found = scored(institution)
    assert found.penalty == expected
    assert found.penalty_breakdown == ({kind.value: expected} if expected else {})
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
        assert _bounds(model.new_bool_var("b")) == (0, 1)
        assert _bounds(model.new_int_var(2, 9, "i")) == (2, 9)
        assert _bounds(
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

    def test_every_kind_is_either_scored_or_named_as_pending(self) -> None:
        assert set(TERMS) | PENDING == set(ConstraintKind)
        assert not set(TERMS) & PENDING

    def test_a_kind_this_part_cannot_score_stops_the_solve(self) -> None:
        """Loud rather than quiet. Scoring the kinds we have and omitting the rest produces
        a timetable optimised against a rulebook nobody wrote down. Part 2 empties `PENDING`
        and this test goes with it."""
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
