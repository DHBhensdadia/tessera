"""Command-line entry point, including the benchmark runner."""

from __future__ import annotations

import argparse
import sys

import tessera
from tessera.cli import bench, fidelity, itc


def main(argv: list[str] | None = None) -> None:
    """Takes its arguments rather than only reading `sys.argv`, so it can be tested.

    The version test called `main()` under pytest and argparse read *pytest's* arguments,
    which is a failure mode a placeholder entry point could not have."""
    parser = argparse.ArgumentParser(prog="tessera", description="Tessera's command line.")
    parser.add_argument("--version", action="version", version=f"tessera {tessera.__version__}")
    commands = parser.add_subparsers(dest="command")

    read_itc = commands.add_parser(
        "itc",
        help="import an ITC-2019 instance into a project",
        description=itc.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    itc.add_arguments(read_itc)
    read_itc.set_defaults(run=itc.run)

    measure = commands.add_parser(
        "bench",
        help="run the ITC-2007 benchmark",
        description=bench.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bench.add_arguments(measure)
    measure.set_defaults(run=bench.run)

    write_report = commands.add_parser(
        "fidelity",
        help="regenerate the ITC-2019 fidelity report",
        description=fidelity.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fidelity.add_arguments(write_report)
    write_report.set_defaults(run=fidelity.run)

    args = parser.parse_args(argv)
    if not hasattr(args, "run"):
        # No subcommand. Printing the version was this command's whole behaviour before
        # there were any, and something that already prints something is a kinder default
        # than a usage error.
        print(f"tessera {tessera.__version__}")
        return
    code = args.run(args)
    if code:
        sys.exit(code)
