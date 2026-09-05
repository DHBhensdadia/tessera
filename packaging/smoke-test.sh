#!/bin/bash
# End-to-end verification of a built .dmg.
#
# This is the real guard for behaviour that only appears in a shipped bundle. The unit
# tests spawn the engine from Python and pass whether or not the app leaks a process;
# the orphan regression that prompted this script reproduced solely with the SwiftUI
# application as parent, which means it is only catchable here.
#
#   ./packaging/build.sh && ./packaging/smoke-test.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DMG=$(ls "$ROOT"/packaging/out/Tessera-*-arm64.dmg 2>/dev/null | head -1)
STAGE=$(mktemp -d)
FAILURES=0

cleanup() {
    pkill -9 -f "$STAGE/Tessera.app" 2>/dev/null || true
    rm -rf "$STAGE"
}
trap cleanup EXIT

check() {  # check <description> <expected> <actual>
    if [ "$2" = "$3" ]; then
        echo "  ok    $1"
    else
        echo "  FAIL  $1 — expected '$2', got '$3'"
        FAILURES=$((FAILURES + 1))
    fi
}

[ -n "$DMG" ] || { echo "no .dmg found; run packaging/build.sh first"; exit 1; }
echo "testing $(basename "$DMG")"

echo "==> install from the disk image"
MOUNT=$(hdiutil attach "$DMG" -nobrowse -readonly | grep Volumes | awk '{print $NF}')
cp -R "$MOUNT/Tessera.app" "$STAGE/"
hdiutil detach "$MOUNT" -quiet
check "app copied out of the image" "yes" "$([ -d "$STAGE/Tessera.app" ] && echo yes || echo no)"

# Gatekeeper only engages on quarantined files, so testing a locally built app tests
# nothing. Setting the flag by hand is what makes this resemble a real download.
xattr -w com.apple.quarantine "0083;00000000;Safari;" "$STAGE/Tessera.app"
GATE=$(spctl --assess --type execute "$STAGE/Tessera.app" 2>&1 | sed 's/.*: //' || true)
check "unsigned build is refused by Gatekeeper (expected until notarization)" "rejected" "$GATE"
xattr -dr com.apple.quarantine "$STAGE/Tessera.app"

check "signature is valid" "yes" \
    "$(codesign --verify --deep --strict "$STAGE/Tessera.app" >/dev/null 2>&1 && echo yes || echo no)"

ENGINE_BIN="$STAGE/Tessera.app/Contents/Resources/engine/tessera-engine"

echo "==> launch"
pkill -9 -f 'tessera-engine' 2>/dev/null || true

# Open a *project*, not just the application.
#
# This used to be a bare `open` of the app, and it saw an engine because the application
# was reopening projects nobody had asked for — one engine per stale window. That is the
# behaviour 3.4b removed, and this check was quietly depending on it: a plain launch now
# correctly starts nothing, and the test failed for the right reason.
#
# Asking for a project is the better check anyway. It proves the shipped engine binary
# runs *for the thing a user does*, rather than proving something started.
# Waited on properly: the directory appears before the schema is in it, and an app
# opening a half-made project refuses it and starts nothing — which would look exactly
# like the failure this check is for.
SEED_HANDSHAKE=$(mktemp)
"$ENGINE_BIN" --project "$STAGE/launch.tessera" >"$SEED_HANDSHAKE" 2>/dev/null &
SEED_PID=$!
for _ in $(seq 1 60); do [ -s "$SEED_HANDSHAKE" ] && break; sleep 0.25; done
kill "$SEED_PID" 2>/dev/null || true
wait "$SEED_PID" 2>/dev/null || true
check "a project could be made for the launch check" "yes" \
    "$([ -s "$SEED_HANDSHAKE" ] && echo yes || echo no)"

open -n "$STAGE/Tessera.app" --args --open "$STAGE/launch.tessera"
sleep 20

APP_PID=$(pgrep -f "$STAGE/Tessera.app/Contents/MacOS/Tessera" | head -1 || true)
ENGINE_PID=$(pgrep -f "$STAGE/Tessera.app/Contents/Resources/engine/tessera-engine" | head -1 || true)
check "application is running" "yes" "$([ -n "$APP_PID" ] && echo yes || echo no)"
check "engine was spawned" "yes" "$([ -n "$ENGINE_PID" ] && echo yes || echo no)"

if [ -n "$ENGINE_PID" ]; then
    PORT=$(lsof -aPi -p "$ENGINE_PID" 2>/dev/null | grep LISTEN | sed -E 's/.*:([0-9]+) .*/\1/' | head -1)
    check "engine is listening" "yes" "$([ -n "$PORT" ] && echo yes || echo no)"
    check "bound to loopback only" "yes" \
        "$(lsof -aPi -p "$ENGINE_PID" 2>/dev/null | grep LISTEN | grep -q 'localhost:' && echo yes || echo no)"
    check "unauthenticated request refused" "401" \
        "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" || true)"
fi

echo "==> the console renders from the shipped bundle"
# Run the bundled engine directly rather than through the app, because the handshake —
# and therefore the token — goes to whoever started it. Without the token every console
# request is a 401, which would prove the route exists and nothing about whether the
# templates travelled.
#
# This is the check that catches the whole class of PyInstaller data bugs: templates are
# read from disk at render time, so a spec that forgets them builds cleanly, passes every
# unit test, and serves a stack trace to the first person who downloads the app.
HANDSHAKE=$(mktemp)
"$ENGINE_BIN" --project "$STAGE/smoke.tessera" >"$HANDSHAKE" 2>/dev/null &
DIRECT_PID=$!
for _ in $(seq 1 40); do [ -s "$HANDSHAKE" ] && break; sleep 0.25; done

DIRECT_PORT=$(sed -n '1p' "$HANDSHAKE" | sed -E 's/.*"port": *([0-9]+).*/\1/')
DIRECT_TOKEN=$(sed -n '1p' "$HANDSHAKE" | sed -E 's/.*"token": *"([^"]+)".*/\1/')
check "engine announces a port when run directly" "yes" \
    "$([ -n "$DIRECT_PORT" ] && echo yes || echo no)"

if [ -n "$DIRECT_PORT" ]; then
    CONSOLE=$(curl -s -H "x-tessera-token: $DIRECT_TOKEN" \
        "http://127.0.0.1:$DIRECT_PORT/console/rooms" || true)
    check "console page renders (templates were bundled)" "yes" \
        "$(echo "$CONSOLE" | grep -q "Tessera console\|<h1>Rooms</h1>" && echo yes || echo no)"
    check "console refuses a foreign Host header" "403" \
        "$(curl -s -o /dev/null -w '%{http_code}' -H "Host: evil.example" \
            -H "x-tessera-token: $DIRECT_TOKEN" \
            "http://127.0.0.1:$DIRECT_PORT/console/rooms" || true)"
    # pandas is the largest dependency this project freezes, and the import path is the
    # only thing that uses it. A missing hidden import is invisible until the first person
    # to download the app tries to upload a spreadsheet.
    IMPORTED=$(printf 'Room,Seats\nLH-901,42\n' | curl -s -X POST \
        -H "x-tessera-token: $DIRECT_TOKEN" \
        -F "file=@-;filename=rooms.csv;type=text/csv" \
        "http://127.0.0.1:$DIRECT_PORT/api/v1/imports/spreadsheet?term_id=1" || true)
    # OR-Tools is now reachable from the engine's entry point, which is what took the disk
    # image from 47 to 68 MB. A frozen build that cannot solve is a build that does nothing a
    # person downloaded it for, and the failure would be a ModuleNotFoundError nobody sees
    # until the first Generate. sse-starlette rides along: were it missing, the stream would
    # fail rather than reach `done`.
    #
    # The term is seeded with the repository's own Python rather than through the API, which
    # would be a dozen curl calls. That is fair here — this script runs from the repo, right
    # after `build.sh`, and what is under test is the *frozen engine*, not the seeding.
    check "a term with teaching in it could be seeded" "yes" \
        "$(cd "$ROOT" && uv run python packaging/seed_for_smoke.py "$STAGE/solve.tessera" \
            >/dev/null 2>&1 && echo yes || echo no)"

    SOLVE_HANDSHAKE="$STAGE/solve-handshake.txt"
    "$ENGINE_BIN" --project "$STAGE/solve.tessera" > "$SOLVE_HANDSHAKE" 2>/dev/null &
    SOLVE_PID=$!
    for _ in $(seq 1 120); do [ -s "$SOLVE_HANDSHAKE" ] && break; sleep 0.25; done
    SOLVE_PORT=$(sed -n '1p' "$SOLVE_HANDSHAKE" | sed -E 's/.*"port": *([0-9]+).*/\1/')
    SOLVE_TOKEN=$(sed -n '1p' "$SOLVE_HANDSHAKE" | sed -E 's/.*"token": *"([^"]+)".*/\1/')

    if [ -n "$SOLVE_PORT" ]; then
        SOLVE_API="http://127.0.0.1:$SOLVE_PORT/api/v1"
        check "the pre-flight answers from the shipped bundle (OR-Tools was frozen in)" "200" \
            "$(curl -s -o /dev/null -w '%{http_code}' -X POST \
                -H "x-tessera-token: $SOLVE_TOKEN" "$SOLVE_API/terms/1/preflight" || true)"

        SOLVE_JOB=$(curl -s -X POST -H "x-tessera-token: $SOLVE_TOKEN" \
            -H 'content-type: application/json' -d '{"time_budget_seconds": 20}' \
            "$SOLVE_API/terms/1/solve" | grep -o '"job_id":"[^"]*"' | cut -d'"' -f4)
        check "a solve starts in the shipped bundle" "yes" \
            "$([ -n "$SOLVE_JOB" ] && echo yes || echo no)"

        if [ -n "$SOLVE_JOB" ]; then
            check "the progress stream runs to done (sse-starlette was frozen in)" "event: done" \
                "$(curl -sN --max-time 40 -H "x-tessera-token: $SOLVE_TOKEN" \
                    "$SOLVE_API/solve/$SOLVE_JOB/stream" \
                    | tr -d '\r' | grep -m 1 '^event: done' || true)"
            check "the solve produced a timetable" "1" \
                "$(curl -s -H "x-tessera-token: $SOLVE_TOKEN" \
                    "$SOLVE_API/terms/1/timetables" | grep -o '"total":[0-9]*' | cut -d: -f2)"
        fi

        # The same journey through the console, which the API checks above cannot stand in
        # for. Six templates and one script were added in 4.8 and every one of them is read
        # from disk at render time — a spec that missed `solve/` or `timetables/` builds
        # cleanly, passes every unit test, and serves a stack trace to the first person who
        # presses Generate. #66's class of bug, in the places 4.8 put new ones.
        echo "==> and the console's own way to a timetable"
        SOLVE_CONSOLE="http://127.0.0.1:$SOLVE_PORT/console"
        check "the generate form renders from the bundle" "yes" \
            "$(curl -s -H "x-tessera-token: $SOLVE_TOKEN" "$SOLVE_CONSOLE/terms/1/timetables" \
                | grep -q 'name="time_budget_seconds"' && echo yes || echo no)"

        CONSOLE_JOB=$(curl -s -o /dev/null -w '%{redirect_url}' -X POST \
            -H "x-tessera-token: $SOLVE_TOKEN" \
            -d "time_budget_seconds=20&seed_timetable_id=" \
            "$SOLVE_CONSOLE/terms/1/generate" | sed 's|.*/||')
        check "pressing Generate starts a solve" "yes" \
            "$([ -n "$CONSOLE_JOB" ] && echo yes || echo no)"

        if [ -n "$CONSOLE_JOB" ]; then
            WATCH=$(curl -s -H "x-tessera-token: $SOLVE_TOKEN" "$SOLVE_CONSOLE/solve/$CONSOLE_JOB")
            # The one file in this project that is neither Python nor a template, and the one
            # a spec is most likely to leave behind.
            check "the watch page carries its script (watch.js travelled)" "yes" \
                "$(echo "$WATCH" | grep -q "EventSource" && echo yes || echo no)"

            for _ in $(seq 1 120); do
                WATCH=$(curl -s -H "x-tessera-token: $SOLVE_TOKEN" \
                    "$SOLVE_CONSOLE/solve/$CONSOLE_JOB")
                echo "$WATCH" | grep -q "Stop and keep" || break
                sleep 0.5
            done
            CONSOLE_TIMETABLE=$(echo "$WATCH" \
                | sed -n 's|.*/console/timetables/\([0-9][0-9]*\)".*|\1|p' | head -1)
            check "the solve settles and offers its timetable" "yes" \
                "$([ -n "$CONSOLE_TIMETABLE" ] && echo yes || echo no)"

            if [ -n "$CONSOLE_TIMETABLE" ]; then
                GRID=$(curl -s -H "x-tessera-token: $SOLVE_TOKEN" \
                    "$SOLVE_CONSOLE/timetables/$CONSOLE_TIMETABLE")
                check "the timetable renders as a week grid" "yes" \
                    "$(echo "$GRID" | grep -q 'class="week"' && echo yes || echo no)"
                check "with teaching drawn in it" "yes" \
                    "$(echo "$GRID" | grep -q 'class="taught"' && echo yes || echo no)"
            fi
        fi
    fi
    kill "$SOLVE_PID" 2>/dev/null || true
    wait "$SOLVE_PID" 2>/dev/null || true

    check "a spreadsheet can be read from the shipped bundle" "rooms" \
        "$(echo "$IMPORTED" | sed -n 's/.*"detected_kind": *"\([a-z]*\)".*/\1/p')"

    check "console refuses an unauthenticated browser" "401" \
        "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$DIRECT_PORT/console/rooms" || true)"
fi
# Suppressed because bash announces the reaped job on stderr, and a stray "Killed: 9"
# in the middle of a passing run reads like a failure.
{ kill -9 "$DIRECT_PID" && wait "$DIRECT_PID"; } 2>/dev/null || true
rm -f "$HANDSHAKE"

echo "==> force quit, the way a user would"
kill -9 "$APP_PID" 2>/dev/null || true
sleep 6
SURVIVOR=$(pgrep -f "$STAGE/Tessera.app/Contents/Resources/engine/tessera-engine" | head -1 || true)
check "engine exits with the application" "" "$SURVIVOR"

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "all checks passed"
else
    echo "$FAILURES check(s) failed"
    exit 1
fi
