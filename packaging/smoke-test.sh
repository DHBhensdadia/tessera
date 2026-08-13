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

echo "==> launch"
pkill -9 -f 'tessera-engine' 2>/dev/null || true
open "$STAGE/Tessera.app"
sleep 9

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
ENGINE_BIN="$STAGE/Tessera.app/Contents/Resources/engine/tessera-engine"
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
