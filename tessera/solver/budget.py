"""How long to search, how finely, and how reproducibly.

Its own module because both halves of the solver need it — `solve` for the feasibility pass and
`search` for the rounds — and having one import the other would be a cycle around a dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Budget:
    """What a caller is willing to spend, and what they need back.

    **Deterministic by default** (#206). Parallel CP-SAT gives a different answer each run and
    P5 warns at 4.5 that Phase 0.1 saw an instance score *worse* with five times the budget, so
    the defaults are the reproducible ones and speed is opted into.
    """

    seconds: float = 30.0
    """NFR-4 asks for a first feasible solution at department scale in under 30 seconds."""

    workers: int = 1
    """One by default. Deterministic, and what every test and benchmark should use."""

    seed: int = 0
    """Pins CP-SAT's search *and* the loop's choice of neighbourhood."""

    deterministic_seconds: float | None = None
    """A budget measured in work done rather than in time passed (D4).

    A pinned seed and one worker make a solve reproducible *on one machine*; they do not make
    it reproducible on a slower one, because the wall clock decides when the search stops.
    CP-SAT counts its own progress in a machine-independent unit, and capping that instead is
    what lets a benchmark assert on a number rather than on a range — the flaky gate P5 warns
    4.5 about, refused one phase early.

    `seconds` stays set alongside it as a ceiling, so a deterministic budget calibrated on one
    machine cannot run for an hour on another. A test asserts the ceiling is not what stopped
    the search.

    **This caps each solve, not the run.** The outer loop keeps going while the clock allows,
    so a reproducible *run* needs `rounds` as well — that is what counts something the machine
    cannot change.
    """

    rounds: int | None = None
    """How many Fix-and-Optimize rounds to run, or `None` to keep going until the time is up.

    A budget in seconds and a reproducible answer are not compatible: how many rounds fit
    depends on how fast the machine is. So tests and benchmarks count rounds and cap each round
    by work, which is reproducible anywhere; a person waiting gets seconds, which is the thing
    they actually asked for. When this is set the wall clock becomes a ceiling that should not
    be reached, and `test_a_round_budget_does_not_run_out_of_time` asserts it is not.
    """

    window: int = 20
    """How many sessions a round may move. Everything else is frozen at its current placement.

    Twenty, measured over three seeds on two sizes rather than picked. A window is a trade
    between how much a round can change and whether it can be solved at all: at forty, a
    department-scale round comes back with **nothing** — not a worse answer, no answer — and
    the loop spends its whole budget on refusals. Medians at 30 s, department scale: 11,740 at
    a window of 8, 11,629 at 12, **11,427 at 20**, and 13,044 at 40, which is the untouched
    incumbent.
    """

    round_seconds: float = 5.0
    """The wall-clock ceiling on one round's sub-solve."""

    round_deterministic_seconds: float | None = None
    """The same in work rather than time, for a reproducible loop."""

    whole_model_ceiling: int = 120_000
    """How large a scored model may be before the loop stops trying to solve it whole.

    The unrestricted attempt is worth making: it is what proves a lower bound (D6), and on
    anything small it simply answers the question and the loop never runs. It is also what
    cannot be afforded at size — measured, at a hundred-hour week with the default preferences:

    | | variables | built in | a single solve at 30 s |
    |---|---|---|---|
    | 150 sessions, 12 rooms | 49,223 | 0.56 s | a timetable, no bound proven |
    | 500 sessions, 40 rooms | 182,694 | 2.15 s | **nothing at all** |

    So the ceiling sits between them. It is checked against the model actually built rather
    than against an estimate of it: an estimate would have to know the shape of all sixteen
    terms, and being wrong would change which problems get a bound without saying so. The cost
    of being exact is that an over-ceiling model is built and discarded — 2.15 s of a 30 s
    budget at department scale, and more at NFR-9's ceiling, which is recorded in the backlog
    rather than engineered around while nothing needs it.
    """
