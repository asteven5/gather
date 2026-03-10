"""Application configuration and directory setup."""

import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="\U0001f436 %(levelname)s: %(message)s",
)
logger = logging.getLogger("gather")

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
LIBRARY_DIR = BASE_DIR / "library"

for _d in (UPLOAD_DIR, OUTPUT_DIR, LIBRARY_DIR):
    _d.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------
TIMEZONE = "US/Central"
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_BITRATE = "12000k"
AUDIO_SAMPLE_RATE = "44100"
AUDIO_CHANNELS = "2"

# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------
THUMB_SIZE = 400

# ---------------------------------------------------------------------------
# Overlay font
# ---------------------------------------------------------------------------
FONT_PATH = "/System/Library/Fonts/Avenir Next.ttc"
FONT_SIZE = 48

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8000
