"""
Video Routes - Refactored to use services.

Endpoints for text-to-video and image-to-video generation via the
registered ``video`` service from the refactored service registry.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_current_user
from api.routes._helpers import temp_upload
from services.core import get_service

logger = logging.getLogger("capivarex.api.routes.video")

router = APIRouter()


async def _get_video_service():
    """Resolve and lazily initialise the video service."""
    service = get_service("video")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Video service is not available",
        )
    if not service.is_initialized():
        await service.initialize()
    return service


def _validate_and_generate(service, user_plan: str, duration: int, ratio: str):
    """Validate access for video generation."""
    validation = service.validate_access(
        user_plan=user_plan,
        duration=duration,
        ratio=ratio,
    )
    if not validation.get("allowed"):
        raise HTTPException(
            status_code=403,
            detail=validation.get("error", "Access denied"),
        )


@router.post("/text-to-video")
async def text_to_video(
    prompt: str = Form(...),
    duration: int = Form(default=5),
    ratio: str = Form(default="16:9"),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate a video from a text prompt."""
    try:
        service = await _get_video_service()
        user_plan: str = current_user.get("plan", "professional")

        _validate_and_generate(service, user_plan, duration, ratio)

        result = await service.generate_text_to_video(
            prompt=prompt,
            user_plan=user_plan,
            duration=duration,
            ratio=ratio,
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Video generation failed"),
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image-to-video")
async def image_to_video(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    duration: int = Form(default=5),
    ratio: str = Form(default="16:9"),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate a video from an uploaded image and a text prompt."""
    try:
        async with temp_upload(image, prefix="video_ref") as temp_image_path:
            service = await _get_video_service()
            user_plan: str = current_user.get("plan", "professional")

            _validate_and_generate(service, user_plan, duration, ratio)

            result = await service.generate_image_to_video(
                image_path=temp_image_path,
                prompt=prompt,
                user_plan=user_plan,
                duration=duration,
                ratio=ratio,
            )

            if not result.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=result.get("error", "Video generation failed"),
                )

            return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
