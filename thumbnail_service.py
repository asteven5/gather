"""Thumbnail generation and management."""

import shutil
from pathlib import Path

from config import OUTPUT_DIR, THUMB_SIZE, logger
from video_service import _get_duration_secs, _secs_to_timestamp

# Re-export so routes.py can import from one place.
__all__ = [
    "generate_thumbnail",
    "generate_thumbnail_options",
    "apply_thumbnail_option",
]


def generate_thumbnail(
    video_path: Path, thumb_path: Path, timestamp: str = "00:00:01",
) -> None:
    """Extract a square thumbnail frame from a video."""
    import subprocess

    size = THUMB_SIZE
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", timestamp,
            "-vframes", "1",
            "-vf", (
                f"scale={size}:{size}:force_original_aspect_ratio=increase,"
                f"crop={size}:{size}:(iw-{size})/2:(ih-{size})/4"
            ),
            str(thumb_path),
        ],
        capture_output=True, text=True, check=False,
    )


def generate_thumbnail_options(
    video_path: Path,
    percentages: tuple[float, ...] = (0.25, 0.50, 0.75),
) -> list[dict]:
    """Generate thumbnail previews at the given percentage points."""
    duration = _get_duration_secs(video_path)
    if duration <= 0:
        duration = 10.0

    options: list[dict] = []
    for i, pct in enumerate(percentages):
        ts = _secs_to_timestamp(duration * pct)
        fname = f"thumb_option_{i}.jpg"
        dest = OUTPUT_DIR / fname
        generate_thumbnail(video_path, dest, ts)
        options.append({"timestamp": ts, "filename": fname})

    return options


def apply_thumbnail_option(
    filename: str, year_dir: Path, video_stem: str,
) -> None:
    """Copy an already-generated preview image as the final thumbnail."""
    src = OUTPUT_DIR / filename
    if not src.exists():
        raise FileNotFoundError(f"Preview {filename} not found")
    shutil.copy(src, year_dir / f"{video_stem}.jpg")
