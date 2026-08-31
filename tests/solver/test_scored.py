"""That the suite this phase is judged on actually scores something.

D2 exists because P5's suite does not. The mapped ITC-2007 instances carry no constraints at
all, so the solver reports *penalty 0, bound 0, optimal* on every one of them and "better
scores than raw CP-SAT" is a comparison of nothing with nothing. That is asserted here rather
than described, because it is the reason the exit test was rewritten and a reader should be
able to check it.

The instances themselves are unchanged and still checksummed by
`tests/importers/cbctt/test_sweep.py`. What is added is Tessera's own default preferences, and
the course each session belongs to — which the mapping already knows and simply had no field
for.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tessera.domain.validation import Snapshot
from tessera.solver import Outcome, solve
from tessera.solver.model import build
from tessera.solver.objective import add
from tests.solver.scored import DEFAULTS, cbctt, department

TOY = Path(__file__).parents[1] / "importers" / "cbctt" / "fixtures" / "toy.ctt"


def unscored(snapshot: Snapshot) -> Snapshot:
    """The same term as 4.2 imported it — structure, no preferences."""
    return Snapshot.of(
        grid=snapshot.grid,
        sessions=list(snapshot.sessions.values()),
        rooms=list(snapshot.rooms.values()),
        groups=snapshot.groups,
    )


class TestWhyTheSuiteHadToBeReplaced:
    def test_a_mapped_instance_has_nothing_to_optimise(self) -> None:
        """P5's exit test, shown to be unsatisfiable rather than argued to be.

        `objective.add` returning `None` is not a small thing: `solve` then never calls
        `minimize` at all, so the search is a satisfaction problem and the first timetable it
        reaches is the answer.
        """
        bare = unscored(cbctt(TOY))

        assert bare.constraints == ()
        assert add(build(bare), bare) is None

    def test_and_therefore_scores_zero_and_calls_it_optimal(self) -> None:
        bare = unscored(cbctt(TOY))
        found = solve(bare)

        assert found.outcome is Outcome.SOLVED
        assert (found.penalty, found.lower_bound, found.is_optimal) == (0, 0, True)


class TestTheSuiteThatReplacedIt:
    def test_the_defaults_are_the_ones_a_new_term_gets(self) -> None:
        """Not a set chosen to suit the phase. Group gaps at 8 and instructor gaps at 5 are
        the two terms #225 measured at +111,502 and +130,502 variables."""
        weights = {c.kind.value: c.weight for c in DEFAULTS}

        assert weights["minimise_group_gaps"] == 8
        assert weights["minimise_instructor_gaps"] == 5
        assert all(not c.is_hard for c in DEFAULTS)

    def test_a_generated_department_scores_on_the_rules_it_carries(self) -> None:
        snapshot = department(24, 6)
        found = solve(snapshot)

        assert found.penalty > 0
        assert sum(found.penalty_breakdown.values()) == found.penalty

    def test_every_session_of_a_cbctt_instance_is_traced_to_a_course(self) -> None:
        """Two of the seven defaults are about a course. Recovered from the group the mapping
        gives each course to carry its headcount, so a session that cannot be traced is a
        change in the mapping rather than a missing feature — and `cbctt` raises rather than
        quietly scoring those two rules as zero."""
        snapshot = cbctt(TOY)

        assert len(snapshot.course_of) == len(snapshot.sessions)
        assert len(snapshot.sessions_of_course) == 4


def instances() -> Path | None:
    given = os.environ.get("TESSERA_ITC2007_INSTANCES")
    if not given:
        return None
    found = Path(given).expanduser()
    return found if list(found.glob("comp*.ctt")) else None


ROOT = instances()


@pytest.mark.benchmark
@pytest.mark.skipif(ROOT is None, reason="set TESSERA_ITC2007_INSTANCES to the ITC-2007 directory")
@pytest.mark.parametrize("stem", [f"comp{n:02d}" for n in range(1, 22)])
def test_every_real_instance_maps_into_the_scored_suite(stem: str) -> None:
    """All twenty-one, because the course recovery is the part that could silently half-work.

    No solving: the twenty-one solves are part 3's, and a pre-push gate is the wrong place for
    them. What is checked is that every session of every instance finds its course and every
    instance carries the same seven rules — so a phase-3 sweep cannot report a score for a term
    that was quietly missing two of them.
    """
    assert ROOT is not None
    snapshot = cbctt(ROOT / f"{stem}.ctt")

    assert len(snapshot.course_of) == len(snapshot.sessions)
    assert len(snapshot.constraints) == len(DEFAULTS)
