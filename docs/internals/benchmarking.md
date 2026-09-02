# Benchmarking

How this project finds out whether its solver is any good, against numbers it did not choose.

Everything here is in `tessera/bench/`, `tessera/cli/bench.py` and `benchmarks/`. It measures
the solver; it is not part of it, and `import-linter` keeps the product's logic unable to import
any of it.

## The shape of it

```
comp02.ctt ──► importers.cbctt.read ──► Competition ──► solver.solve ──► a timetable
                       │                    │                                │
                       │           the four soft costs                       │
                       │           as CP-SAT arithmetic                      │
                       │                                                     │
                       └────► importers.cbctt.score.check ◄──────────────────┘
                              the second reading, which agrees or the run stops
```

## 1. Why the benchmark has its own objective

P5 asks for a comparison against published best-known results. There are three ways to produce a
number to set beside 24 for `comp02`, and two of them are dishonest.

Scoring a mapped instance with Tessera's own validator gives **0 on all 21**: 4.2's importer
carries none of CB-CTT's four soft constraints, so the term prices nothing and every solver
reports a perfect score. Attaching Tessera's default preferences instead gives a real number for
a *different objective* — reproducible, scientific-looking, and not comparable with anybody's.

So the benchmark computes the published metric. `tessera/bench/cbctt.py` writes CB-CTT's four
soft costs as arithmetic over the same CP-SAT model the product builds:

| | weight | counted as |
|---|---|---|
| `RoomCapacity` | 1 | per student above the room's capacity, per lecture |
| `MinimumWorkingDays` | 5 | per day below the course's declared minimum |
| `CurriculumCompactness` | 2 | per lecture with no adjacent lecture of its curriculum that day |
| `RoomStability` | 1 | per room a course uses beyond the first |

Two of those are counted the way a paraphrase gets wrong. **Compactness is per lecture, not per
gap** — a curriculum at periods 1 and 3 has two isolated lectures, four points, not one gap.
**Stability is per course, not per lecture** — three rooms cost two, however many lectures.

**The search is the product; the objective is the problem statement.** `solve()` takes a cost
model, so the Fix-and-Optimize loop that ships is the one being measured, not a copy written for
the occasion. A benchmark measuring code no user runs would be the same species of dishonesty as
scoring it with the wrong objective.

## 2. Three things are true here that are false in the product

- **Capacity is priced, not required.** A room seating sixty seats sixty in Tessera, and that is
  a hard invariant kept knowingly: `comp01` needs 64 lectures in rooms for 31 and the week holds
  60 such room-periods, so Tessera refuses a timetable Udine actually ran. CB-CTT prices a
  standing student at one point, so under its rules `comp01` is an ordinary instance. The
  relaxation is a `Formulation` flag and `tessera.bench` is the only place allowed to set it.
- **Unavailability is per course.** Tessera blocks an *instructor*, so 4.2 carries a course's
  unavailability only where its teacher teaches nothing else — 2,785 rows dropped across the
  suite. `Competition.enforce` writes them back from the instance, which is why a benchmark
  answer is a valid CB-CTT solution where a mapped one is not.
- **The term carries no Tessera preferences at all.** Leaving the defaults on would optimise a
  blend of two rulebooks and report the result as a CB-CTT score.

## 3. The checker is a second reading, and it is proven by being made to fail

`tessera/importers/cbctt/score.py` computes the same four costs from the parsed instance and a
solution, sharing nothing with the model above — `import-linter` forbids `tessera.importers` from
importing `ortools`, so the independence is a build failure rather than a promise.

Every benchmark row is scored twice and **a disagreement stops the run**. That agreement held on
all 21 instances, component for component.

A checker is not verified by passing. Every run in the Phase 0.1 sweep reported feasible, and one
that always answered "no violations" would have looked identical. So `tests/importers/cbctt/`
breaks it twelve ways — one per hard rule and per soft cost — and each mutation must name the
rule it broke.

## 4. The budget is the measurement

At the competition's own three hundred seconds, a default `Budget` spends every one of them on a
single unrestricted solve: `_left()` hands the whole-model attempt whatever the clock has, so the
outer loop never runs. Switching that attempt off is not the answer either. Penalties at 300 s:

| | whole attempt only | rounds only | 60 s share, then rounds |
|---|---|---|---|
| `comp01` | 23 | 506 | **21** |
| `comp02` | 2961 | 222 | **240** |
| `comp05` | 856 | 712 | **537** |
| `comp11` | **0**, proven | 8 | **0**, proven, in 38 s |

Neither pure mode wins. The unrestricted attempt is decisive where CP-SAT can make progress on
the whole model and hopeless where it cannot, and `whole_model_ceiling` cannot decide it because
it reads the model's *size* — every CB-CTT model is small enough to attempt. So `Budget`'s
`whole_seconds` bounds it in **time**, and a fifth of the budget beats both pure modes.

## 5. What the gate checks, and what it will not do

Three verdicts (`tessera/bench/results.py`), because *the score got worse* misses two real
regressions:

| | |
|---|---|
| **quality** | a penalty above the baseline — exact, because the score travels between architectures unchanged |
| **coverage** | an instance that was solved and is not, or one that stopped being measured at all |
| **effort** | the same answer for more than 1 % more searching — seven times the largest difference two architectures showed |

The thresholds are measured rather than chosen: on the same commit and seed, `macos-14` and
`ubuntu-latest` return the **same penalty**, a **different timetable**, and a
`deterministic_time` **0.133 %** apart. A result file therefore records the OR-Tools version, the
Python version and the machine — a benchmark result is a claim about a solver *and* a machine.

**Nothing here writes the baseline.** CI reads it and reports; updating it is a commit somebody
approved, which is also the moment somebody looks at whether the numbers were meant to move.

## 6. Where the instances come from

They are **not in this repository**. The 21 `.ctt` files are somebody else's data with no
declared licence, and absence of one is not permission. `scripts/itc2007.py` fetches them and
verifies each against `scripts/itc2007-instances.sha256`, committed since 4.2 — which is what
makes fetching as trustworthy as committing.

Two failures, reported as the different facts they are: a host that cannot be reached exits `75`
and the caller skips, saying why; a file that hashes wrong exits `1` and names both digests,
because a re-issued instance voids every number attached to it.

## 7. What the numbers do not claim

The best-known column is **withheld**. The canonical CB-CTT portal is gone — `satt.diegm.uniud.it`
does not resolve, `tabu.diegm.uniud.it/ctt/` redirects to itself, the competition's results page
is a 404 — and its successor at `opthub.uniud.it` is a single-page application. The values this
project holds are the ones Phase 0.1 used, and 0.1 did not record where it got them. They sit in
`benchmarks/best-known.toml` with `verified = false`, and `tessera bench` prints its own absence
rather than a comparison nobody has checked.

**A score at or below a published figure stops the run.** Not a celebration — an alarm. The
likelier cause is a defect in the objective or the checker, and this project has already shipped
one number that was too good and looked entirely sound.

## 8. Where to look when something is wrong

| Symptom | Look at |
|---|---|
| the objective and the checker disagree | `bench/cbctt.py` against `importers/cbctt/score.py` — one of the two readings is wrong and neither number is usable |
| a benchmark answer is rejected by the checker | `Competition.enforce` — per-course unavailability is the rule the import cannot carry |
| the loop never runs | `Budget.whole_seconds` is `None`, so the unrestricted attempt has the whole clock |
| `comp01` solves here and not in the product | correct — capacity is priced here and required there |
| a score changed and nothing else did | the OR-Tools version in the results file |
