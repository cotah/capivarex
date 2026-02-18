"""
Image Routes - Refactored to use services.

Endpoints for image generation and editing via the registered ``image``
service from the refactored service registry.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_current_user
from api.routes._helpers import temp_upload
from services.core import get_service

logger = logging.getLogger("capivarax.api.routes.image")

router = APIRouter()

# Valid aspect ratios supported by Imagen 4
VALID_ASPECT_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}


async def _get_image_service():
    """Resolve and lazily initialise the image service."""
    service = get_service("image")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Image service is not available",
        )
    if not service.is_initialized():
        await service.initialize()
    return service


def _validate_image_access(
    user_plan: str,
    aspect_ratio: str,
) -> Dict[str, Any]:
    """Validate that the user's plan and requested parameters are allowed."""
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        return {
            "allowed": False,
            "error": f"Invalid aspect ratio '{aspect_ratio}'. "
                     f"Allowed: {', '.join(sorted(VALID_ASPECT_RATIOS))}",
        }
    return {"allowed": True}


@router.post("/generate")
async def generate_image(
    prompt: str = Form(...),
    aspect_ratio: str = Form(default="1:1"),
    negative_prompt: Optional[str] = Form(default=None),
    seed: Optional[int] = Form(default=None),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate an image from a text prompt."""
    user_plan: str = current_user.get("plan", "enterprise")

    validation = _validate_image_access(user_plan=user_plan, aspect_ratio=aspect_ratio)
    if not validation.get("allowed"):
        raise HTTPException(status_code=403, detail=validation.get("error", "Access denied"))

    service = await _get_image_service()
    result = await service.generate_image(
        prompt=prompt,
        user_plan=user_plan,
        aspect_ratio=aspect_ratio,
        negative_prompt=negative_prompt,
        seed=seed,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Image generation failed"))

    payload: Dict[str, Any] = {
        "success": True,
        "image_path": result.get("image_path"),
        "model_used": result.get("model_used"),
        "aspect_ratio": result.get("aspect_ratio", aspect_ratio),
    }
    if "seed" in result:
        payload["seed"] = result["seed"]

    return payload


@router.post("/edit")
async def edit_image(
    prompt: str = Form(...),
    reference_image: UploadFile = File(...),
    aspect_ratio: str = Form(default="1:1"),
    negative_prompt: Optional[str] = Form(default=None),
    seed: Optional[int] = Form(default=None),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Edit an image using a reference image and a text prompt."""
    async with temp_upload(reference_image, prefix="ref") as temp_image_path:
        user_plan: str = current_user.get("plan", "enterprise")

        validation = _validate_image_access(user_plan=user_plan, aspect_ratio=aspect_ratio)
        if not validation.get("allowed"):
            raise HTTPException(status_code=403, detail=validation.get("error", "Access denied"))

        service = await _get_image_service()
        result = await service.edit_image(
            reference_image_path=temp_image_path,
            edit_prompt=prompt,
            user_plan=user_plan,
            aspect_ratio=aspect_ratio,
            negative_prompt=negative_prompt,
            seed=seed,
        )

        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Image edit failed"))

        payload: Dict[str, Any] = {
            "success": True,
            "image_path": result.get("image_path"),
            "model_used": result.get("model_used"),
            "aspect_ratio": result.get("aspect_ratio", aspect_ratio),
        }
        if "seed" in result:
            payload["seed"] = result["seed"]

        return payload
