"""Which rules cannot hold together — and what the answer is allowed to claim.

Two things are being checked, and the second is the one that keeps the feature honest.

**That the conflict is right**: each of the seven invariants, and a hard distribution rule,
is broken on its own and the set names it. That is 4.1's mutation discipline pointed at a
different output — a core that always returned the same rule would look identical to a
correct one on any single term.

**That every member of it is necessary**: the deletion filter re-solves with each member
relaxed in turn and the term becomes solvable every time. Asserted by re-solving rather than
by trusting the word *minimal* in OR-Tools' documentation, because the report's whole claim
rests on it.

What is deliberately *not* asserted anywhere is that relaxing one member makes a timetable
possible. Where several independent conflicts exist CP-SAT names one, and P7's mockup and
the wire schema both said otherwise until this phase (D5).
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings

from tessera.domain.validation import Snapshot
from tessera.solver import Budget, Outcome, solve
from tessera.solver.explain import conflict, necessary_one_at_a_time
from tessera.solver.model import Model, build
from tessera.solver.result import Requirement
from tests.domain.validation.generated import Instance
from tests.solver import impossible as no
from tests.solver.generated import snapshot_of, to_solve

#: Small, and never asserted on as a duration — these terms are tiny and the budget is a
#: ceiling that should not be reached rather than the thing being measured (#244).
BUDGET = Budget(seconds=10.0)


def named(snapshot: Snapshot) -> set[str]:
    return {requirement.rule for requirement in conflict(snapshot, BUDGET)}


class TestEachRuleCanBeNamed:
    """Break one rule at a time; the conflict has to say which one.

    Six of the seven invariants reach here. The seventh, `room_not_double_booked`, is in
    `TestTheConflictIsMinimal` — it takes two sessions to break, so it arrives as part of a
    pair rather than alone.
    """

    @pytest.mark.parametrize(
        ("term", "expected"),
        [
            (no.no_room_big_enough(), "room_fits_group"),
            (no.no_room_with_the_feature(), "room_has_required_features"),
            (no.more_sessions_than_room_periods(), "room_not_double_booked"),
            (no.instructor_teaching_more_than_the_week(), "instructor_not_double_booked"),
            (no.group_attending_more_than_the_week(), "group_not_double_booked"),
            (no.the_only_room_is_shut_all_week(), "availability_respected"),
            (no.short_only_once_lunch_is_taken_out(), "breaks_protected"),
        ],
        ids=[
            "capacity",
            "features",
            "room clash",
            "instructor clash",
            "group clash",
            "a closed room",
            "a break",
        ],
    )
    def test_the_rule_that_was_broken_is_the_rule_that_is_named(
        self, term: Snapshot, expected: str
    ) -> None:
        assert expected in named(term)

    def test_a_person_in_two_rooms_at_once_is_named_by_the_person(self) -> None:
        """Nothing is short of anything here, so this is the core earning its place.

        Two rooms, two hours of teaching, a week of eight — and one instructor pinned into
        both at nine o'clock. `preflight` is silent, which is correct; the arithmetic is fine
        and the arrangement is not.
        """
        from tessera.solver import preflight

        term = no.one_instructor_pinned_into_two_rooms()

        assert preflight.check(term) == (), "no count can see this one"
        assert conflict(term, BUDGET) == (
            Requirement("instructor_not_double_booked", "instructor", 1),
        )

    def test_two_rules_that_contradict_each_other_are_named_as_rows(self) -> None:
        """By constraint id, because that is the row somebody would edit.

        Per kind would say *same day and different day disagree* in an institution that has
        four of each and leave the reader to find which.
        """
        assert conflict(no.rules_that_contradict_each_other(), BUDGET) == (
            Requirement("different_day", "constraint", 8),
            Requirement("same_day", "constraint", 7),
        )


class TestTheConflictIsMinimal:
    """Every member load-bearing, proven by asking again without it."""

    @pytest.mark.parametrize(
        "term",
        [
            no.one_instructor_pinned_into_two_rooms(),
            no.rules_that_contradict_each_other(),
            no.instructor_away_most_of_the_week(),
            no.more_sessions_than_room_periods(),
            no.short_only_once_lunch_is_taken_out(),
            no.the_only_room_is_shut_all_week(),
        ],
        ids=["pinned", "rules", "away", "pigeonhole", "lunch", "closed"],
    )
    def test_dropping_any_member_makes_the_term_solvable(self, term: Snapshot) -> None:
        found = conflict(term, BUDGET)

        assert found, "no conflict to check for minimality — the property would hold vacuously"
        verdict = necessary_one_at_a_time(term, BUDGET, found)

        assert all(verdict.values()), (
            f"{[str(r) for r, ok in verdict.items() if not ok]} could be relaxed and the term "
            "would still have no timetable, so the set is not minimal and the report claims "
            "more than it has"
        )

    def test_an_instructor_who_is_hardly_in_needs_two_rules_to_explain(self) -> None:
        """The shape P7 draws: an availability *and* the rule that stops overlapping it.

        Neither alone is a contradiction — three hours of teaching fit two hours only because
        they may not be taught at once — which is why the panel has room for more than one
        line.
        """
        found = conflict(no.instructor_away_most_of_the_week(), BUDGET)

        assert set(found) == {
            Requirement("availability_respected", "instructor", 1),
            Requirement("instructor_not_double_booked", "instructor", 1),
        }


class TestWhatItRefusesToSay:
    """The claims the mechanism does not support, asserted as refusals."""

    def test_a_solvable_term_produces_no_conflict(self) -> None:
        assert conflict(no.alternating_weeks_are_not_a_conflict(), BUDGET) == ()

    def test_a_rule_written_without_a_literal_is_a_defect_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard that makes an empty core impossible to ship quietly (D9).

        Sabotaging the builder is the only way here: every hard rule really does carry a
        literal, which is what the test above asserts. So this reintroduces the fault the
        guard exists for — a constraint written unconditionally — and confirms the guard
        fires rather than returning an explanation with nothing in it.
        """
        real = build

        def unconditional(snapshot: Snapshot, *args: Any, **kwargs: Any) -> Model:
            model = real(snapshot, *args, **kwargs)
            model.cp.add(model.starts[min(model.starts)] < 0)
            return model

        monkeypatch.setattr("tessera.solver.model.build", unconditional)

        with pytest.raises(AssertionError, match="no rule to blame"):
            conflict(no.more_sessions_than_room_periods(), BUDGET)

    def test_a_budget_measured_in_work_is_honoured(self) -> None:
        """The explainer takes the same reproducible budget the rest of the solver does.

        A conflict set that depended on how fast the machine was would be a different answer
        on CI from the one here, which is #257 arriving in a fourth place.
        """
        reproducible = Budget(seconds=10.0, deterministic_seconds=2.0)

        assert conflict(no.rules_that_contradict_each_other(), reproducible) == (
            Requirement("different_day", "constraint", 8),
            Requirement("same_day", "constraint", 7),
        )

    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(instance=to_solve())
    def test_a_term_the_solver_solves_has_no_conflict(self, instance: Instance) -> None:
        """The counterpart of the pre-flight's soundness property.

        A conflict is a claim that some rules cannot hold together. If the solver just found
        a timetable, they held.
        """
        snapshot = snapshot_of(instance)
        assume(solve(snapshot, BUDGET).outcome is Outcome.SOLVED)

        assert conflict(snapshot, BUDGET) == ()


class TestTheSolveCarriesIt:
    """What a caller gets, through the path that ships."""

    def test_an_impossible_term_comes_back_naming_rules(self) -> None:
        found = solve(no.one_instructor_pinned_into_two_rooms(), BUDGET)

        assert found.outcome is Outcome.IMPOSSIBLE
        assert found.explanation is not None
        assert [str(r) for r in found.explanation.conflict] == [
            "instructor_not_double_booked/instructor 1"
        ]

    def test_a_counted_term_answers_from_the_count_and_never_builds_a_model(self) -> None:
        """Arithmetic first. The conflict set is for what counting cannot see."""
        found = solve(no.capacity_threshold(), BUDGET)

        assert found.explanation is not None
        assert found.explanation.shortfalls, "the count is what refuted this"
        assert found.explanation.conflict == ()
        assert found.work == 0.0

    def test_the_builders_refusal_still_wins(self) -> None:
        found = solve(no.two_pins_in_one_room(), BUDGET)

        assert found.outcome is Outcome.IMPOSSIBLE
        assert found.explanation is not None
        assert "both pinned into room 1" in found.explanation.unbuildable
        assert found.explanation.conflict == ()

    def test_running_out_of_time_is_never_explained(self) -> None:
        """A budget too small to prove anything must not produce a set of rules to blame."""
        found = solve(no.one_instructor_pinned_into_two_rooms(), Budget(seconds=1e-6))

        assert found.outcome is Outcome.OUT_OF_TIME
        assert found.explanation is None
