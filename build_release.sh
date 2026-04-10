#!/bin/bash
# build_release.sh — Package Gather for distribution.
#
# Bundles all runtime files INSIDE Gather.app so the customer sees
# a single app icon when they unzip — nothing else.
#
#   Gather.app/
#   └── Contents/
#       └── Resources/
#           └── app/          ← Python + HTML + JS tucked in here
#               └── bin/      ← static ffmpeg + ffprobe
#
# Usage:  ./build_release.sh

set -euo pipefail

PROJ="$(cd "$(dirname "$0")" && pwd)"
BUILD="$(mktemp -d)"
ZIP_OUT="$PROJ/website/Gather.zip"

echo "🐶 Building Gather release…"
echo "   Project dir : $PROJ"
echo ""

# ── 1. Copy Gather.app shell, strip dev artifacts ─────────────────────────
cp -R "$PROJ/Gather.app" "$BUILD/Gather.app"
find "$BUILD/Gather.app" -name "*.bak" -delete
find "$BUILD/Gather.app" -name ".DS_Store" -delete

# ── 2. Create app/ inside the bundle for runtime files ────────────────────
APP_DIR="$BUILD/Gather.app/Contents/Resources/app"
mkdir -p "$APP_DIR"

RUNTIME_FILES=(
    main.py
    config.py
    models.py
    routes.py
    video_service.py
    drive_service.py
    youtube_service.py
    roku_service.py
    stripe_routes.py
    thumbnail_service.py
    update_service.py
    index.html
    faq.js
    requirements.txt
)

for f in "${RUNTIME_FILES[@]}"; do
    if [ ! -f "$PROJ/$f" ]; then
        echo "⚠️  Missing runtime file: $f (skipping)"
    else
        cp "$PROJ/$f" "$APP_DIR/$f"
    fi
done

echo "   Bundled ${#RUNTIME_FILES[@]} runtime files into Gather.app"

# ── 3. Bundle static ffmpeg/ffprobe binaries ──────────────────────────────
BIN_DIR="$APP_DIR/bin"
mkdir -p "$BIN_DIR"

FFMPEG_URL="https://evermeet.cx/ffmpeg/getrelease/zip"
FFPROBE_URL="https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
DL_TMP="$(mktemp -d)"

echo "   Downloading ffmpeg…"
curl -sL "$FFMPEG_URL" -o "$DL_TMP/ffmpeg.zip"
unzip -qo "$DL_TMP/ffmpeg.zip" -d "$DL_TMP/ffmpeg"
cp "$DL_TMP/ffmpeg/ffmpeg" "$BIN_DIR/ffmpeg"
chmod +x "$BIN_DIR/ffmpeg"

echo "   Downloading ffprobe…"
curl -sL "$FFPROBE_URL" -o "$DL_TMP/ffprobe.zip"
unzip -qo "$DL_TMP/ffprobe.zip" -d "$DL_TMP/ffprobe"
cp "$DL_TMP/ffprobe/ffprobe" "$BIN_DIR/ffprobe"
chmod +x "$BIN_DIR/ffprobe"

rm -rf "$DL_TMP"
echo "   Bundled ffmpeg + ffprobe into app/bin/"

# ── 4. Compile fresh AppleScript with bundled-path support ────────────────
if [ -f "$PROJ/Gather.applescript" ]; then
    echo "   Compiling AppleScript…"
    osacompile -o "$BUILD/Gather.app/Contents/Resources/Scripts/main.scpt" \
               "$PROJ/Gather.applescript"
else
    echo "⚠️  Gather.applescript not found — using existing main.scpt"
fi

# ── 5. Re-sign the app (old signature is invalid after modifying bundle) ──
echo "   Re-signing app bundle…"
codesign --remove-signature "$BUILD/Gather.app" 2>/dev/null || true
codesign --force --deep -s - "$BUILD/Gather.app"

# ── 6. Zip it up — just Gather.app, nothing else ─────────────────────────
echo "   Creating zip…"
rm -f "$ZIP_OUT"
(cd "$BUILD" && zip -r -q "$ZIP_OUT" Gather.app/ -x "*.DS_Store")

# ── 7. Summary ────────────────────────────────────────────────────────────
FILE_COUNT=$(unzip -l "$ZIP_OUT" | tail -1 | awk '{print $2}')
ZIP_SIZE=$(du -h "$ZIP_OUT" | cut -f1)

echo ""
echo "✅ Built: $ZIP_OUT"
echo "   Files : $FILE_COUNT"
echo "   Size  : $ZIP_SIZE"
echo ""
echo "   Customer sees:"
echo "   📁 → unzip → 🎬 Gather.app (just double-click!)"

# ── 8. Clean up ───────────────────────────────────────────────────────────
rm -rf "$BUILD"

echo ""
echo "🐶 Done! Deploy website/ to ship it."
