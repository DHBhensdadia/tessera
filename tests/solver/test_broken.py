"""When CP-SAT itself falls over, and why that is not allowed to become silence.

OR-Tools 9.15.6755 raises `IndexError` out of its own presolve on the term below. It is a
knife-edge — one session more, one slot shorter, one day longer or one extra room and it
vanishes — and it is not our model: `CpModel.validate()` returns empty on it, and with
presolve disabled the identical model answers `INFEASIBLE` in milliseconds. There is no newer
OR-Tools to move to.

**So the engine reports what it knows instead of dying with the library.** The risk in that is
obvious and is what most of this file is about: a catch around a solve can quietly turn a real
defect into "no timetable found", and the suite would go green while the solver was broken.
Hence a catch by exception *type* rather than by `Exception`, and a test that says so.
"""

from __future__ import annotations

import pytest
from ortools.sat.python import cp_model

from tessera.domain.constraints import Constraint, ConstraintKind, ConstraintTarget, TargetKind
from tessera.domain.entities import Room, Session, SessionKind
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import RoomId, SessionId, StudentGroupId
from tessera.domain.time_grid import TimeGrid
from tessera.domain.validation import Snapshot
from tessera.solver import Budget, Outcome, solve
from tessera.solver.search import attempted


def the_term_that_breaks_cpsat() -> Snapshot:
    """Five two-slot sessions into a two-day, five-slot week with one room.

    The week holds exactly ten slots and the teaching needs exactly ten, so the rule — no day
    heavier than its even share — is genuinely unsatisfiable: a day must hold five slots and
    sessions come in twos. `INFEASIBLE` is the right answer and CP-SAT reaches it with presolve
    off. With presolve on it raises instead.
    """
    return Snapshot.of(
        grid=TimeGrid(days=2, slots_per_day=5, slot_minutes=60, day_start_minute=9 * 60),
        sessions=[
            Session(
                id=SessionId(n),
                kind=SessionKind.LECTURE,
                duration_slots=2,
                attendee_ids=frozenset({StudentGroupId(1)}),
            )
            for n in range(1, 6)
        ],
        rooms=[Room(id=RoomId(1), name="Room 1", capacity=0)],
        groups=GroupSet(
            [
                StudentGroup(id=StudentGroupId(1), name="G1", size=0, kind=GroupKind.STRUCTURAL),
                StudentGroup(id=StudentGroupId(2), name="G2", size=0, kind=GroupKind.STRUCTURAL),
            ]
        ),
        constraints=[
            Constraint(
                kind=ConstraintKind.BALANCE_DAILY_LOAD,
                is_hard=True,
                weight=0,
                targets=frozenset(
                    {
                        ConstraintTarget(kind=TargetKind.GROUP, id=1),
                        ConstraintTarget(kind=TargetKind.GROUP, id=2),
                    }
                ),
            )
        ],
    )


class TestSolvingDoesNotRaise:
    def test_the_term_that_breaks_the_library_still_gets_an_answer(self) -> None:
        """The invariant, and it survives OR-Tools fixing the bug.

        Either CP-SAT answers — in which case the term is `IMPOSSIBLE`, since it genuinely has
        no timetable — or it falls over and the engine says it did not find one. What may not
        happen is an `IndexError` reaching the caller, because a person pressing *Generate*
        gets a crash rather than a sentence.
        """
        found = solve(the_term_that_breaks_cpsat(), Budget(seconds=10.0))

        assert found.outcome in (Outcome.IMPOSSIBLE, Outcome.OUT_OF_TIME)
        assert found.placements == ()

    def test_and_when_it_falls_over_it_says_so(self) -> None:
        """Silence would be the defect this whole file is about.

        Skipped rather than asserted-around if OR-Tools ever fixes its presolve: the failure is
        then unreachable through this term, which is a better world and not a broken test.
        """
        found = solve(the_term_that_breaks_cpsat(), Budget(seconds=10.0))
        if found.outcome is Outcome.IMPOSSIBLE:
            pytest.skip("OR-Tools no longer falls over on this term, which is the good outcome")

        assert found.search_failed, "the solver broke and the answer does not mention it"
        assert "IndexError" in found.search_failed
        assert found.outcome is Outcome.OUT_OF_TIME, (
            "a solver that broke has not proven anything — `impossible` would be a claim"
        )


class TestTheCatchIsNarrow:
    """The guard for the guard. A catch that swallowed everything would hide real defects."""

    def test_what_the_library_raises_is_caught(self, monkeypatch: pytest.MonkeyPatch) -> None:
        solver = cp_model.CpSolver()
        monkeypatch.setattr(
            solver, "solve", lambda *_: (_ for _ in ()).throw(IndexError("absl::...at"))
        )

        status, broke = attempted(solver, cp_model.CpModel())

        assert status == cp_model.UNKNOWN
        assert "IndexError" in broke

    @pytest.mark.parametrize(
        "failure", [RuntimeError("something else"), ValueError("a bad bound"), MemoryError()]
    )
    def test_anything_else_still_reaches_the_caller(
        self, failure: Exception, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A solve that fails for a reason we could fix must stay loud.

        #239 raises on a `MODEL_INVALID` status for the same reason — a duplicated solution
        hint once hid behind forty-one silently empty rounds — and widening this catch to
        `Exception` would put that lesson back.
        """
        solver = cp_model.CpSolver()
        monkeypatch.setattr(solver, "solve", lambda *_: (_ for _ in ()).throw(failure))

        with pytest.raises(type(failure)):
            attempted(solver, cp_model.CpModel())

    def test_an_ordinary_solve_reports_no_failure(self) -> None:
        model = cp_model.CpModel()
        model.add(model.new_int_var(0, 3, "x") >= 1)

        status, broke = attempted(cp_model.CpSolver(), model)

        assert status == cp_model.OPTIMAL
        assert broke == ""
