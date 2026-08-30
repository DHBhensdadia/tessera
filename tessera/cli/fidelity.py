"""`tessera fidelity` — regenerate the ITC-2019 fidelity report.

Separate from `tessera itc`, which imports one instance into one project. This reads all 36
and writes a document, so it shares nothing but the parser.

The report is committed, and the test suite regenerates it and compares. That is what makes
the file evidence rather than prose: it cannot describe a mapping other than the one that runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tessera.importers.itc.fidelity import gather, report

#: Where the committed copy lives, relative to the repository root.
DEFAULT_OUT = Path("docs/fidelity/itc-2019.md")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--suite",
        choices=("itc2019", "cbctt"),
        default="itc2019",
        help="which benchmark to report on (default: itc2019)",
    )
    parser.add_argument(
        "--instances",
        type=Path,
        required=True,
        metavar="DIR",
        help="the extracted ITC-2019 Instances directory, holding Early/ Middle/ Late/ Test/",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"where to write it (default: {DEFAULT_OUT})",
    )


def run(args: argparse.Namespace) -> int:
    if args.suite == "cbctt":
        return _cbctt(args)
    if not (args.instances / "Test").is_dir():
        print(f"{args.instances} does not look like the extracted Instances directory")
        return 1

    readings = gather(args.instances)
    if len(readings) != 36:
        # Loud rather than quiet. A report over 31 instances that says "36" nowhere is still
        # a report somebody will quote, and the missing five would never be noticed.
        print(f"expected 36 instances, found {len(readings)} — refusing to write a partial report")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report(readings) + "\n")
    print(f"wrote {args.out} from {len(readings)} instances")
    return 0


#: What a solve returned for each ITC-2007 instance, and how long it took.
#:
#: Recorded rather than recomputed. Twenty-one solves take minutes and the report is read far
#: more often than it is regenerated; `tests/importers/cbctt/test_sweep.py` re-runs them
#: deliberately. Every figure was measured at the competition's own 300-second timeout, on one
#: worker with a pinned seed, so it is reproducible rather than merely plausible.
CBCTT_OUTCOMES: dict[str, tuple[str, float]] = {
    "comp01": ("out_of_time", 300.0),
    "comp02": ("solved", 19.8),
    "comp03": ("solved", 17.4),
    "comp04": ("solved", 25.8),
    "comp05": ("solved", 2.9),
    "comp06": ("solved", 47.8),
    "comp07": ("solved", 91.2),
    "comp08": ("solved", 37.2),
    "comp09": ("solved", 25.2),
    "comp10": ("solved", 51.1),
    "comp11": ("solved", 1.2),
    "comp12": ("solved", 8.0),
    "comp13": ("solved", 29.3),
    "comp14": ("solved", 20.2),
    "comp15": ("solved", 17.2),
    "comp16": ("solved", 50.7),
    "comp17": ("solved", 41.1),
    "comp18": ("solved", 3.9),
    "comp19": ("solved", 20.3),
    "comp20": ("out_of_time", 300.1),
    "comp21": ("solved", 37.3),
}


def _cbctt(args: argparse.Namespace) -> int:
    """The ITC-2007 report."""
    from tessera.importers.cbctt.fidelity import gather as gather_cbctt
    from tessera.importers.cbctt.fidelity import report as report_cbctt

    readings = gather_cbctt(args.instances, CBCTT_OUTCOMES)
    if len(readings) != 21:
        print(f"expected 21 instances in {args.instances}, found {len(readings)}")
        return 1

    out = args.out if args.out != DEFAULT_OUT else Path("docs/fidelity/itc-2007.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_cbctt(readings) + "\n")
    print(f"wrote {out} from {len(readings)} instances")
    return 0
