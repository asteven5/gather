"""Lightweight update checker — pings gathermovies.com/version.json on startup."""

import json
import urllib.request
import urllib.error
from typing import Optional

from config import APP_VERSION, logger

_VERSION_URL = "https://gathermovies.com/version.json"
_TIMEOUT_SECS = 5


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Convert '1.2.3' to (1, 2, 3) for comparison."""
    return tuple(int(x) for x in version_str.strip().split("."))


def check_for_update() -> Optional[dict]:
    """Check if a newer version is available.

    Returns a dict with update info if available, None otherwise.
    Fails silently on any error — no internet should never block the app.
    """
    try:
        req = urllib.request.Request(_VERSION_URL, headers={
            "User-Agent": f"Gather/{APP_VERSION}",
        })
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECS) as resp:
            data = json.loads(resp.read().decode())

        remote_version = data.get("version", "")
        if not remote_version:
            return None

        if _parse_version(remote_version) > _parse_version(APP_VERSION):
            logger.info(
                "Update available: %s → %s", APP_VERSION, remote_version,
            )
            return {
                "update_available": True,
                "current_version": APP_VERSION,
                "latest_version": remote_version,
                "download_url": data.get("download_url", "https://gathermovies.com"),
                "release_notes": data.get("release_notes", ""),
            }

        return None

    except (urllib.error.URLError, json.JSONDecodeError, ValueError, OSError) as exc:
        logger.debug("Update check failed (non-fatal): %s", exc)
        return None
