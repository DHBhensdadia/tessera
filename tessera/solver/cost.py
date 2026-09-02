"""What the search is trying to minimise, as something the search does not have to know.

Until now `search` imported `objective` and asked it directly, which was right while there was
one objective. 4.5 has two: Tessera's sixteen weighted rules, and **CB-CTT's four**, because a
benchmark against published results has to compute the published metric rather than a different
one that happens to be ours (4.5 D1). The alternative to this protocol was a second copy of the
Fix-and-Optimize loop inside the benchmark, which would measure code no user ever runs — the
same species of dishonesty as scoring the benchmark with the wrong objective.

So the decomposition is: **the search is the product, the objective is the problem statement.**
Everything about *how* to improve a timetable stays in `search` and `model`; everything about
*what better means* arrives through here.

Three methods rather than 4.5 D2's four. The plan also named `cost`, for what a timetable the
loop already holds is worth — and that is derivable from `add`: freeze every session, add the
objective, and read it back, which is exactly what `search._what_it_costs` already does. A
fourth method would be a second way to compute one number, and two ways to compute one number
is the drift Decision #5 exists to prevent.

**`blame` is separate from `add` on purpose, and it is not a convenience.** `worst_first` ranks
sessions by what they cost *as an independent reading attributes it* — the validator, for
Tessera; the CB-CTT checker, for the benchmark — because taking the ranking from the objective
would let one implementation choose the neighbourhoods that flatter it (4.1's D1). Folding it
into `add` would quietly undo that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from tessera.domain.validation import Snapshot
from tessera.solver import neighbourhood
from tessera.solver import objective as rules

if TYPE_CHECKING:
    from collections.abc import Mapping

    from tessera.domain.ids import SessionId
    from tessera.domain.validation.snapshot import Placement
    from tessera.solver.model import Model
    from tessera.solver.objective import Objective


class CostModel(Protocol):
    """Everything the Fix-and-Optimize loop needs to know about what it is optimising."""

    def enforce(self, model: Model) -> None:
        """Write the rules that are refused rather than priced.

        Called for the feasibility pass, which must not carry the objective: three of
        Tessera's sixteen terms need a boolean per subject per hour and stop a
        department-scale model reaching any solution at all (#225). A hard rule is still a
        constraint, so it goes in.
        """

    def add(self, model: Model) -> Objective | None:
        """Write the priced rules and return what to minimise, or `None` if nothing is priced.

        `None` is not an error. A term may carry no preferences, and then every timetable is
        as good as every other — `minimize(0)` would turn a satisfaction problem into an
        optimisation problem CP-SAT would go on to prove optimal.
        """

    def blame(self, placed: Mapping[SessionId, Placement]) -> Mapping[SessionId, int]:
        """What each session costs, as a reading independent of `add`.

        Sessions costing nothing may be absent rather than present with zero — the caller
        treats a missing session as blameless, and an empty mapping as "nothing is to blame",
        which is what makes `worst_first` fall back to a random window.
        """


@dataclass(frozen=True, slots=True)
class Preferences:
    """Tessera's own rules: sixteen kinds, each weighted by the term that set it.

    The default, and deliberately nothing but a name for what `search` did before this module
    existed. If this ever stops being a thin forwarding layer, the product and the benchmark
    have started to diverge in the loop rather than in the objective, which is the thing the
    protocol exists to prevent.
    """

    snapshot: Snapshot

    def enforce(self, model: Model) -> None:
        rules.enforce(model, self.snapshot)

    def add(self, model: Model) -> Objective | None:
        return rules.add(model, self.snapshot)

    def blame(self, placed: Mapping[SessionId, Placement]) -> Mapping[SessionId, int]:
        return neighbourhood.blamed(self.snapshot, placed)
