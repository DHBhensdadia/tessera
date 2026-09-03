"""What the counting check proves, and — the harder half — what it must never claim.

**A false positive here is worse than no check at all.** Reporting a shortfall that is not
there refuses a term somebody could have run, and it does it in milliseconds with an
authoritative number attached. So the suite is weighted towards silence: every one of the
twenty-one published ITC-2007 instances is checked, twenty of them for *nothing*, and a
generated term the solver actually solves must never be refuted.

The one instance that is refuted, `comp01`, is the reason the module exists. It is
published, nobody built it to be impossible, and #213 counted it independently four phases
ago and wrote the numbers into `docs/fidelity/itc-2007.md`. This asserts the same three
numbers, computed from the term rather than read from the document.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, find, given, settings

from tessera.domain.entities import Room, Unavailability
from tessera.domain.ids import AssignmentId, InstructorId, RoomId, SessionId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot
from tessera.solver import Budget, Outcome, preflight, solve
from tessera.solver.model import Formulation
from tessera.solver.preflight import (
    BY_CLASSES,
    BY_LOAD,
    BY_SWEEP,
    _capacity_is_the_only_filter,
    _classes,
    _sweep,
    _Term,
    _unplaceable,
)
from tessera.solver.result import Explanation, Solution
from tests.domain.validation.generated import Instance
from tests.domain.validation.test_scale import institution
from tests.solver import impossible as no
from tests.solver.generated import snapshot_of, to_solve
from tests.solver.scored import cbctt

#: Small enough that a generated term is decided rather than abandoned, and never asserted
#: on as a duration — what a solve does in ten seconds is a fact about the machine (#244).
BUDGET = Budget(seconds=10.0)


def rules_named(snapshot: Snapshot) -> set[str]:
    return {shortfall.rule for shortfall in preflight.check(snapshot)}


class TestTheReasonsItCanName:
    """One term per arithmetic reason, and the smallest change that makes it go away.

    The second half is the point. A check that fires is not a check that fires *for this* —
    §2b of the working agreement, and the reason Phase 1.5's orphan test turned out to be a
    false guard.
    """

    def test_a_session_no_room_can_seat(self) -> None:
        term = no.no_room_big_enough()
        found = preflight.check(term)

        assert [s.rule for s in found] == ["room_fits_group"] * 2, (
            "both sessions are unplaceable, and a term with two problems has two lines"
        )
        assert all(s.available == 0 and len(s.sessions) == 1 for s in found)

        roomier = no.term(
            sessions=list(term.sessions.values()),
            rooms=[no.room(1, seats=40)],
            sizes={1: 40},
        )
        assert preflight.check(roomier) == ()

    def test_a_session_needing_a_feature_nobody_has(self) -> None:
        term = no.no_room_with_the_feature()
        (found,) = preflight.check(term)

        assert found.rule == "room_has_required_features"
        assert found.counted_by == BY_CLASSES, "features are not a threshold, so not a sweep"

        equipped = no.term(
            sessions=list(term.sessions.values()),
            rooms=[no.room(1, seats=100, features=frozenset({no.PROJECTOR}))],
            sizes={1: 10},
        )
        assert preflight.check(equipped) == ()

    def test_more_large_classes_than_large_rooms(self) -> None:
        """`comp01`'s shape. The rooms are plentiful; the *big* rooms are not."""
        (found,) = preflight.check(no.capacity_threshold())

        assert (found.rule, found.counted_by) == ("room_fits_group", BY_SWEEP)
        assert (found.threshold, found.needed, found.available, found.short) == (50, 18, 16, 2)
        assert len(found.sessions) == 9

        roomier = no.term(
            sessions=[no.lecture(n, group=n, instructor=n, duration=2) for n in range(1, 10)],
            rooms=[no.room(n, seats=60) for n in range(1, 4)],
            sizes=dict.fromkeys(range(1, 10), 50),
        )
        assert preflight.check(roomier) == (), "a third large room is four more hours than needed"

    def test_more_teaching_than_room_periods(self) -> None:
        (found,) = preflight.check(no.more_sessions_than_room_periods())

        assert found.rule == "room_not_double_booked", (
            "every room fits every session, so nothing narrowed the estate — what is short "
            "is the week"
        )
        assert (found.needed, found.available) == (9, 8)

        roomier = no.term(
            sessions=[no.lecture(n, group=n, instructor=n) for n in range(1, 10)],
            rooms=[no.room(1, seats=100), no.room(2, seats=100)],
            sizes=dict.fromkeys(range(1, 10), 10),
        )
        assert preflight.check(roomier) == ()

    def test_an_instructor_who_is_hardly_ever_in(self) -> None:
        """P7's headline case, and the rule named is the one bounding the supply."""
        (found,) = preflight.check(no.instructor_away_most_of_the_week())

        assert (found.rule, found.subject_kind, found.subject_id) == (
            "availability_respected",
            "instructor",
            1,
        )
        assert (found.needed, found.available, found.counted_by) == (3, 2, BY_LOAD)

        available = no.term(
            sessions=[no.lecture(n, group=n, instructor=1) for n in range(1, 4)],
            rooms=[no.room(n, seats=100) for n in range(1, 4)],
            sizes=dict.fromkeys(range(1, 4), 10),
            unavailability=[
                Unavailability(instructor_id=InstructorId(1), slot=slot)
                for slot in range(3, no.WEEK)
            ],
        )
        assert preflight.check(available) == (), "three free hours hold three hours of teaching"

    def test_an_instructor_teaching_more_hours_than_the_week_has(self) -> None:
        (found,) = preflight.check(no.instructor_teaching_more_than_the_week())

        assert found.rule == "instructor_not_double_booked", (
            "nothing was said about when they are free, so the bound is the week itself"
        )
        assert (found.needed, found.available) == (9, 8)

        shorter = no.term(
            sessions=[no.lecture(n, group=n, instructor=1) for n in range(1, 9)],
            rooms=[no.room(n, seats=100) for n in range(1, 9)],
            sizes=dict.fromkeys(range(1, 9), 10),
        )
        assert preflight.check(shorter) == ()

    def test_a_group_with_more_classes_than_hours(self) -> None:
        (found,) = preflight.check(no.group_attending_more_than_the_week())

        assert (found.rule, found.subject_kind, found.subject_id) == (
            "group_not_double_booked",
            "group",
            1,
        )
        assert (found.needed, found.available) == (9, 8)

        split = no.term(
            sessions=[no.lecture(n, group=1 + n % 2, instructor=n) for n in range(1, 10)],
            rooms=[no.room(n, seats=100) for n in range(1, 10)],
            sizes={1: 10, 2: 10},
        )
        assert preflight.check(split) == (), "two groups of at most five classes each"

    def test_the_deeper_of_two_thresholds_is_the_one_reported(self) -> None:
        """Both counts hold; one line is the useful number of lines.

        Reporting every threshold that is short would produce a panel restating one problem
        at every capacity below the binding one — the failure mode of a check that prints
        its working rather than its finding.
        """
        (found,) = preflight.check(no.two_thresholds_short_by_different_amounts())

        assert (found.threshold, found.needed, found.available, found.short) == (100, 12, 8, 4)
        assert found.rule == "room_fits_group"

    def test_a_break_is_not_room_time(self) -> None:
        """Seven hours into a room open for six of the week's eight.

        The two hours of lunch are the whole shortfall: counted as room time this term has
        an hour spare, and a check that reported nothing here would be over-stating supply
        by exactly the size of the break.
        """
        (found,) = preflight.check(no.short_only_once_lunch_is_taken_out())

        assert (found.rule, found.needed, found.available) == ("room_not_double_booked", 7, 6)

        shorter = no.term(
            sessions=[no.lecture(n, group=n, instructor=n) for n in range(1, 7)],
            rooms=[no.room(1, seats=100)],
            sizes=dict.fromkeys(range(1, 7), 10),
            grid=no.WITH_LUNCH,
        )
        assert preflight.check(shorter) == (), "six hours of teaching fit six teaching hours"

    def test_an_institution_with_no_rooms_names_its_sessions(self) -> None:
        (found,) = preflight.check(no.an_institution_with_no_rooms())

        assert (found.rule, found.available) == ("room_has_required_features", 0)
        assert found.sessions == (1,)

    def test_alternating_weeks_are_not_counted_against_each_other(self) -> None:
        """The false positive the whole module is arranged around.

        Sixteen hours for one group in a week eight hours long — and feasible, because half
        of them happen in odd weeks and half in even. Counted without regard to pattern this
        term reads as impossible, which is the mistake that would refuse a real timetable.
        """
        assert preflight.check(no.alternating_weeks_are_not_a_conflict()) == ()

    def test_the_week_pattern_guard_is_what_keeps_it_silent(self) -> None:
        """The same term with the patterns removed *is* impossible, and is refuted.

        Without this the test above passes for any reason at all, including the check having
        quietly stopped looking at groups.
        """
        term = no.alternating_weeks_are_not_a_conflict()
        every_week = no.term(
            sessions=[
                no.lecture(int(s), group=1, instructor=int(s)) for s in sorted(term.sessions)
            ],
            rooms=[no.room(n, seats=100) for n in range(1, 3)],
            sizes={1: 10},
        )
        assert "group_not_double_booked" in rules_named(every_week)


class TestSilenceIsNotAVerdict:
    """*Could not find one* and *there is not one* are different sentences (#205).

    This module may only ever say the second, so the property that matters is the
    contrapositive: anything the solver can actually solve must not be refuted here.
    """

    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(instance=to_solve())
    def test_a_term_the_solver_solves_is_never_refuted(self, instance: Instance) -> None:
        snapshot = snapshot_of(instance)
        found = solve(snapshot, BUDGET)
        assume(found.outcome is Outcome.SOLVED)

        assert preflight.check(snapshot) == (), (
            "a timetable exists for this term — the solver just produced one — so every "
            "count that says otherwise is wrong"
        )

    def test_generated_terms_do_get_solved(self) -> None:
        """The guard against a property that holds because it never fires (#262).

        `assume` discards every term the solver could not place, and a run where it discards
        *all* of them passes exactly like a run where the property is true. Derandomised,
        because a search that succeeds on most runs is a test that fails on some.
        """
        find(
            to_solve(),
            lambda instance: solve(snapshot_of(instance), BUDGET).outcome is Outcome.SOLVED,
            settings=settings(max_examples=200, deadline=None, database=None, derandomize=True),
        )

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(instance=to_solve())
    def test_a_refuted_term_is_never_solved(self, instance: Instance) -> None:
        """The same claim from the other end, on whatever the generator makes impossible."""
        snapshot = snapshot_of(instance)
        assume(preflight.check(snapshot))

        assert solve(snapshot, BUDGET).outcome is not Outcome.SOLVED


class TestTheTwoCountings:
    """The sweep is an optimisation of the flow, so it has to answer the same question.

    Where eligibility is capacity alone the two are interchangeable and the sweep is chosen
    for speed. **The flow is the definition**: if they ever disagree the sweep is wrong and
    comes out, which is why this compares them rather than trusting the argument that they
    are equivalent.
    """

    @pytest.mark.parametrize(
        "term",
        [
            no.capacity_threshold(),
            no.more_sessions_than_room_periods(),
            no.no_room_big_enough(),
            no.instructor_away_most_of_the_week(),
            no.alternating_weeks_are_not_a_conflict(),
        ],
        ids=["threshold", "pigeonhole", "unplaceable", "instructor", "alternating"],
    )
    def test_the_sweep_and_the_flow_reach_the_same_verdict(self, term: Snapshot) -> None:
        counted = _Term.of(term, capacity_is_priced=False)
        homeless = {shortfall.sessions[0] for shortfall in _unplaceable(counted)}
        swept = _sweep(counted, homeless)
        flowed = _classes(counted, homeless)

        assert bool(swept) == bool(flowed), (
            f"the sweep found {len(swept)} and the flow {len(flowed)} on the same term"
        )
        assert [s.needed for s in swept] == [s.needed for s in flowed]
        assert [s.available for s in swept] == [s.available for s in flowed]
        assert [sorted(s.sessions) for s in swept] == [sorted(s.sessions) for s in flowed]

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(instance=to_solve())
    def test_they_agree_on_generated_terms_too(self, instance: Instance) -> None:
        counted = _Term.of(snapshot_of(instance), capacity_is_priced=False)
        assume(_capacity_is_the_only_filter(counted))
        homeless = {shortfall.sessions[0] for shortfall in _unplaceable(counted)}

        swept, flowed = _sweep(counted, homeless), _classes(counted, homeless)
        assert bool(swept) == bool(flowed)
        assert [s.needed for s in swept] == [s.needed for s in flowed]
        assert [s.available for s in swept] == [s.available for s in flowed]


class TestWhatTheSolverDoesWithIt:
    """The count runs first, and what it found reaches the caller."""

    def test_a_counted_term_is_refused_without_a_search(self) -> None:
        found = solve(no.capacity_threshold(), BUDGET)

        assert found.outcome is Outcome.IMPOSSIBLE
        assert found.explanation is not None
        assert [s.rule for s in found.explanation.shortfalls] == ["room_fits_group"]
        assert found.work == 0.0, "nothing was searched, because nothing needed to be"

    def test_a_refusal_from_the_builder_keeps_its_sentence(self) -> None:
        """`model.build` names the two sessions and the room, and used to be ignored.

        A pin cannot be counted — arithmetic has nothing to say about two sessions wanting
        one room at one hour — so this is the path where the builder is the only thing that
        knows, and until now `solve` caught the exception and discarded the message.
        """
        term = no.term(
            sessions=[no.lecture(1, group=1), no.lecture(2, group=1)],
            rooms=[no.room(1, seats=100)],
            sizes={1: 10},
        )
        pinned = Snapshot.of(
            grid=term.grid,
            sessions=list(term.sessions.values()),
            rooms=list(term.rooms.values()),
            groups=term.groups,
            assignments=[_pin(1, start=0, room=1), _pin(2, start=0, room=1)],
        )
        found = solve(pinned, BUDGET)

        assert found.outcome is Outcome.IMPOSSIBLE
        assert found.explanation is not None
        assert "both pinned into room 1" in found.explanation.unbuildable
        assert found.explanation.shortfalls == (), "the count had nothing to say about a pin"

    def test_a_priced_capacity_leaves_the_count_with_nothing_to_say(self) -> None:
        """CB-CTT's rules, where a room too small is a cost rather than a refusal (#260).

        Without this the benchmark would report `comp01` — which 4.5 solves and scores as a
        valid CB-CTT solution — as having no timetable, and the harness would lose two of
        its twenty-one instances to a check that was measuring a different problem.
        """
        term = no.capacity_threshold()

        assert preflight.check(term) != ()
        assert preflight.check(term, capacity_is_priced=True) == ()
        assert solve(term, BUDGET, formulation=Formulation(capacity_is_priced=True)).outcome is (
            Outcome.SOLVED
        )


class TestTheExplanationRecord:
    """`Solution` refuses the two shapes an explanation must never take."""

    def test_an_explanation_belongs_only_to_an_impossible_solve(self) -> None:
        with pytest.raises(ValueError, match="has not been shown that none does"):
            Solution(
                outcome=Outcome.OUT_OF_TIME,
                explanation=Explanation(unbuildable="the budget ran out"),
            )

    def test_an_explanation_that_explains_nothing_is_refused(self) -> None:
        with pytest.raises(ValueError, match="explains nothing"):
            Explanation()

    def test_running_out_of_time_carries_no_explanation(self) -> None:
        """The distinction `Outcome` exists for, asserted where it would be lost."""
        found = solve(no.capacity_threshold(), Budget(seconds=0.001))

        assert found.outcome is Outcome.IMPOSSIBLE, "counting does not need a budget"
        assert found.explanation is not None


def instances() -> Path | None:
    given = os.environ.get("TESSERA_ITC2007_INSTANCES")
    if not given:
        return None
    found = Path(given).expanduser()
    return found if list(found.glob("comp*.ctt")) else None


ROOT = instances()


@pytest.mark.benchmark
@pytest.mark.skipif(ROOT is None, reason="set TESSERA_ITC2007_INSTANCES to the ITC-2007 directory")
class TestTheRealInstances:
    """Twenty-one published terms: one refuted, twenty untouched."""

    def test_comp01_is_refuted_with_the_numbers_the_record_already_carries(self) -> None:
        """#213, recomputed rather than quoted.

        > 64 lectures need a room seating 31 or more and the week contains 60 such
        > room-periods, short by four, so no arrangement exists.

        CP-SAT reports `out_of_time` on this term at thirty seconds under every formulation
        this project has.
        """
        assert ROOT is not None
        (found,) = preflight.check(cbctt(ROOT / "comp01.ctt", constraints=()))

        assert (found.threshold, found.needed, found.available, found.short) == (31, 64, 60, 4)
        assert (found.rule, found.counted_by) == ("room_fits_group", BY_SWEEP)
        assert len(found.sessions) == 64

    @pytest.mark.parametrize("stem", [f"comp{n:02d}" for n in range(2, 22)])
    def test_no_other_instance_is_refuted(self, stem: str) -> None:
        """Including `comp20`, which 4.2 could not solve and nothing has proven impossible.

        Being quiet about it is the correct answer and the one this check has to get right:
        a count that guessed at the instances the solver merely failed on would be inventing
        the thing the module was written to avoid.
        """
        assert ROOT is not None
        assert preflight.check(cbctt(ROOT / f"{stem}.ctt", constraints=())) == ()

    def test_comp01_solves_once_capacity_is_priced(self) -> None:
        assert ROOT is not None
        term = cbctt(ROOT / "comp01.ctt", constraints=())

        assert preflight.check(term, capacity_is_priced=True) == ()


@pytest.mark.slow
class TestWhatItCosts:
    """P7 budgets fifty milliseconds, and the shape is what is asserted rather than the number.

    Measured on macOS 15 / arm64, best of three, at NFR-9's ceiling of 5,000 sessions and 500
    rooms: **10.3 ms** on an estate where every room is the same, **12.4 ms** on one with four
    hundred distinct capacities, and **0.97 ms** at department scale. The 21 ITC-2007
    instances peak at 1.1 ms.

    What is asserted is that the second of those is not materially worse than the first —
    which is the property that would break if the nested sweep were replaced by the general
    flow, whose prototype took **766 ms** on the same estate. A wall-clock threshold would be
    an assertion about the machine (#244); this is an assertion about the algorithm.
    """

    @staticmethod
    def ceiling(capacities: int | None) -> Snapshot:
        filled = institution(sessions=5000, rooms=500)
        rooms = (
            list(filled.rooms.values())
            if capacities is None
            else [
                Room(id=RoomId(i), name=f"Room {i}", capacity=20 + i % capacities)
                for i in range(1, 501)
            ]
        )
        return Snapshot.of(
            grid=filled.grid,
            sessions=list(filled.sessions.values()),
            rooms=rooms,
            groups=filled.groups,
            assignments=[],
        )

    @staticmethod
    def fastest(snapshot: Snapshot) -> float:
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            preflight.check(snapshot)
            best = min(best, time.perf_counter() - started)
        return best

    def test_the_cost_does_not_follow_the_number_of_room_sizes(self) -> None:
        uniform = self.fastest(self.ceiling(None))
        varied = self.fastest(self.ceiling(400))

        assert varied < uniform * 4, (
            f"{varied * 1000:.1f} ms against {uniform * 1000:.1f} ms — an estate of many "
            "sizes is being counted class by class rather than swept"
        )


def _pin(session: int, *, start: int, room: int) -> Assignment:
    return Assignment(
        id=AssignmentId(session),
        session_id=SessionId(session),
        start_slot=start,
        room_id=RoomId(room),
        is_pinned=True,
    )
