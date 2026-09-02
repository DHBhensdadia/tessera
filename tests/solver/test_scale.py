"""How big the model gets, and how long a first solution takes.

NFR-4 asks for a first feasible solution at department scale — around 500 sessions — in under
30 seconds. That is what is asserted. The NFR-9 ceiling (5,000 sessions, 500 rooms) is
**measured and recorded rather than asserted**, because what it currently shows is a finding
this phase should not paper over:

> With every room able to host every session, the ceiling instance builds **2.5 million**
> (session, room) candidates and takes **58 seconds to construct**, before any search.

That is #35's failure arriving through a different dimension. #35 measured the boolean cube at
1.6 M booleans and 2.8 s to construct and forbade it; the model here replaces the *period*
dimension with an integer, which is what it was asked to do, and the *room* dimension is only
small when capacity and features rule rooms out.

**In this fixture they rule nothing out.** Every room seats 60, every group has 25 students,
and nothing requires a feature — so all 500 rooms are candidates for all 5,000 sessions. A real
institution prunes hard: the four-session fixture in `tests/domain/validation` goes from
sixteen possible pairs to six. But the model has no defence of its own if pruning does not
bite, and 500 interchangeable rooms are also *symmetric*, which P5 already lists as untested
headroom for 4.4.

Marked `slow`. Recorded here so the number is checked rather than remembered.
"""

from __future__ import annotations

import pytest

from tessera.domain.ids import AssignmentId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot, validate
from tessera.solver import Budget, solve
from tessera.solver.model import build, size
from tests.domain.validation.test_scale import institution

pytestmark = pytest.mark.slow


def bare(sessions: int, rooms: int) -> Snapshot:
    """An institution of a given size with nothing placed."""
    filled = institution(sessions=sessions, rooms=rooms)
    return Snapshot.of(
        grid=filled.grid,
        sessions=list(filled.sessions.values()),
        rooms=list(filled.rooms.values()),
        groups=filled.groups,
    )


#: Twenty units of CP-SAT's own work, against the **1.17** a department at this scale actually
#: needs — seventeen times over. `seconds` is a ceiling that should not be reached, not the
#: budget (#231, #244).
#:
#: It used to be `Budget(seconds=30)` with `assert found.seconds < 30`, which is a claim about
#: the machine wearing the clothes of a claim about the solver. It held for three phases and
#: then failed on a laptop six hours into continuous CP-SAT (#264).
AT_SCALE = Budget(seconds=300, deterministic_seconds=20.0, rounds=0)


def test_a_department_is_solved_and_the_validator_accepts_it() -> None:
    """NFR-4 asks for a first feasible solution at department scale in under 30 seconds, and
    4.1 exists so that "solved" can be checked by something sharing none of the solver's logic.

    One solve, both questions. They were two tests solving the same institution twice, which
    cost ten seconds to learn nothing the first had not already established.

    **The thirty seconds is measured, not asserted** (#244). What a fixed amount of *searching*
    produces is a fact about the model and belongs in a test; how long that searching takes is a
    fact about the hardware and belongs in the record. Measured 2026-09-02 on macOS 15 / arm64:
    **5.4 seconds**, and 1.17 units of work. A model that regressed would need more work, which
    is what the cap below catches — on any machine, at any speed.
    """
    snapshot = bare(sessions=500, rooms=40)
    found = solve(snapshot, AT_SCALE)

    assert found.solved
    assert found.seconds < AT_SCALE.seconds, "the wall clock was the ceiling, not the budget"

    judged = validate(
        Snapshot.of(
            grid=snapshot.grid,
            sessions=list(snapshot.sessions.values()),
            rooms=list(snapshot.rooms.values()),
            groups=snapshot.groups,
            assignments=[
                Assignment(
                    id=AssignmentId(i),
                    session_id=p.session,
                    start_slot=p.start_slot,
                    room_id=p.room,
                )
                for i, p in enumerate(found.placements, start=1)
            ],
        )
    )

    assert judged.is_feasible
    assert judged.is_complete
    assert judged.violations == ()


def test_the_model_is_as_big_as_the_rooms_that_could_hold_each_session() -> None:
    """The size is (sessions x candidate rooms), and *candidate* is the load-bearing word.

    Recorded rather than bounded: with this fixture nothing is pruned, so the count is the
    product. If a later change makes it larger than that, something has gone wrong beyond
    the fixture.

    **This is the relationship the ceiling finding is about.** At NFR-9's 5,000 sessions and
    500 rooms the same product is 2.5 million candidates and 58 seconds to construct — measured
    once and written into the phase record, not asserted here. A test that spent two minutes
    proving `5000 * 500` on every push would be buying a number nobody can act on today; part 2
    owns the fix, and its test will be the one that proves the fix works.
    """
    snapshot = bare(sessions=500, rooms=40)
    sessions, candidates = size(build(snapshot))

    assert sessions == 500
    assert candidates == 500 * 40
