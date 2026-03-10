"""Video processing service — ffmpeg operations, date overlays, stitching."""

import concurrent.futures
import datetime
import os
import subprocess
from pathlib import Path

import pytz
from PIL import Image, ImageDraw, ImageFont

from config import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    FONT_PATH,
    FONT_SIZE,
    LIBRARY_DIR,
    OUTPUT_DIR,
    THUMB_SIZE,
    TIMEZONE,
    UPLOAD_DIR,
    VIDEO_BITRATE,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    logger,
)

# ---------------------------------------------------------------------------
# Shared ffmpeg arg fragments (DRY)
# ---------------------------------------------------------------------------
_AUDIO_ARGS = ["-c:a", "aac", "-ar", AUDIO_SAMPLE_RATE, "-ac", AUDIO_CHANNELS]
_FASTSTART = ["-movflags", "+faststart"]
_HW_VIDEO_ARGS = ["-c:v", "h264_videotoolbox", "-b:v", VIDEO_BITRATE, "-profile:v", "high", *_FASTSTART]
_SW_VIDEO_ARGS = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", *_FASTSTART]


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------
_METADATA_TAGS = (
    "format_tags=com.apple.quicktime.creationdate",
    "format_tags=creation_time",
)


def get_creation_datetime(file_path: Path) -> datetime.datetime:
    """Extract the video creation date from metadata, falling back to mtime."""
    tz = pytz.timezone(TIMEZONE)

    for tag in _METADATA_TAGS:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-select_streams", "v:0",
                    "-show_entries", tag,
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            date_str = result.stdout.strip()
            if date_str:
                dt = datetime.datetime.fromisoformat(
                    date_str.replace("Z", "+00:00")
                )
                return dt.astimezone(tz)
        except (ValueError, OSError) as exc:
            logger.warning("Failed to parse date from tag %s: %s", tag, exc)

    logger.info("Using file mtime for %s", file_path.name)
    return datetime.datetime.fromtimestamp(
        os.path.getmtime(file_path), tz=pytz.utc
    ).astimezone(tz)


def format_creation_date(file_path: Path) -> str:
    """Return a human-readable creation-date string."""
    return get_creation_datetime(file_path).strftime("%B %d, %Y %I:%M %p")


# ---------------------------------------------------------------------------
# Overlay image
# ---------------------------------------------------------------------------
def _create_date_overlay(text: str, output_path: Path) -> Path:
    """Generate a transparent PNG with the date text overlaid."""
    img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except OSError:
        logger.warning("System font not found, using default")
        font = ImageFont.load_default()

    pad_x, pad_y = 20, 12
    text_pos = (50, VIDEO_HEIGHT - 110)
    bbox = draw.textbbox(text_pos, text, font=font)

    # Rounded semi-transparent background pill
    draw.rounded_rectangle(
        [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y],
        radius=14,
        fill=(0, 0, 0, 150),
    )

    # Subtle drop shadow for depth
    draw.text(
        (text_pos[0] + 2, text_pos[1] + 2),
        text, font=font, fill=(0, 0, 0, 120),
    )

    # Main text
    draw.text(text_pos, text, font=font, fill=(255, 255, 255, 230))
    img.save(output_path)
    return output_path


# ---------------------------------------------------------------------------
# Single-video processing
# ---------------------------------------------------------------------------
def _build_filter_complex() -> str:
    # setsar=1 normalizes any funky pixel aspect ratios.
    # format=yuv420p converts 10-bit HDR to 8-bit for H.264 compatibility.
    return (
        f"[0:v:0]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1,"
        f"format=yuv420p,"
        f"unsharp=5:5:0.5:5:5:0.0,"
        f"eq=contrast=1.01:saturation=1.03[v];"
        f"[v][1:v:0]overlay=0:0[vout]"
    )


def _process_single_video(index: int, filename: str, date_text: str) -> Path:
    """Process one video: add date overlay and standardize encoding."""
    input_path = UPLOAD_DIR / filename
    output_path = UPLOAD_DIR / f"proc_{index}_{filename}"
    overlay_path = UPLOAD_DIR / f"overlay_{index}.png"

    logger.info("Processing %s (Part %d)...", filename, index + 1)
    _create_date_overlay(date_text, overlay_path)

    shared = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-i", str(overlay_path),
        "-filter_complex", _build_filter_complex(),
        "-map", "[vout]", "-map", "0:a:0?",
    ]

    strategies = [
        [*shared, *_HW_VIDEO_ARGS, *_AUDIO_ARGS, str(output_path)],
        [*shared, *_SW_VIDEO_ARGS, *_AUDIO_ARGS, str(output_path)],
    ]

    last_stderr = ""
    for i, cmd in enumerate(strategies, 1):
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            logger.info("Finished %s", filename)
            overlay_path.unlink(missing_ok=True)
            return output_path
        last_stderr = result.stderr
        logger.warning(
            "Strategy %d failed for %s: %s",
            i, filename, last_stderr.strip().splitlines()[-1] if last_stderr.strip() else "unknown error",
        )

    overlay_path.unlink(missing_ok=True)
    raise RuntimeError(
        f"All encoding strategies failed for {filename}.\n"
        f"Last ffmpeg error:\n{last_stderr}"
    )


# ---------------------------------------------------------------------------
# Concatenation
# ---------------------------------------------------------------------------
def _concat_videos(processed_files: list[Path], output_path: Path) -> Path:
    """Concatenate pre-processed video segments into one final movie."""
    concat_list = UPLOAD_DIR / "concat.txt"
    with open(concat_list, "w") as fh:
        for p in processed_files:
            safe = str(p.absolute()).replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")

    # Fast path: stream-copy (no re-encode)
    fast_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy",
        *_FASTSTART, str(output_path),
    ]
    result = subprocess.run(fast_cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        logger.warning("Stream-copy concat failed, falling back to re-encode")
        slow_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            *_HW_VIDEO_ARGS, *_AUDIO_ARGS,
            str(output_path),
        ]
        result = subprocess.run(slow_cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.error("Concat fallback also failed: %s", result.stderr)
            raise RuntimeError(f"Video concatenation failed: {result.stderr}")

    concat_list.unlink(missing_ok=True)
    return output_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def process_videos(filenames: list[str]) -> Path:
    """Process and stitch multiple videos into a single movie."""
    logger.info("Starting parallel processing of %d videos...", len(filenames))

    processed_map: dict[int, Path] = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(
                _process_single_video, i, name,
                format_creation_date(UPLOAD_DIR / name),
            ): i
            for i, name in enumerate(filenames)
        }
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            processed_map[idx] = future.result()  # raises on failure

    ordered = [processed_map[i] for i in range(len(filenames))]
    final = OUTPUT_DIR / "final_movie.mp4"
    _concat_videos(ordered, final)

    logger.info("Movie completed at %s", final)
    return final


def _get_duration_secs(video_path: Path) -> float:
    """Return the duration of a video in seconds."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _secs_to_timestamp(secs: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def generate_thumbnail(
    video_path: Path,
    thumb_path: Path,
    timestamp: str = "00:00:01",
) -> None:
    """Extract a square thumbnail frame from a video at *timestamp*."""
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
        capture_output=True,
        text=True,
        check=False,
    )


def generate_thumbnail_options(
    video_path: Path,
    percentages: tuple[float, ...] = (0.25, 0.50, 0.75),
) -> list[dict]:
    """Generate thumbnail previews at the given percentage points.

    Returns a list of {"timestamp": "HH:MM:SS", "filename": "..."}.
    """
    duration = _get_duration_secs(video_path)
    if duration <= 0:
        duration = 10.0  # fallback: just grab early frames

    options: list[dict] = []
    for i, pct in enumerate(percentages):
        ts = _secs_to_timestamp(duration * pct)
        fname = f"thumb_option_{i}.jpg"
        dest = OUTPUT_DIR / fname
        generate_thumbnail(video_path, dest, ts)
        options.append({"timestamp": ts, "filename": fname})

    return options


def apply_thumbnail_option(filename: str, year_dir: Path, video_stem: str) -> None:
    """Copy an already-generated preview image as the final thumbnail."""
    import shutil

    src = OUTPUT_DIR / filename
    if not src.exists():
        raise FileNotFoundError(f"Preview {filename} not found")
    shutil.copy(src, year_dir / f"{video_stem}.jpg")


def cleanup_uploads() -> None:
    """Remove all files from the upload directory."""
    for f in UPLOAD_DIR.iterdir():
        try:
            f.unlink()
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", f.name, exc)
