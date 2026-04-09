"""FastAPI route handlers."""

import asyncio
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from config import BASE_DIR, LIBRARY_DIR, OUTPUT_DIR, UPLOAD_DIR, logger
from models import (
    DeleteVideoRequest,
    DriveUploadRequest,
    SaveToLibraryRequest,
    SelectThumbnailRequest,
    UpdateThumbnailRequest,
    YouTubeUploadRequest,
)
import drive_service
import update_service
import youtube_service
from thumbnail_service import (
    apply_thumbnail_option,
    generate_thumbnail,
    generate_thumbnail_options,
)
from video_service import (
    StitchCancelled,
    VideoMeta,
    cleanup_uploads,
    probe_video,
    process_videos_fast,
    process_videos_polished,
)

# In-memory task tracker for long-running video processing jobs.
# Keyed by task_id → {"status": "processing"|"done"|"error", ...}
_tasks: dict[str, dict] = {}
_cancel_flags: dict[str, threading.Event] = {}

router = APIRouter()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main HTML page."""
    return (BASE_DIR / "index.html").read_text()


@router.get("/faq.js")
async def faq_js():
    """Serve the FAQ JavaScript module."""
    return FileResponse(BASE_DIR / "faq.js", media_type="application/javascript")


# ---------------------------------------------------------------------------
# Window focus (called by Dock icon reopen handler)
# ---------------------------------------------------------------------------
@router.get("/focus")
async def focus_window():
    """Bring the Gather window to the front."""
    try:
        import webview
        for w in webview.windows:
            w.restore()
            w.show()
    except Exception:
        pass
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Update check
# ---------------------------------------------------------------------------
@router.get("/check-update")
async def check_update():
    """Check if a newer version of Gather is available."""
    import asyncio
    result = await asyncio.to_thread(update_service.check_for_update)
    return result or {"update_available": False}


# ---------------------------------------------------------------------------
# Upload & processing
# ---------------------------------------------------------------------------
def _run_processing(
    task_id: str,
    metadata: list[VideoMeta],
    year: str,
    mode: str,
) -> None:
    """Background worker: process & stitch videos, then update task status."""
    cancel_event = _cancel_flags.get(task_id, threading.Event())

    def cancel_check() -> None:
        if cancel_event.is_set():
            raise StitchCancelled("Stitching cancelled by user")

    try:
        if mode == "polished":
            process_videos_polished(metadata, cancel_check=cancel_check)
        else:
            process_videos_fast(metadata, cancel_check=cancel_check)
        _tasks[task_id] = {"status": "done", "year": year}
        logger.info("Task %s finished successfully.", task_id)
    except StitchCancelled:
        _tasks[task_id] = {"status": "cancelled"}
        logger.info("Task %s was cancelled by user.", task_id)
    except Exception as exc:
        logger.exception("Task %s failed", task_id)
        _tasks[task_id] = {"status": "error", "detail": str(exc)}
    finally:
        _cancel_flags.pop(task_id, None)


@router.post("/upload")
async def upload_videos(
    files: list[UploadFile] = File(...),
    mode: str = Form("fast"),
):
    """Upload video files and kick off processing in the background.

    Accepts a ``mode`` form field: ``"fast"`` (subtitle dates, no re-encode)
    or ``"polished"`` (dates burned into the first few seconds).
    """
    try:
        cleanup_uploads()

        filenames: list[str] = []
        for file in files:
            dest = UPLOAD_DIR / file.filename
            with open(dest, "wb") as buf:
                shutil.copyfileobj(file.file, buf)
            filenames.append(file.filename)

        # Probe all videos once (Change 2).
        metadata = [probe_video(UPLOAD_DIR / name) for name in filenames]
        metadata.sort(key=lambda m: m.creation_dt)

        year = str(metadata[0].creation_dt.year)

        task_id = uuid.uuid4().hex
        _tasks[task_id] = {"status": "processing", "year": year}
        _cancel_flags[task_id] = threading.Event()

        thread = threading.Thread(
            target=_run_processing,
            args=(task_id, metadata, year, mode),
            daemon=True,
        )
        thread.start()

        return {"status": "processing", "task_id": task_id, "year": year}
    except Exception as exc:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/upload/status/{task_id}")
async def upload_status(task_id: str):
    """Poll the progress of a background video-processing task."""
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown task")
    return task


@router.post("/upload/cancel/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a running video-processing task."""
    flag = _cancel_flags.get(task_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="Unknown or already finished task")
    flag.set()
    return {"status": "cancelling"}


# ---------------------------------------------------------------------------
# Library CRUD
# ---------------------------------------------------------------------------
@router.post("/save-to-library")
async def save_to_library(data: SaveToLibraryRequest):
    """Save the processed movie to the year-based library."""
    temp_file = OUTPUT_DIR / "final_movie.mp4"
    if not temp_file.exists():
        raise HTTPException(status_code=404, detail="No processed video found")

    year_dir = LIBRARY_DIR / data.year
    year_dir.mkdir(exist_ok=True)

    final_path = year_dir / f"{data.safe_title}.mp4"
    shutil.copy(temp_file, final_path)

    thumb_path = year_dir / f"{data.safe_title}.jpg"
    generate_thumbnail(final_path, thumb_path)

    return {"status": "success"}


@router.post("/delete-video")
async def delete_video(data: DeleteVideoRequest):
    """Delete a video and its thumbnail from the library."""
    video_path = LIBRARY_DIR / data.year / data.filename
    thumb_path = LIBRARY_DIR / data.year / (Path(data.filename).stem + ".jpg")

    if video_path.exists():
        video_path.unlink()
    if thumb_path.exists():
        thumb_path.unlink()

    return {"status": "success"}


@router.post("/thumbnail-options")
async def thumbnail_options(data: DeleteVideoRequest):
    """Generate 3 thumbnail previews at different points in the video."""
    video_path = LIBRARY_DIR / data.year / data.filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    options = await asyncio.to_thread(generate_thumbnail_options, video_path)
    return {"options": options}


@router.post("/thumbnail-options-refresh")
async def thumbnail_options_refresh(data: DeleteVideoRequest):
    """Generate 3 new random thumbnail previews."""
    import random

    video_path = LIBRARY_DIR / data.year / data.filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    pcts = tuple(sorted(random.uniform(0.05, 0.95) for _ in range(3)))
    options = await asyncio.to_thread(
        generate_thumbnail_options, video_path, pcts,
    )
    return {"options": options}


@router.post("/select-thumbnail")
async def select_thumbnail(data: SelectThumbnailRequest):
    """Instantly apply an already-generated preview as the final thumbnail."""
    year_dir = LIBRARY_DIR / data.year
    video_stem = Path(data.filename).stem
    preview_file = f"thumb_option_{data.option_index}.jpg"

    try:
        apply_thumbnail_option(preview_file, year_dir, video_stem)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Preview not found")

    return {"status": "success"}


@router.get("/thumbnail-preview/{filename}")
async def thumbnail_preview(filename: str):
    """Serve a temporary thumbnail preview image."""
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid path")

    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Preview not found")

    return FileResponse(file_path)


@router.post("/update-thumbnail")
async def update_thumbnail(data: UpdateThumbnailRequest):
    """Regenerate a video thumbnail at a specific timestamp."""
    video_path = LIBRARY_DIR / data.year / data.filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    thumb_path = LIBRARY_DIR / data.year / (Path(data.filename).stem + ".jpg")
    generate_thumbnail(video_path, thumb_path, data.timestamp)

    return {"status": "success"}


@router.get("/library-data")
async def get_library_data():
    """Return all library videos organized by year."""
    if not LIBRARY_DIR.exists():
        return {}

    years: dict[str, list[dict]] = {}
    for year_dir in sorted(LIBRARY_DIR.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        videos = []
        mp4s = sorted(
            year_dir.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for video in mp4s:
            thumb_name = video.stem + ".jpg"
            videos.append({
                "title": video.stem,
                "filename": video.name,
                "thumb": thumb_name if (year_dir / thumb_name).exists() else None,
            })
        years[year_dir.name] = videos

    return years


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------
@router.get("/youtube/status")
async def youtube_status():
    """Check whether YouTube is configured and authenticated."""
    return {
        "configured": youtube_service.is_configured(),
        "authenticated": youtube_service.is_authenticated(),
    }


@router.post("/youtube/auth")
async def youtube_auth():
    """Start the YouTube OAuth2 flow (opens a browser window)."""
    try:
        await asyncio.to_thread(youtube_service.authenticate)
        return {"status": "success"}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("YouTube auth failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/youtube/upload")
async def youtube_upload(data: YouTubeUploadRequest):
    """Kick off a YouTube upload in the background and return a task ID."""
    video_path = LIBRARY_DIR / data.year / data.filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    if not youtube_service.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with YouTube")

    task_id = uuid.uuid4().hex
    _tasks[task_id] = {"status": "uploading", "service": "youtube"}

    def _worker() -> None:
        try:
            result = youtube_service.upload_video(
                video_path, data.title, data.description, data.privacy,
            )
            _tasks[task_id] = {"status": "done", "service": "youtube", **result}
        except youtube_service.AuthExpiredError as exc:
            _tasks[task_id] = {"status": "auth_expired", "detail": str(exc)}
        except Exception as exc:
            logger.exception("YouTube upload failed")
            _tasks[task_id] = {"status": "error", "detail": str(exc)}

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "uploading", "task_id": task_id}


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------
@router.get("/drive/status")
async def drive_status():
    """Check whether Google Drive is configured and authenticated."""
    return {
        "configured": drive_service.is_configured(),
        "authenticated": drive_service.is_authenticated(),
    }


@router.post("/drive/auth")
async def drive_auth():
    """Start the Google Drive OAuth2 flow (opens a browser window)."""
    try:
        await asyncio.to_thread(drive_service.authenticate)
        return {"status": "success"}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Drive auth failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/drive/upload")
async def drive_upload(data: DriveUploadRequest):
    """Kick off a Google Drive upload in the background and return a task ID."""
    video_path = LIBRARY_DIR / data.year / data.filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    if not drive_service.is_authenticated():
        raise HTTPException(
            status_code=401, detail="Not authenticated with Google Drive",
        )

    task_id = uuid.uuid4().hex
    _tasks[task_id] = {"status": "uploading", "service": "drive"}

    def _worker() -> None:
        try:
            result = drive_service.upload_video(video_path, data.title)
            _tasks[task_id] = {"status": "done", "service": "drive", **result}
        except drive_service.AuthExpiredError as exc:
            _tasks[task_id] = {"status": "auth_expired", "detail": str(exc)}
        except Exception as exc:
            logger.exception("Drive upload failed")
            _tasks[task_id] = {"status": "error", "detail": str(exc)}

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "uploading", "task_id": task_id}


@router.get("/library/{year}/{filename}")
async def get_library_file(year: str, filename: str):
    """Serve a library video or thumbnail file."""
    # Security: prevent path traversal
    if ".." in year or "/" in year or ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid path")

    file_path = LIBRARY_DIR / year / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Belt-and-suspenders: make sure resolved path stays inside the library
    if not file_path.resolve().is_relative_to(LIBRARY_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(file_path)
