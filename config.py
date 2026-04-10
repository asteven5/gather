"""Application configuration and directory setup."""

APP_VERSION = "1.2.0"

import logging
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

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


def _data_dir() -> Path:
    """Return the root directory for user data (uploads, output, library).

    Inside a .app bundle the code lives in Contents/Resources/app/ which is
    read-only-ish, so we store user data in ~/Gather instead.
    In dev mode (files next to the project root) we use the project dir.
    """
    if ".app/Contents/Resources" in str(BASE_DIR):
        return Path.home() / "Gather"
    return BASE_DIR


DATA_DIR = _data_dir()
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"
LIBRARY_DIR = DATA_DIR / "library"

for _d in (UPLOAD_DIR, OUTPUT_DIR, LIBRARY_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------
TIMEZONE = "US/Central"
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_BITRATE = "12000k"
VIDEO_FRAME_RATE = "30000/1001"  # 29.97 fps (NTSC)
AUDIO_SAMPLE_RATE = "44100"
AUDIO_CHANNELS = "2"

# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------
THUMB_SIZE = 400

# ---------------------------------------------------------------------------
# Overlay font (platform-aware — falls back to Pillow default if missing)
# ---------------------------------------------------------------------------
def _system_font() -> str:
    """Return a reasonable system font path for the current platform."""
    candidates: tuple[str, ...] = ()
    if sys.platform == "darwin":
        candidates = (
            "/System/Library/Fonts/Avenir Next.ttc",
            "/System/Library/Fonts/Helvetica.ttc",
        )
    elif sys.platform == "win32":
        candidates = (
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        )
    else:  # Linux / other
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        )
    for path in candidates:
        if Path(path).exists():
            return path
    return ""  # Pillow will use its built-in default


FONT_PATH = _system_font()
FONT_SIZE = 48

# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8000

# ---------------------------------------------------------------------------
# Binary resolution — bundled copies take priority over system PATH
# ---------------------------------------------------------------------------
def _find_binary(name: str) -> str:
    """Locate *name*, preferring the bundled ``bin/`` dir inside the app."""
    bundled = BASE_DIR / "bin" / name
    if bundled.is_file() and os.access(bundled, os.X_OK):
        logger.info("Using bundled %s: %s", name, bundled)
        return str(bundled)
    found = shutil.which(name)
    if found:
        logger.info("Using system %s: %s", name, found)
        return found
    return ""  # empty -> caught by the startup check


FFMPEG = _find_binary("ffmpeg")
FFPROBE = _find_binary("ffprobe")


def check_dependencies() -> list[str]:
    """Return a list of missing required binaries."""
    missing: list[str] = []
    if not FFMPEG:
        missing.append("ffmpeg")
    if not FFPROBE:
        missing.append("ffprobe")
    return missing


# ---------------------------------------------------------------------------
# Performance tuning
# ---------------------------------------------------------------------------
DATE_DISPLAY_SECS = 5.0
WORKER_COUNT = max(1, (os.cpu_count() or 2) // 2)
FFMPEG_THREADS = str((os.cpu_count() or 2) // WORKER_COUNT)
