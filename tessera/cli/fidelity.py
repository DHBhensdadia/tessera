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
