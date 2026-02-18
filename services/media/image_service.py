"""
Image Service - Refactored with BaseService architecture.

Provides:
- Image generation via Google Imagen 4 API
- Metrics tracking
"""

import os
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional

from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()

logger = logging.getLogger(__name__)


@register_service("image")
class ImageService(BaseService):
    """
    Image service for image generation using Imagen 4.

    Features:
    - Image generation with Imagen 4
    - Plan-based image count
    - Automatic retry on failures
    - Metrics tracking
    """

    MODEL_NAME: str = "imagen-4.0-generate-001"

    def __init__(self, name: str = "image", config: Optional[Dict[str, Any]] = None):
        super().__init__(name, config)
        self.api_key: Optional[str] = None
        self.client: Optional[Any] = None

    async def _initialize(self) -> None:
        """Initialize Imagen client."""
        self.api_key = os.environ.get("GEMINI_API_KEY")

        if not self.api_key:
            raise ServiceUnavailableError(
                "GEMINI_API_KEY not found in environment variables"
            )

        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
            self.logger.info("Imagen 4 client initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Imagen client: {e}")
            raise ServiceUnavailableError(f"Failed to initialize Imagen API: {e}")

    async def _health_check(self) -> bool:
        """Check if Image service is healthy."""
        return self.client is not None and self.api_key is not None

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def generate_image(
        self,
        prompt: str,
        user_plan: str,
        aspect_ratio: str = "1:1",
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate an image with Imagen 4.

        Args:
            prompt: Image generation prompt
            user_plan: User plan (basic, pro, enterprise)
            aspect_ratio: Aspect ratio (1:1, 3:4, 4:3, 9:16, 16:9)
            negative_prompt: Negative prompt (unused by Imagen 4 but kept for interface compat)
            seed: Random seed (unused by Imagen 4 but kept for interface compat)

        Returns:
            Dict with success status and image paths
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        num_images_map = {
            "basic": 1,
            "pro": 2,
            "enterprise": 4,
        }
        num_images = num_images_map.get(user_plan, 1)

        try:
            from google.genai import types

            self.logger.info(f"Generating {num_images} image(s) with Imagen 4")
            self.logger.info(f"Prompt: {prompt}")
            self.logger.info(f"Aspect ratio: {aspect_ratio}")

            config = types.GenerateImagesConfig(
                number_of_images=num_images,
                aspect_ratio=aspect_ratio,
                person_generation="allow_adult",
            )

            response = self.client.models.generate_images(
                model=self.MODEL_NAME,
                prompt=prompt,
                config=config,
            )

            os.makedirs("generated_images", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            saved_images = []
            for idx, generated_image in enumerate(response.generated_images):
                output_path = os.path.join("generated_images", f"img_{timestamp}_{idx}.png")

                with open(output_path, "wb") as f:
                    f.write(generated_image.image.image_bytes)

                saved_images.append(output_path)
                self.logger.info(f"Image saved: {output_path}")

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "success": True,
                "image_paths": saved_images,
                "image_path": saved_images[0],
                "model_used": self.MODEL_NAME,
                "prompt": prompt,
                "count": len(saved_images),
            }

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.exception(f"Failed to generate image with Imagen: {e}")
            return {
                "success": False,
                "error": f"Image generation failed: {str(e)}",
            }

    async def edit_image(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Image editing placeholder."""
        self.logger.warning("edit_image is not implemented for Imagen 4.")
        return {
            "success": False,
            "error": "Image editing is not supported in this version.",
        }


# Singleton getter
_image_service: Optional[ImageService] = None


def get_image_service() -> ImageService:
    """Get global image service instance."""
    global _image_service
    if _image_service is None:
        from services.core import get_service
        _image_service = get_service("image")
    return _image_service
