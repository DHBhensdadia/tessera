"""Whether two machines get the same answer, which is the whole basis of 4.5's gate.

P5 tells 4.5 to derive its regression threshold from **measured run-to-run variance, not
guessed**, and warns — from 0.1, which ran eight workers — that a naive 5 % gate would flake.
Since then #206 pinned the seed and defaulted the worker count to one, and #231 made budgets
deterministic. So the variance P5 says to measure may be **zero**, and the gate can then be
exact rather than tolerant, which is a far stronger gate: it catches a change of one point.

It was a hypothesis, the CI matrix answered it, and **the answer is not one thing** — which is
the whole reason the three quantities below are asserted separately rather than rolled into
one. Measured on `macos-14` (arm64) and `ubuntu-latest` (x86-64), the same commit, the same
seed, the same work budget:

| | arm64 | x86-64 | travels? |
|---|---|---|---|
| penalty | 1470 | 1470 | **yes, exactly** |
| timetable | `688e1ce9` | `6d6d8c39` | **no** — a different arrangement, costing the same |
| `deterministic_time` | 2.8773943755865643 | 2.8812268035781194 | **no** — 0.133 % apart |

So CP-SAT's *answer* is architecture-independent here and its *route* is not, and its own work
unit is machine-independent only to about a part in a thousand. A gate that had asserted the
score alone would have called this settled; a gate that had hashed all three together would
have said "different" and taught nothing.

The file is therefore the experiment in four parts:

1. **The same machine, twice.** `test_headroom.py` already asserts this for a single solve
   with `rounds=0`. A benchmark runs the whole loop, which chooses neighbourhoods from a
   seeded `Random` and stops on a clock the machine controls, so it is a different claim. This
   holds on **both** architectures, so each machine is self-consistent.
2. **The score, exactly, on any machine.** The one quantity that travels.
3. **The timetable, from a set of two measured arrangements.** Weaker than an equality and
   much stronger than nothing: any *third* timetable means the model or the search changed,
   which is what the assertion is for. If a third runner is ever added the set grows by
   measurement, not by loosening.
4. **The anti-vacuity guard.** A committed number proves nothing if every configuration
   produces it. A different seed has to give a different answer.

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

#: The score, and it is the same on every machine measured. Exact, because nothing has been
#: seen to move it.
PENALTY = 1470

#: The timetables, one per architecture, and each is exact *on* that architecture — two runs
#: there agree bit for bit. Named rather than numbered so a failure says which machine's answer
#: turned up somewhere unexpected.
TIMETABLES = {
    "arm64": "688e1ce9685c2f9c",
    "x86-64": "6d6d8c39f4b6d053",
}

#: What the search spent, on arm64. x86-64 reports 2.8812268035781194 for the same work.
WORK = 2.8773943755865643

SPREAD = 0.01
"""How far `work` may sit from the recorded figure before it counts as a change.

**Derived, not chosen.** The two architectures differ by 0.133 %, so this is roughly seven
times the largest difference anybody has measured. The headroom is there because two samples
do not bound a distribution and a runner refresh is not an event anyone announces; it is not
there to make the gate comfortable. Part 3's harness measures this over twenty-one instances
instead of one term, and should replace this number with that one.
"""


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

    def test_the_timetable_is_one_of_the_two_that_were_measured(self, found: Solution) -> None:
        """arm64 and x86-64 find different arrangements of the same cost. Both are recorded,
        and a third would mean the model or the search changed rather than the hardware."""
        assert digest(found) in set(TIMETABLES.values()), (
            f"{digest(found)} is neither of the measured timetables {TIMETABLES}"
        )

    def test_the_work_is_within_the_measured_spread(self, found: Solution) -> None:
        """Separate from the score deliberately, and it is what that separation bought.

        `deterministic_time` is CP-SAT's machine-independent unit, and it turns out to be
        machine-independent to about a part in a thousand rather than exactly: 2.87739 on
        arm64 against 2.88123 on x86-64. Asserted here as a band around the recorded figure,
        which is P5's *measured, not guessed* with the measurement now in hand.
        """
        assert abs(found.work - WORK) / WORK <= SPREAD, (
            f"{found.work} is more than {SPREAD:.0%} from the recorded {WORK}"
        )

    def test_the_clock_is_not_what_stopped_it(self, found: Solution) -> None:
        """Without this, the three assertions above are wall-clock outcomes in disguise."""
        assert found.seconds < BUDGET.seconds
        assert len(found.trajectory) == BUDGET.rounds


class TestTheCommittedAnswerIsNotWhateverAnythingWouldProduce:
    def test_another_seed_finds_another_timetable(self) -> None:
        elsewhere = solve(TERM, replace(BUDGET, seed=7))

        assert elsewhere.outcome is Outcome.SOLVED
        assert digest(elsewhere) not in set(TIMETABLES.values())
        assert elsewhere.penalty != PENALTY
