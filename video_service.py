"""Video processing service — probing, stitching (fast + polished), thumbnails."""

import concurrent.futures
import dataclasses
import datetime
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytz
from PIL import Image, ImageDraw, ImageFont

from config import (
    FFMPEG,
    FFPROBE,    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    DATE_DISPLAY_SECS,
    FFMPEG_THREADS,
    FONT_PATH,
    FONT_SIZE,
    OUTPUT_DIR,
    TIMEZONE,
    UPLOAD_DIR,
    VIDEO_BITRATE,
    VIDEO_FRAME_RATE,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    WORKER_COUNT,
    logger,
)

# ---------------------------------------------------------------------------
# Cancellation support
# ---------------------------------------------------------------------------
class StitchCancelled(Exception):
    """Raised when the user cancels a stitching operation."""


def _no_op_cancel_check() -> None:
    """Default cancel check that never cancels."""


def _cancellable_run(
    cmd: list[str],
    cancel_check: callable = _no_op_cancel_check,
) -> subprocess.CompletedProcess:
    """Run a subprocess with periodic cancellation checks (~0.5s intervals).

    Uses Popen so we can terminate ffmpeg mid-encode when the user cancels,
    instead of waiting for the entire encode to finish.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    # Drain stderr in a background thread to prevent pipe-buffer deadlock.
    stderr_chunks: list[str] = []

    def _drain():
        for line in proc.stderr:
            stderr_chunks.append(line)

    drain = threading.Thread(target=_drain, daemon=True)
    drain.start()

    try:
        while proc.poll() is None:
            time.sleep(0.5)
            cancel_check()
    except StitchCancelled:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise
    finally:
        drain.join(timeout=2)

    return subprocess.CompletedProcess(
        cmd, proc.returncode, stdout="", stderr="".join(stderr_chunks),
    )


# ---------------------------------------------------------------------------
# Shared ffmpeg arg fragments (DRY)
# ---------------------------------------------------------------------------
_AUDIO_ARGS = ["-c:a", "aac", "-ar", AUDIO_SAMPLE_RATE, "-ac", AUDIO_CHANNELS]
_FASTSTART = ["-movflags", "+faststart"]
_SW_VIDEO_ARGS = [
    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
    "-threads", FFMPEG_THREADS, *_FASTSTART,
]


def _hw_video_strategies() -> list[list[str]]:
    """Return platform-specific HW encoder arg lists to try before software."""
    if sys.platform == "darwin":
        return [
            ["-c:v", "h264_videotoolbox", "-b:v", VIDEO_BITRATE,
             "-profile:v", "high", *_FASTSTART],
        ]
    if sys.platform == "win32":
        return [
            ["-c:v", "h264_nvenc", "-preset", "p4",
             "-b:v", VIDEO_BITRATE, "-threads", FFMPEG_THREADS, *_FASTSTART],
            ["-c:v", "h264_qsv", "-preset", "faster",
             "-b:v", VIDEO_BITRATE, "-threads", FFMPEG_THREADS, *_FASTSTART],
            ["-c:v", "h264_amf", "-quality", "speed",
             "-b:v", VIDEO_BITRATE, "-threads", FFMPEG_THREADS, *_FASTSTART],
        ]
    return [
        ["-c:v", "h264_nvenc", "-preset", "p4",
         "-b:v", VIDEO_BITRATE, "-threads", FFMPEG_THREADS, *_FASTSTART],
        ["-c:v", "h264_vaapi", "-b:v", VIDEO_BITRATE,
         "-threads", FFMPEG_THREADS, *_FASTSTART],
    ]


_HW_STRATEGIES = _hw_video_strategies()


# ---------------------------------------------------------------------------
# Change 3 — Detect working encoder once at startup
# ---------------------------------------------------------------------------
def _detect_working_encoder() -> list[str]:
    """Try each encoder strategy with a tiny test. Return the first winner."""
    test_base = [
        FFMPEG, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
        "-frames:v", "1",
    ]
    for strategy in [*_HW_STRATEGIES, _SW_VIDEO_ARGS]:
        cmd = [*test_base, *strategy, "-f", "null", "-"]
        if subprocess.run(cmd, capture_output=True, check=False).returncode == 0:
            logger.info("Detected working encoder: %s", strategy[1])
            return strategy
    logger.warning("No HW encoder found, falling back to libx264")
    return _SW_VIDEO_ARGS


_WORKING_ENCODER = _detect_working_encoder()


# ---------------------------------------------------------------------------
# Change 2 — VideoMeta: single probe per file
# ---------------------------------------------------------------------------
_METADATA_DATE_KEYS = (
    "com.apple.quicktime.creationdate",
    "creation_time",
)


@dataclasses.dataclass(frozen=True)
class VideoMeta:
    """Everything we need to know about a clip, extracted in one probe."""

    filename: str
    creation_dt: datetime.datetime
    date_text: str
    has_audio: bool
    audio_codec: str
    audio_channels: int
    duration_secs: float
    codec: str
    width: int
    height: int
    pix_fmt: str
    r_frame_rate: str  # e.g. "30000/1001" — needed for homogeneity check
    rotation: int         # display rotation in degrees (0, 90, -90, 180, etc.)


def probe_video(file_path: Path) -> VideoMeta:
    """Extract all metadata in a single ffprobe call."""
    tz = pytz.timezone(TIMEZONE)
    result = subprocess.run(
        [
            FFPROBE, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams",
            str(file_path),
        ],
        capture_output=True, text=True, check=False,
    )
    data = json.loads(result.stdout) if result.stdout.strip() else {}

    # --- Streams ---
    streams = data.get("streams", [])
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"), {},
    )
    audio_stream = next(
        (s for s in streams if s.get("codec_type") == "audio"), {},
    )
    has_audio = bool(audio_stream)
    audio_codec = audio_stream.get("codec_name", "none")
    audio_channels = int(audio_stream.get("channels", 0))

    codec = video_stream.get("codec_name", "unknown")
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    pix_fmt = video_stream.get("pix_fmt", "unknown")
    r_frame_rate = video_stream.get("r_frame_rate", "0/1")

    # --- Rotation (display matrix or legacy tag) ---
    rotation = 0
    for sd in video_stream.get("side_data_list", []):
        if sd.get("side_data_type") == "Display Matrix":
            try:
                rotation = int(float(sd.get("rotation", 0)))
            except (TypeError, ValueError):
                pass
    rotate_tag = video_stream.get("tags", {}).get("rotate", "")
    if rotate_tag and rotation == 0:
        try:
            rotation = int(rotate_tag)
        except (TypeError, ValueError):
            pass

    # --- Duration ---
    fmt = data.get("format", {})
    try:
        duration = float(fmt.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0

    # --- Creation date ---
    tags = fmt.get("tags", {})
    creation_dt = None
    for key in _METADATA_DATE_KEYS:
        # Tags may be case-insensitive; check both raw and lower-case.
        date_str = tags.get(key, "") or tags.get(key.lower(), "")
        if date_str:
            try:
                dt = datetime.datetime.fromisoformat(
                    date_str.replace("Z", "+00:00"),
                )
                creation_dt = dt.astimezone(tz)
                break
            except (ValueError, OSError):
                continue

    if creation_dt is None:
        creation_dt = datetime.datetime.fromtimestamp(
            os.path.getmtime(file_path), tz=pytz.utc,
        ).astimezone(tz)

    date_text = creation_dt.strftime("%B %d, %Y %I:%M %p")

    return VideoMeta(
        filename=file_path.name,
        creation_dt=creation_dt,
        date_text=date_text,
        has_audio=has_audio,
        audio_codec=audio_codec,
        audio_channels=audio_channels,
        duration_secs=duration,
        codec=codec,
        width=width,
        height=height,
        pix_fmt=pix_fmt,
        r_frame_rate=r_frame_rate,
        rotation=rotation,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _clips_are_homogeneous(metadata: list[VideoMeta]) -> bool:
    """Check if all clips share codec, resolution, pixel format, frame rate, and audio."""
    first = metadata[0]
    return all(
        m.codec == first.codec
        and m.width == first.width
        and m.height == first.height
        and m.pix_fmt == first.pix_fmt
        and m.r_frame_rate == first.r_frame_rate
        and m.has_audio == first.has_audio
        and m.audio_codec == first.audio_codec
        and m.audio_channels == first.audio_channels
        and m.rotation == first.rotation
        for m in metadata[1:]
    )


def _is_portrait(meta: VideoMeta) -> bool:
    """Check if a video clip is in portrait orientation (considering rotation).

    Phone cameras typically encode landscape (1920x1080) and flag portrait
    via a display-matrix rotation of +/-90 degrees.
    """
    if abs(meta.rotation) in (90, 270):
        return meta.width > meta.height  # rotation swaps effective dims
    return meta.height > meta.width


def determine_output_dimensions(metadata: list[VideoMeta]) -> tuple[int, int]:
    """Determine output dimensions based on clip orientations.

    If every clip is portrait, output in portrait mode (swapped dimensions).
    Otherwise, output in landscape mode (default).
    """
    if all(_is_portrait(m) for m in metadata):
        return VIDEO_HEIGHT, VIDEO_WIDTH  # e.g. 1080×1920
    return VIDEO_WIDTH, VIDEO_HEIGHT      # e.g. 1920×1080


def _matches_target_format(
    meta: VideoMeta, target_w: int, target_h: int,
) -> bool:
    """Check if a clip already matches the output format (tail can be copied).

    Clips with rotation metadata always need re-encoding to physically
    rotate the pixels — stream-copy would preserve the raw (unrotated) layout.
    """
    if meta.rotation != 0:
        return False
    return (
        meta.codec == "h264"
        and meta.width == target_w
        and meta.height == target_h
        and meta.pix_fmt == "yuv420p"
        and meta.r_frame_rate == VIDEO_FRAME_RATE
    )


def _secs_to_timestamp(secs: float) -> str:
    """HH:MM:SS for ffmpeg seek and thumbnail use."""
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _secs_to_srt_ts(secs: float) -> str:
    """HH:MM:SS,mmm for SRT subtitle timestamps."""
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = secs % 60
    ms = int((s % 1) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Date overlay image (used by polished stitch)
# ---------------------------------------------------------------------------
def _create_date_overlay(
    text: str, output_path: Path, target_w: int, target_h: int,
) -> Path:
    """Generate a transparent PNG with the date text overlaid."""
    img = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except OSError:
        logger.warning("System font not found, using default")
        font = ImageFont.load_default()

    pad_x, pad_y = 20, 12
    text_pos = (50, target_h - 110)
    bbox = draw.textbbox(text_pos, text, font=font)

    draw.rounded_rectangle(
        [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y],
        radius=14, fill=(0, 0, 0, 150),
    )
    draw.text(
        (text_pos[0] + 2, text_pos[1] + 2),
        text, font=font, fill=(0, 0, 0, 120),
    )
    draw.text(text_pos, text, font=font, fill=(255, 255, 255, 230))
    img.save(output_path)
    return output_path


# ---------------------------------------------------------------------------
# Shared scale filter (DRY — used by normalize, filter_complex, and tail encode)
# ---------------------------------------------------------------------------
def _fit_scale(target_w: int, target_h: int) -> str:
    """Scale to fit within target dims (aspect-ratio preserved) + black-bar pad."""
    return (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1"
    )


# Filter graph (used by polished stitch)
# ---------------------------------------------------------------------------
def _build_filter_complex(
    has_audio: bool, target_w: int, target_h: int,
) -> str:
    """Video filter graph with optional silent audio for no-audio clips."""
    vf = (
        f"[0:v:0]{_fit_scale(target_w, target_h)},"
        f"format=yuv420p,"
        f"unsharp=5:5:0.5:5:5:0.0,"
        f"eq=contrast=1.01:saturation=1.03[v];"
        f"[v][1:v:0]overlay=0:0[vout]"
    )
    if not has_audio:
        vf += f";anullsrc=r={AUDIO_SAMPLE_RATE}:cl=stereo[aout]"
    return vf


def _audio_map_args(has_audio: bool) -> list[str]:
    """Return the -map args for the audio stream."""
    if has_audio:
        return ["-map", "0:a:0"]
    return ["-map", "[aout]", "-shortest"]


# ---------------------------------------------------------------------------
# Concat helper (shared by both modes)
# ---------------------------------------------------------------------------
def _concat_segments(
    segment_files: list[Path],
    output_path: Path,
    cancel_check: callable = _no_op_cancel_check,
) -> Path:
    """Concat segments via stream-copy, falling back to re-encode."""
    concat_list = output_path.parent / f"concat_{output_path.stem}.txt"
    with open(concat_list, "w") as fh:
        for p in segment_files:
            safe = str(p.absolute()).replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")

    fast_cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy",
        *_FASTSTART, str(output_path),
    ]
    result = _cancellable_run(fast_cmd, cancel_check)

    if result.returncode != 0:
        logger.warning("Stream-copy concat failed, falling back to re-encode")
        slow_cmd = [
            FFMPEG, "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            *_WORKING_ENCODER, *_AUDIO_ARGS,
            str(output_path),
        ]
        result = _cancellable_run(slow_cmd, cancel_check)
        if result.returncode != 0:
            concat_list.unlink(missing_ok=True)
            raise RuntimeError(f"Concat failed: {result.stderr}")

    concat_list.unlink(missing_ok=True)
    return output_path


# ===================================================================
# ⚡ FAST STITCH — subtitle dates, zero re-encoding
# ===================================================================
def _generate_subtitle_track(
    metadata: list[VideoMeta], output_path: Path,
) -> Path:
    """Generate an SRT subtitle file with a date entry per clip."""
    lines: list[str] = []
    pos = 0.0
    for i, meta in enumerate(metadata):
        start = _secs_to_srt_ts(pos)
        end = _secs_to_srt_ts(pos + min(DATE_DISPLAY_SECS, meta.duration_secs))
        lines.append(str(i + 1))
        lines.append(f"{start} --> {end}")
        lines.append(meta.date_text)
        lines.append("")
        pos += meta.duration_secs

    output_path.write_text("\n".join(lines))
    return output_path


def _normalize_clip(
    index: int,
    meta: VideoMeta,
    target_w: int,
    target_h: int,
    cancel_check: callable = _no_op_cancel_check,
) -> Path:
    """Re-encode a single clip to a standard format for reliable concat.

    Each clip is processed in its own ffmpeg invocation so that
    container-level quirks (edit lists, unusual atoms, MOV vs MP4
    differences) never confuse the concat demuxer downstream.
    Clips that already match the target format are stream-copied.
    """
    src = UPLOAD_DIR / meta.filename
    if _matches_target_format(meta, target_w, target_h) and meta.has_audio:
        return src  # already perfect — skip

    output = UPLOAD_DIR / f"norm_{index}_{meta.filename}"
    vf = f"{_fit_scale(target_w, target_h)},format=yuv420p"
    fps_args = ["-r", VIDEO_FRAME_RATE, "-video_track_timescale", "30000"]

    if meta.has_audio:
        cmd = [
            FFMPEG, "-y", "-i", str(src),
            "-vf", vf,
            *fps_args,
            *_WORKING_ENCODER, *_AUDIO_ARGS,
            *_FASTSTART, str(output),
        ]
    else:
        cmd = [
            FFMPEG, "-y",
            "-i", str(src),
            "-f", "lavfi", "-i",
            f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl=stereo",
            "-vf", vf,
            *fps_args,
            *_WORKING_ENCODER, *_AUDIO_ARGS, "-shortest",
            *_FASTSTART, str(output),
        ]

    result = _cancellable_run(cmd, cancel_check)
    if result.returncode != 0:
        raise RuntimeError(
            f"Normalize failed for {meta.filename}: {result.stderr}",
        )
    return output


def process_videos_fast(
    metadata: list[VideoMeta],
    cancel_check: callable = _no_op_cancel_check,
) -> Path:
    """Stream-copy concat + subtitle track.  No re-encoding."""
    target_w, target_h = determine_output_dimensions(metadata)
    logger.info("Fast stitch: %d clips (%dx%d)...", len(metadata), target_w, target_h)

    final = OUTPUT_DIR / "final_movie.mp4"
    sub_path = OUTPUT_DIR / "dates.srt"
    concat_only = OUTPUT_DIR / "concat_raw.mp4"

    cancel_check()
    _generate_subtitle_track(metadata, sub_path)

    if _clips_are_homogeneous(metadata):
        cancel_check()
        input_files = [UPLOAD_DIR / m.filename for m in metadata]
        _concat_segments(input_files, concat_only, cancel_check)
    else:
        logger.info("Mixed formats — normalizing each clip individually")
        norm_map: dict[int, Path] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            futures = {
                pool.submit(_normalize_clip, i, meta, target_w, target_h, cancel_check): i
                for i, meta in enumerate(metadata)
            }
            for future in concurrent.futures.as_completed(futures):
                cancel_check()
                idx = futures[future]
                norm_map[idx] = future.result()
        normalized = [norm_map[i] for i in range(len(metadata))]
        _concat_segments(normalized, concat_only, cancel_check)
        for p in normalized:
            if p.name.startswith("norm_"):
                p.unlink(missing_ok=True)

    cancel_check()
    # Mux subtitle track (stream-copy everything)
    mux_cmd = [
        FFMPEG, "-y",
        "-i", str(concat_only),
        "-i", str(sub_path),
        "-c", "copy", "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        *_FASTSTART, str(final),
    ]
    result = _cancellable_run(mux_cmd, cancel_check)
    concat_only.unlink(missing_ok=True)
    sub_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"Subtitle mux failed: {result.stderr}")

    logger.info("Fast stitch complete: %s", final)
    return final


# ===================================================================
# 🎬 POLISHED STITCH — partial re-encode (head only)
# ===================================================================
def _find_split_keyframe(file_path: Path, target_secs: float) -> float:
    """Find the PTS of the first keyframe at or after *target_secs*."""
    result = subprocess.run(
        [
            FFPROBE, "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "packet=pts_time,flags",
            "-of", "csv=p=0",
            "-read_intervals", f"{target_secs}%{target_secs + 10}",
            str(file_path),
        ],
        capture_output=True, text=True, check=False,
    )
    for line in result.stdout.strip().splitlines():
        parts = line.split(",", 1)
        if len(parts) == 2 and "K" in parts[1]:
            try:
                return float(parts[0])
            except ValueError:
                continue
    return target_secs


def _process_full_video(
    index: int,
    meta: VideoMeta,
    target_w: int,
    target_h: int,
    cancel_check: callable = _no_op_cancel_check,
) -> Path:
    """Full re-encode — used for short clips that are all date overlay."""
    input_path = UPLOAD_DIR / meta.filename
    output_path = UPLOAD_DIR / f"proc_{index}_{meta.filename}"
    overlay_path = UPLOAD_DIR / f"overlay_{index}.png"

    logger.info("Full encode (short clip): %s", meta.filename)
    _create_date_overlay(meta.date_text, overlay_path, target_w, target_h)

    fps_args = ["-r", VIDEO_FRAME_RATE, "-video_track_timescale", "30000"]
    cmd = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-i", str(overlay_path),
        "-filter_complex", _build_filter_complex(meta.has_audio, target_w, target_h),
        "-map", "[vout]", *_audio_map_args(meta.has_audio),
        *fps_args,
        *_WORKING_ENCODER, *_AUDIO_ARGS,
        str(output_path),
    ]
    result = _cancellable_run(cmd, cancel_check)
    overlay_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"Full encode failed for {meta.filename}: {result.stderr}",
        )
    return output_path


def _process_partial_video(
    index: int,
    meta: VideoMeta,
    target_w: int,
    target_h: int,
    cancel_check: callable = _no_op_cancel_check,
) -> Path:
    """Re-encode the first few seconds (date overlay), stream-copy the rest."""
    input_path = UPLOAD_DIR / meta.filename

    # Short clips: just encode the whole thing.
    if meta.duration_secs <= DATE_DISPLAY_SECS:
        return _process_full_video(index, meta, target_w, target_h, cancel_check)

    split_time = _find_split_keyframe(input_path, DATE_DISPLAY_SECS)
    logger.info(
        "Partial encode %s: head=%.1fs, tail=stream-copy",
        meta.filename, split_time,
    )

    output_path = UPLOAD_DIR / f"partial_{index}_{meta.filename}"
    overlay_path = UPLOAD_DIR / f"overlay_{index}.png"
    head_path = UPLOAD_DIR / f"head_{index}.mp4"
    tail_path = UPLOAD_DIR / f"tail_{index}.mp4"

    _create_date_overlay(meta.date_text, overlay_path, target_w, target_h)

    fps_args = ["-r", VIDEO_FRAME_RATE, "-video_track_timescale", "30000"]

    # --- Head: re-encode with date overlay ---
    head_cmd = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-i", str(overlay_path),
        "-t", str(split_time),
        "-filter_complex", _build_filter_complex(meta.has_audio, target_w, target_h),
        "-map", "[vout]", *_audio_map_args(meta.has_audio),
        *fps_args,
        *_WORKING_ENCODER, *_AUDIO_ARGS,
        str(head_path),
    ]
    result = _cancellable_run(head_cmd, cancel_check)
    overlay_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"Head encode failed for {meta.filename}: {result.stderr}")

    # --- Tail: stream-copy when source matches target, normalize otherwise ---
    if _matches_target_format(meta, target_w, target_h):
        tail_cmd = [
            FFMPEG, "-y",
            "-ss", str(split_time),
            "-i", str(input_path),
            "-c", "copy",
            *_FASTSTART, str(tail_path),
        ]
    else:
        # Normalize tail (no overlay — just scale + format)
        norm_vf = f"{_fit_scale(target_w, target_h)},format=yuv420p"
        if meta.has_audio:
            tail_cmd = [
                FFMPEG, "-y",
                "-ss", str(split_time),
                "-i", str(input_path),
                "-vf", norm_vf,
                *fps_args,
                *_WORKING_ENCODER, *_AUDIO_ARGS,
                str(tail_path),
            ]
        else:
            tail_cmd = [
                FFMPEG, "-y",
                "-ss", str(split_time),
                "-i", str(input_path),
                "-filter_complex",
                f"[0:v:0]{norm_vf}[vout];"
                f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl=stereo[aout]",
                "-map", "[vout]", "-map", "[aout]", "-shortest",
                *fps_args,
                *_WORKING_ENCODER, *_AUDIO_ARGS,
                str(tail_path),
            ]

    result = _cancellable_run(tail_cmd, cancel_check)
    if result.returncode != 0:
        raise RuntimeError(f"Tail failed for {meta.filename}: {result.stderr}")

    # --- Splice head + tail ---
    _concat_segments([head_path, tail_path], output_path, cancel_check)
    head_path.unlink(missing_ok=True)
    tail_path.unlink(missing_ok=True)

    logger.info("Finished partial encode: %s", meta.filename)
    return output_path


def process_videos_polished(
    metadata: list[VideoMeta],
    cancel_check: callable = _no_op_cancel_check,
) -> Path:
    """Partial re-encode (head-only date overlay) + concat."""
    target_w, target_h = determine_output_dimensions(metadata)
    logger.info("Polished stitch: %d clips (%dx%d)...", len(metadata), target_w, target_h)

    processed_map: dict[int, Path] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
        futures = {
            pool.submit(_process_partial_video, i, meta, target_w, target_h, cancel_check): i
            for i, meta in enumerate(metadata)
        }
        for future in concurrent.futures.as_completed(futures):
            cancel_check()
            idx = futures[future]
            processed_map[idx] = future.result()

    cancel_check()
    ordered = [processed_map[i] for i in range(len(metadata))]
    final = OUTPUT_DIR / "final_movie.mp4"
    _concat_segments(ordered, final, cancel_check)

    logger.info("Polished stitch complete: %s", final)
    return final


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------
def _get_duration_secs(video_path: Path) -> float:
    """Return the duration of a video in seconds."""
    result = subprocess.run(
        [
            FFPROBE, "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def cleanup_uploads() -> None:
    """Remove all files from the upload directory."""
    for f in UPLOAD_DIR.iterdir():
        try:
            f.unlink()
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", f.name, exc)
