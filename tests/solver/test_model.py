"""What the model is built from, before anything is searched.

Most of the correctness of this phase is in the *shape* of the model rather than in the
search: a start whose domain contains an illegal hour, or a room that should never have been a
candidate, is a wrong answer CP-SAT will find efficiently. So these tests are about what got
written down.

The other half — that a solved timetable actually satisfies the rules — is
`test_feasibility.py`, and it asks the 4.1 validator rather than asking the solver again.
"""

from __future__ import annotations

import pytest
from ortools.sat.python import cp_model

from tessera.domain.entities import Unavailability, WeekPattern
from tessera.domain.ids import AssignmentId, InstructorId
from tessera.domain.timetable import Assignment
from tessera.solver import Outcome, solve
from tessera.solver.model import UnsatisfiableError, build, size
from tessera.solver.result import Requirement
from tests.domain.validation.institution import (
    CUPBOARD,
    HALL,
    LAB,
    LAB_A,
    LAB_B,
    LECTURE,
    LUNCH,
    STUDIO,
    TUTORIAL,
    Institution,
)
from tests.solver import impossible as no


@pytest.fixture
def empty() -> Institution:
    """The known-good institution with nothing placed — the solver's job rather than a fact."""
    return Institution(assignments=())


class TestWhichRoomsAreEvenConsidered:
    def test_a_session_only_gets_rooms_that_could_hold_it(self, empty: Institution) -> None:
        """#35's pruning, and the reason the model does not explode.

        The lab needs thirty workstations and there is one room with them; the lecture needs
        sixty seats and there are two rooms that big. Forty rooms would become three, which is
        the difference between a model that fits in memory and one that does not.
        """
        model = build(empty.snapshot())

        assert [c.room for c in model.candidates[LAB_A]] == [LAB]
        assert [c.room for c in model.candidates[LECTURE]] == [HALL]

    def test_it_uses_the_same_test_the_validator_uses(self, empty: Institution) -> None:
        """`Room.can_host`, so the solver cannot consider a room the validator would reject.

        Two answers to "may this session go here" is the drift Decision #5 is about, and it
        would show up as a timetable the solver was proud of and the interface painted red.
        """
        model = build(empty.snapshot())
        rooms = empty.snapshot().rooms

        for session_id, candidates in model.candidates.items():
            session = empty.snapshot().sessions[session_id]
            headcount = empty.snapshot().headcount(session)
            for candidate in candidates:
                assert rooms[candidate.room].can_host(
                    headcount, session.required_features, session.required_counts
                )

    def test_a_session_nothing_can_hold_is_refused_while_building(self) -> None:
        """Arithmetic already knows. CP-SAT would report INFEASIBLE after searching, which is
        a slower way to learn it and a worse one — this message names the session."""
        crowded = Institution(assignments=()).rooms_of_only(CUPBOARD)

        with pytest.raises(UnsatisfiableError, match="no room that can hold it"):
            build(crowded.snapshot())


class TestWhenASessionMayStart:
    def test_the_domain_is_the_legal_hours_not_a_range(self, empty: Institution) -> None:
        """D2. The grid already refuses a session that runs past the end of a day, crosses
        midnight or runs through a break, so the domain is those hours and the solver never
        explores an impossible one."""
        model = build(empty.snapshot())
        grid = empty.grid
        lecture = model.starts[LECTURE]  # two hours long

        allowed = {v for v in range(grid.slot_count) if lecture.proto.domain and _in(lecture, v)}

        assert all(grid.can_hold(v, 2) for v in allowed)
        assert LUNCH not in allowed  # would run through lunch
        assert grid.slots_per_day - 1 not in allowed  # would run past the end of the day

    def test_an_instructor_being_away_removes_hours(self, empty: Institution) -> None:
        """Not a constraint: it does not depend on which room is chosen, so it belongs in the
        domain where the solver never has to consider it."""
        away = empty.closed(
            *(Unavailability(instructor_id=InstructorId(1), slot=s) for s in range(4))
        )
        model = build(away.snapshot())

        assert not any(_in(model.starts[LECTURE], v) for v in range(4))

    def test_a_session_with_nowhere_to_start_is_refused(self, empty: Institution) -> None:
        never = empty.closed(
            *(
                Unavailability(instructor_id=InstructorId(1), slot=s)
                for s in range(empty.grid.slot_count)
            )
        )

        with pytest.raises(UnsatisfiableError, match="no hour it could start in"):
            build(never.snapshot())


class TestPins:
    def test_a_pinned_session_does_not_move(self, empty: Institution) -> None:
        """Decision #10 put `is_pinned` in the schema on day one *because retrofitting
        reworks the solver interface*. This is where that either pays off or is ignored."""
        pinned = Institution(
            assignments=(
                Assignment(
                    id=AssignmentId(1),
                    session_id=TUTORIAL,
                    start_slot=6,
                    room_id=STUDIO,
                    is_pinned=True,
                ),
            )
        )
        found = solve(pinned.snapshot())
        where = {p.session: (p.start_slot, p.room) for p in found.placements}

        assert found.solved
        assert where[TUTORIAL] == (6, STUDIO)

    def test_an_unpinned_placement_is_free_to_move(self, empty: Institution) -> None:
        """The other half. A stored assignment that is *not* pinned is a starting point, not
        a constraint — otherwise re-solving would only ever return what it was given."""
        loose = Institution(
            assignments=(
                Assignment(id=AssignmentId(1), session_id=LECTURE, start_slot=0, room_id=HALL),
                # Deliberately illegal: two labs in one room at one hour.
                Assignment(id=AssignmentId(2), session_id=LAB_A, start_slot=2, room_id=LAB),
                Assignment(id=AssignmentId(3), session_id=LAB_B, start_slot=2, room_id=LAB),
                Assignment(id=AssignmentId(4), session_id=TUTORIAL, start_slot=6, room_id=STUDIO),
            )
        )
        found = solve(loose.snapshot())
        where = {p.session: p.start_slot for p in found.placements}

        assert found.solved
        assert where[LAB_A] != where[LAB_B]

    def test_pins_that_contradict_each_other_are_impossible(self) -> None:
        """Two sessions pinned into one room at one hour. The solver must say so rather than
        quietly unpinning one."""
        contradictory = Institution(
            assignments=(
                Assignment(
                    id=AssignmentId(1), session_id=LAB_A, start_slot=2, room_id=LAB, is_pinned=True
                ),
                Assignment(
                    id=AssignmentId(2), session_id=LAB_B, start_slot=2, room_id=LAB, is_pinned=True
                ),
            )
        )

        assert solve(contradictory.snapshot()).outcome is Outcome.IMPOSSIBLE


class TestTheThingsThatShareTime:
    def test_a_rooms_turnaround_is_part_of_its_time(self, empty: Institution) -> None:
        """The lab needs an hour to clear, so two labs cannot sit an hour apart in it.

        Expressed as the interval's length rather than as a rule of its own — a room being
        cleared *is in use*, and two rules about when a room is free could disagree.
        """
        model = build(empty.snapshot())
        in_lab = [c for c in model.candidates[LAB_A] if c.room == LAB]

        assert in_lab
        assert in_lab[0].interval.size_expr() == 2  # one hour taught, one to clear

    def test_people_are_only_busy_while_teaching(self, empty: Institution) -> None:
        """The mirror of the above, and #190: the students have left and the instructor has
        stopped teaching while the room is being cleared."""
        model = build(empty.snapshot())

        assert model.teaching[LAB_A].size_expr() == 1

    def test_alternating_weeks_may_share_a_room_and_an_hour(self) -> None:
        """Two labs in one room at one hour, one in odd weeks and one in even.

        Universities run fortnightly labs, and a solver that forbade this would refuse a
        timetable that works. `AddNoOverlap` cannot say "except these pairs", so the sessions
        are split by pattern instead.
        """
        alternating = (
            Institution(assignments=())
            .patterned(LAB_A, WeekPattern.ODD_WEEKS)
            .patterned(LAB_B, WeekPattern.EVEN_WEEKS)
            .pinned_to(LAB_A, at=2, room=LAB)
            .pinned_to(LAB_B, at=2, room=LAB)
        )

        assert solve(alternating.snapshot()).solved

    def test_every_week_still_collides(self) -> None:
        """The half that keeps the above meaningful."""
        both = (
            Institution(assignments=())
            .pinned_to(LAB_A, at=2, room=LAB)
            .pinned_to(LAB_B, at=2, room=LAB)
        )

        assert solve(both.snapshot()).outcome is Outcome.IMPOSSIBLE


class TestTheModelIsSmall:
    def test_it_is_not_a_boolean_cube(self, empty: Institution) -> None:
        """#35, made checkable.

        The forbidden formulation is one boolean per (session, period, room) — at department
        scale, 1.6 M of them at 30-minute slots and 2.8 s merely to construct. Here the period
        dimension is an integer, so the count is (session, room) pairs *after* pruning, which
        for this institution is six rather than sixteen.
        """
        sessions, candidates = size(build(empty.snapshot()))

        assert sessions == 4
        assert candidates == 6
        assert candidates < sessions * len(empty.rooms) * empty.grid.slot_count


def _in(var: object, value: int) -> bool:
    """Whether a value is in an IntVar's domain, read off the proto."""
    flat = var.proto.domain  # type: ignore[attr-defined]
    return any(flat[i] <= value <= flat[i + 1] for i in range(0, len(flat), 2))


class TestARoomThatIsShut:
    def test_a_room_closed_all_week_is_not_a_candidate(self, empty: Institution) -> None:
        """Dropped while building, not constrained away.

        A room shut for the whole term is not a room this session could be in, and carrying
        a presence literal for it means the solver explores a branch that can never be true.
        """
        shut = empty.closed(
            *(Unavailability(room_id=LAB, slot=s) for s in range(empty.grid.slot_count))
        )

        with pytest.raises(UnsatisfiableError, match="no room that can hold it"):
            build(shut.snapshot())

    def test_a_room_closed_for_part_of_the_week_keeps_its_other_hours(
        self, empty: Institution
    ) -> None:
        """The branch between the two: the room stays a candidate and the hours it is shut
        are refused *only when this session is in it*."""
        morning = empty.closed(*(Unavailability(room_id=LAB, slot=s) for s in range(4)))
        found = solve(morning.snapshot())

        assert found.solved
        assert all(p.start_slot >= 4 for p in found.placements if p.room == LAB)


class TestPinsThatCannotWork:
    def test_two_pins_into_one_room_at_one_hour_are_named(self) -> None:
        """The search would find this and report INFEASIBLE. Saying it while building names
        the two sessions and the room, which is the difference between a message somebody can
        act on and one that sends them looking."""
        clashing = (
            Institution(assignments=())
            .pinned_to(LAB_A, at=2, room=LAB)
            .pinned_to(LAB_B, at=2, room=LAB)
        )

        with pytest.raises(UnsatisfiableError, match="both pinned into room"):
            build(clashing.snapshot())

    def test_pins_in_weeks_that_never_meet_are_fine(self) -> None:
        """The same two pins, one in odd weeks and one in even. A check that ignored the
        pattern would refuse a fortnightly arrangement that works."""
        alternating = (
            Institution(assignments=())
            .patterned(LAB_A, WeekPattern.ODD_WEEKS)
            .patterned(LAB_B, WeekPattern.EVEN_WEEKS)
            .pinned_to(LAB_A, at=2, room=LAB)
            .pinned_to(LAB_B, at=2, room=LAB)
        )

        assert solve(alternating.snapshot()).solved

    def test_a_pin_into_a_room_that_cannot_hold_it_is_named(self) -> None:
        """Pinning a sixty-student lecture into a ten-seat seminar room. The pin is the
        mistake, and the message says which room and which session."""
        wrong = Institution(assignments=()).pinned_to(LECTURE, at=0, room=CUPBOARD)

        with pytest.raises(UnsatisfiableError, match=r"pinned to room \d+, which cannot hold it"):
            build(wrong.snapshot())

    def test_pins_in_different_rooms_are_not_a_collision(self) -> None:
        """The first thing the check rules out, and the commonest case.

        Asserted against the *check* rather than against the solve: these two share an
        instructor, so pinning them to the same hour is genuinely impossible — just not for
        this reason. Asking whether the term solves would have tested the instructor
        invariant and called it a pin collision, which is how a test ends up passing for
        the wrong reason.
        """
        apart = (
            Institution(assignments=())
            .pinned_to(LAB_A, at=2, room=LAB)
            .pinned_to(TUTORIAL, at=2, room=STUDIO)
        )

        # Builds without complaint. These two do clash — they share an instructor — but that
        # is the search's to find, and the pin check has nothing to say about it.
        model = build(apart.snapshot())

        assert set(model.starts) == {s.id for s in apart.sessions}
        assert solve(apart.snapshot()).outcome is Outcome.IMPOSSIBLE


class TestTheModelCanBeRelaxed:
    """The second way to build a term: every hard rule behind a literal that can turn it off.

    Not a second model — the same builder, so a rule is expressed once and cannot drift into
    saying two things (Decision #5 one layer out, #281). What changes is *how* each rule is
    written: the fast model expresses most of them by leaving values out of a domain, and a
    value that is absent cannot be blamed, because there is no constraint to attach a literal
    to. So the domains widen and the filtering comes back as constraints.

    What these tests protect is that **every** hard rule made it across. A rule that stayed in
    the domain would be silently unblameable: the term would still be refused, correctly, and
    the explanation would simply never mention it.
    """

    @staticmethod
    def satisfiable(term: object) -> bool:
        model = build(term, relaxable=True)  # type: ignore[arg-type]
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        solver.parameters.max_time_in_seconds = 10.0
        return solver.solve(model.cp) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    @pytest.mark.parametrize(
        "term",
        [
            no.more_sessions_than_room_periods(),
            no.instructor_away_most_of_the_week(),
            no.rules_that_contradict_each_other(),
            no.capacity_threshold(),
            no.short_only_once_lunch_is_taken_out(),
            no.the_only_room_is_shut_all_week(),
        ],
        ids=["pigeonhole", "away", "rules", "capacity", "lunch", "closed"],
    )
    def test_with_no_rule_asserted_every_term_has_a_timetable(self, term: object) -> None:
        """Nothing is left to refuse a term once every rule is switched off.

        The guard that makes an empty conflict set a defect rather than a case: if this fails,
        some constraint was written unconditionally and no explanation could ever name it.
        """
        assert self.satisfiable(term)

    def test_the_rules_that_can_be_switched_off_are_the_ones_that_bind(self) -> None:
        """A literal exists for each rule the term actually narrows something with.

        Created where a rule bites and not otherwise: a term with no breaks and nobody marked
        away writes nothing about either, and its relaxable model is the ordinary one with
        wider domains.
        """
        away = build(no.instructor_away_most_of_the_week(), relaxable=True)

        assert Requirement("availability_respected", "instructor", 1) in away.assumptions
        assert Requirement("instructor_not_double_booked", "instructor", 1) in away.assumptions
        assert Requirement("breaks_protected", "grid") not in away.assumptions

        lunch = build(no.short_only_once_lunch_is_taken_out(), relaxable=True)

        assert Requirement("breaks_protected", "grid") in lunch.assumptions

    def test_a_room_can_be_refused_for_two_reasons_at_once(self) -> None:
        """Capacity and equipment are separate rules and a room can fail both.

        Reported as two, because they are two things to fix and a reader told only about seats
        would buy a bigger room and hit the same refusal.
        """
        term = no.term(
            sessions=[
                no.lecture(1, group=1, features=frozenset({no.PROJECTOR})),
            ],
            rooms=[no.room(1, seats=5)],
            sizes={1: 40},
        )
        model = build(term, relaxable=True)

        assert Requirement("room_fits_group", "room", 1) in model.assumptions
        assert Requirement("room_has_required_features", "room", 1) in model.assumptions

    def test_an_ordinary_build_creates_no_literals(self) -> None:
        """Every existing caller is untouched, which is what makes this a mode and not a cost."""
        assert build(no.capacity_threshold()).assumptions == {}

    def test_a_pin_that_cannot_work_still_refuses_before_any_model(self) -> None:
        """`build` names both sessions and the room, which no conflict set could improve on.

        A core would say `room_not_double_booked` and leave the reader to find which two of
        five hundred sessions. The better message wins and the explainer is never reached.
        """
        with pytest.raises(UnsatisfiableError, match="both pinned into room 1"):
            build(no.two_pins_in_one_room(), relaxable=True)

    def test_freezing_and_explaining_are_not_combined(self) -> None:
        """A relaxable model explains a whole term; a frozen one is a round of the loop."""
        term = no.capacity_threshold()
        placement = next(iter(build(term).starts))

        with pytest.raises(ValueError, match="does not freeze part of one"):
            build(term, fixed={placement: None}, relaxable=True)  # type: ignore[dict-item]
