"""Whether two machines get the same answer, which is the whole basis of 4.5's gate.

P5 tells 4.5 to derive its regression threshold from **measured run-to-run variance, not
guessed**, and warns — from 0.1, which ran eight workers — that a naive 5 % gate would flake.
Since then #206 pinned the seed and defaulted the worker count to one, and #231 made budgets
deterministic. So the variance P5 says to measure may be **zero**, and the gate can then be
exact rather than tolerant, which is a far stronger gate: it catches a change of one point.

May be. That is a hypothesis, and this file is the experiment, in three parts:

1. **The same machine, twice.** `test_headroom.py` already asserts this for a single solve
   with `rounds=0`. A benchmark runs the whole loop, which chooses neighbourhoods from a
   seeded `Random` and stops on a clock the machine controls, so it is a different claim.
2. **Two machines, through CI.** The answer to a fixed term under a fixed budget is written
   down below and asserted. The matrix runs `ubuntu-latest` (x86-64) and `macos-14` (arm64),
   so a difference between architectures arrives as a red build with both numbers in it rather
   than as a benchmark nobody else can reproduce.
3. **The anti-vacuity guard.** A committed number proves nothing if every configuration
   produces it. A different seed has to give a different answer, or 1 and 2 are asserting only
   that the solver reliably does the same trivial thing.

**A red build here is not always a defect.** An OR-Tools upgrade changes CP-SAT's search and
therefore these numbers, and that is the gate working: a solver upgrade is exactly the change
that should not slip through as "the lockfile moved". The numbers are re-measured and committed
deliberately, by somebody who looked.

**Nothing here asserts a wall-clock outcome** (#244, which turned `main` red in 4.4 part 2).
Every budget is counted in rounds and in CP-SAT's own work unit, and a test asserts the clock
is not what stopped the search.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from tessera.solver import Budget, Outcome, Solution, solve
from tests.solver.scored import department

#: Fixed, and not to be tuned. Every number below is the answer to *this* question; changing
#: the term or the budget invalidates all of them at once, which is why they are in one place
#: rather than spread over the tests that assert them.
TERM = department(60, 8)

BUDGET = Budget(
    seconds=300,
    deterministic_seconds=2.0,
    rounds=2,
    round_deterministic_seconds=1.0,
    round_seconds=60,
)

#: Measured on macOS 15 / arm64, OR-Tools as locked, 2026-09-01. Two runs agreed exactly,
#: including the last bit of `work`.
PENALTY = 1470
WORK = 2.8773943755865643
TIMETABLE = "688e1ce9685c2f9c"


def digest(found: Solution) -> str:
    """The timetable itself, not only its score.

    Two different timetables can cost the same, so a score-only assertion would let the search
    change its mind without anybody noticing — the silent drift a solver upgrade produces.

    Measured rather than argued: building the model's rooms in the opposite order changes both
    this and `work` and leaves `penalty` **exactly where it was**, so the score assertion alone
    would have passed a model built differently.
    """
    lines = "\n".join(
        f"{p.session} {p.start_slot} {p.room}"
        for p in sorted(found.placements, key=lambda p: p.session)
    )
    return hashlib.sha256(lines.encode()).hexdigest()[:16]


@pytest.fixture(scope="module")
def found() -> Solution:
    """One solve, shared. Three tests asking the same question should not cost three answers."""
    return solve(TERM, BUDGET)


class TestTheSameMachineTwice:
    def test_the_whole_loop_repeats_exactly(self, found: Solution) -> None:
        again = solve(TERM, BUDGET)

        assert found.outcome is Outcome.SOLVED
        assert (found.penalty, found.work) == (again.penalty, again.work)
        assert digest(found) == digest(again)
        assert [step.penalty for step in found.trajectory] == [
            step.penalty for step in again.trajectory
        ]


class TestTwoMachines:
    """Asserted against the numbers above, so CI's two runners have to agree with the machine
    they were measured on. If they do not, the difference *is* the threshold D7 needs, and it
    gets recorded rather than smoothed over with a tolerance nobody derived."""

    def test_the_score_is_the_one_that_was_committed(self, found: Solution) -> None:
        assert found.penalty == PENALTY

    def test_the_timetable_is_the_one_that_was_committed(self, found: Solution) -> None:
        assert digest(found) == TIMETABLE

    def test_the_work_is_the_one_that_was_committed(self, found: Solution) -> None:
        """Separate from the score deliberately. `deterministic_time` is a float CP-SAT
        accumulates as it goes, and it is the likeliest of the three to differ in its last
        bits between architectures — which would be worth knowing, and is not the same finding
        as the two machines disagreeing about the timetable."""
        assert found.work == WORK

    def test_the_clock_is_not_what_stopped_it(self, found: Solution) -> None:
        """Without this, the three assertions above are wall-clock outcomes in disguise."""
        assert found.seconds < BUDGET.seconds
        assert len(found.trajectory) == BUDGET.rounds


class TestTheCommittedAnswerIsNotWhateverAnythingWouldProduce:
    def test_another_seed_finds_another_timetable(self) -> None:
        elsewhere = solve(TERM, replace(BUDGET, seed=7))

        assert elsewhere.outcome is Outcome.SOLVED
        assert digest(elsewhere) != TIMETABLE
        assert elsewhere.penalty != PENALTY
