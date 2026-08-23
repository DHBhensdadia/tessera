#!/bin/bash
# Every gate CI runs, locally, reporting pass or fail by exit code.
#
# This exists because reading the tail of a command's output is not a check. Three tests
# failed for an entire phase while `pytest ... | grep -E 'passed|failed|Required'`
# reported green: pytest writes `FAILED` in capitals, and the coverage table pushed the
# summary line out of the tail being read. Exit code 1, reported as success.
#
# A check that cannot fail is worse than no check, because it is trusted.
#
#   ./scripts/check.sh
set -uo pipefail

cd "$(dirname "$0")/.."
FAILED=0

run() {  # run <name> <command...>
    local name="$1"; shift
    if output=$("$@" 2>&1); then
        printf '  ok    %s\n' "$name"
    else
        printf '  FAIL  %s\n' "$name"
        printf '%s\n' "$output" | tail -25 | sed 's/^/        /'
        FAILED=$((FAILED + 1))
    fi
}

echo "running the gates"
# First, because it is the one gate that can fail in CI while every other passes here.
# CI installs with `uv sync --locked`, which refuses a lockfile that does not match
# pyproject.toml. `uv run` quietly re-locks instead — so bumping the version left the
# lockfile correct on disk, uncommitted, and green locally while CI went red on all three
# jobs. Sibling of Decision #44: a local check that cannot see a failure CI will hit is
# the kind of green that gets trusted.
run "lockfile matches pyproject"  uv lock --check
# The OpenAPI document exists twice: `docs/` is the one people read, and the copy inside
# the Swift package is the one the generator plugin reads, because SwiftPM plugins are
# sandboxed to their package directory. `tessera-openapi` writes both in one function —
# this is the gate that says so, because "two copies that must agree" has been the shape of
# enough defects in this project to stop being a convention.
run "openapi copies agree"    cmp -s docs/openapi.json client/Sources/EngineClient/openapi.json
run "ruff (lint)"             uv run ruff check .
run "ruff (format)"           uv run ruff format --check .
run "mypy (strict)"           uv run mypy
run "import boundaries"       uv run lint-imports
run "pytest + coverage gate"  uv run pytest --cov --cov-fail-under=85 -q
# The client used to be compiled only when a tag was pushed, which meant a broken client
# was discovered at release time — the worst moment and the one Decision #49 was written
# about for the Python half. `swift build` covers all three targets, including the
# gallery, so a component the gallery no longer matches fails here rather than later.
run "swift (build)"           swift build --package-path client
run "swift (test)"            swift test --package-path client

echo
if [ "$FAILED" -eq 0 ]; then
    echo "all gates passed"
else
    echo "$FAILED gate(s) failed"
    exit 1
fi
