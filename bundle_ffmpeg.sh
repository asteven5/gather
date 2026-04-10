#!/usr/bin/env bash
# bundle_ffmpeg.sh — Download a static ffmpeg/ffprobe build and embed it
# inside the Gather.app bundle so users don't need Homebrew.
#
# Usage:  ./bundle_ffmpeg.sh [path/to/Gather.app]
#
# Grabs the latest static macOS build from evermeet.cx (trusted source used by
# Homebrew itself) for the current architecture (arm64 / x86_64).

set -euo pipefail

APP_PATH="${1:-./Gather.app}"
BIN_DIR="${APP_PATH}/Contents/Resources/app/bin"

ARCH="$(uname -m)"  # arm64 or x86_64

# evermeet.cx hosts universal/arch-specific static builds
FFMPEG_URL="https://evermeet.cx/ffmpeg/getrelease/zip"
FFPROBE_URL="https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"

TMPDIR_DL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_DL"' EXIT

echo "🐶 Bundling ffmpeg into ${APP_PATH} (arch: ${ARCH})..."

mkdir -p "$BIN_DIR"

# --- ffmpeg ---
echo "   Downloading ffmpeg..."
curl -sL "$FFMPEG_URL" -o "${TMPDIR_DL}/ffmpeg.zip"
unzip -qo "${TMPDIR_DL}/ffmpeg.zip" -d "${TMPDIR_DL}/ffmpeg"
cp "${TMPDIR_DL}/ffmpeg/ffmpeg" "${BIN_DIR}/ffmpeg"
chmod +x "${BIN_DIR}/ffmpeg"

# --- ffprobe ---
echo "   Downloading ffprobe..."
curl -sL "$FFPROBE_URL" -o "${TMPDIR_DL}/ffprobe.zip"
unzip -qo "${TMPDIR_DL}/ffprobe.zip" -d "${TMPDIR_DL}/ffprobe"
cp "${TMPDIR_DL}/ffprobe/ffprobe" "${BIN_DIR}/ffprobe"
chmod +x "${BIN_DIR}/ffprobe"

echo ""
echo "✅ Done! Bundled binaries:"
ls -lh "${BIN_DIR}/"
echo ""
echo "   ffmpeg version:  $("${BIN_DIR}/ffmpeg" -version | head -1)"
echo "   ffprobe version: $("${BIN_DIR}/ffprobe" -version | head -1)"
