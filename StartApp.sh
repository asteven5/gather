#!/usr/bin/env bash
cd "$(dirname "$0")"

# Support both dev layout (files here) and distribution layout (_internal/)
if [ -d "_internal" ]; then
    cd _internal
fi

# --- Check for ffmpeg ---
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: ffmpeg is not installed!"
    echo ""
    echo "Install it with your package manager:"
    echo "  Ubuntu/Debian:  sudo apt install ffmpeg"
    echo "  Fedora:         sudo dnf install ffmpeg"
    echo "  Arch:           sudo pacman -S ffmpeg"
    echo "  Or download from https://ffmpeg.org"
    read -rp "Press enter to exit..."
    exit 1
fi

# --- Check for uv ---
if ! command -v uv &> /dev/null; then
    echo "Initializing environment (installing uv)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck source=/dev/null
    source "$HOME/.cargo/env"
fi

echo "Starting Gather..."
uv run --with fastapi --with uvicorn --with python-multipart --with jinja2 --with Pillow --with pytz --with pywebview main.py
echo "Gather has closed."
