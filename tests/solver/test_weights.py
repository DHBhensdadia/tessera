"""What a weight does — checked where the answer is a fact rather than a sample.

P5's exit test for this phase reads *"raising a weight measurably reduces that violation
class"*. Run against a time limit that is **not reliably true**, and this project already has
the counter-example: Phase 0.1 watched `comp09` come back with a *worse* score when given five
times the budget. CP-SAT is anytime, so what a time-limited solve returns is the best it
happened to reach, and comparing two of those compares two accidents.

At a **proven optimum** it is a theorem. Let `u` be the violation count of one kind and `C` the
cost of every other rule. If `x` is optimal at weight `v` and `y` is optimal at weight `w > v`:

    v·u(x) + C(x)  <=  v·u(y) + C(y)
    w·u(y) + C(y)  <=  w·u(x) + C(x)

Add them and `(v - w)·u(x) <= (v - w)·u(y)`; divide by the negative `v - w` and `u(y) <= u(x)`.
Raising a weight cannot increase the class it is attached to. And if it strictly decreases it,
the first line forces `C(y) > C(x)` — something else got worse, which is what a trade is.

So every test here solves to proven optimality and skips anything it cannot prove. That the
skip is not quietly eating the whole suite is itself measured, in
`test_a_weight_can_be_seen_to_change_the_answer`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import HealthCheck, assume, find, given, settings
from hypothesis import strategies as st

from tessera.domain.constraints import Constraint, ConstraintKind, ConstraintTarget, TargetKind
from tessera.domain.ids import SessionId
from tessera.solver import Budget, Solution, solve
from tessera.solver.objective import TERMS
from tests.domain.validation.generated import Instance
from tests.domain.validation.institution import LECTURE, TUTORIAL, Institution
from tests.solver.generated import _as, snapshot_of, to_score

#: Small terms, so a proven optimum is the ordinary outcome rather than a lucky one.
BUDGET = Budget(seconds=10)

#: The two weights compared. Far enough apart that the heavier rule genuinely dominates the
#: others, which the generator gives weights of one to four.
LIGHT, HEAVY = 1, 20

WEIGHED = frozenset(TERMS)


def priced(instance: Instance, kind: ConstraintKind, weight: int) -> Solution:
    """The term solved with one kind's weight changed and everything else left alone."""
    return solve(
        snapshot_of(
            replace(
                instance,
                constraints=[
                    _as(c, weight=weight) if c.kind is kind else c for c in instance.constraints
                ],
            )
        ),
        BUDGET,
    )


def units(found: Solution, kind: ConstraintKind, weight: int) -> int:
    """How many times this kind was broken, recovered from what it cost.

    The breakdown carries cost rather than count, and cost is `weight x units` — so the
    division is exact, and a remainder would mean the two had come apart.
    """
    cost = found.penalty_breakdown.get(kind.value, 0)
    assert cost % weight == 0, f"{kind.value} cost {cost}, which is not {weight} times anything"
    return cost // weight


def others(found: Solution, kind: ConstraintKind) -> int:
    """What every rule *except* this one cost. Their weights never change, so two of these
    are comparable across the pair of solves."""
    return found.penalty - found.penalty_breakdown.get(kind.value, 0)


def moved(instance: Instance, kind: ConstraintKind) -> tuple[Solution, Solution] | None:
    """The same term at two weights, or `None` if either could not be proven optimal."""
    light, heavy = priced(instance, kind, LIGHT), priced(instance, kind, HEAVY)
    return (light, heavy) if light.is_optimal and heavy.is_optimal else None


#: Pairs of rules that pull against each other, so that raising one weight has something to
#: buy the reduction *from*.
#:
#: **Measured, not guessed.** Eight pairs were tried and five never produced a trade at all:
#: gaps against hours-in-a-row, a minimum gap against gaps, same-room against not-overlap,
#: same-time against different-day. On terms this small both rules in each of those can simply
#: be satisfied at once, so the light weighting already scores zero and there is nothing for a
#: heavier one to improve. The three left are all concentration against spread, which is where
#: this palette's genuine disagreements are — and that is worth knowing rather than hiding
#: behind a strategy that looked broad.
CONTESTED = (
    (ConstraintKind.SAME_DAY, ConstraintKind.DIFFERENT_DAY),
    (ConstraintKind.SAME_DAY, ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY),
    (ConstraintKind.SAME_DAY, ConstraintKind.BALANCE_DAILY_LOAD),
)


def contested() -> st.SearchStrategy[Instance]:
    """A term carrying two rules that disagree about where its teaching should go."""
    return st.sampled_from(CONTESTED).flatmap(lambda pair: to_score(frozenset(pair), least_rules=2))


#: Every kind, and the pairs that argue. The first is breadth — all sixteen terms get asked
#: the question; the second is depth, because on the broad strategy 153 of 188 proven pairs
#: already scored zero at the light weight and had nothing to trade.
TERMS_TO_WEIGH = st.one_of(to_score(WEIGHED, least_rules=2), contested())

WEIGHING = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


class TestRaisingAWeight:
    @WEIGHING
    @given(instance=TERMS_TO_WEIGH, which=st.integers(min_value=0, max_value=2))
    def test_never_increases_the_class_it_is_attached_to(
        self, instance: Instance, which: int
    ) -> None:
        """D5, and the half that is a theorem rather than an observation.

        Only at a proven optimum, which is why `is_optimal` gates it rather than a time
        budget. Skipping is honest here: an unproven pair says nothing either way, and
        asserting on it would be asserting on wherever the search happened to stop. Three
        quarters of generated terms are proven, so the gate is not quietly eating the suite.
        """
        kind = instance.constraints[which % len(instance.constraints)].kind
        pair = moved(instance, kind)
        assume(pair is not None)
        assert pair is not None
        light, heavy = pair

        assert units(heavy, kind, HEAVY) <= units(light, kind, LIGHT), (
            f"{kind.value} was broken more often once it was worth more"
        )

    @WEIGHING
    @given(instance=TERMS_TO_WEIGH, which=st.integers(min_value=0, max_value=2))
    def test_buys_the_reduction_from_some_other_rule(self, instance: Instance, which: int) -> None:
        """The other half of the same theorem, and the one that makes it a *trade*.

        Nothing is free. If a heavier weight bought fewer violations of its own kind, some
        other kind must have got strictly worse — otherwise the cheaper weighting would have
        found that same arrangement and preferred it.

        The trade is an `if` rather than an `assume` on purpose. Written as a second
        assumption this discarded **every** example — 50 filtered, 0 kept — and Hypothesis
        said so rather than passing quietly. `test_a_weight_can_be_seen_to_change_the_answer`
        is what proves the branch is reached.
        """
        kind = instance.constraints[which % len(instance.constraints)].kind
        pair = moved(instance, kind)
        assume(pair is not None)
        assert pair is not None
        light, heavy = pair

        if units(heavy, kind, HEAVY) < units(light, kind, LIGHT):
            assert others(heavy, kind) > others(light, kind), (
                f"{kind.value} improved and nothing else got worse, so the cheaper "
                "weighting was not optimal after all"
            )

    def test_a_weight_can_be_seen_to_change_the_answer(self) -> None:
        """The guard against a property that holds because it never fires.

        Both tests above skip terms with no proven optimum, and the second only asserts
        anything where the weight actually bought something. A run where that branch is never
        reached passes exactly like a run where it always holds — which is the failure this
        phase already had once, in part 1, where 300 examples compared zero with zero.

        So: a generated term must exist where raising the weight genuinely reduces the class.
        Derandomised, because a search that succeeds on most runs is a test that fails on
        some.
        """

        def bites(instance: Instance) -> bool:
            kind = instance.constraints[0].kind
            pair = moved(instance, kind)
            if pair is None:
                return False
            light, heavy = pair
            return units(heavy, kind, HEAVY) < units(light, kind, LIGHT)

        find(
            contested(),
            bites,
            settings=settings(max_examples=400, deadline=None, database=None, derandomize=True),
        )


def about(kind: ConstraintKind, *targets: SessionId, weight: int) -> Constraint:
    return Constraint(
        kind=kind,
        weight=weight,
        targets=frozenset(ConstraintTarget(kind=TargetKind.SESSION, id=t) for t in targets),
    )


class TestTwoRulesThatCannotBothHold:
    """A term where the answer is forced, so the weight is visibly the thing deciding it.

    The lecture and the tutorial are asked to be on the same day *and* on different days.
    Exactly one of those can hold, whatever the solver does, so the optimum is always the
    cheaper rule broken — and which rule that is, is the weight's decision and nothing else's.
    """

    @staticmethod
    def contested(same_day: int, different_day: int) -> Solution:
        term = Institution(assignments=()).ruled(
            about(ConstraintKind.SAME_DAY, LECTURE, TUTORIAL, weight=same_day),
            about(ConstraintKind.DIFFERENT_DAY, LECTURE, TUTORIAL, weight=different_day),
        )
        found = solve(term.snapshot(), BUDGET)
        assert found.is_optimal, "the contested term was not solved to proven optimality"
        return found

    @pytest.mark.parametrize(
        ("same_day", "different_day", "broken"),
        [
            (5, 1, ConstraintKind.DIFFERENT_DAY),
            (1, 5, ConstraintKind.SAME_DAY),
            (100, 1, ConstraintKind.DIFFERENT_DAY),
            (1, 2, ConstraintKind.SAME_DAY),
        ],
    )
    def test_the_cheaper_rule_is_the_one_that_gives(
        self, same_day: int, different_day: int, broken: ConstraintKind
    ) -> None:
        found = self.contested(same_day, different_day)
        cost = different_day if broken is ConstraintKind.DIFFERENT_DAY else same_day

        assert found.penalty == cost
        assert found.penalty_breakdown == {broken.value: cost}

    def test_raising_one_weight_moves_the_violation_to_the_other_rule(self) -> None:
        """P5's sentence, demonstrated: the same term, one weight raised, and the class it
        names goes from broken to kept."""
        before = self.contested(same_day=1, different_day=5)
        after = self.contested(same_day=5, different_day=1)

        assert before.penalty_breakdown == {ConstraintKind.SAME_DAY.value: 1}
        assert after.penalty_breakdown == {ConstraintKind.DIFFERENT_DAY.value: 1}

    def test_an_equal_fight_is_still_settled_and_still_costs_one(self) -> None:
        """Neither rule can win on weight, so the solver picks one — but the *cost* is
        determined, and a term that returned zero here would mean both rules were satisfied,
        which is impossible."""
        found = self.contested(same_day=3, different_day=3)

        assert found.penalty == 3
        assert len(found.penalty_breakdown) == 1
