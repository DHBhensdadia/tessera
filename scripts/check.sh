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
run "ruff (lint)"             uv run ruff check .
run "ruff (format)"           uv run ruff format --check .
run "mypy (strict)"           uv run mypy
run "import boundaries"       uv run lint-imports
run "pytest + coverage gate"  uv run pytest --cov --cov-fail-under=85 -q

echo
if [ "$FAILED" -eq 0 ]; then
    echo "all gates passed"
else
    echo "$FAILED gate(s) failed"
    exit 1
fi
