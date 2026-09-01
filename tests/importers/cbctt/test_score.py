"""The checker, broken one rule at a time.

**A checker is not verified by passing.** Every run in the Phase 0.1 sweep reported feasible,
and a checker that always answered "no violations" would have produced identical output — 21
instances of worthless evidence that looked perfect. So the question this file asks is never
*does it accept a good solution*; it is *can it be made to reject a bad one, and does it name
the right rule when it does*.

Every hard-rule mutation below is constructed to trip **one** rule. That takes care: a
curriculum clash that also double-books a room would pass even if only the room check worked,
which is the specific way a mutation suite can be green and prove nothing. Where the
formulation makes isolation impossible — two lectures of one course in one period genuinely
are a curriculum clash and a teacher clash as well — the test says so and asserts the rule it
is about is among them.

The soft costs are asserted **component by component** rather than on the total. Two errors of
opposite sign in different components sum to the right answer, and 4.3's whole exit test is
that a score can be compared kind for kind rather than as one number.

The known-good solution is `fixtures/toy.sol`, built by hand for the organisers' own example
instance and scoring **zero** on all four costs — which makes every mutation's cost a delta
from nothing, computable on paper and written into each test rather than read off the run.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tessera.importers.cbctt import read
from tessera.importers.cbctt.format import Course, Instance, MalformedInstanceError
from tessera.importers.cbctt.score import Costs, check
from tessera.importers.cbctt.solution import Placement
from tessera.importers.cbctt.solution import read as read_solution
from tessera.importers.cbctt.solution import write as write_solution

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def toy() -> Instance:
    return read(FIXTURES / "toy.ctt")


@pytest.fixture
def good() -> tuple[Placement, ...]:
    return read_solution(FIXTURES / "toy.sol")


def without(
    placements: tuple[Placement, ...], course: str, day: int, period: int
) -> tuple[Placement, ...]:
    return tuple(p for p in placements if (p.course, p.day, p.period) != (course, day, period))


def moved(
    placements: tuple[Placement, ...],
    course: str,
    from_day: int,
    from_period: int,
    *,
    day: int | None = None,
    period: int | None = None,
    room: str | None = None,
) -> tuple[Placement, ...]:
    """The same timetable with one lecture somewhere else. Fails loudly if it is not there.

    The source is named `from_day` and `from_period` so that `day=`, `period=` and `room=` are
    free to mean the destination. Naming them `day` and `period` collides with the keywords for
    where the lecture is going, and Python reports that as *multiple values for argument 'day'*
    on the six tests that move a lecture to a different hour — a confusing way to be told the
    helper cannot express what it is for.

    The destination is three named arguments rather than `**kwargs` because `**kwargs` cannot
    be typed for `dataclasses.replace`: every value is `int | str`, and `mypy --strict` rightly
    refuses to believe the `str` is going to `room`.
    """
    where = (course, from_day, from_period)
    matches = [p for p in placements if (p.course, p.day, p.period) == where]
    if len(matches) != 1:
        raise AssertionError(
            f"{course} at day {from_day} period {from_period} appears {len(matches)} times — "
            "the mutation is aimed at a lecture that is not there"
        )
    was = matches[0]
    goes = Placement(
        course=was.course,
        day=was.day if day is None else day,
        period=was.period if period is None else period,
        room=was.room if room is None else room,
    )
    return (*without(placements, course, from_day, from_period), goes)


class TestTheHandBuiltSolution:
    """The baseline every mutation is a delta from. On its own this class proves nothing —
    a checker that always agreed would pass all of it. It is here so the deltas mean
    something."""

    def test_it_breaks_no_hard_rule(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        report = check(toy, good)

        assert report.feasible, report.violations

    def test_it_costs_nothing_at_all(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        assert check(toy, good).costs == Costs()

    def test_it_places_every_lecture(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        assert len(good) == toy.lectures == 16


class TestEachHardRuleCanBeMadeToFail:
    def test_a_dropped_lecture(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        report = check(toy, without(good, "SceCosC", 4, 0))

        assert report.rules_broken == {"Lectures"}
        assert "2 lectures placed and needs 3" in report.violations[0].detail

    def test_an_extra_lecture_that_clashes_with_nothing(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """Day 0 period 3 is free in room A, free of Cur1, and free of Ocra — so the only
        thing wrong with a fourth SceCosC lecture there is that there should be three."""
        report = check(toy, (*good, Placement("SceCosC", 0, 3, "A")))

        assert report.rules_broken == {"Lectures"}

    def test_a_course_taught_twice_in_one_period(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """The one that cannot be isolated, and should not be: a course in two rooms at once
        is also its curriculum in two places and its teacher in two places. The formulation
        says all three, so the assertion is that `Lectures` is among them and says what it
        found."""
        report = check(toy, (*good, Placement("SceCosC", 1, 0, "B")))

        assert "Lectures" in report.rules_broken
        assert any("taught 2 times at day 1 period 0" in v.detail for v in report.violations)

    def test_a_lecture_of_a_course_that_does_not_exist(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        report = check(toy, (*good, Placement("NoSuchCourse", 0, 3, "A")))

        assert report.rules_broken == {"Lectures"}
        assert "not a course in this instance" in report.violations[0].detail

    def test_a_day_outside_the_week(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        report = check(toy, moved(good, "SceCosC", 4, 0, day=5))

        assert report.rules_broken == {"Lectures"}
        assert "outside the 5-day week" in report.violations[0].detail

    def test_a_period_outside_the_day(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        report = check(toy, moved(good, "SceCosC", 4, 0, period=4))

        assert report.rules_broken == {"Lectures"}
        assert "outside the 4 a day" in report.violations[0].detail

    def test_two_courses_of_one_curriculum_at_once(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """SceCosC joins TecCos at day 1 period 2 — same curriculum, **different rooms and
        different teachers**, so nothing but `Conflicts` can catch it."""
        report = check(toy, moved(good, "SceCosC", 1, 0, period=2))

        assert report.rules_broken == {"Conflicts"}
        assert "curriculum Cur1" in report.violations[0].detail

    def test_one_teacher_in_two_places(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        """The toy has four teachers and four courses, so a teacher clash has to be built.

        Geotec is given SceCosC's teacher — the two share no curriculum, which is what makes
        the clash a *teacher* clash and nothing else — and then put in the same period, in a
        room that is free.
        """
        shared = replace(
            toy,
            courses=tuple(
                replace(c, teacher="Ocra") if c.id == "Geotec" else c for c in toy.courses
            ),
        )
        assert check(shared, good).feasible, "the instance change alone must break nothing"

        report = check(shared, moved(good, "Geotec", 1, 3, period=0, room="B"))

        assert report.rules_broken == {"Conflicts"}
        assert "Ocra teaches" in report.violations[0].detail

    def test_two_lectures_in_one_room_at_once(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """Geotec onto SceCosC in room A. They share no curriculum and no teacher."""
        report = check(toy, moved(good, "Geotec", 1, 3, period=0))

        assert report.rules_broken == {"RoomOccupancy"}
        assert "room A holds ['Geotec', 'SceCosC']" in report.violations[0].detail

    def test_a_room_that_does_not_exist(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        report = check(toy, moved(good, "Geotec", 1, 3, room="Z"))

        assert report.rules_broken == {"RoomOccupancy"}
        assert "not a room in this instance" in report.violations[0].detail

    def test_a_period_the_course_declared_unavailable(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """TecCos declares day 2 period 0 unavailable. Room B is free there, its curricula are
        clear at that period, and its teacher teaches nothing else — so the move is legal in
        every way but the one being tested."""
        report = check(toy, moved(good, "TecCos", 0, 1, day=2, period=0))

        assert report.rules_broken == {"Availability"}
        assert "declares unavailable" in report.violations[0].detail


class TestEachSoftCostCanBeMadeToMove:
    """Each mutation stays feasible and moves exactly one component, by an amount worked out
    on paper. A cost that could only be seen in the total would be indistinguishable from a
    different cost of the same size."""

    def test_students_who_would_have_to_stand(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """All five TecCos lectures into room A: 40 students, 32 seats, eight over, five
        times. Room A is free at every one of those periods and TecCos still uses a single
        room, so stability does not move with it."""
        crammed = tuple(replace(p, room="A") if p.course == "TecCos" else p for p in good)
        report = check(toy, crammed)

        assert report.feasible, report.violations
        assert report.costs == Costs(room_capacity=40)

    def test_a_course_taught_on_too_few_days(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """SceCosC asks for three working days and gets two — one short, five points.

        Day 2 period 0 is chosen because it keeps both curricula contiguous on both days it
        touches, so compactness stays where it was.
        """
        report = check(toy, moved(good, "SceCosC", 1, 0, day=2, period=0))

        assert report.feasible, report.violations
        assert report.costs == Costs(minimum_working_days=5)

    def test_lectures_a_curriculum_has_to_come_in_for_alone(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """Cur2's day 0 becomes TecCos at period 1 and Geotec at period 3. **Two** isolated
        lectures, not one gap — which is the counting a paraphrase of this formulation gets
        wrong — so four points, not two."""
        report = check(toy, moved(good, "Geotec", 0, 2, period=3))

        assert report.feasible, report.violations
        assert report.costs == Costs(curriculum_compactness=4)

    def test_a_course_that_moves_room(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        """One Geotec lecture into room B. Eighteen students in a room for fifty costs
        nothing, the period does not change, so only the second room shows."""
        report = check(toy, moved(good, "Geotec", 0, 2, room="B"))

        assert report.feasible, report.violations
        assert report.costs == Costs(room_stability=1)


class TestThePublishedNumber:
    """`penalty` is what goes in the README beside somebody else's, so it gets its own tests
    rather than being trusted to follow from four components that are each correct."""

    def test_the_total_is_the_four_components(self) -> None:
        costs = Costs(
            room_capacity=8, minimum_working_days=5, curriculum_compactness=4, room_stability=1
        )

        assert costs.total == 18

    def test_the_penalty_is_the_total(self, toy: Instance, good: tuple[Placement, ...]) -> None:
        """Two components move at once here — capacity and stability — which is the case a
        component-by-component suite never sees."""
        report = check(toy, moved(good, "TecCos", 0, 1, room="A"))

        assert report.costs == Costs(room_capacity=8, room_stability=1)
        assert report.penalty == report.costs.total == 9

    def test_a_perfect_timetable_scores_nothing(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        assert check(toy, good).penalty == 0


class TestTheCostsAreCountedTheWayTheFormulationCountsThem:
    def test_a_course_in_three_rooms_costs_two_not_three(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        """Stability is *rooms beyond the first*, and it is per course rather than per
        lecture — a course with five lectures in two rooms costs one, not four."""
        spread = moved(good, "Geotec", 0, 2, room="B")

        assert check(toy, spread).costs.room_stability == 1

    def test_adjacency_does_not_run_across_midnight(self, toy: Instance) -> None:
        """The last period of one day does not neighbour the first of the next.

        Cur1 is given the **last** period of day 0 and the **first** of day 1 and nothing
        else, which are consecutive indices if the week is flattened into one line and are two
        isolated lectures if it is not. The first version of this test used day 0 period 0 and
        day 1 period 1 — not adjacent under either reading, so it asserted four points that
        both a right and a wrong checker would produce. It passed, which is what makes that
        kind of test worse than none.
        """
        ends = (Placement("ArcTec", 0, 3, "B"), Placement("ArcTec", 1, 0, "B"))
        report = check(toy, ends)

        assert report.costs.curriculum_compactness == 2 * 2


class TestTheSolutionFile:
    def test_it_round_trips(self, good: tuple[Placement, ...]) -> None:
        assert read_solution(write_solution(good)) == tuple(sorted(good))

    def test_it_is_written_in_a_stable_order(self, good: tuple[Placement, ...]) -> None:
        """A file that changes when the timetable has not makes every stored result's diff
        unreadable."""
        shuffled = tuple(reversed(good))

        assert write_solution(shuffled) == write_solution(good)

    def test_blank_lines_are_not_lectures(self) -> None:
        assert read_solution("\nArcTec B 0 0\n\n") == (Placement("ArcTec", 0, 0, "B"),)

    def test_a_duplicate_line_survives_reading(self) -> None:
        """Sorting into a set would delete the evidence of the fault `Lectures` exists to
        catch."""
        assert len(read_solution("ArcTec B 0 0\nArcTec B 0 0\n")) == 2

    def test_a_line_with_the_wrong_number_of_fields(self) -> None:
        with pytest.raises(MalformedInstanceError, match="needs four fields"):
            read_solution("ArcTec B 0\n")

    def test_a_period_that_is_not_a_number(self) -> None:
        with pytest.raises(MalformedInstanceError, match="period 'late' is not a number"):
            read_solution("ArcTec B 0 late\n")


class TestTheCheckerDoesNotFallOverOnRubbish:
    def test_an_empty_solution_is_reported_rather_than_crashing(self, toy: Instance) -> None:
        report = check(toy, ())

        assert not report.feasible
        assert report.rules_broken == {"Lectures"}

    def test_an_unknown_course_does_not_reach_the_arithmetic(self, toy: Instance) -> None:
        """`teacher_of` and the capacity lookup would both raise on a course the instance has
        never heard of. A garbled file has to produce a report saying so."""
        report = check(toy, (Placement("Ghost", 0, 0, "A"),))

        assert "not a course in this instance" in report.violations[0].detail
        assert report.costs.room_capacity == 0

    def test_an_unknown_room_does_not_reach_the_arithmetic(
        self, toy: Instance, good: tuple[Placement, ...]
    ) -> None:
        report = check(toy, moved(good, "TecCos", 0, 1, room="Z"))

        assert report.costs.room_capacity == 0


def test_a_course_with_no_lectures_at_all_is_still_scored() -> None:
    """The soft costs are computed whatever the hard rules say, so half the mutations above
    can exist. A course placed nowhere is short of every working day it asked for."""
    lonely = Instance(
        name="one course, nowhere",
        days=5,
        periods_per_day=4,
        courses=(Course(id="C", teacher="T", lectures=2, min_working_days=2, students=10),),
        rooms=(),
        curricula=(),
        unavailable=(),
    )

    assert check(lonely, ()).costs.minimum_working_days == 10
