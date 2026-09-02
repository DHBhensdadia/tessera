"""`tessera bench` — run the ITC-2007 benchmark and say what it found.

A subcommand rather than a second console script (D8): the benchmark measures the product, so
it is part of the product's command line, not a separate tool with its own name. Argparse
rather than Typer, and no Rich — a table whose destination is a markdown file and a README does
not need a rendering library inside the shipped `.app`, and nothing here needs an argument
parser the module does not already have.

The instances are not in this repository. `scripts/itc2007.py` fetches and verifies them
(4.5's D10), and this reads whatever directory it is pointed at.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from tessera.bench import results as store
from tessera.bench.run import COMPETITION, Published, Row, median_gap, sweep, table
from tessera.solver import Budget

SUITES = ("itc2007",)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--suite",
        default="itc2007",
        choices=SUITES,
        help="which benchmark to run; only ITC-2007 exists",
    )
    parser.add_argument(
        "--instances",
        type=Path,
        help="where the .ctt files are; defaults to $TESSERA_ITC2007_INSTANCES",
    )
    parser.add_argument(
        "--only", default="", help="a comma-separated list of instances, for a quick look"
    )
    parser.add_argument(
        "--seconds", type=float, default=COMPETITION.seconds, help="wall clock per instance"
    )
    parser.add_argument("--write", type=Path, help="write the results to this file as JSON")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="compare against this results file and exit non-zero if anything got worse",
    )


def run(args: argparse.Namespace) -> int:
    # `--suite` is a choice of one, and that is deliberate rather than unfinished. ITC-2019
    # would need most of ITC-2019's model: 0 of 36 instances import losslessly, all 52,254
    # classes and all 56,667 distribution constraints are dropped, and 30 of 36 need week masks
    # Tessera does not have. The seam exists; it is not filled with a promise (D9).
    directory = args.instances or _from_the_environment()
    if directory is None:
        print("no instances: pass --instances or set TESSERA_ITC2007_INSTANCES")
        print("  uv run python scripts/itc2007.py <directory>")
        return 1
    if not list(directory.glob("comp*.ctt")):
        print(f"{directory} holds no comp*.ctt files")
        return 1

    # The share scales with the budget rather than being fixed at sixty seconds, so a short
    # look at one instance still reaches the rounds.
    budget = Budget(
        seconds=args.seconds,
        whole_seconds=args.seconds * 0.2,
        round_seconds=COMPETITION.round_seconds,
    )
    published = Published.load()
    only = tuple(name.strip() for name in args.only.split(",") if name.strip())

    print(f"{args.suite}: {directory}")
    rows = sweep(directory, budget, only, on_row=_say)
    print()
    print(table(rows, published, budget))

    if published.verified and (gap := median_gap(rows)) is not None:
        print()
        print(f"Median gap to best known: {gap}")

    found = store.Results.of(
        rows,
        budget=f"{budget.seconds:.0f}s wall, {budget.whole_seconds:.0f}s of it on the "
        f"unrestricted attempt, {budget.workers} worker, seed {budget.seed}",
    )
    if args.write:
        found.write(args.write)
        print(f"\nwritten to {args.write}")

    return _judge(found, args.baseline) if args.baseline else _refuse_a_bad_answer(rows)


def _say(row: Row) -> None:
    """A line per instance as it lands. A sweep is an hour and a half; silence is not progress."""
    score = f"{row.penalty:6}" if row.solved else f"{row.outcome:>6}"
    print(f"  {row.instance}  {score}  {row.rounds:5} rounds  {row.seconds:5.0f}s", flush=True)


def _judge(found: store.Results, baseline: Path) -> int:
    if not baseline.exists():
        print(f"\nno baseline at {baseline} — nothing to compare against")
        return 1

    verdicts = store.compare(store.Results.read(baseline), found)
    print()
    if not verdicts:
        print(f"nothing got worse against {baseline}")
        return 0
    for verdict in verdicts:
        print(f"  {verdict}")
    print(f"\n{len(verdicts)} regression(s) against {baseline}")
    return 1


def _refuse_a_bad_answer(rows: list[Row]) -> int:
    """Two things that mean the run itself is not trustworthy, whatever the scores say.

    A timetable the checker rejects has no score worth reading, and a score **strictly below**
    the published best-known is far likelier to be a defect in the objective than a result —
    this project has already had one number that was too good and looked entirely sound (#186).

    **Strictly below, not at or below**, which corrects D4 as it was written. `comp11`'s
    published figure is zero and its optimum is zero: matching it is the right answer and
    happens on every run, so alarming on equality would be a gate that cries wolf from the first
    day (#258). Equality is reported and the run continues; beating it stops everything.
    """
    invalid = [row for row in rows if row.solved and not row.feasible]
    for row in invalid:
        print(f"  {row.instance}: the checker rejected the timetable — {row.violations} broken")

    for row in rows:
        if row.gap == 0:
            print(f"  {row.instance}: {row.penalty} matches the published figure")

    beaten = [row for row in rows if row.gap is not None and row.gap < 0]
    for row in beaten:
        print(
            f"  {row.instance}: {row.penalty} is below the published {row.best_known}. "
            "Check the objective and the checker before believing it."
        )

    return 1 if invalid or beaten else 0


def _from_the_environment() -> Path | None:
    given = os.environ.get("TESSERA_ITC2007_INSTANCES")
    return Path(given).expanduser() if given else None
