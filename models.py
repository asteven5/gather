"""Pydantic request models with input validation."""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel


# ---------------------------------------------------------------------------
# Reusable validated types (DRY > copy-pasting validators)
# ---------------------------------------------------------------------------
def _check_year(value: str) -> str:
    if not re.match(r"^\d{4}$", value):
        raise ValueError("Year must be a 4-digit string")
    return value


def _check_safe_filename(value: str) -> str:
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError("Invalid filename — path traversal not allowed")
    return value


def _check_timestamp(value: str) -> str:
    if not re.match(r"^\d{2}:\d{2}:\d{2}$", value):
        raise ValueError("Timestamp must be HH:MM:SS format")
    return value


Year = Annotated[str, AfterValidator(_check_year)]
SafeFilename = Annotated[str, AfterValidator(_check_safe_filename)]
Timestamp = Annotated[str, AfterValidator(_check_timestamp)]


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class SaveToLibraryRequest(BaseModel):
    year: Year
    title: str = "My Movie"

    @property
    def safe_title(self) -> str:
        sanitized = "".join(
            c for c in self.title if c.isalnum() or c in (" ", "_")
        ).rstrip()
        return sanitized or "My Movie"


class DeleteVideoRequest(BaseModel):
    year: Year
    filename: SafeFilename


class UpdateThumbnailRequest(BaseModel):
    year: Year
    filename: SafeFilename
    timestamp: Timestamp = "00:00:01"


class SelectThumbnailRequest(BaseModel):
    year: Year
    filename: SafeFilename
    option_index: int


class YouTubeUploadRequest(BaseModel):
    year: Year
    filename: SafeFilename
    title: str = "My Video"
    description: str = ""
    privacy: str = "private"
