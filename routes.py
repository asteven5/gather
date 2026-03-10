"""FastAPI route handlers."""

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from config import BASE_DIR, LIBRARY_DIR, OUTPUT_DIR, UPLOAD_DIR, logger
from models import (
    DeleteVideoRequest,
    SaveToLibraryRequest,
    SelectThumbnailRequest,
    UpdateThumbnailRequest,
    YouTubeUploadRequest,
)
import youtube_service
from video_service import (
    apply_thumbnail_option,
    cleanup_uploads,
    format_creation_date,
    generate_thumbnail,
    generate_thumbnail_options,
    get_creation_datetime,
    process_videos,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main HTML page."""
    return (BASE_DIR / "index.html").read_text()


# ---------------------------------------------------------------------------
# Upload & processing
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload_videos(files: list[UploadFile] = File(...)):
    """Upload video files, process them, and stitch into a single movie."""
    try:
        cleanup_uploads()

        filenames: list[str] = []
        for file in files:
            dest = UPLOAD_DIR / file.filename
            with open(dest, "wb") as buf:
                shutil.copyfileobj(file.file, buf)
            filenames.append(file.filename)

        first_dt = get_creation_datetime(UPLOAD_DIR / filenames[0])
        year = str(first_dt.year)

        filenames.sort(key=lambda name: get_creation_datetime(UPLOAD_DIR / name))

        # Run blocking ffmpeg work off the event loop so the server stays
        # responsive to other requests while encoding.
        await asyncio.to_thread(process_videos, filenames)

        return {"status": "success", "year": year}
    except Exception as exc:
        logger.exception("Upload processing failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        for video in sorted(year_dir.glob("*.mp4"), reverse=True):
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
    """Upload a library video to YouTube."""
    video_path = LIBRARY_DIR / data.year / data.filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    if not youtube_service.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with YouTube")

    try:
        result = await asyncio.to_thread(
            youtube_service.upload_video,
            video_path,
            data.title,
            data.description,
            data.privacy,
        )
        return result
    except Exception as exc:
        logger.exception("YouTube upload failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
