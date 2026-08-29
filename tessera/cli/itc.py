"""`tessera itc` — read a competition instance into a project, and say what it cost.

A command rather than an API route on purpose. No university has an ITC-2019 file; this is
for developing against real data and for the fidelity report, and putting it in the product's
import flow would offer every user a format none of them has while implying Tessera reads it
fully. It does not, and the ledger this prints is the honest account of how far short it falls.

The output is the point as much as the import is. An import that says *"imported 7 rooms"* and
stops has told you the flattering half.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tessera import engine, project
from tessera.importers.itc import MalformedInstanceError, read
from tessera.importers.itc.apply import Fate, Ledger, Mapped, mapped
from tessera.repository import imports as imports_repo
from tessera.repository import session_scope
from tessera.repository.database import create_project_engine


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("instance", type=Path, help="an ITC-2019 instance XML file")
    parser.add_argument(
        "--into",
        type=Path,
        required=True,
        metavar="PROJECT",
        help="the .tessera project to write into; created if it does not exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="do everything except keep it — the same work, rolled back",
    )


def run(args: argparse.Namespace) -> int:
    try:
        instance = read(args.instance, name=str(args.instance))
    except (OSError, MalformedInstanceError) as error:
        print(f"cannot read {args.instance}: {error}")
        return 1

    plan = mapped(instance)
    database = project.resolve(args.into)
    engine.migrate(database)

    db_engine = create_project_engine(database)
    try:
        with session_scope(db_engine) as session:
            outcome = imports_repo.apply_instance(session, plan, dry_run=args.dry_run)
    finally:
        db_engine.dispose()

    _report(plan, args.into, dry_run=args.dry_run)
    return 0 if outcome.rolled_back or outcome.term_id else 1


def _report(plan: Mapped, into: Path, *, dry_run: bool) -> None:
    grid = plan.grid
    start = f"{grid.day_start_minute // 60:02d}:{grid.day_start_minute % 60:02d}"
    print(f"{plan.instance} → {into}{'  (dry run, nothing kept)' if dry_run else ''}")
    print(
        f"  teaching week: {grid.days} days, {grid.slots_per_day} slots of "
        f"{grid.slot_minutes} minutes from {start}"
    )
    if not grid.is_exact:
        print(
            f"  ITC states times to 5 minutes; {grid.slot_minutes} is the finest grid that "
            "fits Tessera's 96-slot day"
        )
    print()
    _lines("carried", plan.ledger, Fate.CARRIED)
    _lines("approximated", plan.ledger, Fate.APPROXIMATED)
    _lines("dropped", plan.ledger, Fate.DROPPED)


def _lines(heading: str, ledger: Ledger, fate: Fate) -> None:
    entries = ledger.of(fate)
    if not entries:
        return
    print(f"{heading} ({sum(e.count for e in entries):,}):")
    for entry in entries:
        because = f"  — {entry.because}" if entry.because else ""
        print(f"  {entry.count:>7,}  {entry.what}{because}")
    print()
