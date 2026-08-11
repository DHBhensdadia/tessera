# Continuous integration

Defined in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml). Around twenty
seconds end to end.

## What runs

| Job | Platform | Checks |
|---|---|---|
| **lint, types, boundaries** | ubuntu-latest | `ruff check` · `ruff format --check` · `mypy --strict` · `lint-imports` |
| **tests** | ubuntu-latest **and** macos-14 | `pytest` with branch coverage, gated at 85 % |

Tests run on both platforms because **both are production targets**: the engine ships
to Linux as a Docker image and to macOS inside the `.app` bundle. A failure on one and
not the other is a real signal, not noise.

## When it runs

```yaml
on:
  push:
  pull_request:
```

Every push on every branch. Pull requests additionally, but **only from forks** —
guarded on each job by:

```yaml
if: >-
  github.event_name == 'push' ||
  github.event.pull_request.head.repo.full_name != github.repository
```

A pull request from a branch in this repository has already fired a push event, so
without that guard every same-repo PR would run the entire suite twice for no extra
signal.

An earlier version triggered only on pushes to `main`, which meant **a feature branch
ran no CI at all** — you could not see a branch go green without opening a pull request
against it. Worth knowing if the triggers are ever narrowed again.

## Two flags worth understanding

**`uv sync --locked`** asserts the lockfile matches `pyproject.toml` and fails if it is
stale, rather than resolving something other than what was committed. It is mutually
exclusive with `UV_FROZEN`, which means the opposite — trust the lockfile without
checking it. Setting both is an error, not a redundancy.

**`concurrency` with `cancel-in-progress`** kills superseded runs when you push again,
so feedback stays fast and the queue does not fill with runs nobody will read.

## Reading a red build

Work down this list; the first match is usually the cause.

| Symptom | Where to look |
|---|---|
| Fails in **under 15 seconds**, all jobs | Setup, not your code — dependency resolution or a workflow syntax error |
| `lint, types, boundaries` only | `ruff`, `mypy`, or a layer violation. Reproduce locally with the same command |
| Contract broken, naming a module | An import crossed an architectural boundary — see [project layout](project-layout.md) |
| One platform only | A genuine portability problem. Path handling and case sensitivity are the usual causes |
| Coverage gate | New code without tests. The threshold is 85 %, in the `pytest` step |

Everything CI runs is runnable locally, and locally it takes three seconds:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports && uv run pytest --cov
```

The one class of failure that cannot be caught locally is the workflow definition
itself — a bad trigger, a wrong `if`, an invalid action version. Those only appear on
GitHub.

## Dependencies

[`dependabot.yml`](../../.github/dependabot.yml) opens PRs weekly for uv dependencies
and monthly for Actions. Minor and patch bumps are **grouped into one PR** so that
major bumps — the ones actually worth reading — stand out instead of being buried.

## Branch protection

`main` blocks force-pushes and deletion, and nothing else. Required status checks are
deliberately **not** enabled: GitHub only applies them to pull requests, which on a
solo project would mean opening a PR to fix a typo. The reasoning is in
[ADR-0015](../adr/0015-solo-git-workflow.md).

The protection that remains is the kind that prevents an unrecoverable accident rather
than a recoverable one — a mistyped `git push --force` can destroy history in a way a
red build never does.
