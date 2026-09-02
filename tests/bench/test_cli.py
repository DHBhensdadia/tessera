"""`tessera bench`, exercised through the entry point people actually type.

An entry point that has never been executed is the kind of thing that breaks silently and is
noticed by a user — `tests/test_cli.py` says so about the other two subcommands, and this one
is the same shape.

The toy instance is copied under real instance names so the published-value lookup has
something to find, which is how the two refusals at the end are reached at all.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tessera.cli import main

TOY = Path(__file__).parents[1] / "importers" / "cbctt" / "fixtures" / "toy.ctt"

#: Short, and the share scales with it, so the rounds are still reached.
QUICK = ["--seconds", "6"]


def instances(where: Path, *names: str) -> Path:
    """Copies of the toy under instance names the sweep will glob.

    `comp98` and `comp99` on purpose: they match `comp*.ctt` and have **no** published figure,
    so the toy scoring zero does not trip the at-or-below-best-known refusal. The one test that
    wants that refusal names its copy `comp11`, whose published figure is zero.
    """
    where.mkdir(parents=True, exist_ok=True)
    for name in names:
        (where / f"{name}.ctt").write_text(TOY.read_text())
    return where


def test_the_bench_command_is_reachable(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["bench", "--help"])

    assert stopped.value.code == 0
    assert "--suite" in capsys.readouterr().out


def test_only_itc2007_is_a_suite(capsys: pytest.CaptureFixture[str]) -> None:
    """D9. ITC-2019 would need most of ITC-2019's model — 0 of 36 instances import losslessly —
    so the seam exists and is not filled with a promise."""
    with pytest.raises(SystemExit) as stopped:
        main(["bench", "--suite", "itc2019"])

    assert stopped.value.code == 2
    assert "itc2007" in capsys.readouterr().err


class TestWhenItCannotRun:
    def test_no_directory_at_all(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TESSERA_ITC2007_INSTANCES", raising=False)
        with pytest.raises(SystemExit) as stopped:
            main(["bench"])

        assert stopped.value.code == 1
        assert "scripts/itc2007.py" in capsys.readouterr().out, "it says how to get them"

    def test_a_directory_with_nothing_in_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as stopped:
            main(["bench", "--instances", str(tmp_path)])

        assert stopped.value.code == 1
        assert "no comp*.ctt" in capsys.readouterr().out


class TestARun:
    def test_it_prints_a_table_and_a_line_per_instance(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        where = instances(tmp_path, "comp98", "comp99")
        main(["bench", "--instances", str(where), *QUICK])
        printed = capsys.readouterr().out

        assert "| instance | penalty |" in printed
        assert "comp98" in printed and "comp99" in printed
        assert "Budget: 6 s wall" in printed

    def test_it_writes_a_results_file(self, tmp_path: Path) -> None:
        where = instances(tmp_path / "in", "comp99")
        out = tmp_path / "results.json"
        main(["bench", "--instances", str(where), "--write", str(out), *QUICK])
        written = json.loads(out.read_text())

        assert [r["instance"] for r in written["rows"]] == ["comp99"]
        assert written["machine"] and written["ortools"]

    def test_it_can_be_narrowed_to_one_instance(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        where = instances(tmp_path, "comp98", "comp99")
        main(["bench", "--instances", str(where), "--only", "comp99", *QUICK])
        printed = capsys.readouterr().out

        assert "| comp99 |" in printed
        assert "| comp98 |" not in printed


class TestAgainstABaseline:
    def test_a_baseline_that_is_not_there(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        where = instances(tmp_path / "in", "comp99")
        with pytest.raises(SystemExit) as stopped:
            main(
                [
                    "bench",
                    "--instances",
                    str(where),
                    "--baseline",
                    str(tmp_path / "no.json"),
                    *QUICK,
                ]
            )

        assert stopped.value.code == 1
        assert "nothing to compare against" in capsys.readouterr().out

    def test_the_same_run_twice_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        where = instances(tmp_path / "in", "comp99")
        baseline = tmp_path / "baseline.json"
        main(["bench", "--instances", str(where), "--write", str(baseline), *QUICK])
        capsys.readouterr()

        main(["bench", "--instances", str(where), "--baseline", str(baseline), *QUICK])

        assert "nothing got worse" in capsys.readouterr().out

    def test_a_worse_score_fails_and_names_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        where = instances(tmp_path / "in", "comp99")
        baseline = tmp_path / "baseline.json"
        main(["bench", "--instances", str(where), "--write", str(baseline), *QUICK])
        capsys.readouterr()

        # The baseline is edited rather than the solver: what is being tested is the gate, and
        # a gate is tested by handing it a difference, not by breaking the thing it watches.
        payload = json.loads(baseline.read_text())
        payload["rows"][0]["penalty"] -= 1
        baseline.write_text(json.dumps(payload))

        with pytest.raises(SystemExit) as stopped:
            main(["bench", "--instances", str(where), "--baseline", str(baseline), *QUICK])

        printed = capsys.readouterr().out
        assert stopped.value.code == 1
        assert "quality: comp99" in printed
        assert "1 regression(s)" in printed


class TestTheRefusals:
    def test_matching_a_published_figure_is_reported_and_allowed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`comp11`'s published figure is 0 and its optimum is 0, so matching it is the right
        answer and happens on every run. D4 said *at or below* stops the run; alarming on
        equality would be a gate that cries wolf from the first day, which is #258's lesson."""
        where = instances(tmp_path, "comp11")
        main(["bench", "--instances", str(where), *QUICK])

        assert "matches the published figure" in capsys.readouterr().out

    def test_a_score_below_the_published_one_stops_the_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not a celebration — an alarm. The likelier cause is a defect in the objective or the
        checker, and #186 is what a number that was too good and looked entirely sound cost the
        last time."""
        from tessera.bench.run import Published

        impossible = Published(
            scores={"comp99": 5}, verified=False, source="a test", checked="today"
        )
        monkeypatch.setattr(Published, "load", staticmethod(lambda *_: impossible))
        where = instances(tmp_path, "comp99")

        with pytest.raises(SystemExit) as stopped:
            main(["bench", "--instances", str(where), *QUICK])

        assert stopped.value.code == 1
        assert "is below the published" in capsys.readouterr().out

    def test_a_timetable_the_checker_rejects_stops_the_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A score attached to an invalid solution is not a score."""
        from tessera.bench.cbctt import Competition
        from tessera.importers.cbctt.score import Violation

        real = Competition.check

        def rejected(self: Competition, placed: object) -> object:
            return replace(real(self, placed), violations=(Violation("Lectures", "invented"),))  # type: ignore[arg-type]

        monkeypatch.setattr(Competition, "check", rejected)
        where = instances(tmp_path, "comp99")

        with pytest.raises(SystemExit) as stopped:
            main(["bench", "--instances", str(where), *QUICK])

        assert stopped.value.code == 1
        assert "the checker rejected the timetable" in capsys.readouterr().out


def test_the_median_gap_is_printed_once_the_values_are_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of #269. While `verified` is false the comparison is withheld entirely;
    the day somebody sources it, the summary line appears — median rather than mean, because
    the mean is dominated by the three instances whose optimum is near zero.
    """
    from tessera.bench.run import Published

    sourced = Published(
        scores={"comp98": 3, "comp99": 7}, verified=True, source="a test", checked="today"
    )
    monkeypatch.setattr(Published, "load", staticmethod(lambda *_: sourced))
    where = instances(tmp_path, "comp98", "comp99")

    with pytest.raises(SystemExit) as stopped:
        main(["bench", "--instances", str(where), *QUICK])

    printed = capsys.readouterr().out
    assert "best known" in printed
    assert "Median gap to best known: -5" in printed
    assert stopped.value.code == 1, "beating a published figure is an alarm, not a result"
