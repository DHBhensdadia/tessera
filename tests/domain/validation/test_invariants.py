"""Breaking a good timetable one rule at a time.

**A validator is not verified by passing.** Phase 0.1 reported FEASIBLE on all 21 instances,
and a checker that always returned "no violations" would have produced identical output —
every result worthless while looking perfect. Agreement is evidence only if the checker can
disagree, so each rule here is shown to fire on a timetable built to break it.

Each mutation must break **that rule alone**. 0.1 made the point with a curriculum clash
constructed to trip the curriculum rule only: one that also double-booked a room would have
passed even if only the room rule worked. So every test asserts the *set* of rules that fired,
not merely that the expected one is among them.
"""

from __future__ import annotations

import pytest

from tessera.domain.constraints import INVARIANTS
from tessera.domain.entities import Unavailability, WeekPattern
from tessera.domain.ids import InstructorId, RoomId
from tessera.domain.validation import (
    Report,
    Snapshot,
    validate,
    validate_move,
    validate_viewport,
    violations_for,
)
from tessera.domain.validation.invariants import RULES, _named
from tests.domain.validation.institution import (
    CUPBOARD,
    HALL,
    LAB,
    LAB_A,
    LAB_B,
    LECTURE,
    STUDIO,
    TUTORIAL,
    Institution,
)


def fired(report: Report) -> set[str]:
    """Which rules complained. The set, because 'and nothing else' is half the claim."""
    return {violation.rule for violation in report.violations}


@pytest.fixture
def good() -> Institution:
    return Institution()


class TestTheBaseline:
    def test_nothing_is_wrong_with_it(self, good: Institution) -> None:
        """First, because every other test in this file is a difference from here.

        It has already earned its place: the lab has a one-slot turnaround and the tutorial
        after it teaches the same batch, and this failed until the indexes stopped treating
        a room's turnaround as time the students were still in it.
        """
        report = validate(good.snapshot())

        assert report.violations == ()
        assert report.is_feasible
        assert report.is_complete

    def test_every_invariant_has_a_rule(self) -> None:
        """Seven declared, seven checked. A rule the domain announces and nobody enforces is
        worse than one it never claimed: the rules screen shows it to a person as a promise."""
        assert len(RULES) == len(INVARIANTS)
        assert {rule.__name__ for rule in RULES} == {i.key for i in INVARIANTS}


class TestOneRuleAtATime:
    def test_a_room_hosting_two_classes(self, good: Institution) -> None:
        """Both labs into the lab at once. They have different instructors and different
        batches precisely so this is a room clash and nothing else."""
        report = validate(good.moved(LAB_B, at=2).snapshot())

        assert fired(report) == {"room_not_double_booked"}
        assert not report.is_feasible

    def test_an_instructor_in_two_places(self, good: Institution) -> None:
        """Instructor 2 teaches the lab and the tutorial; put them at the same hour, in
        different rooms, for different batches."""
        report = validate(good.moved(TUTORIAL, at=2).snapshot())

        assert fired(report) == {"instructor_not_double_booked"}

    def test_students_in_two_places(self, good: Institution) -> None:
        """The lecture is to the whole year and the lab to one batch of it.

        The clash is through the group *tree*: nothing names the same group twice, and a
        validator comparing attendee lists directly would see none of it.
        """
        report = validate(good.moved(LECTURE, at=2).snapshot())

        assert fired(report) == {"group_not_double_booked"}

    def test_a_room_too_small(self, good: Institution) -> None:
        """Sixty students into a room that seats ten. The seminar room has no equipment and
        the lecture needs none, so capacity is the only thing wrong."""
        report = validate(good.moved(LECTURE, to=CUPBOARD).snapshot())

        assert fired(report) == {"room_fits_group"}

    def test_a_room_without_the_equipment(self, good: Institution) -> None:
        """The lab needs thirty workstations; the hall has a projector and space for a
        hundred. Capacity is fine, which is what leaves features alone."""
        report = validate(good.moved(LAB_A, to=HALL).snapshot())

        assert fired(report) == {"room_has_required_features"}

    def test_a_room_with_too_few_of_the_equipment(self, good: Institution) -> None:
        """Present is not the same as enough. A lab with twenty-nine machines *has* computers.

        This is the case `Room.feature_counts` exists for, and the one a validator checking
        only `required <= room.features` would wave through — thirty students, twenty-nine
        seats, and nobody finds out until the class starts.
        """
        lab = next(room for room in good.rooms if room.id == LAB)
        thinner = lab.model_copy(update={"feature_counts": {**lab.feature_counts, 2: 29}})
        report = validate(
            Snapshot.of(
                grid=good.grid,
                sessions=good.sessions,
                rooms=tuple(thinner if r.id == LAB else r for r in good.rooms),
                groups=good.groups,
                assignments=good.assignments,
            )
        )

        assert fired(report) == {"room_has_required_features"}

    def test_a_room_that_is_closed(self, good: Institution) -> None:
        report = validate(
            good.closed(Unavailability(room_id=LAB, slot=2, reason="being refurbished")).snapshot()
        )

        assert fired(report) == {"availability_respected"}
        assert "being refurbished" in report.violations[0].message

    def test_an_instructor_who_is_away(self, good: Institution) -> None:
        report = validate(
            good.closed(Unavailability(instructor_id=InstructorId(2), slot=2)).snapshot()
        )

        assert fired(report) == {"availability_respected"}

    def test_a_class_running_through_lunch(self, good: Institution) -> None:
        """The two-hour lecture started at noon runs into the break.

        The message comes from `TimeGrid.span`, which already refuses this and already
        explains it — a second wording here could drift from the rule it describes.
        """
        report = validate(good.moved(LECTURE, at=3).snapshot())

        assert fired(report) == {"breaks_protected"}
        assert "break" in report.violations[0].message


class TestWhatIsNotAViolation:
    def test_a_soft_unavailability_does_not_forbid(self, good: Institution) -> None:
        """*Would rather not* is not *cannot*. Part 2 gives it a weight; here it is silent,
        and a validator that treated the two alike would make every stated preference an
        impossibility."""
        report = validate(
            good.closed(Unavailability(room_id=LAB, slot=2, is_hard=False, weight=5)).snapshot()
        )

        assert report.violations == ()

    def test_sessions_in_alternating_weeks_do_not_clash(self, good: Institution) -> None:
        """D7. Two labs in one room at one hour, one in odd weeks and one in even.

        Universities run fortnightly labs — 4.0 measured that 30 of the 36 ITC instances need
        partial-week teaching — and a validator that ignored the pattern would forbid a
        timetable that works.
        """
        clashing = good.moved(LAB_B, at=2)

        assert fired(validate(clashing.snapshot())) == {"room_not_double_booked"}

        alternating = clashing.patterned(LAB_A, WeekPattern.ODD_WEEKS).patterned(
            LAB_B, WeekPattern.EVEN_WEEKS
        )
        assert validate(alternating.snapshot()).violations == ()

    def test_an_unplaced_session_is_incompleteness(self, good: Institution) -> None:
        """D6. A half-built timetable is the normal state while somebody is working on one."""
        report = validate(
            Snapshot.of(
                grid=good.grid,
                sessions=good.sessions,
                rooms=good.rooms,
                groups=good.groups,
                assignments=good.assignments[:-1],
            )
        )

        assert report.violations == ()
        assert report.is_feasible
        assert not report.is_complete
        assert report.unplaced == (TUTORIAL,)


class TestOneMove:
    def test_a_legal_cell(self, good: Institution) -> None:
        """Slot 3, not slot 1: the lecture runs 09:00 to 11:00 and is taught to the whole
        year, so the tutorial's batch is genuinely busy then. Picking a cell that only looks
        free would have made this test pass for the wrong reason."""
        verdict = validate_move(good.snapshot(), TUTORIAL, 3, STUDIO)

        assert verdict.legal
        assert verdict.violations == ()

    def test_an_illegal_cell_says_why(self, good: Institution) -> None:
        """Slot 3 in the lab, where the lab itself is free but is still being cleared.

        Turnaround is occupancy, not a rule of its own — a chemistry lab that needs twenty
        minutes to clear *is in use* for those twenty minutes — and this is where that shows.
        """
        verdict = validate_move(good.snapshot(), TUTORIAL, 3, LAB)

        assert not verdict.legal
        assert {v.rule for v in verdict.violations} == {"room_not_double_booked"}

    def test_a_cell_can_be_wrong_in_more_than_one_way(self, good: Institution) -> None:
        """The lab at 11:00: the room is taken *and* the instructor is already teaching in it.

        Every reason is reported, not the first. A verdict that stopped at one would send
        somebody to fix the room and hand them the same refusal again.
        """
        verdict = validate_move(good.snapshot(), TUTORIAL, 2, LAB)

        assert {v.rule for v in verdict.violations} == {
            "room_not_double_booked",
            "instructor_not_double_booked",
        }

    def test_a_session_does_not_clash_with_itself(self, good: Institution) -> None:
        """Dragged back onto the cell it already occupies.

        The session is still in every index while the question is asked — rebuilding them per
        move would be correct and would cost the flatness the whole design is for — so the
        lookups filter it out instead.
        """
        verdict = validate_move(good.snapshot(), LAB_A, 2, LAB)

        assert verdict.legal

    def test_the_fold_equals_the_whole(self, good: Institution) -> None:
        """D2's claim, made checkable rather than asserted.

        Validating every placement one at a time must produce exactly what validating the
        timetable produces. If these ever differ, there are two implementations behind the
        solver and the interface, which is the thing Decision #5 exists to prevent.
        """
        snapshot = good.moved(LAB_B, at=2).moved(LECTURE, to=CUPBOARD).snapshot()

        whole = validate(snapshot).violations
        folded = tuple(
            violation
            for placement in snapshot.placements.values()
            for violation in violations_for(snapshot, placement)
        )

        assert set(whole) == set(folded)
        assert len(whole) == len(folded)


class TestTheViewport:
    """The form a drag actually uses, and the one 0.2 proved must be scoped.

    The whole-grid variant measured 43 ms p99 at the NFR-9 ceiling — 2.7 times over budget,
    with 25,000 cells of real validation before serialisation began. It measures fine at
    department scale, which is exactly why it had to be measured at the ceiling.
    """

    def test_it_answers_every_cell_it_was_asked_about(self, good: Institution) -> None:
        cells = validate_viewport(good.snapshot(), TUTORIAL, [LAB, STUDIO], 0, 4)

        assert len(cells) == 8
        assert {(c.room_id, c.start_slot) for c in cells} == {
            (room, slot) for room in (LAB, STUDIO) for slot in range(4)
        }

    def test_it_marks_the_cells_that_would_not_work(self, good: Institution) -> None:
        """Of the eight cells on this morning's screen, exactly one works.

        The batch is in the lecture until 11:00, their instructor is teaching the lab at
        11:00, and the lab itself is occupied or being cleared from 11:00 to 13:00. Only the
        studio at noon is free — and the reasons differ per cell, which is what the interface
        turns into a tooltip.
        """
        cells = {
            (c.room_id, c.start_slot): c
            for c in validate_viewport(good.snapshot(), TUTORIAL, [LAB, STUDIO], 0, 4)
        }
        legal = {key for key, cell in cells.items() if cell.legal}

        assert legal == {(STUDIO, 3)}
        assert {v.rule for v in cells[(STUDIO, 0)].violations} == {"group_not_double_booked"}
        assert {v.rule for v in cells[(STUDIO, 2)].violations} == {"instructor_not_double_booked"}
        # 12:00 in the lab: free of people, but the previous class is still being cleared.
        assert {v.rule for v in cells[(LAB, 3)].violations} == {"room_not_double_booked"}

    def test_it_agrees_with_asking_cell_by_cell(self, good: Institution) -> None:
        """The viewport is a fold over the move check, and this is what keeps it one.

        A viewport that answered differently would be the drift Decision #5 forbids, arriving
        by the back door — the interface renders from this while the solver checks the other.
        """
        snapshot = good.snapshot()

        for cell in validate_viewport(snapshot, TUTORIAL, [LAB, STUDIO], 0, 8):
            one = validate_move(snapshot, TUTORIAL, cell.start_slot, cell.room_id)
            assert cell.legal == one.legal
            assert cell.violations == one.violations


class TestTheEdges:
    def test_a_clash_across_several_slots_is_reported_once(self, good: Institution) -> None:
        """The lecture runs two hours. Overlapping it should say so once, not once per hour.

        A person reading four identical sentences about the same pair of sessions learns
        nothing from the second, and a badge counting them says the timetable is twice as
        broken as it is.
        """
        overlapping = good.lasting(TUTORIAL, 2).moved(TUTORIAL, at=0)
        report = validate(overlapping.snapshot())
        for_tutorial = [v for v in report.violations if v.session_id == TUTORIAL]

        # Two full hours of overlap, one sentence about it.
        assert len(for_tutorial) == 1
        assert for_tutorial[0].rule == "group_not_double_booked"
        assert for_tutorial[0].conflicting_session_id == LECTURE

    def test_the_same_instructor_across_several_slots_is_reported_once(
        self, good: Institution
    ) -> None:
        """The other side of the same deduplication.

        Two two-hour sessions, both taught by instructor 2, at the same hours in different
        rooms for different batches — so the instructor is the only thing wrong, and they
        overlap twice over.
        """
        clash = good.lasting(LAB_A, 2).lasting(TUTORIAL, 2).moved(TUTORIAL, at=2, to=STUDIO)
        report = validate(clash.snapshot())

        assert fired(report) == {"instructor_not_double_booked"}
        # One sentence per session, not one per overlapping hour.
        assert len(report.violations) == 2
        assert {v.session_id for v in report.violations} == {LAB_A, TUTORIAL}

    def test_a_room_that_does_not_exist_is_not_a_crash(self, good: Institution) -> None:
        """A move check is answered for whatever the client asks about, and a stale room id
        is an ordinary thing for a client to hold. The rules that need the room step aside
        rather than raising — the ones that do not still answer."""
        verdict = validate_move(good.snapshot(), TUTORIAL, 3, RoomId(999))

        assert verdict.legal

    def test_a_rule_cannot_name_an_invariant_that_does_not_exist(self) -> None:
        """The guard behind every `_named(...)` call.

        A typo would produce violations naming a rule the interface cannot explain: the rules
        screen looks the sentence up in `INVARIANTS`, so an unknown key renders as nothing at
        all — a red cell with no reason given.
        """
        with pytest.raises(AssertionError, match="not one of the invariants"):
            _named("room_occupied")

    def test_an_instructor_closure_can_carry_its_reason(self, good: Institution) -> None:
        report = validate(
            good.closed(
                Unavailability(instructor_id=InstructorId(2), slot=2, reason="on sabbatical")
            ).snapshot()
        )

        assert "on sabbatical" in report.violations[0].message
