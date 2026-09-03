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

    windows: tuple[int, ...] = (3, 3, 8, 20)
    """How many sessions a round may move, cycled round by round.

    A schedule rather than a number, because the best window is a property of the **term** and
    not of the solver, and the split is sharp. Medians at thirty seconds over three seeds, as a
    percentage above the best schedule for that instance:

    | | (3,) | (20,) | (3,8,20) | (3,3,3,20) | **(3,3,8,20)** |
    |---|---|---|---|---|---|
    | dept(500,40) | +12 % | +31 % | +41 % | **best** | +11 % |
    | dept(150,12) | **best** | +168 % | +356 % | +8 % | +14 % |
    | `comp05` | +69 % | +13 % | **best** | +58 % | +35 % |
    | `comp02` | +34 % | +4 % | **best** | +16 % | +22 % |
    | **worst case** | +69 % | +168 % | +356 % | +58 % | **+35 %** |

    The generated departments run at about a quarter of their room-slots occupied and reward
    many cheap moves; `comp02` runs at about seven tenths, and a window of three cannot
    rearrange anything there — it needs a big enough bite to escape where it is.

    **Chosen on the worst case rather than the average**, because a default is what runs on the
    institution nobody measured. No schedule is best everywhere, and one that is 356 % adrift
    on a term of the wrong shape is a worse default than one that is never more than a third
    off. Pass an explicit schedule to do better on a term you know.
    """

    whole_seconds: float | None = None
    """How much of the clock the one unrestricted attempt may take, or `None` for all of it.

    **`None` is what this always did, and it is wrong for a long budget.** `_left()` hands the
    whole-model solve everything remaining, so on a three-hundred-second job it takes three
    hundred seconds and the Fix-and-Optimize rounds never run at all. Measured on ITC-2007 at
    exactly that budget, penalties, whole attempt against rounds only:

    | | whole attempt | rounds only |
    |---|---|---|
    | `comp02` | 2961 | **222** |
    | `comp05` | 856 | **712** |
    | `comp11` | **0**, proven | 8 |

    **Neither wins.** The unrestricted attempt is the only thing that can prove an optimum, and
    on `comp11` it finds one in thirty-three seconds; on `comp02` it spends five minutes to be
    thirteen times worse than the loop. `whole_model_ceiling` was meant to decide this and
    cannot: it reads the model's *size*, and these models are all small enough to attempt.

    So the share is a share of the clock. Give the whole attempt a bounded slice — it returns
    early when it proves an optimum, so a generous slice costs nothing on the instances it
    suits — and the rounds get the rest.
    """

    explain_seconds: float = 5.0
    """How long the explainer may spend naming the rules that cannot hold together.

    Its own slice, and small. It runs only after something has already proved the term
    impossible, so the answer is not in doubt and what is being bought is a *sentence* — and
    the model it searches is the weak one: every hard rule sits behind an assumption literal,
    which keeps the rule's meaning and costs its propagation (#275). Spending a person's whole
    budget on a better-worded refusal would be the wrong trade.

    Bounded rather than generous for a second reason: coming back with nothing is a supported
    answer. `Outcome` already says the term has no timetable; the conflict set is the part
    that may be missing, and a missing sentence is better than a slow one.
    """

    round_seconds: float = 5.0
    """The wall-clock ceiling on one round's sub-solve."""

    round_deterministic_seconds: float | None = None
    """The same in work rather than time, for a reproducible loop."""

    strategies: tuple[str, ...] = ()
    """Which neighbourhood strategies to rotate through, or empty for all of them in order.

    A rotation rather than a choice, because the four fail differently: one frees a day, one a
    subject's week, one the sessions carrying the most cost, and one at random. A loop that used
    only the best of them would stall wherever that one is blind, and the point of the set is
    that its members are blind in different places.
    """

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
