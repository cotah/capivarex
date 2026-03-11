"""
Static media serving — exposes generated images and videos to the webapp.

GET /api/images/{filename} returns files from ``generated_images/``.
GET /api/videos/{filename} returns files from ``generated_videos/``.

No authentication is required; filenames are timestamp/UUID-based and
not guessable.
"""

import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

# Only allow safe filenames: alphanumeric, hyphens, underscores, dots
_SAFE_FILENAME = re.compile(r"^[\w\-]+\.\w+$")

# Supported media types
_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}

_IMAGES_DIR = os.path.join(os.getcwd(), "generated_images")
_VIDEOS_DIR = os.path.join(os.getcwd(), "generated_videos")


def _serve_file(filename: str, base_dir: str, media_types: dict, default_type: str):
    """Validate and return a FileResponse for a media file.

    Path-traversal is prevented by validating the filename against a
    strict regex and checking the resolved path stays inside *base_dir*.
    """
    if not _SAFE_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = os.path.join(base_dir, filename)

    # Prevent path traversal (belt-and-suspenders)
    real_path = os.path.realpath(path)
    real_dir = os.path.realpath(base_dir)
    if not real_path.startswith(real_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")

    ext = os.path.splitext(filename)[1].lower()
    media_type = media_types.get(ext, default_type)

    return FileResponse(path, media_type=media_type)


@router.get("/api/images/{filename}")
async def serve_image(filename: str):
    """Serve a generated image by filename."""
    return _serve_file(filename, _IMAGES_DIR, _IMAGE_MEDIA_TYPES, "image/png")


@router.get("/api/videos/{filename}")
async def serve_video(filename: str):
    """Serve a generated video by filename."""
    return _serve_file(filename, _VIDEOS_DIR, _VIDEO_MEDIA_TYPES, "video/mp4")
