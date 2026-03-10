"""YouTube upload service — OAuth2 authentication and video upload."""

import json
from pathlib import Path

from config import BASE_DIR, logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
TOKEN_FILE = BASE_DIR / "youtube_tokens.json"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


# ---------------------------------------------------------------------------
# Status checks
# ---------------------------------------------------------------------------
def is_configured() -> bool:
    """Return True if a client_secrets.json file exists."""
    return CLIENT_SECRETS_FILE.exists()


def is_authenticated() -> bool:
    """Return True if we have usable (valid or refreshable) credentials."""
    if not TOKEN_FILE.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        return bool(creds and (creds.valid or creds.refresh_token))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# OAuth2
# ---------------------------------------------------------------------------
def authenticate() -> None:
    """Run the installed-app OAuth2 flow (opens a browser)."""
    if not is_configured():
        raise FileNotFoundError(
            "client_secrets.json not found. "
            "Download it from the Google Cloud Console and place it "
            "in the Gather app folder."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE), SCOPES,
    )
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as fh:
        fh.write(creds.to_json())

    logger.info("YouTube authentication successful")


def _get_credentials():
    """Load credentials from disk, refreshing if expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
    return creds


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def upload_video(
    video_path: Path,
    title: str = "My Video",
    description: str = "",
    privacy: str = "private",
) -> dict:
    """Upload *video_path* to YouTube.

    Returns ``{"id": "...", "url": "https://youtube.com/watch?v=..."}``.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(
                "YouTube upload %d%% complete", int(status.progress() * 100),
            )

    video_id = response["id"]
    logger.info("YouTube upload finished — video ID: %s", video_id)

    return {
        "id": video_id,
        "url": f"https://youtube.com/watch?v={video_id}",
    }
