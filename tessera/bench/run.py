"""One instance, one budget, one row — and the table those rows make.

**The budget is the measurement** (D11). At the competition's own three hundred seconds the
default `Budget` spends every one of them on a single unrestricted solve: `_left()` hands the
whole-model attempt whatever the clock has, the model is under `whole_model_ceiling`, and
Fix-and-Optimize — the algorithm this project chose on evidence, and which P5 calls
*load-bearing, not an improvement* — is never reached.

Switching it off entirely is not the answer either. Measured at 300 s, one worker, pinned seed,
penalties:

| | whole attempt only | rounds only | **60 s share, then rounds** |
|---|---|---|---|
| `comp01` | 23 | 506 | **21** |
| `comp02` | 2961 | 222 | **240** |
| `comp05` | 856 | 712 | **537** |
| `comp11` | **0**, proven | 8 | **0**, proven, in 38 s |

**Neither pure mode wins.** The unrestricted attempt is decisive where CP-SAT can make real
progress on the whole model — `comp01` and `comp11`, where the loop is twenty times worse — and
hopeless where it cannot: `comp02` at 2961 against the loop's 222. `whole_model_ceiling` was
meant to decide this and cannot, because it reads the model's *size* and every CB-CTT model is
small enough to attempt.

So the share is a share of the **clock** (`Budget.whole_seconds`), and sixty seconds of three
hundred beats both pure modes on three instances and ties on the fourth. It costs nothing where
the whole attempt suits the instance, because a proven optimum returns immediately: `comp11`
still finishes in 38 seconds.

**Every row is scored twice.** The CP-SAT objective and the independently written checker must
return the same integer, as they did on all 21 in part 2; a disagreement stops the run rather
than being reported as a footnote.
"""

from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from tessera.bench.cbctt import FORMULATION, Competition
from tessera.domain.ids import SessionId
from tessera.domain.validation.snapshot import Placement
from tessera.solver import Budget, Outcome, Solution

#: The competition's protocol — 300 seconds, one worker, a pinned seed — with a bounded share
#: for the unrestricted attempt and the rest to the rounds (D11). `round_seconds` at 30 rather
#: than 10 made no measurable difference on either instance it was tried on, so it is the
#: rounder number.
COMPETITION = Budget(seconds=300, whole_seconds=60, round_seconds=30)

BEST_KNOWN = Path(__file__).parents[2] / "benchmarks" / "best-known.toml"


@dataclass(frozen=True, slots=True)
class Published:
    """Somebody else's numbers, and whether anybody has checked them."""

    scores: dict[str, int]
    verified: bool
    source: str
    checked: str

    @staticmethod
    def load(path: Path = BEST_KNOWN) -> Published:
        read = tomllib.loads(path.read_text())
        return Published(
            scores=dict(read["best_known"]),
            verified=bool(read["meta"]["verified"]),
            source=str(read["meta"]["source"]),
            checked=str(read["meta"]["checked"]),
        )


@dataclass(frozen=True, slots=True)
class Row:
    """What one instance did, and everything a reader needs to judge it."""

    instance: str
    outcome: str
    penalty: int
    bound: int
    proven: bool
    feasible: bool
    violations: int
    rounds: int
    work: float
    seconds: float
    best_known: int | None = None

    @property
    def solved(self) -> bool:
        return self.outcome == Outcome.SOLVED.value

    @property
    def gap(self) -> int | None:
        """How far above the published figure, in points.

        Absolute rather than a ratio, and 0.1's reporting rules say why: on an instance whose
        optimum is near zero a percentage explodes. `comp20` read +4525 % at a gap of 181,
        which looks worse than `comp05`'s +85 % at 242 and is not.
        """
        if self.best_known is None or not self.solved:
            return None
        return self.penalty - self.best_known


def run_one(instance: Path, budget: Budget = COMPETITION, best_known: int | None = None) -> Row:
    """Solve one instance and score the answer twice.

    The checker's verdict travels with the row rather than being asserted away: a run that
    produced an *invalid* CB-CTT solution has no score worth reporting, and saying so in the
    table is more useful than refusing to print it.
    """
    competition = Competition.read(instance)
    began = time.perf_counter()
    found = solve_it(competition, budget)
    seconds = time.perf_counter() - began

    if found.outcome is not Outcome.SOLVED:
        return Row(
            instance=instance.stem,
            outcome=found.outcome.value,
            penalty=0,
            bound=0,
            proven=False,
            feasible=False,
            violations=0,
            rounds=len(found.trajectory),
            work=found.work,
            seconds=seconds,
            best_known=best_known,
        )

    report = competition.check(_placed(found))
    if found.penalty != report.penalty:
        raise AssertionError(
            f"{instance.stem}: the objective says {found.penalty} and the checker says "
            f"{report.penalty}. One of the two readings is wrong and neither number is usable."
        )

    return Row(
        instance=instance.stem,
        outcome=found.outcome.value,
        penalty=found.penalty,
        bound=found.lower_bound,
        proven=found.bound_is_proven,
        feasible=report.feasible,
        violations=len(report.violations),
        rounds=len(found.trajectory),
        work=found.work,
        seconds=seconds,
        best_known=best_known,
    )


def solve_it(competition: Competition, budget: Budget) -> Solution:
    from tessera.solver import solve

    return solve(competition.snapshot, budget, FORMULATION, costs=competition)


def _placed(found: Solution) -> dict[SessionId, Placement]:
    return {
        p.session: Placement(
            session_id=p.session, start_slot=p.start_slot, room_id=p.room, is_pinned=False
        )
        for p in found.placements
    }


def sweep(
    directory: Path,
    budget: Budget = COMPETITION,
    only: tuple[str, ...] = (),
    on_row: object = None,
) -> list[Row]:
    """Every `comp*.ctt` in a directory, in name order."""
    published = Published.load()
    rows = []
    for instance in sorted(directory.glob("comp*.ctt")):
        if only and instance.stem not in only:
            continue
        row = run_one(instance, budget, published.scores.get(instance.stem))
        rows.append(row)
        if callable(on_row):
            on_row(row)
    return rows


def median_gap(rows: list[Row]) -> int | None:
    """The median absolute gap. Median rather than mean, per 0.1's reporting rules.

    The mean is dominated by the three instances whose optimum is near zero, where a ratio
    explodes and an absolute gap of four looks like nothing.
    """
    gaps = [row.gap for row in rows if row.gap is not None]
    return int(median(gaps)) if gaps else None


def table(rows: list[Row], published: Published, budget: Budget = COMPETITION) -> str:
    """The rows as markdown, with the budget beside them because P5 says so.

    The published column is printed only when somebody has checked it. An unverified number in
    a comparison is worse than no comparison: the reader cannot tell which half is in doubt.
    """
    head = ["| instance | penalty | valid | rounds | work | seconds |"]
    rule = ["|---|---|---|---|---|---|"]
    if published.verified:
        head = ["| instance | penalty | best known | gap | valid | rounds | work | seconds |"]
        rule = ["|---|---|---|---|---|---|---|---|"]

    lines = head + rule
    for row in rows:
        score = str(row.penalty) if row.solved else "—"
        valid = "yes" if row.feasible else ("no" if row.solved else "—")
        cells = [row.instance, score]
        if published.verified:
            cells += [
                str(row.best_known) if row.best_known is not None else "—",
                str(row.gap) if row.gap is not None else "—",
            ]
        cells += [valid, str(row.rounds), f"{row.work:.1f}", f"{row.seconds:.0f}"]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(
        f"Budget: {budget.seconds:.0f} s wall, {budget.workers} worker, seed "
        f"{budget.seed}, Fix-and-Optimize only."
    )
    if not published.verified:
        lines.append("")
        lines.append(
            "No published comparison is shown: the best-known values this project holds are "
            f"**unverified** ({published.source}), and the portal that would confirm them was "
            f"unreachable when last checked on {published.checked}."
        )
    return "\n".join(lines)
