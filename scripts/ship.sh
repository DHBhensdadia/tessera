#!/bin/bash
# Push, then wait for CI and report what it actually said.
#
# This exists because "CI green" was reported three times when the final state of main
# was red. The cause was ordering, not carelessness: gates ran before the code commits,
# CI was checked after those, and then a documentation commit went out afterwards and
# was never verified by anything. Documentation is not exempt — ruff formats fenced
# Python inside markdown, and that is precisely what broke.
#
# So: gates before every push, CI checked after the *last* one.
#
#   ./scripts/ship.sh
set -uo pipefail

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty — commit or stash first"
    git status --short | sed 's/^/  /'
    exit 1
fi

echo "==> gates"
if ! ./scripts/check.sh; then
    echo
    echo "not pushing"
    exit 1
fi

echo
echo "==> push"
git push origin "$(git rev-parse --abbrev-ref HEAD)" || exit 1

echo
echo "==> waiting for CI on the commit just pushed"
SHA=$(git rev-parse HEAD)
sleep 20

for _ in $(seq 1 60); do
    RUN=$(gh run list --workflow=CI --limit 20 \
            --json databaseId,headSha,status,conclusion \
            --jq "[.[] | select(.headSha == \"$SHA\")] | first" 2>/dev/null)
    [ -n "$RUN" ] && [ "$(echo "$RUN" | jq -r .status)" = "completed" ] && break
    sleep 10
done

if [ -z "${RUN:-}" ] || [ "$RUN" = "null" ]; then
    echo "  no CI run found for $SHA — check manually"
    exit 1
fi

gh run view "$(echo "$RUN" | jq -r .databaseId)" \
    --json jobs -q '.jobs[] | "  \(.name): \(.conclusion)"'

if [ "$(echo "$RUN" | jq -r .conclusion)" = "success" ]; then
    echo
    echo "green on $(git rev-parse --short HEAD)"
else
    echo
    echo "RED — the pushed commit is not green"
    exit 1
fi
