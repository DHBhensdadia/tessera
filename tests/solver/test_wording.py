"""What the explanation says, and the two things it is not allowed to say.

The sentences are **looked up, not written** (D8). `INVARIANTS` has carried a statement for
each of the seven since 3.5 and `ConstraintSpec` a summary per kind; the rules screen renders
both. An eighth set here would drift, and the symptom would be a rule described one way on the
screen that sets it and another in the sentence explaining why the term is impossible. So the
first test below is an equality against the domain rather than against a string typed twice.

The only new prose is the *quantity* — "64 against 60" — because it exists nowhere else.
"""

from __future__ import annotations

import pytest

from tessera.domain.constraints import INVARIANT_BY_KEY, ConstraintKind
from tessera.solver import Budget, Outcome, preflight, solve
from tessera.solver.result import Explanation, Requirement
from tests.solver import impossible as no

BUDGET = Budget(seconds=10.0)


class TestTheSentencesComeFromTheDomain:
    @pytest.mark.parametrize("invariant", INVARIANT_BY_KEY.values(), ids=lambda i: i.key)
    def test_every_invariant_reads_back_word_for_word(self, invariant: object) -> None:
        """Equality with the domain, not a copy of it.

        If this ever needs updating because a rule was reworded, the explanation was carrying
        prose of its own and the drift D8 exists to prevent had already happened.
        """
        requirement = Requirement(invariant.key, "room", 1)  # type: ignore[attr-defined]

        assert requirement.statement == invariant.statement  # type: ignore[attr-defined]
        assert requirement.because == invariant.because  # type: ignore[attr-defined]

    def test_a_stored_rule_reads_as_the_rules_screen_writes_it(self) -> None:
        """And carries no `because`: it is hard because somebody set it that way."""
        requirement = Requirement(ConstraintKind.SAME_DAY.value, "constraint", 7)

        assert requirement.statement == ConstraintKind.SAME_DAY.spec.describe({})
        assert requirement.because == ""

    def test_no_name_appears_in_anything_the_engine_says(self) -> None:
        """The engine holds ids; the client holds names.

        `Snapshot` has no instructor names in it at all, so a sentence naming Prof. Sharma
        could only be invented. `subject_kind` and `subject_id` travel instead, which is what
        `ConflictingRequirement` was already shaped for.
        """
        requirement = Requirement("instructor_not_double_booked", "instructor", 4)

        assert requirement.statement == "No instructor teaches two sessions at once"
        assert "4" not in requirement.statement


class TestTheCountReadsAsASentence:
    @pytest.mark.parametrize(
        ("term", "expected"),
        [
            (
                no.capacity_threshold(),
                "9 sessions needing a room that seats 50 or more need 18 hours, and the rooms "
                "that could take them offer 16 hours — 2 short.",
            ),
            (
                no.more_sessions_than_room_periods(),
                "9 sessions need 9 hours, and the rooms that could take them offer 8 hours — "
                "1 short.",
            ),
            (
                no.instructor_away_most_of_the_week(),
                "3 sessions need 3 hours, and instructor 1 is free for 2 hours — 1 short.",
            ),
            (
                no.group_attending_more_than_the_week(),
                "9 sessions need 9 hours, and group 1 has 8 hours — 1 short.",
            ),
            (
                no.no_room_with_the_feature(),
                "1 session needs equipment no room in the institution has.",
            ),
            (
                no.the_only_room_is_shut_all_week(),
                "1 session could only go in rooms that are closed all week.",
            ),
            (
                no.instructor_away_all_week(),
                "1 session could only be taught by instructor 1, who is unavailable all week.",
            ),
        ],
        ids=["threshold", "pigeonhole", "away", "group", "features", "closed", "nobody free"],
    )
    def test_the_numbers_are_read_out_in_hours(self, term: object, expected: str) -> None:
        (found,) = preflight.check(term)  # type: ignore[arg-type]

        assert found.statement == expected

    def test_a_supply_of_zero_names_the_resource_that_ran_out(self) -> None:
        """The guard for the pair above, and the third time this defect has been found.

        Two terms with identical arithmetic — a supply of zero against a demand of one — and
        two different resources. The sentence was keyed on the rule alone, so both read as
        being about rooms, and the one whose rooms were open all week sent its reader to the
        screen that was fine. #283 named the wrong rule; #287 put a seats clause where nothing
        had narrowed anything; this is the same mistake in the resource.
        """
        (shut,) = preflight.check(no.the_only_room_is_shut_all_week())
        (nobody,) = preflight.check(no.instructor_away_all_week())

        assert (shut.needed, shut.available) == (nobody.needed, nobody.available)
        assert shut.rule == nobody.rule
        assert "room" in shut.statement and "instructor" not in shut.statement
        assert "instructor" in nobody.statement and "room" not in nobody.statement

    def test_a_seats_clause_appears_only_where_seats_narrowed_the_estate(self) -> None:
        """`room_not_double_booked` is the week being small, not the big rooms being few.

        A clause about capacity there sends a reader to look at seats that are fine — the
        same species of misdirection as calling a closed room too small.
        """
        (pigeonhole,) = preflight.check(no.more_sessions_than_room_periods())
        (threshold,) = preflight.check(no.capacity_threshold())

        assert "seats" not in pigeonhole.statement
        assert "seats 50 or more" in threshold.statement

    def test_one_of_something_is_never_plural(self) -> None:
        (found,) = preflight.check(no.no_room_with_the_feature())

        assert found.statement.startswith("1 session needs")


class TestWhatTheSummaryRefusesToPromise:
    """D5, as wording. The claim P7 drew and the schema described could not be supported."""

    def test_a_conflict_says_that_others_may_remain(self) -> None:
        found = solve(no.one_instructor_pinned_into_two_rooms(), BUDGET)

        assert found.explanation is not None
        summary = found.explanation.summary

        assert "every one of them is needed" in summary
        assert "there may be others" in summary
        assert "not on its own a promise" in summary

    def test_nothing_anywhere_claims_that_relaxing_one_is_enough(self) -> None:
        """Swept across every explanation this suite can produce, not just the one above.

        The sentence that was wrong is easy to reintroduce in a summary, a statement or a
        rule's own wording, so the check is over all three at once.
        """
        terms = [
            no.one_instructor_pinned_into_two_rooms(),
            no.rules_that_contradict_each_other(),
            no.capacity_threshold(),
            no.two_pins_in_one_room(),
            no.instructor_away_most_of_the_week(),
        ]
        for term in terms:
            found = solve(term, BUDGET)
            assert found.outcome is Outcome.IMPOSSIBLE
            assert found.explanation is not None
            words = " ".join((found.explanation.summary, *found.explanation.statements)).lower()

            assert "relaxing any one" not in words
            assert "makes a timetable possible" not in words

    def test_a_count_leads_with_the_worst_shortfall(self) -> None:
        found = solve(no.capacity_threshold(), BUDGET)

        assert found.explanation is not None
        assert found.explanation.summary.startswith("No valid timetable exists: 9 sessions")

    def test_a_builders_refusal_is_quoted_rather_than_paraphrased(self) -> None:
        found = solve(no.two_pins_in_one_room(), BUDGET)

        assert found.explanation is not None
        assert found.explanation.summary.endswith(found.explanation.unbuildable)

    def test_every_proven_thing_gets_a_line(self) -> None:
        explanation = Explanation(
            conflict=(
                Requirement("availability_respected", "instructor", 1),
                Requirement("instructor_not_double_booked", "instructor", 1),
            )
        )

        assert explanation.statements == (
            "Nothing is scheduled when a room or an instructor is unavailable",
            "No instructor teaches two sessions at once",
        )
