"""One instance to one row, and the table those rows make.

The toy instance carries these: it is committed, so they run in CI where the ITC-2007 files
cannot, and it solves in under a second so the whole file is cheap.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tessera.bench.run import (
    BEST_KNOWN,
    COMPETITION,
    Published,
    Row,
    median_gap,
    run_one,
    sweep,
    table,
)
from tessera.solver import Budget

TOY = Path(__file__).parents[1] / "importers" / "cbctt" / "fixtures" / "toy.ctt"

#: Rounds and work, so nothing here turns on how fast the machine is (#244, #264).
QUICK = Budget(seconds=120, deterministic_seconds=5.0, rounds=1, round_deterministic_seconds=1.0)

UNVERIFIED = Published(scores={"toy": 0}, verified=False, source="a test", checked="never")
VERIFIED = Published(scores={"toy": 0}, verified=True, source="a test", checked="today")


def row(instance: str = "comp01", **fields: object) -> Row:
    base = {
        "instance": instance,
        "outcome": "solved",
        "penalty": 100,
        "bound": 0,
        "proven": False,
        "feasible": True,
        "violations": 0,
        "rounds": 3,
        "work": 12.5,
        "seconds": 300.0,
        "best_known": 40,
    }
    return Row(**{**base, **fields})  # type: ignore[arg-type]


class TestOneInstance:
    def test_it_solves_and_the_two_readings_agree(self) -> None:
        found = run_one(TOY, QUICK, best_known=0)

        assert found.solved
        assert found.instance == "toy"
        assert found.feasible, "the checker rejected a timetable the solver called valid"
        assert found.rounds >= 1

    def test_the_row_carries_what_a_reader_needs_to_judge_it(self) -> None:
        """A score with no budget, no work and no validity beside it is a number, not a
        measurement — which is P5's reporting rule and 0.1's before it."""
        found = run_one(TOY, QUICK, best_known=0)

        assert found.work > 0
        assert found.seconds > 0
        assert found.outcome == "solved"

    def test_a_solve_that_found_nothing_is_not_reported_as_a_perfect_score(self) -> None:
        """#235 again. A failed solve carries penalty 0, which in a table of scores is the best
        number on the page; `solved` is what the table reads, not the penalty."""
        starved = Budget(seconds=120, deterministic_seconds=0.0001, rounds=0)
        found = run_one(TOY, starved)

        assert not found.solved
        assert found.gap is None, "an unsolved instance has no gap to anything"


class TestTheGap:
    def test_it_is_absolute_rather_than_a_ratio(self) -> None:
        """0.1's rule: on an instance whose optimum is near zero a percentage explodes.
        `comp20` read +4525 % at a gap of 181, which looks worse than `comp05`'s +85 % at 242
        and is not."""
        assert row(penalty=185, best_known=4).gap == 181
        assert row(penalty=526, best_known=284).gap == 242

    def test_there_is_none_without_a_published_figure(self) -> None:
        assert row(best_known=None).gap is None

    def test_there_is_none_for_an_instance_that_did_not_solve(self) -> None:
        assert row(outcome="out_of_time", penalty=0).gap is None

    def test_the_median_is_the_summary_and_the_mean_is_absent(self) -> None:
        """The mean is dominated by the three instances whose optimum is near zero."""
        rows = [
            row(penalty=10, best_known=5),
            row(penalty=100, best_known=5),
            row(penalty=1000, best_known=5),
        ]

        assert median_gap(rows) == 95

    def test_no_gaps_at_all_is_no_median(self) -> None:
        assert median_gap([row(best_known=None)]) is None


class TestTheTable:
    def test_it_withholds_a_comparison_nobody_has_checked(self) -> None:
        """#269. An unverified number in a comparison is worse than no comparison: the reader
        cannot tell which half is in doubt."""
        printed = table([row()], UNVERIFIED)

        assert "best known" not in printed
        assert "unverified" in printed
        assert "40" not in printed

    def test_it_shows_the_comparison_once_somebody_has(self) -> None:
        printed = table([row()], VERIFIED)

        assert "best known" in printed
        assert "| 40 |" in printed and "| 60 |" in printed

    def test_the_budget_is_beside_every_table(self) -> None:
        """P5: state the time budget beside every comparison. A score without one describes
        the hardware."""
        printed = table([row()], UNVERIFIED, COMPETITION)

        assert "300 s wall" in printed and "seed 0" in printed

    def test_an_unsolved_row_prints_a_dash_rather_than_zero(self) -> None:
        printed = table([row(outcome="out_of_time", penalty=0)], VERIFIED)

        assert "| — |" in printed

    def test_a_rejected_timetable_says_so(self) -> None:
        printed = table([row(feasible=False, violations=3)], UNVERIFIED)

        assert "| no |" in printed


class TestThePublishedValues:
    def test_the_file_that_ships_is_readable_and_complete(self) -> None:
        published = Published.load()

        assert len(published.scores) == 21
        assert published.scores["comp11"] == 0

    def test_and_it_says_it_is_unverified(self) -> None:
        """If this ever flips, somebody has found a source — and the README column appears with
        it, so the flag is not a detail."""
        assert Published.load().verified is False
        assert "2026-09-02" in Published.load().checked

    def test_the_file_lives_where_the_code_looks_for_it(self) -> None:
        assert BEST_KNOWN.exists()


def test_a_sweep_reads_a_directory_in_name_order(tmp_path: Path) -> None:
    for name in ("comp03", "comp01", "comp02"):
        (tmp_path / f"{name}.ctt").write_text(TOY.read_text())

    seen: list[str] = []
    rows = sweep(tmp_path, QUICK, on_row=lambda r: seen.append(r.instance))

    assert [r.instance for r in rows] == ["comp01", "comp02", "comp03"]
    assert seen == ["comp01", "comp02", "comp03"], "progress is reported as it happens"


def test_a_sweep_can_be_narrowed_to_named_instances(tmp_path: Path) -> None:
    for name in ("comp01", "comp02"):
        (tmp_path / f"{name}.ctt").write_text(TOY.read_text())

    assert [r.instance for r in sweep(tmp_path, QUICK, only=("comp02",))] == ["comp02"]


def test_the_two_readings_disagreeing_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exit condition of part 2, wired to the thing that publishes. A benchmark that
    reported a number its own checker disputes would be publishing a coin toss.

    The checker is what gets nudged rather than the solver: `Solution` validates that its own
    breakdown sums to its penalty and refuses an inconsistent one before this assertion could
    ever be reached — which is 4.3's guard doing its job, and a reminder that a mutation has to
    be applied where the claim actually is.
    """
    from tessera.bench.cbctt import Competition

    real = Competition.check

    def disputed(self: Competition, placed: object) -> object:
        report = real(self, placed)  # type: ignore[arg-type]
        return replace(report, costs=replace(report.costs, room_capacity=report.penalty + 1))

    monkeypatch.setattr(Competition, "check", disputed)

    with pytest.raises(AssertionError, match="the objective says"):
        run_one(TOY, QUICK)
