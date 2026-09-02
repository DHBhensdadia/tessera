"""The results file, and the three ways a run can be worse than the one before it.

D7's verdicts are separate because *the score got worse* misses two real regressions: an
instance that stopped being solved at all, and a change that reaches the same score for
measurably more searching. #248 is why the third exists — CP-SAT's own portfolio buys its
advantage by spending two to five times the work, so quality and effort are different axes.

The thresholds are #257's measurement rather than anybody's preference: quality exact, coverage
exact, effort within a band seven times the largest difference two architectures showed.
"""

from __future__ import annotations

import json
from pathlib import Path

from tessera.bench.results import SPREAD, Results, compare
from tessera.bench.run import Row


def row(instance: str, penalty: int = 100, work: float = 10.0, outcome: str = "solved") -> Row:
    return Row(
        instance=instance,
        outcome=outcome,
        penalty=penalty,
        bound=0,
        proven=False,
        feasible=outcome == "solved",
        violations=0,
        rounds=5,
        work=work,
        seconds=30.0,
        best_known=50,
    )


def results(*rows: Row) -> Results:
    return Results(rows=list(rows), ortools="9.15", python="3.13", machine="test", budget="300s")


class TestNothingGotWorse:
    def test_an_identical_run_says_nothing(self) -> None:
        before = results(row("comp01"), row("comp02"))

        assert compare(before, results(row("comp01"), row("comp02"))) == []

    def test_a_better_score_is_not_a_regression(self) -> None:
        before = results(row("comp01", penalty=100))

        assert compare(before, results(row("comp01", penalty=90))) == []

    def test_less_work_is_not_a_regression(self) -> None:
        before = results(row("comp01", work=10.0))

        assert compare(before, results(row("comp01", work=1.0))) == []

    def test_an_instance_the_baseline_never_had_is_new(self) -> None:
        """A row that did not exist cannot have got worse. Silence, not a verdict."""
        before = results(row("comp01"))

        assert compare(before, results(row("comp01"), row("comp02"))) == []


class TestQuality:
    def test_a_worse_score_is_named_with_both_numbers(self) -> None:
        found = compare(results(row("comp05", penalty=712)), results(row("comp05", penalty=713)))

        assert [v.kind for v in found] == ["quality"]
        assert "712 became 713" in found[0].detail

    def test_one_point_is_enough(self) -> None:
        """Exact, because #257 measured the score travelling between architectures unchanged.
        A tolerance here would be inventing a doubt the measurement did not find."""
        found = compare(results(row("comp05", penalty=0)), results(row("comp05", penalty=1)))

        assert [v.kind for v in found] == ["quality"]


class TestCoverage:
    def test_an_instance_that_stopped_solving(self) -> None:
        found = compare(
            results(row("comp20")), results(row("comp20", outcome="out_of_time", penalty=0))
        )

        assert [v.kind for v in found] == ["coverage"]
        assert "out_of_time" in found[0].detail

    def test_it_is_not_also_reported_as_a_better_score(self) -> None:
        """A failed solve carries penalty 0, which would read as a perfect score — #235's trap.
        Coverage is reported and the row is not judged on quality at all."""
        found = compare(
            results(row("comp20", penalty=900)),
            results(row("comp20", outcome="out_of_time", penalty=0)),
        )

        assert [v.kind for v in found] == ["coverage"]

    def test_a_row_that_stopped_being_measured(self) -> None:
        """Not the same as improving. A suite that quietly shrank is a suite that says less."""
        found = compare(results(row("comp01"), row("comp02")), results(row("comp01")))

        assert [(v.kind, v.instance) for v in found] == [("coverage", "comp02")]


class TestEffort:
    def test_the_same_answer_for_measurably_more_searching(self) -> None:
        before = results(row("comp05", work=100.0))
        found = compare(before, results(row("comp05", work=100.0 * (1 + SPREAD * 2))))

        assert [v.kind for v in found] == ["effort"]
        assert "more than 1%" in found[0].detail

    def test_inside_the_measured_band_is_silence(self) -> None:
        """0.133 % is what two architectures actually differed by; the band is seven times it,
        and a difference inside it is the hardware rather than the code."""
        before = results(row("comp05", work=100.0))

        assert compare(before, results(row("comp05", work=100.0 * (1 + SPREAD / 2)))) == []

    def test_a_baseline_that_did_no_work_is_not_divided_by(self) -> None:
        before = results(row("comp01", work=0.0))

        assert compare(before, results(row("comp01", work=5.0))) == []


class TestTheFileItself:
    def test_it_round_trips(self, tmp_path: Path) -> None:
        before = results(row("comp02", penalty=240), row("comp01", penalty=21))
        path = tmp_path / "itc2007.json"
        before.write(path)

        assert Results.read(path) == Results(
            rows=sorted(before.rows, key=lambda r: r.instance),
            ortools=before.ortools,
            python=before.python,
            machine=before.machine,
            budget=before.budget,
        )

    def test_rows_are_sorted_so_a_diff_reads_as_a_diff_of_answers(self, tmp_path: Path) -> None:
        path = tmp_path / "itc2007.json"
        results(row("comp09"), row("comp01"), row("comp05")).write(path)
        written = json.loads(path.read_text())

        assert [r["instance"] for r in written["rows"]] == ["comp01", "comp05", "comp09"]

    def test_it_records_the_machine_as_well_as_the_solver(self, tmp_path: Path) -> None:
        """#257: the same commit takes a different route to the same score on a different
        architecture, so a result file that named only the code would be half a claim."""
        found = Results.of([row("comp01")], budget="300s, 60s share")
        path = tmp_path / "itc2007.json"
        found.write(path)
        written = json.loads(path.read_text())

        assert written["ortools"] and written["python"] and written["machine"]
        assert written["budget"] == "300s, 60s share"


def test_the_worst_kind_is_reported_first() -> None:
    """An instance that stopped solving matters more than one that got a point worse, and a
    reader who stops after the first line should have read the important one."""
    found = compare(
        results(row("comp01", penalty=10, work=10.0), row("comp02")),
        results(row("comp01", penalty=99, work=99.0), row("comp02", outcome="out_of_time")),
    )

    assert [v.kind for v in found] == ["coverage", "quality", "effort"]


def test_a_verdict_reads_as_a_sentence() -> None:
    """The CLI prints these straight, so the string form is the interface a reader meets."""
    found = compare(results(row("comp05", penalty=712)), results(row("comp05", penalty=713)))

    assert str(found[0]) == "quality: comp05 — 712 became 713"
