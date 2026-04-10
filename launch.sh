#!/bin/bash
# Gather launcher — called by Gather.app
# Ensures proper PATH and environment for uv + ffmpeg.

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd "$(dirname "$0")"

# Support both dev layout (files here) and distribution layout (_internal/)
if [ -d "_internal" ]; then
    cd _internal
fi

exec uv run --with-requirements requirements.txt main.py
