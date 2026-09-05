#!/bin/bash
# Push the phase branch, wait for CI, and only then fast-forward main.
#
# This exists because "CI green" was reported three times when the final state of main
# was red. The cause was ordering, not carelessness: gates ran before the code commits,
# CI was checked after those, and then a documentation commit went out afterwards and
# was never verified by anything. Documentation is not exempt — ruff formats fenced
# Python inside markdown, and that is precisely what broke.
#
# The order changed again in 4.5, for a failure one step further out. The commits were
# merged into main and pushed, and *then* CI ran and went red on `ubuntu-latest` alone —
# so main sat broken for twenty-seven minutes while the fix was written. Reading CI after
# the merge tells you what you have already published. Reading it before is the same work
# in an order where the answer can still change something.
#
# It is also what makes GitHub's "require status checks" usable here. Those checks admit a
# direct push only when the commit already passed on another ref; a commit that has never
# left the machine has nothing to admit.
#
#   ./scripts/ship.sh          — run it from the phase branch
set -uo pipefail

cd "$(dirname "$0")/.."

BRANCH=$(git rev-parse --abbrev-ref HEAD)
DEADLINE=180

if [ "$BRANCH" = "main" ]; then
    cat <<'WHY'
run this from the phase branch, not from main.

The point of the change is that CI sees the commits before main does, and there is no way
to arrange that once they are already on main. Undo the merge and try again:

  git reset --hard origin/main       # discards nothing: the commits are on the branch
  git checkout <phase branch>
  ./scripts/ship.sh
WHY
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty — commit or stash first"
    git status --short | sed 's/^/  /'
    exit 1
fi

echo "==> where things stand"
git fetch --quiet origin || exit 1

if [ "$(git rev-parse main)" != "$(git rev-parse origin/main)" ]; then
    echo "  local main and origin/main differ — reconcile before shipping"
    echo "    local  $(git rev-parse --short main)"
    echo "    remote $(git rev-parse --short origin/main)"
    exit 1
fi

# A merge that is not a fast-forward would put a merge commit on main, and main has had
# none in 275 commits. Refusing here says so before the gates spend ten minutes.
if ! git merge-base --is-ancestor main "$BRANCH"; then
    echo "  $BRANCH is not ahead of main — rebase it, or main has moved on"
    exit 1
fi

AHEAD=$(git rev-list --count main.."$BRANCH")
echo "  $BRANCH is $AHEAD commit(s) ahead of main, fast-forward clean"

echo
echo "==> gates"
if ! ./scripts/check.sh; then
    echo
    echo "not pushing"
    exit 1
fi

echo
echo "==> push $BRANCH"
git push --set-upstream origin "$BRANCH" || exit 1

echo
echo "==> waiting for CI on the commit about to become main"
SHA=$(git rev-parse HEAD)
sleep 20

# Thirty minutes. The old window was ten, and CI has been taking eleven to twelve for
# months — so the loop was falling out *before the run finished*, keeping a snapshot whose
# conclusion was still null, and reporting that as red. It printed a job list fetched
# afterwards, by which time everything really had passed, so the output contradicted its own
# verdict: every job "success", followed by "RED".
#
# That is the failure this script exists to prevent with the sign flipped, and it is not the
# harmless direction it looks like. A gate that cries wolf is a gate people learn to push
# past, and the one time it is right nobody will read it.
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
    echo "  main is untouched. Watch it, then run this again:"
    echo "    gh run watch \$(gh run list --workflow=CI --limit 20 \\"
    echo "        --json databaseId,headSha --jq '[.[] | select(.headSha == \"$SHA\")] | first.databaseId')"
    exit 1
fi

if [ "$CONCLUSION" != "success" ]; then
    echo "RED — $BRANCH finished $CONCLUSION, and main is untouched"
    exit 1
fi

echo "green on $(git rev-parse --short HEAD) — merging"
echo
echo "==> main"
git checkout --quiet main || exit 1
if ! git merge --ff-only "$BRANCH"; then
    echo "  the merge was not a fast-forward, which should have been caught above"
    git checkout --quiet "$BRANCH"
    exit 1
fi

if ! git push origin main; then
    echo
    echo "  main moved locally but the push failed. Nothing is lost — the commits are also"
    echo "  on $BRANCH, and 'git reset --hard origin/main' puts local main back."
    exit 1
fi

echo
echo "green on $(git rev-parse --short HEAD) as $BRANCH, and main is that commit"

# The branch being green is not main being green, and reading it as though it were is how
# main sat red after 4.8 part 1 while the report said otherwise. Pushing to main starts a
# *second* run of the same SHA, and a test that is not deterministic can fail on either one.
# ship.sh cannot prevent that — it can refuse to let it go unnoticed.
echo
echo "==> main's own run of $SHA"
for _ in $(seq 1 "$DEADLINE"); do
    MAIN_RUN=$(gh run list --workflow=CI --branch main --limit 20 \
                 --json databaseId,headSha,status,conclusion \
                 --jq "[.[] | select(.headSha == \"$SHA\")] | first" 2>/dev/null)
    [ -n "$MAIN_RUN" ] && [ "$(echo "$MAIN_RUN" | jq -r .status)" = "completed" ] && break
    sleep 10
done

if [ -z "${MAIN_RUN:-}" ] || [ "$MAIN_RUN" = "null" ]; then
    echo "  no run found on main for $SHA yet — main is pushed; watch it before claiming green"
elif [ "$(echo "$MAIN_RUN" | jq -r .status)" != "completed" ]; then
    echo "  still running after $((DEADLINE / 6)) minutes — main is pushed and NOT yet green"
elif [ "$(echo "$MAIN_RUN" | jq -r .conclusion)" != "success" ]; then
    gh run view "$(echo "$MAIN_RUN" | jq -r .databaseId)" \
        --json jobs -q '.jobs[] | "  \(.name): \(.conclusion)"'
    echo
    echo "  MAIN IS RED on $SHA, even though $BRANCH was green on it."
    echo "  The same commit ran twice and disagreed, which means something is not"
    echo "  deterministic. Fix that before shipping anything else."
    exit 1
else
    echo "  green on main too"
fi

echo
echo "  the branch is still on the remote; delete it when you are done with it:"
echo "    git push origin --delete $BRANCH"
