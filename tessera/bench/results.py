"""What a run produced, what the last one produced, and whether anything got worse.

**Three verdicts, not one** (D7). *The score got worse* is the obvious one and it misses two
real regressions: an instance that stopped being solved at all, and a change that reaches the
same score for measurably more searching. #248 is why the third exists — quality and work are
separate axes, and CP-SAT's own portfolio buys its advantage by spending two to five times the
work.

**The thresholds are measured, not chosen** (#253, corrected by #257). The CI matrix disagreed
with the first version of them, which is how they came to be measured at all: on the same commit
with the same seed, `macos-14` and `ubuntu-latest` returned **the same penalty** and a
`deterministic_time` **0.133 % apart**. So quality is exact, coverage is exact, and effort gets a
band seven times the largest difference anybody has seen.

**Nothing here writes the baseline.** CI reads it and reports; updating it is a commit somebody
approved, which is also the moment somebody looks at whether the numbers were meant to move
(D6). A bot that silently rewrites the baseline turns every regression into the new normal.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tessera.bench.run import Row

SPREAD = 0.01
"""How far `work` may sit from the baseline before it counts as a change.

Derived: two architectures differ by 0.133 %, so this is roughly seven times the largest
difference measured. The headroom is there because two samples do not bound a distribution, not
because 0.133 % was uncomfortable.
"""


@dataclass(frozen=True, slots=True)
class Verdict:
    """One thing that got worse, in terms a reader can act on."""

    kind: str
    instance: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.instance} — {self.detail}"


@dataclass(frozen=True)
class Results:
    """A run, and enough about the machine to know what it is a claim about.

    A benchmark result is a claim about a solver *and* a machine, and #257 is the measurement
    that proves the second half is not pedantry: the same commit takes a different route to the
    same score on a different architecture.
    """

    rows: list[Row]
    ortools: str
    python: str
    machine: str
    budget: str

    @staticmethod
    def of(rows: list[Row], budget: str) -> Results:
        from importlib.metadata import version

        return Results(
            rows=rows,
            ortools=version("ortools"),
            python=sys.version.split()[0],
            machine=f"{platform.system()} {platform.machine()}",
            budget=budget,
        )

    def write(self, path: Path) -> None:
        """Sorted and indented, so a diff of two runs reads as a diff of two answers."""
        payload: dict[str, Any] = {
            "ortools": self.ortools,
            "python": self.python,
            "machine": self.machine,
            "budget": self.budget,
            "rows": [asdict(row) for row in sorted(self.rows, key=lambda r: r.instance)],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def read(path: Path) -> Results:
        payload = json.loads(path.read_text())
        return Results(
            rows=[Row(**row) for row in payload["rows"]],
            ortools=payload["ortools"],
            python=payload["python"],
            machine=payload["machine"],
            budget=payload["budget"],
        )


def compare(baseline: Results, now: Results) -> list[Verdict]:
    """Everything that got worse, most serious first.

    An instance the baseline does not mention is new rather than regressed, and says nothing.
    An instance the baseline has and this run does not is reported: a row that stopped being
    measured is not a row that improved.
    """
    was = {row.instance: row for row in baseline.rows}
    verdicts: list[Verdict] = []

    for row in sorted(now.rows, key=lambda r: r.instance):
        before = was.pop(row.instance, None)
        if before is None:
            continue

        if before.solved and not row.solved:
            verdicts.append(
                Verdict("coverage", row.instance, f"was {before.outcome}, is now {row.outcome}")
            )
            continue

        if row.solved and row.penalty > before.penalty:
            verdicts.append(
                Verdict("quality", row.instance, f"{before.penalty} became {row.penalty}")
            )

        if before.work > 0 and (row.work - before.work) / before.work > SPREAD:
            verdicts.append(
                Verdict(
                    "effort",
                    row.instance,
                    f"{before.work:.2f} became {row.work:.2f}, more than {SPREAD:.0%} above it",
                )
            )

    verdicts.extend(
        Verdict("coverage", name, "in the baseline and not in this run") for name in sorted(was)
    )

    order = {"coverage": 0, "quality": 1, "effort": 2}
    return sorted(verdicts, key=lambda v: (order[v.kind], v.instance))
