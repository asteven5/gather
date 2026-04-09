# Gather — Performance Plan

> **Author:** Hockey Stick 🐶 (`code-puppy-ed1eda`)
> **Date:** July 2025
> **Status:** Proposed

---

## Problem

Gathering 10 clips into a home video currently spawns **63+ subprocesses** and
fully re-encodes every single clip just to burn a date overlay onto the frames.
On Kenzie's 4-core i5 / 8 GB machine this takes *minutes* when it could take
*seconds*.

---

## Root Causes

### 1. Every clip is fully re-encoded to burn in dates

The date overlay is a PNG composited onto each frame via ffmpeg's `overlay`
filter. This forces a full decode → filter → encode cycle for the **entire**
clip, even though the date only needs to appear for the first few seconds.

### 2. Metadata is extracted redundantly

Each video is probed **up to 5 separate times** across the pipeline:

| Where | Calls per video | What it extracts |
|---|---|---|
| Upload handler (sorting) | 2 ffprobe | Creation date |
| `process_videos` (overlay text) | 2 ffprobe | Creation date *(same data!)* |
| `_process_single_video` | 1 ffprobe | Audio stream presence |

For 10 videos that's **~52 ffprobe subprocesses** doing duplicate work.

### 3. Failed encoder attempts waste time

The code tries hardware encoding first, and if that fails, falls back to
software. This trial-and-error happens **per video** — the same encoder fails
the same way every time, but we keep trying.

### 4. Worker pool is oversized

`ThreadPoolExecutor` defaults to 8 workers on a 4-core machine. Each ffmpeg
instance is itself multi-threaded, so 8 simultaneous encodes thrash the CPU
and blow through memory bandwidth.

---

## The Plan

Four changes, ordered by impact. Changes 1–2 are the big wins; 3–4 are
quick follows that build on the same foundation.

---

### Change 1 — Dual-Mode Stitching

**Impact: HIGH — the core speedup**

Replace the current full-re-encode-everything approach with two user-selectable
modes. Both are dramatically faster than what exists today.

#### Mode comparison

| | ⚡ Fast Stitch | 🎬 Polished Stitch |
|---|---|---|
| How dates are shown | ASS subtitle track | Burned into first ~5 sec of each clip |
| Re-encode? | None | ~5% of frames (head only) |
| Speed (10 clips) | Seconds | Faster than current by ~10–20x |
| Dates always visible? | Depends on player subtitle support | Yes — baked into pixels |
| Best for | Personal viewing, family TV night | YouTube, social media, archival |

---

#### ⚡ Fast Stitch — Subtitle-Based Dates

Zero re-encoding. Dates are displayed via a styled subtitle track muxed into
the final container.

##### Pipeline

```
clip1 ─┐
clip2 ─┼── probe all ── stream-copy concat ── mux ASS subs ── final.mp4
clip3 ─┘
```

1. **Probe all clips** for creation date + duration (one ffprobe each — see
   Change 2).
2. **Concat via stream-copy** — no decode, no encode, just byte-level
   joining. Takes seconds.
3. **Generate an ASS subtitle file** with styled date entries timed to each
   clip's position in the final video.
4. **Mux the subtitle track** into the MP4 container (another stream-copy
   operation — instant).

##### ASS subtitle styling

Replicate the current date-pill look as closely as possible:

```ass
[V4+ Styles]
Style: GatherDate,Nunito,28,&H00FFFFFF,&H00000000,&H96000000,&H00000000,
       0,0,0,0,100,100,0,0,3,0,1.2,7,30,30,40,1

[Events]
Dialogue: 0,0:00:00.00,0:00:05.00,GatherDate,,0,0,0,,June 14, 2025 3:42 PM
Dialogue: 0,0:00:45.23,0:00:50.23,GatherDate,,0,0,0,,June 14, 2025 4:15 PM
```

- Semi-transparent dark background box (`BorderStyle=3` + `OutlineColour`)
- White text, rounded feel via outline padding
- Bottom-left positioning (`Alignment=1`, margins)
- Each date displays for 5 seconds at the start of its clip
- Falls back gracefully — worst case, the viewer just doesn't see dates

##### Mixed-format handling (fast stitch)

If clips come from different phones (different codecs, resolutions, or pixel
formats), stream-copy concat won't work. In that case fast stitch falls back
to **one** normalization re-encode during concat — still far better than the
current N individual re-encodes.

Detection logic:

```python
def _clips_are_homogeneous(metadata: list[VideoMeta]) -> bool:
    """Check if all clips share codec, resolution, and pixel format."""
    first = metadata[0]
    return all(
        m.codec == first.codec
        and m.width == first.width
        and m.height == first.height
        and m.pix_fmt == first.pix_fmt
        for m in metadata[1:]
    )
```

##### Files touched (fast stitch)

| File | Change |
|---|---|
| `video_service.py` | New `_generate_subtitle_track()`, new `process_videos_fast()` |

---

#### 🎬 Polished Stitch — Partial Re-Encode

Dates are permanently burned into the first ~5 seconds of each clip.
The remaining 95%+ of each clip is stream-copied untouched.

##### Pipeline

For each clip:

```
┌──────────────────────────────────────────────┐
│              Original clip (2 min)           │
│  ├── ~5 sec ─┤                               │
│  │  decode   │         untouched bytes       │
│  │  overlay  │         stream-copy           │
│  │  encode   │         (instant)             │
│  ├───────────┤───────────────────────────────│
│     HEAD              TAIL                   │
└──────────────────────────────────────────────┘
         ↓ concat -c copy ↓
┌──────────────────────────────────────────────┐
│  🗓️ date    │  rest of clip (untouched)      │
└──────────────────────────────────────────────┘
```

1. **Find the keyframe split point.** H.264/H.265 can only be cleanly cut at
   keyframe (I-frame) boundaries. Use ffprobe to find the first keyframe at
   or after the target duration (e.g. 5 seconds). Typical iPhone footage has
   keyframes every 1–2 seconds, so the actual date display will be 4–6
   seconds — close enough.

2. **Re-encode the head** (0 → keyframe) with the date overlay burned in,
   matching the source codec parameters so it splices cleanly.

3. **Stream-copy the tail** (keyframe → end) — zero decode, zero encode,
   just raw byte copying. This is where all the time savings come from.

4. **Concat head + tail** with `-c copy` into one seamless clip.

Then concat all processed clips into the final movie, also with `-c copy`.

##### Keyframe detection

```python
def _find_split_keyframe(file_path: Path, target_secs: float = 5.0) -> float:
    """Find the PTS of the first keyframe at or after target_secs."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "packet=pts_time,flags",
            "-of", "csv=p=0",
            "-read_intervals", f"{target_secs}%{target_secs + 10}",
            str(file_path),
        ],
        capture_output=True, text=True, check=False,
    )
    for line in result.stdout.strip().splitlines():
        pts, flags = line.split(",", 1)
        if "K" in flags:        # K = keyframe
            return float(pts)
    return target_secs          # fallback
```

##### Per-clip processing (pseudocode)

```python
def _process_partial(index, filename, date_text, meta):
    split_time = _find_split_keyframe(input_path, DATE_DISPLAY_SECS)

    # 1) Re-encode ONLY the head with date overlay
    #    ffmpeg -y -i input.mp4 -i overlay.png
    #        -t {split_time}
    #        -filter_complex "[overlay filters]"
    #        -map [vout] -map 0:a:0
    #        {encoder_args} head.mp4

    # 2) Stream-copy the tail (instant)
    #    ffmpeg -y -ss {split_time} -i input.mp4
    #        -c copy tail.mp4

    # 3) Splice head + tail (instant)
    #    ffmpeg -y -f concat -safe 0 -i list.txt
    #        -c copy clip_final.mp4
```

##### Short clip handling

If a clip is shorter than the target duration (e.g. a 3-second clip with a
5-second target), just re-encode the whole thing — it's tiny anyway. No split
needed.

```python
if meta.duration_secs <= DATE_DISPLAY_SECS:
    return _process_single_video_full(...)   # existing full-encode path
```

##### Mixed-format handling (polished stitch)

When clips **are** homogeneous (same phone or matching settings):
- Head: re-encode with date overlay, matching source codec params
- Tail: stream-copy
- Final concat: stream-copy
- **Fastest path — only ~5% of total frames are encoded**

When clips are **not** homogeneous (mixed phones/formats):
- Head: re-encode with date overlay to target format (1920x1080, H.264)
- Tail: re-encode to target format (no overlay — just normalization)
- Final concat: stream-copy (all segments now share the same format)
- **Still faster than current** — the tail encode is simpler (no overlay
  compositing), and this only happens with mixed-format sources

##### Files touched (polished stitch)

| File | Change |
|---|---|
| `video_service.py` | New `_find_split_keyframe()`, new `_process_partial()`, short-clip guard |

---

#### Shared config + UI for both modes

##### New config constants

```python
# config.py
DATE_DISPLAY_SECS = 5.0   # how long the date appears (both modes)
```

##### UI change

Replace the single "Start Stitching" button with a mode selector:

```
┌─────────────────────────────────────────┐
│  ⚡ Fast Stitch                         │ ← default
│     Dates as captions · instant         │
├─────────────────────────────────────────┤
│  🎬 Polished Stitch                     │
│     Dates burned in · takes longer      │
└─────────────────────────────────────────┘

        [ Start Stitching ]
```

The backend receives a `mode` parameter (`"fast"` or `"polished"`) and
branches to the corresponding pipeline.

##### Shared files touched

| File | Change |
|---|---|
| `routes.py` | Accept `mode` param in `/upload`, branch pipeline |
| `index.html` | Mode toggle UI above "Start Stitching" button |
| `models.py` | Add `mode` field (or pass via FormData) |
| `config.py` | New `DATE_DISPLAY_SECS` constant |

---

### Change 2 — Probe Once, Know Everything

**Impact: HIGH — ~67% fewer subprocess spawns**

Replace the scattered `get_creation_datetime`, `format_creation_date`, and
`_has_audio_stream` calls with a single `probe_video` function that extracts
everything in one ffprobe invocation per file.

#### New dataclass

```python
@dataclasses.dataclass(frozen=True)
class VideoMeta:
    filename: str
    creation_dt: datetime.datetime
    date_text: str           # pre-formatted for overlay/subtitle
    has_audio: bool
    duration_secs: float
    codec: str               # e.g. "h264"
    width: int
    height: int
    pix_fmt: str             # e.g. "yuv420p"
```

#### Single ffprobe call

```python
def probe_video(file_path: Path) -> VideoMeta:
    """Extract all needed metadata in one subprocess call."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams",
            str(file_path),
        ],
        capture_output=True, text=True, check=False,
    )
    data = json.loads(result.stdout)
    # ... parse creation date, streams, codec info, duration
```

One call. All the data. No redundancy.

#### Subprocess reduction

| | Before | After |
|---|---|---|
| ffprobe calls (10 videos) | ~52 | 10 |
| Total subprocesses | 63+ | 21 |

#### Files touched

| File | Change |
|---|---|
| `video_service.py` | New `probe_video()` + `VideoMeta` dataclass |
| `routes.py` | Call `probe_video` once per file after upload, pass results downstream |

---

### Change 3 — Cache the Working Encoder

**Impact: MEDIUM — eliminates wasted encode attempts**

Instead of trying HW → SW encoding for every single video, detect the working
encoder once at module load time with a 1-frame test.

```python
def _detect_working_encoder() -> list[str]:
    """Run a tiny test encode against each strategy. Return the first winner."""
    test_cmd_base = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
        "-frames:v", "1",
    ]
    for strategy in [*_HW_STRATEGIES, _SW_VIDEO_ARGS]:
        cmd = [*test_cmd_base, *strategy, "-f", "null", "-"]
        if subprocess.run(cmd, capture_output=True, check=False).returncode == 0:
            return strategy
    return _SW_VIDEO_ARGS  # ultimate fallback

_WORKING_ENCODER = _detect_working_encoder()
```

Every subsequent encode goes straight to `_WORKING_ENCODER`. No more per-video
trial and error.

#### Files touched

| File | Change |
|---|---|
| `video_service.py` | New `_detect_working_encoder()`, replace strategy loops |

---

### Change 4 — Right-Size the Worker Pool

**Impact: LOW — reduces CPU thrashing on constrained hardware**

```python
# config.py
WORKER_COUNT = max(1, os.cpu_count() // 2)   # 2 on a 4-core i5
FFMPEG_THREADS = str(os.cpu_count() // WORKER_COUNT)  # 2 threads each
```

```python
# video_service.py — process_videos()
with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
    ...
```

Two well-fed ffmpeg encodes sharing 2 cores each > eight starving encodes
fighting over everything.

Append `-threads {FFMPEG_THREADS}` to encoder args so each ffmpeg instance
knows its budget.

#### Files touched

| File | Change |
|---|---|
| `config.py` | New `WORKER_COUNT` + `FFMPEG_THREADS` constants |
| `video_service.py` | Pass `max_workers`, add `-threads` to ffmpeg args |

---

## Implementation Order

```
Change 2 (single probe)
   |
   +---> Change 1 (dual-mode stitch) <-- depends on probe data (durations, codecs)
   |       |
   |       +---> Fast stitch (subtitles)
   |       +---> Polished stitch (partial re-encode)
   |
   +---> Change 3 (cache encoder)    <-- independent, quick win
   |
   +---> Change 4 (worker pool)      <-- independent, one-liner
```

Start with Change 2 because it produces the `VideoMeta` dataclass that
both stitch modes in Change 1 depend on. Changes 3 and 4 are independent
and can land in any order.

---

## What This Plan Does NOT Include

Staying disciplined (YAGNI 🐶):

- **Single mega-ffmpeg command** — harder to report per-clip progress, more
  fragile, marginal gain over parallel subprocess encoding.
- **Segment-level parallelism** — splitting one clip across cores. Overkill
  for home videos.
- **Cross-session caching** — caching processed clips between app launches.
  Premature for a "stitch once" workflow.
- **GPU-accelerated filters** — would require CUDA/Metal filter graphs.
  Complexity explosion for marginal gains on consumer hardware.

---

## Expected Results

For a 10-clip stitch on the current hardware (i5-7360U, 8 GB RAM):

| Metric | Before | After (⚡ fast) | After (🎬 polished) |
|---|---|---|---|
| Subprocess calls | 63+ | ~12 | ~24 |
| Frames re-encoded | 100% of every clip | 0% | ~5% (head only) |
| Estimated wall time | Minutes | Seconds | Much faster than before |
| Dates visible? | Always (burned in) | Most players (subtitles) | Always (burned in) |
