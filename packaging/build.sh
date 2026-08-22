#!/bin/bash
# Build Tessera.app and a .dmg from it.
#
# Signing runs inside-out — nested Mach-O binaries first, then the bundle — because a
# signature seals the contents it covers. Signing the bundle first and a nested dylib
# afterwards invalidates the outer seal and macOS refuses to launch the result. That
# ordering is also what notarization will require, so it is worth being right now.
#
#   ./packaging/build.sh                        ad-hoc signed, no Apple account needed
#   CODESIGN_IDENTITY="Developer ID Application: …" ./packaging/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/packaging/out"
APP="$OUT/Tessera.app"
IDENTITY="${CODESIGN_IDENTITY:--}"   # "-" is ad-hoc
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
DMG="$OUT/Tessera-$VERSION-arm64.dmg"

echo "==> building engine"
cd "$ROOT"
uv run pyinstaller --noconfirm --clean --log-level WARN \
    --distpath packaging/dist --workpath packaging/build \
    packaging/tessera-engine.spec

echo "==> building client"
cd "$ROOT/client"
swift build -c release --arch arm64
cd "$ROOT"

echo "==> assembling app bundle"
rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/client/.build/arm64-apple-macosx/release/Tessera" "$APP/Contents/MacOS/Tessera"
cp -R "$ROOT/packaging/dist/tessera-engine" "$APP/Contents/Resources/engine"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>               <string>Tessera</string>
    <key>CFBundleDisplayName</key>        <string>Tessera</string>
    <key>CFBundleExecutable</key>         <string>Tessera</string>
    <key>CFBundleIdentifier</key>         <string>com.dhbhensdadia.tessera</string>
    <key>CFBundlePackageType</key>        <string>APPL</string>
    <key>CFBundleShortVersionString</key> <string>$VERSION</string>
    <key>CFBundleVersion</key>            <string>$VERSION</string>
    <key>LSMinimumSystemVersion</key>     <string>14.0</string>
    <key>NSHighResolutionCapable</key>    <true/>
    <key>LSApplicationCategoryType</key>  <string>public.app-category.productivity</string>

    <!-- What makes a .tessera one item in the Finder rather than a folder.
         Decision #25 said a project is a real file you can email, archive and
         double-click; without these two declarations that has been true on paper and
         false in every build since Stage 0. `com.apple.package` is the conformance that
         tells the Finder to present the directory as a document. -->
    <key>UTExportedTypeDeclarations</key>
    <array>
        <dict>
            <key>UTTypeIdentifier</key>          <string>com.dhbhensdadia.tessera.project</string>
            <key>UTTypeDescription</key>         <string>Tessera Project</string>
            <key>UTTypeConformsTo</key>
            <array>
                <string>com.apple.package</string>
            </array>
            <key>UTTypeTagSpecification</key>
            <dict>
                <key>public.filename-extension</key>
                <array><string>tessera</string></array>
            </dict>
        </dict>
    </array>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeName</key>          <string>Tessera Project</string>
            <key>CFBundleTypeRole</key>          <string>Editor</string>
            <key>LSHandlerRank</key>             <string>Owner</string>
            <key>LSTypeIsPackage</key>           <true/>
            <key>LSItemContentTypes</key>
            <array><string>com.dhbhensdadia.tessera.project</string></array>
        </dict>
    </array>
</dict>
</plist>
PLIST

# Entitlements the frozen Python needs once Hardened Runtime is on. Harmless under
# ad-hoc signing; having them proven now means notarization changes only the identity.
cat > "$OUT/entitlements.plist" <<'ENTS'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
    <key>com.apple.security.cs.allow-jit</key><true/>
    <key>com.apple.security.cs.disable-library-validation</key><true/>
</dict>
</plist>
ENTS

echo "==> signing nested binaries"
NESTED=0
while IFS= read -r -d '' file; do
    if file "$file" | grep -q 'Mach-O'; then
        codesign --force --timestamp=none --options=runtime \
                 --entitlements "$OUT/entitlements.plist" \
                 --sign "$IDENTITY" "$file" 2>/dev/null
        NESTED=$((NESTED + 1))
    fi
done < <(find "$APP/Contents/Resources/engine" -type f -print0)
echo "    signed $NESTED nested binaries"

echo "==> signing bundle"
codesign --force --timestamp=none --options=runtime \
         --entitlements "$OUT/entitlements.plist" \
         --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict "$APP"
echo "    signature valid"

echo "==> building dmg"
STAGE="$OUT/stage"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Tessera" -srcfolder "$STAGE" -ov -format UDZO -quiet "$DMG"
rm -rf "$STAGE"

echo
echo "app: $APP  ($(du -sh "$APP" | cut -f1))"
echo "dmg: $DMG  ($(du -sh "$DMG" | cut -f1))"
