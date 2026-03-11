"""
Shared helpers for API routes.

Provides common utilities to reduce duplication across route modules:
- ``_get_db()`` → Supabase client from the database service
- ``_get_service_or_503()`` → fetch any service or raise 503
- ``temp_upload()`` → async context manager for temp file uploads
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import HTTPException, UploadFile

from services.core import get_service


# ---------------------------------------------------------------------------
# Service resolution helpers
# ---------------------------------------------------------------------------

def _get_db():
    """Get the Supabase client from the database service.

    Raises:
        HTTPException 503: If the database service is unavailable.
    """
    db_service = get_service("database")
    if db_service is None:
        raise HTTPException(status_code=503, detail="Database service unavailable")
    return db_service.get_client()


def _get_service_or_503(name: str, label: str | None = None):
    """Retrieve a service from the registry or raise 503.

    Args:
        name: Registered service name.
        label: Human-readable name for the error message (defaults to *name*).
    """
    svc = get_service(name)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail=f"{label or name.capitalize()} service unavailable",
        )
    return svc


# ---------------------------------------------------------------------------
# Temp file upload context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def temp_upload(upload_file: UploadFile, prefix: str = "ref"):
    """Save an uploaded file to a temp directory and clean up on exit.

    Usage::

        async with temp_upload(file, prefix="video_ref") as path:
            result = await service.process(path)

    Args:
        upload_file: The FastAPI ``UploadFile`` to persist temporarily.
        prefix: Filename prefix inside ``temp_uploads/``.

    Yields:
        The absolute path to the saved temporary file.
    """
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_path = os.path.join(temp_dir, f"{prefix}_{timestamp}_{upload_file.filename}")

    try:
        content = await upload_file.read()
        with open(temp_path, "wb") as f:
            f.write(content)
        yield temp_path
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
