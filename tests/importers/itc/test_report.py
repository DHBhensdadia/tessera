"""That the committed fidelity report is the one this code produces.

Without this the report is prose: accurate the day it was written, and quietly wrong from the
first change to the mapping afterwards. With it, `docs/fidelity/itc-2019.md` cannot describe
an importer other than the one that runs — which is what D1 asks for when it says the claim
must be falsifiable.

Marked `benchmark`: regenerating needs all 36 instances. The report is committed, so a reader
never needs them; only this check does.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tessera.importers.itc.apply import Fate
from tessera.importers.itc.fidelity import COMPETITION, Reading, gather, report

pytestmark = pytest.mark.benchmark

REPO = Path(__file__).parents[3]
COMMITTED = REPO / "docs" / "fidelity" / "itc-2019.md"


def _instances() -> Path | None:
    given = os.environ.get("TESSERA_ITC_INSTANCES")
    if not given:
        return None
    found = Path(given).expanduser()
    return found if (found / "Test").is_dir() else None


ROOT = _instances()
needs_download = pytest.mark.skipif(
    ROOT is None,
    reason="set TESSERA_ITC_INSTANCES to the extracted ITC-2019 Instances directory",
)


@pytest.fixture(scope="module")
def readings() -> list[Reading]:
    assert ROOT is not None
    return gather(ROOT)


@needs_download
def test_the_committed_report_is_up_to_date(readings: list[Reading]) -> None:
    """Byte for byte. The report carries no generation date precisely so that it can be —
    a date would make every regeneration a diff and turn this check into noise."""
    regenerated = report(readings) + "\n"

    assert COMMITTED.read_text() == regenerated, (
        "docs/fidelity/itc-2019.md is stale — regenerate it with "
        "`tessera fidelity --instances <dir>`"
    )


@needs_download
def test_it_covers_every_instance(readings: list[Reading]) -> None:
    assert len(readings) == 36
    assert sum(1 for r in readings if r.is_competition) == 30

    text = COMMITTED.read_text()
    for reading in readings:
        assert f"`{reading.name}`" in text, f"{reading.name} is not named in the report"


@needs_download
def test_it_says_what_it_could_not_carry(readings: list[Reading]) -> None:
    """Every dropped line in every ledger reaches the document.

    The failure this prevents is the quiet one: a mapping that starts dropping something new
    and a report that never mentions it, because the report was written by hand once.
    """
    text = COMMITTED.read_text()
    dropped = {entry.what for reading in readings for entry in reading.plan.ledger.of(Fate.DROPPED)}

    for what in dropped:
        needle = what.removeprefix("distribution: ")
        assert needle in text, f"{what!r} is dropped but the report does not say so"


@needs_download
def test_it_does_not_claim_a_lossless_import(readings: list[Reading]) -> None:
    """The report's headline, checked against the ledgers rather than against itself."""
    assert all(not r.plan.ledger.is_lossless for r in readings)
    assert "0 of the 36 instances import without loss" in COMMITTED.read_text()


@needs_download
def test_no_reason_in_the_report_names_a_single_instance(readings: list[Reading]) -> None:
    """Reasons are summed across 36 instances, so one carrying a number true of only one of
    them is a wrong sentence in a document people are asked to trust. A line reading "over a
    term of 16 weeks" reached a generated report this way."""
    for reading in readings:
        for entry in reading.plan.ledger.entries:
            assert reading.name not in entry.because
            assert str(reading.instance.nr_weeks) not in entry.because


@needs_download
def test_the_bands_are_the_ones_the_organisers_published(readings: list[Reading]) -> None:
    """D8: the 30 and the 6 stay distinct. Published results are comparable against the
    competition set only, so a report that merged them would make a claim nobody could
    check against the literature."""
    assert {r.band for r in readings if r.is_competition} == set(COMPETITION)
    assert {r.band for r in readings if not r.is_competition} == {"Test"}
