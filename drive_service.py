"""Google Drive upload service — OAuth2 authentication and file upload."""

from pathlib import Path

from config import BASE_DIR, logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
TOKEN_FILE = BASE_DIR / "drive_tokens.json"

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

DRIVE_FOLDER_NAME = "Gather"


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

    logger.info("Google Drive authentication successful")


class AuthExpiredError(Exception):
    """Raised when stored credentials can no longer be refreshed."""


def _get_credentials():
    """Load credentials from disk, refreshing if expired.

    Raises ``AuthExpiredError`` when the refresh token has been revoked or
    expired (common with Google Cloud projects in *testing* mode, where
    refresh tokens only last 7 days).  The stale token file is removed so
    the next call to ``is_authenticated()`` returns ``False``.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            TOKEN_FILE.unlink(missing_ok=True)
            logger.warning("Drive refresh token expired — deleted stale token file")
            raise AuthExpiredError(
                "Your Google Drive authorization has expired. Please re-authenticate."
            )
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
    return creds


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------
def _get_or_create_folder(service, name: str) -> str:
    """Find or create a top-level Drive folder, returning its ID."""
    query = (
        f"name = '{name}' "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false"
    )
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id)")
        .execute()
    )

    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    logger.info("Created Drive folder '%s' (id=%s)", name, folder["id"])
    return folder["id"]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def upload_video(video_path: Path, title: str = "My Video") -> dict:
    """Upload *video_path* to Google Drive inside a 'Gather' folder.

    Returns ``{"id": "...", "url": "https://drive.google.com/file/d/..."}``.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _get_credentials()
    service = build("drive", "v3", credentials=creds)

    folder_id = _get_or_create_folder(service, DRIVE_FOLDER_NAME)

    filename = title if title.lower().endswith(".mp4") else f"{title}.mp4"
    file_metadata = {
        "name": filename,
        "parents": [folder_id],
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,
    )

    request = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(
                "Drive upload %d%% complete", int(status.progress() * 100),
            )

    file_id = response["id"]
    logger.info("Drive upload finished — file ID: %s", file_id)

    return {
        "id": file_id,
        "url": f"https://drive.google.com/file/d/{file_id}/view",
    }
