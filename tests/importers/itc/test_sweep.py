"""Every published instance, against the competition's own numbers.

This is the external oracle, and this project has rarely had one. The `.md` index files that
ship with the instances state five counts per instance — courses, classes, rooms, students,
distributions — for the thirty Early, Middle and Late instances. That is **150 numbers written
by somebody else**, and a parser that agrees with all of them is not merely self-consistent.

Marked `benchmark`, because it needs the 279 MiB download that `test_format.py` deliberately
does not. Point `TESSERA_ITC_INSTANCES` at the extracted `Instances` directory; without it
these skip, so the fast suite and CI stay offline.

Two of the five counts are **not** what the file literally contains, which is the finding this
sweep produced and the reason it was worth writing:

* **Rooms** counts only rooms some class can actually be assigned to. Five instances list
  rooms no class references — `lums-fal17` has 97 rooms of which 73 are reachable.
* **Distributions** counts only those over two or more classes. Fifteen instances carry
  single-class distributions, and all 106 of them across the whole set are `SameAttendees` —
  vacuous over one class, which is presumably why the organisers left them out.

Neither is a parser bug, and finding out which it was is the whole point of having an oracle:
the numbers disagreed, and the disagreement had to be explained rather than adjusted away.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from tessera.importers.itc import Instance, read
from tessera.importers.itc.apply import (
    COUNTERPARTS,
    GRANULARITIES,
    MAX_SLOTS_PER_DAY,
    mapped,
)

pytestmark = pytest.mark.benchmark

CHECKSUMS = Path(__file__).parents[3] / "scripts" / "itc-instances.sha256"

#: `| agh-fis-spr17 | Early | Early Instance 1 (340 courses; 1,239 classes; ...) | ... |`
ROW = re.compile(r"^\|\s*(?P<name>[\w-]+)\s*\|[^|]*\|\s*[\w ]+ Instance \d+ \((?P<counts>[^)]*)\)")
COUNT = re.compile(
    r"(?:(?P<number>[\d,]+)|no) (?P<what>courses|classes|rooms|students|distributions)"
)


def instances() -> Path | None:
    """Where the download was extracted, or nothing."""
    given = os.environ.get("TESSERA_ITC_INSTANCES")
    if not given:
        return None
    found = Path(given).expanduser()
    return found if (found / "Test").is_dir() else None


ROOT = instances()
needs_download = pytest.mark.skipif(
    ROOT is None,
    reason="set TESSERA_ITC_INSTANCES to the extracted ITC-2019 Instances directory",
)


def published() -> list[tuple[str, Path, dict[str, int]]]:
    """What the organisers say each instance contains, read from their own index files."""
    if ROOT is None:
        return []
    found = []
    for index in sorted(ROOT.glob("*/*.md")):
        for line in index.read_text().splitlines():
            row = ROW.match(line)
            if row is None:
                continue
            counts = {
                c.group("what"): int(c.group("number").replace(",", "")) if c.group("number") else 0
                for c in COUNT.finditer(row.group("counts"))
            }
            # The Test tier's index describes its instances in prose — "Test Instance 3
            # (Small)" — so there is nothing to compare and it is not pretended otherwise.
            if counts:
                found.append((row.group("name"), index.parent / f"{row.group('name')}.xml", counts))
    return found


def every_file() -> list[tuple[str, Path]]:
    return [] if ROOT is None else [(p.stem, p) for p in sorted(ROOT.glob("*/*.xml"))]


@needs_download
@pytest.mark.parametrize(
    ("name", "path"), every_file(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_it_parses(name: str, path: Path) -> None:
    """All 36, including the six the tables say nothing about.

    A count that matches proves the totals; this proves every element in every file is a shape
    the parser will read at all, which is the part that would otherwise be discovered halfway
    through a benchmark run in phase 4.5.
    """
    found = read(path)

    assert found.name == name
    assert found.classes, "an instance with no classes is not one"
    assert all(k.times for k in found.classes)


@needs_download
@pytest.mark.parametrize(
    ("name", "path", "counts"), published(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_it_matches_the_published_counts(name: str, path: Path, counts: dict[str, int]) -> None:
    found = read(path)

    assert {
        "courses": len(found.courses),
        "classes": len(found.classes),
        "rooms": _reachable_rooms(found),
        "students": len(found.students),
        "distributions": _effective_distributions(found),
    } == counts


def _reachable_rooms(found: Instance) -> int:
    """Rooms some class may be assigned to, which is what the tables count."""
    usable = {option.room for k in found.classes for option in k.rooms}
    return sum(1 for room in found.rooms if room.id in usable)


def _effective_distributions(found: Instance) -> int:
    """Distributions over two or more classes, which is what the tables count."""
    return sum(1 for d in found.distributions if len(d.classes) >= 2)


@needs_download
def test_the_tables_cover_thirty_instances() -> None:
    """A guard on the oracle itself, not the parser.

    Without it, a regex that quietly stopped matching would turn 150 assertions into zero and
    the suite would still be green — the failure mode where a test's silence is mistaken for
    a pass.
    """
    assert len(published()) == 30
    assert len(every_file()) == 36


@needs_download
def test_the_files_are_the_ones_the_numbers_came_from() -> None:
    """Checksums, so a corrupted or re-issued download is caught rather than parsed.

    The counts in the fidelity report are only meaningful attached to specific bytes. If the
    organisers re-post an instance, this fails and the report is re-run — which is the correct
    outcome, and not one anybody would notice unaided.
    """
    expected: dict[str, str] = {}
    for line in CHECKSUMS.read_text().splitlines():
        if line.strip():
            digest, relative = line.split()
            expected[relative] = digest
    assert len(expected) == 36

    assert ROOT is not None  # guaranteed by the skip, restated for the type checker
    wrong = {}
    for relative, digest in expected.items():
        found = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if found != digest:
            wrong[relative] = found
    assert wrong == {}


@needs_download
@pytest.mark.parametrize(
    ("name", "path"), every_file(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_it_maps_onto_a_grid_the_domain_accepts(name: str, path: Path) -> None:
    """Every instance reaches a teaching week Tessera will actually store.

    Built through the real `TimeGrid`, so the domain's own validators decide. The mapping
    picks the finest granularity that fits `slots_per_day <= 96`, and that ceiling is not
    moving — D2 rules out reshaping the domain for a benchmark — so an instance it could not
    fit would be a genuine dead end rather than a tuning problem.
    """
    plan = mapped(read(path))
    grid = plan.grid.to_domain()

    assert grid.slots_per_day <= MAX_SLOTS_PER_DAY
    assert grid.slot_count == grid.days * grid.slots_per_day
    assert plan.grid.slot_minutes in GRANULARITIES


@needs_download
@pytest.mark.parametrize(
    ("name", "path"), every_file(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_every_closure_lands_inside_the_week(name: str, path: Path) -> None:
    """The check that would otherwise be made only when a project refused the import.

    A closure slot outside the grid means the day arithmetic is wrong, and the symptom in a
    project would be a room blocked on the wrong day — consistent, plausible and false.
    """
    plan = mapped(read(path))
    week = plan.grid.days * plan.grid.slots_per_day

    for closure in plan.closures:
        assert all(0 <= slot < week for slot in closure.slots)


@needs_download
def test_no_published_instance_imports_without_loss() -> None:
    """The phase's headline, stated as a test so it cannot quietly stop being true.

    If a later phase closes enough of the gap that one of these becomes lossless, this fails
    and the fidelity report is rewritten — which is the correct outcome, and one nobody would
    notice unaided.
    """
    lossless = [name for name, path in every_file() if mapped(read(path)).ledger.is_lossless]

    assert lossless == []


@needs_download
def test_the_counterpart_table_names_every_distribution_type_in_the_set() -> None:
    """A type missing from the table is reported as having no counterpart without anyone
    having decided that. The set uses 19; the table must cover all of them."""
    used: set[str] = set()
    for _, path in every_file():
        used |= {d.name for d in read(path).distributions}

    assert used <= set(COUNTERPARTS)
    assert len(used) == 19
