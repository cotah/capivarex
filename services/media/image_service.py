"""
Image Service - Refactored with BaseService architecture.

FIX [2025-02]: O método `client.models.generate_images()` da google-genai SDK
               é SÍNCRONO (bloqueante). Chamá-lo diretamente num contexto async
               bloqueia o event loop do Railway por vários segundos, causando
               timeout da resposta HTTP antes de a imagem ser gerada.

  ANTES: response = self.client.models.generate_images(...)  ← bloqueia event loop
  DEPOIS: response = await asyncio.to_thread(
              self.client.models.generate_images, ...
          )  ← executa em thread pool, não bloqueia
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

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
    - Image generation with Imagen 4 via google-genai nova SDK
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
            self.logger.error("Failed to initialize Imagen client: %s", e)
            raise ServiceUnavailableError(f"Failed to initialize Imagen API: {e}")

    async def _health_check(self) -> bool:
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
            negative_prompt: Kept for interface compat (Imagen 4 não suporta)
            seed: Kept for interface compat (Imagen 4 não suporta)

        Returns:
            Dict with success status and image paths
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        num_images_map = {"basic": 1, "pro": 2, "enterprise": 4}
        num_images = num_images_map.get(user_plan, 1)

        try:
            from google.genai import types

            self.logger.info(
                "Generating %d image(s) with Imagen 4, prompt: %.80s...",
                num_images,
                prompt,
            )

            config = types.GenerateImagesConfig(
                number_of_images=num_images,
                aspect_ratio=aspect_ratio,
                person_generation="allow_adult",
            )

            # FIX: generate_images é síncrono na google-genai SDK.
            # Usar asyncio.to_thread para não bloquear o event loop.
            # ANTES: response = self.client.models.generate_images(...)  ← BLOQUEIA
            # DEPOIS: response = await asyncio.to_thread(...)  ← não bloqueia
            response = await asyncio.to_thread(
                self.client.models.generate_images,
                model=self.MODEL_NAME,
                prompt=prompt,
                config=config,
            )

            os.makedirs("generated_images", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved_images = []

            for idx, generated_image in enumerate(response.generated_images):
                output_path = os.path.join(
                    "generated_images", f"img_{timestamp}_{idx}.png"
                )
                with open(output_path, "wb") as f:
                    f.write(generated_image.image.image_bytes)
                saved_images.append(output_path)
                self.logger.info("Image saved: %s", output_path)

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "success": True,
                "image_paths": saved_images,
                "image_path": saved_images[0] if saved_images else None,
                "model_used": self.MODEL_NAME,
                "prompt": prompt,
                "count": len(saved_images),
            }

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.exception("Failed to generate image with Imagen: %s", e)
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
    global _image_service
    if _image_service is None:
        from services.core import get_service

        _image_service = get_service("image")
    return _image_service
