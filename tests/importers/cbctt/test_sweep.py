"""All 21 ITC-2007 instances, against the numbers the report states.

Marked `benchmark`: it needs the 272 KB download that `test_format.py` deliberately does not.
Point `TESSERA_ITC2007_INSTANCES` at the directory; without it these skip, so CI stays offline.

The solves themselves are **not** re-run here. Twenty-one of them take minutes, and one of them
is a 300-second timeout by design — a pre-push gate is the wrong place for that. What is
checked is everything that is cheap and everything that could go quietly wrong: the files are
the ones the numbers came from, every instance still parses and maps, and the capacity proof
the report leans on still holds.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from tessera.cli.fidelity import CBCTT_OUTCOMES
from tessera.importers.cbctt import read
from tessera.importers.cbctt.apply import mapped
from tessera.importers.cbctt.fidelity import bottleneck, gather, report

pytestmark = pytest.mark.benchmark

REPO = Path(__file__).parents[3]
CHECKSUMS = REPO / "scripts" / "itc2007-instances.sha256"
COMMITTED = REPO / "docs" / "fidelity" / "itc-2007.md"


def instances() -> Path | None:
    given = os.environ.get("TESSERA_ITC2007_INSTANCES")
    if not given:
        return None
    found = Path(given).expanduser()
    return found if list(found.glob("comp*.ctt")) else None


ROOT = instances()
needs_download = pytest.mark.skipif(
    ROOT is None, reason="set TESSERA_ITC2007_INSTANCES to the ITC-2007 directory"
)


@needs_download
def test_the_files_are_the_ones_the_numbers_came_from() -> None:
    """Checksums, so a re-issued or corrupted instance is caught rather than parsed.

    Every figure in the report is attached to specific bytes. The official site serves these
    openly today; if it reposts one, this fails and the report is regenerated — which is the
    correct outcome and not one anybody would notice unaided.
    """
    assert ROOT is not None
    expected: dict[str, str] = {}
    for line in CHECKSUMS.read_text().splitlines():
        if line.strip():
            digest, name = line.split()
            expected[name] = digest

    assert len(expected) == 21
    wrong = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name, digest in expected.items()
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
    }
    assert wrong == {}


@needs_download
@pytest.mark.parametrize("stem", sorted(CBCTT_OUTCOMES))
def test_every_instance_parses_and_maps(stem: str) -> None:
    """Parsing and mapping are deterministic and fast, so they are checked for all 21.

    The header agreeing with the sections is the only self-check the format offers, and it is
    what a parser silently dropping rows would fail — the gap Phase 0.1 closed one level down.
    """
    assert ROOT is not None
    instance = read(ROOT / f"{stem}.ctt")
    term = mapped(instance)

    assert instance.lectures == len(term.sessions)
    assert len(term.rooms) == len(instance.rooms)
    assert term.grid.days == instance.days
    assert term.grid.slots_per_day == instance.periods_per_day


@needs_download
def test_the_capacity_proof_still_holds() -> None:
    """The report's strongest claim, re-derived rather than trusted.

    `comp01` needs 64 lectures in rooms seating 31 or more, and the week has 60 such
    room-periods. That is arithmetic, and it is the difference between *"the solver gave up"*
    and *"no arrangement exists"* — the report says the second, so the second has to be true.
    """
    assert ROOT is not None
    blocked = bottleneck(read(ROOT / "comp01.ctt"))

    assert blocked is not None
    assert (blocked.lectures, blocked.room_slots) == (64, 60)
    assert blocked.short_by == 4


@needs_download
def test_only_comp01_is_provably_impossible() -> None:
    """The other twenty must *not* trip the same proof, or the report overstates its case."""
    assert ROOT is not None
    impossible = [stem for stem in sorted(CBCTT_OUTCOMES) if bottleneck(read(ROOT / f"{stem}.ctt"))]

    assert impossible == ["comp01"]


@needs_download
def test_the_committed_report_is_up_to_date() -> None:
    """Byte for byte, so the document cannot describe an importer other than the one that runs.

    The solve outcomes it quotes are recorded rather than recomputed, and that is stated where
    they are declared — a reader who wants them re-measured runs the sweep deliberately.
    """
    assert ROOT is not None
    regenerated = report(gather(ROOT, CBCTT_OUTCOMES)) + "\n"

    assert COMMITTED.read_text() == regenerated, (
        "docs/fidelity/itc-2007.md is stale — regenerate with "
        "`tessera fidelity --suite cbctt --instances <dir>`"
    )
