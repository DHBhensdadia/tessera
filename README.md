# Tessera — university timetable scheduling

[![CI](https://github.com/DHBhensdadia/tessera/actions/workflows/ci.yml/badge.svg)](https://github.com/DHBhensdadia/tessera/actions/workflows/ci.yml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/licence-MIT-green.svg)](LICENSE)

Generate conflict-free university timetables, refine them by hand, and find out *why*
when no valid timetable exists.

## Install

Download the latest `.dmg` from [Releases](https://github.com/DHBhensdadia/tessera/releases)
and drag Tessera to Applications. Apple Silicon, macOS 14 or later. No runtime to
install, no server to configure, no account, and nothing leaves your machine.

Builds are signed but **not yet notarized**, so macOS refuses them on first launch.
Right-click the app and choose Open, or:

```bash
xattr -dr com.apple.quarantine /Applications/Tessera.app
```

> **v0.1.0 is a walking skeleton.** It starts, opens a project, and reports that its
> engine is running — one thin slice through every layer. Data entry, solving and the
> timetable editor arrive in later releases.

> **Status: early development.** The architecture is validated and the repository
> skeleton is in place; features are being built in order. Nothing here is usable yet.

## What it is

A native macOS application for building university course timetables. Enter rooms,
instructors, courses and student groups; a constraint solver produces a conflict-free
schedule optimised against preferences you control; then drag sessions around and watch
conflicts light up before you drop.

The solver is an OR-Tools CP-SAT model driven by a Fix-and-Optimize loop, the family of
approach that won the International Timetabling Competition 2019.

## Planned capabilities

- **Explains infeasibility.** When no valid timetable exists, it names the smallest set
  of constraints that cannot coexist, rather than reporting "no solution found".
- **Pin and re-optimise.** Fix the placements you care about; the solver rebuilds the
  rest around them.
- **Live conflict validation.** Conflicts highlight while dragging, before the drop.
- **Scenario comparison.** Generate several timetables, compare them on gaps, load
  balance and room utilisation, publish one.
- **Exports** to PDF, self-contained HTML, CSV and calendar subscriptions.

Quality is measured, not asserted.

## Benchmark

The solver is run against the 21 ITC-2007 curriculum-based instances, under the competition's
own rules and its own three-hundred-second budget. Every timetable below is checked by an
independently written implementation of the same formulation, which shares no code with the
model that produced it — a disagreement between the two stops the run rather than being
reported.

| | |
|---|---|
| instances solved | **21 / 21** |
| valid CB-CTT solutions | **21 / 21** |
| budget | 300 s wall, one worker, `random_seed = 0` |
| hardware | macOS 15, arm64 · OR-Tools 9.15.6755 |

| instance | penalty | rounds | | instance | penalty | rounds | | instance | penalty | rounds |
|---|---|---|---|---|---|---|---|---|---|---|
| comp01 | 14 | 1768 | | comp08 | 649 | 32 | | comp15 | 223 | 1240 |
| comp02 | 282 | 1140 | | comp09 | 213 | 275 | | comp16 | 255 | 292 |
| comp03 | 221 | 1255 | | comp10 | 1704 | 28 | | comp17 | 450 | 77 |
| comp04 | 127 | 376 | | comp11 | **0** | 1 | | comp18 | 186 | 32 |
| comp05 | 537 | 696 | | comp12 | 531 | 992 | | comp19 | 196 | 873 |
| comp06 | 2986 | 24 | | comp13 | 164 | 252 | | comp20 | 3296 | 28 |
| comp07 | 2697 | 28 | | comp14 | 163 | 392 | | comp21 | 278 | 632 |

**No comparison against published best-known figures is shown, and that is deliberate.** The
canonical results portal for this benchmark is gone — one host no longer resolves, another
redirects to itself, and the competition's own results page is a 404 — so the values this
project holds cannot be traced to a source. They are in
[`benchmarks/best-known.toml`](benchmarks/best-known.toml) marked `verified = false`, and the
harness prints its own absence rather than a comparison nobody has checked.

**What the table does say is where the solver is weak, and why.** The `rounds` column is the
number of Fix-and-Optimize iterations each instance fitted into its budget, and it predicts the
result almost perfectly: `comp01` fitted 1,768 rounds, `comp06` fitted 24, and the difference
between them is a factor of eighty in how long one round takes to build. Every instance below a
hundred rounds scores badly and every instance above two hundred scores respectably. The
bottleneck is not the search — it is rebuilding a sub-model in Python once per round, which is
[a known cost](docs/internals/benchmarking.md) with a fix already scoped.

`comp11` is solved to its optimum of zero, and `comp01` comes within nine points.

How the benchmark works, what it relaxes and what it refuses to claim:
[docs/internals/benchmarking.md](docs/internals/benchmarking.md).

## Architecture

A thin SwiftUI client talks over loopback to a Python engine bundled inside the app as a
sidecar process. The engine is the entire product and ships three ways from one
codebase — inside the macOS app, as a Docker image, and as a command-line tool — so it
is useful on Linux and Windows even though the editor is macOS-only.

```
tessera/
├── domain/       pure model and constraint validation, no framework imports
├── solver/       CP-SAT model and Fix-and-Optimize search
├── repository/   persistence
├── api/          HTTP surface
├── export/       PDF, HTML, CSV, ICS
├── importers/    spreadsheets and competition formats
└── cli/          command line and benchmark runner
```

Architectural boundaries between these are enforced in CI, not by convention. Decisions
and their reasoning are recorded in [`docs/adr/`](docs/adr/).

## How far the model generalises

Tessera's data model is measured against the 36 published
[ITC-2019](https://www.itc2019.org/) instances, and the result is written down rather than
claimed: [**docs/fidelity/itc-2019.md**](docs/fidelity/itc-2019.md) says, per instance, what
was carried, what was approximated and what was dropped.

**None of the 36 imports without loss.** The report is generated by the same code that
performs the import and regenerated in the test suite, so it cannot describe an importer other
than the one that runs.

The same is done for [ITC-2007](https://www.eeecs.qub.ac.uk/itc2007/), whose 21 curriculum-based
instances are real University of Udine timetables:
[**docs/fidelity/itc-2007.md**](docs/fidelity/itc-2007.md). There the teaching structure crosses
intact — **19 of 21 are solved**, each verified by the validator — and the report says plainly
where Tessera's stricter rules refuse a timetable a university actually ran.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13.

```bash
uv sync
uv run pytest
uv run ruff check
uv run mypy
uv run lint-imports
```

### Benchmark instances

Tests marked `benchmark` read the 36 published [ITC-2019](https://www.itc2019.org/) instances
and are skipped unless you point them at a copy:

```bash
TESSERA_ITC_INSTANCES=/path/to/Instances \
TESSERA_ITC2007_INSTANCES=/path/to/ITC-2007 \
    uv run pytest -m benchmark
```

The full set is not redistributed here — registration on itc2019.org is required. Two small
instances are vendored under `tests/importers/itc/fixtures/` so the parser's own tests need no
download. `scripts/itc-instances.sha256` records the SHA-256 of all 36, so a corrupted or
re-issued file is caught rather than silently parsed:

```bash
cd /path/to/Instances && shasum -a 256 -c /path/to/scripts/itc-instances.sha256
```

## Licence

MIT — see [LICENSE](LICENSE).
