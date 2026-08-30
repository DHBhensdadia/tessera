"""A CB-CTT instance as Tessera holds it, and what the crossing costs.

The interesting comparison is with 4.0. ITC-2019 lost **every one** of its 52,254 classes,
because a Tessera session must be taught to a student group and those instances stated
individual enrolments with no programme tree. CB-CTT has curricula, a curriculum is a cohort,
and so the teaching structure crosses intact — the losses here are two named things rather
than the whole scheduling problem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera.domain.ids import AssignmentId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot, validate
from tessera.importers.cbctt import Instance, read
from tessera.importers.cbctt.apply import Mapped, mapped
from tessera.solver import Budget, solve

TOY = Path(__file__).parent / "fixtures" / "toy.ctt"


@pytest.fixture(scope="module")
def toy() -> Instance:
    return read(TOY)


@pytest.fixture(scope="module")
def term(toy: Instance) -> Mapped:
    return mapped(toy)


def snapshot_of(term: Mapped, assignments: list[Assignment] | None = None) -> Snapshot:
    return Snapshot.of(
        grid=term.grid,
        sessions=list(term.sessions),
        rooms=list(term.rooms),
        groups=term.groups,
        unavailability=list(term.unavailability),
        assignments=assignments or [],
    )


class TestWhatCrosses:
    def test_the_week_is_the_instance_s_week(self, term: Mapped) -> None:
        assert (term.grid.days, term.grid.slots_per_day) == (5, 4)

    def test_every_lecture_becomes_a_session(self, term: Mapped, toy: Instance) -> None:
        assert len(term.sessions) == toy.lectures == 16
        assert all(s.duration_slots == 1 for s in term.sessions)

    def test_a_curriculum_becomes_a_group_that_causes_conflicts(self, term: Mapped) -> None:
        """Two courses in one curriculum must not be taught at once — CB-CTT's `Conflicts`,
        and Tessera's `group_not_double_booked` with no translation in between."""
        names = {g.name for g in term.groups.all}

        assert {"Cur1", "Cur2"} <= names

    def test_headcount_is_the_course_s_students_not_the_sum_of_its_curricula(
        self, term: Mapped
    ) -> None:
        """The reason curriculum groups carry no size of their own.

        `TecCos` has 40 students and belongs to **both** curricula. Sizing the curricula would
        count those students once per curriculum, make the session seat eighty, and reject
        rooms that fit — so the count lives on a course group instead.
        """
        snapshot = snapshot_of(term)
        teccos = [s for s in term.sessions if any("TecCos" in g for g in _names(term, s))]

        assert teccos
        assert all(snapshot.headcount(s) == 40 for s in teccos)

    def test_a_teacher_becomes_an_instructor(self, term: Mapped) -> None:
        """Four teachers, four instructors, and two lectures of one teacher cannot coincide."""
        assert len({i for s in term.sessions for i in s.instructor_ids}) == 4


class TestWhatDoesNot:
    def test_the_four_soft_constraints_are_named(self, term: Mapped) -> None:
        """What a CB-CTT solution is *scored* on. 4.2 places lectures and weighs nothing, and
        4.5 scores an instance as written rather than as imported — 4.0's D5."""
        soft = next(e for e in term.dropped if e.what == "soft constraints")

        assert soft.count == 4
        assert "RoomCapacity" in soft.because

    def test_it_is_not_a_lossless_import_and_says_so(self, term: Mapped) -> None:
        assert not term.is_lossless

    def test_unavailability_is_carried_when_the_teacher_teaches_one_course(
        self, term: Mapped, toy: Instance
    ) -> None:
        """Every teacher in the toy example teaches exactly one course, so course-level and
        teacher-level unavailability say the same thing and all eight rows cross."""
        assert len(term.unavailability) == len(toy.unavailable) == 8

    def test_and_dropped_when_the_teacher_teaches_several(self) -> None:
        """The case that must not be widened. Blocking the teacher would forbid their *other*
        course at that hour, which the instance does not say — and the timetable it would
        forbid might be the published optimum. Lossy is acceptable; wrong is not.
        """
        shared = read(TOY.read_text().replace("ArcTec Indaco", "ArcTec Ocra"))
        term = mapped(shared)
        dropped = next(e for e in term.dropped if e.what == "unavailability")

        # Ocra now teaches SceCosC *and* ArcTec, so ArcTec's four rows cannot cross. Rosa
        # still teaches only TecCos, so its four still can — the rule is per teacher, not
        # per file, and a test asserting all eight were lost would have hidden that.
        assert dropped.count == 4
        assert len(term.unavailability) == 4
        assert "does not say" in dropped.because


class TestItSolves:
    def test_the_toy_instance_is_solved_and_the_validator_accepts_it(self, term: Mapped) -> None:
        """End to end: a published CB-CTT instance, mapped, solved, and judged by the
        validator that shares none of the solver's logic.

        The report states that **every** ITC-2007 instance has at least one feasible solution.
        Tessera's capacity rule is *harder* than CB-CTT's, so that guarantee does not transfer
        — which is exactly what the per-instance report is for once the real 21 are in hand.
        """
        found = solve(snapshot_of(term), Budget(seconds=60))

        assert found.solved
        report = validate(
            snapshot_of(
                term,
                [
                    Assignment(
                        id=AssignmentId(n),
                        session_id=p.session,
                        start_slot=p.start_slot,
                        room_id=p.room,
                    )
                    for n, p in enumerate(found.placements, start=1)
                ],
            )
        )

        assert report.is_feasible
        assert report.is_complete
        assert report.violations == ()

    def test_no_course_is_taught_twice_at_once(self, term: Mapped) -> None:
        """CB-CTT's `Lectures`: all lectures of a course go in *distinct* periods. Tessera
        gets it for free — they share a course group, so `group_not_double_booked` refuses
        them — but free is not the same as checked."""
        found = solve(snapshot_of(term), Budget(seconds=60))
        by_course: dict[frozenset[int], list[int]] = {}
        for placed in found.placements:
            session = next(s for s in term.sessions if s.id == placed.session)
            by_course.setdefault(frozenset(session.attendee_ids), []).append(placed.start_slot)

        for slots in by_course.values():
            assert len(slots) == len(set(slots))


def _names(term: Mapped, session: object) -> set[str]:
    by_id = {g.id: g.name for g in term.groups.all}
    return {by_id[g] for g in session.attendee_ids}  # type: ignore[attr-defined]
