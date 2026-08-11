# Project layout

## The shape

```
tessera/            the engine — this is the entire product
├── domain/         entities and the constraint validator
├── solver/         CP-SAT model and the Fix-and-Optimize loop
├── repository/     persistence (SQLAlchemy, Alembic)
├── api/            HTTP surface (FastAPI, SSE)
├── export/         PDF, HTML, CSV, ICS
├── importers/      CSV, Excel, ITC XML
└── cli/            command-line entry point

client/             SwiftUI macOS app — renders and edits, owns no business logic
tests/              mirrors the package layout
benchmarks/         ITC instances and the benchmark harness
docs/               ADRs, internals, and the published documentation site
```

The Swift client talks to the engine over loopback HTTP. The engine also ships as a
Docker image and a CLI, so it must never depend on the client existing —
see [ADR-0001](../adr/0001-engine-client-sidecar.md).

The package is `tessera/` rather than `engine/` so imports read `tessera.domain` and
the top-level module matches the distribution name on PyPI, which is
`tessera-timetable`.

## The layers

Direction of permitted dependency, top to bottom. **Nothing beneath may import
anything above it.**

```
cli · api                  transport and entry points
export · importers         format translation
solver                     optimisation
repository                 persistence
domain                     entities, rules, validation   ← depends on nothing
```

`domain/` is the asset. It has no framework imports at all — no FastAPI, no SQLAlchemy,
no OR-Tools. That is what lets the model and the rules survive a change of web
framework, database, or even of the desktop platform. Every other decision in the
project is downstream of protecting it ([ADR-0003](../adr/0003-framework-free-domain.md)).

One rule matters more than the rest: **the constraint validator is written once, in
`domain/`, and used by both the solver and the UI.** If the UI ever decided legality
for itself, its logic would drift from the solver's and produce bugs that reproduce
only on someone else's data ([ADR-0004](../adr/0004-one-validator.md)).

## How the layers are enforced

Conventions erode one convenient import at a time, so these are checked mechanically
and a violation fails the build.

**`import-linter`**, configured in `pyproject.toml` under `[tool.importlinter]`, holds
five contracts:

| Contract | Effect |
|---|---|
| Layers | `api` → `repository` → `domain`, never upward |
| Domain is framework-free | `domain/` may not import fastapi, starlette, sqlalchemy, alembic, ortools, reportlab or jinja2 |
| Solver knows nothing of transport or storage | no fastapi, starlette, sqlalchemy, alembic |
| Repository knows nothing of transport or solving | no fastapi, starlette, ortools |
| Exporters and importers are standalone | no fastapi, starlette, sqlalchemy, ortools |

`include_external_packages = true` is required, because those contracts name
third-party packages rather than only internal modules.

**`tests/test_project_structure.py`** repeats the most important check at runtime by
walking the source tree for banned imports. That looks redundant and is deliberate: it
catches a violation even if the import-linter configuration itself is broken or
removed, and it names the offending file and line directly.

Both were verified to *reject* a violation rather than merely to pass — adding
`import sqlalchemy` to `domain/` fails both. A guard that has never been seen to fail
is not known to work.

## Tooling

Everything is driven by **uv**. `uv sync --locked` installs exactly what `uv.lock`
records and fails if the lockfile is stale, rather than silently resolving something
else.

| Tool | Role |
|---|---|
| `ruff` | Lint and format. Line length 100, `ANN` requires annotations, relative imports banned |
| `mypy --strict` | Type checking over `tessera/` and `tests/` |
| `import-linter` | The layer contracts above |
| `pytest` | Tests, with branch coverage; CI gates at 85 % |
| `pre-commit` | Runs the above before a commit is created |

Run the whole set exactly as CI does:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports && uv run pytest --cov
```

Three seconds. Running it before pushing is what keeps `main` green — CI is the
backstop, not the gate.

## Version

The version lives once, in `pyproject.toml`, and `tessera.__version__` is asserted
against it by a test. Two places that can disagree eventually will.
