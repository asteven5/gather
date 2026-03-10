#!/bin/bash
cd "$(dirname "$0")"

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null
then
    echo "ERROR: ffmpeg is not installed!"
    echo "Please install it via Homebrew: brew install ffmpeg"
    echo "Or download it from https://ffmpeg.org"
    read -p "Press enter to exit..."
    exit
fi

# Check for uv
if ! command -v uv &> /dev/null
then
    echo "Initializing environment (installing uv)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

# Run the app using uv to handle dependencies automatically
echo "Starting Gather..."
uv run --with fastapi --with uvicorn --with python-multipart --with jinja2 --with Pillow --with pytz --with pywebview main.py
echo "Gather has closed."
