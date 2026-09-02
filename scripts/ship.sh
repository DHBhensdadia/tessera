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

# Thirty minutes. The old window was ten, and CI has been taking eleven to twelve for
# months — so the loop was falling out *before the run finished*, keeping a snapshot whose
# conclusion was still null, and reporting that as red. It printed a job list fetched
# afterwards, by which time everything really had passed, so the output contradicted its own
# verdict: every job "success", followed by "RED".
#
# That is #49's failure with the sign flipped, and it is not the harmless direction it looks
# like. A gate that cries wolf is a gate people learn to push past, and the one time it is
# right nobody will read it.
DEADLINE=180

for _ in $(seq 1 "$DEADLINE"); do
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

STATUS=$(echo "$RUN" | jq -r .status)
CONCLUSION=$(echo "$RUN" | jq -r .conclusion)

gh run view "$(echo "$RUN" | jq -r .databaseId)" \
    --json jobs -q '.jobs[] | "  \(.name): \(.conclusion)"'

echo
# "Did not finish" and "finished red" are different facts and used to print the same
# sentence. Saying which one happened is the whole repair: one means look at the run, the
# other means wait for it.
if [ "$STATUS" != "completed" ]; then
    echo "CI has not finished after $((DEADLINE / 6)) minutes — status $STATUS, nothing is claimed"
    echo "  gh run watch \$(gh run list --workflow=CI --limit 20 \\"
    echo "      --json databaseId,headSha --jq '[.[] | select(.headSha == \"$SHA\")] | first.databaseId')"
    exit 1
fi

if [ "$CONCLUSION" = "success" ]; then
    echo "green on $(git rev-parse --short HEAD)"
else
    echo "RED — the pushed commit finished $CONCLUSION"
    exit 1
fi
