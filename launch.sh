#!/bin/bash
# Gather launcher — called by Gather.app
# Ensures proper PATH and environment for uv + ffmpeg.

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd "$(dirname "$0")"

exec uv run --with fastapi --with uvicorn --with python-multipart --with jinja2 --with Pillow --with pytz --with pywebview main.py
