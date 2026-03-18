"""
Image Service - Refactored with BaseService architecture.

FIX [2025-02]:
  1. O método `client.models.generate_images()` da google-genai SDK é SÍNCRONO.
     Usar asyncio.to_thread para não bloquear o event loop.
  2. Sempre gera 1 imagem (não 2 ou 4). Utilizador controla se quer mais.
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
    - Always generates 1 image (clean, no collage)
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

        SEMPRE gera 1 imagem. Se o utilizador quiser mais,
        pode pedir explicitamente.

        Args:
            prompt: Image generation prompt
            user_plan: User plan (basic, pro, enterprise)
            aspect_ratio: Aspect ratio (1:1, 3:4, 4:3, 9:16, 16:9)
            negative_prompt: Kept for interface compat
            seed: Kept for interface compat

        Returns:
            Dict with success status and image paths
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        # FIX: Sempre 1 imagem. Antes era 2 para pro e 4 para enterprise,
        # o que causava colagens e múltiplas fotos indesejadas.
        num_images = 1

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
            self.logger.warning("Imagen 4 failed, trying DALL-E fallback: %s", e)

            # ── DALL-E 3 fallback ────────────────────────────────────────
            try:
                dalle_result = await self._generate_with_dalle(
                    prompt=prompt, aspect_ratio=aspect_ratio
                )
                if dalle_result and dalle_result.get("success"):
                    return dalle_result
            except Exception as dalle_err:
                self.logger.error("DALL-E fallback also failed: %s", dalle_err)

            return {
                "success": False,
                "error": f"Image generation failed (Gemini + DALL-E): {str(e)}",
            }

    async def _generate_with_dalle(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> Dict[str, Any]:
        """Fallback: generate image with DALL-E 3 via OpenAI."""
        import httpx
        from openai import AsyncOpenAI

        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key:
            return {"success": False, "error": "OPENAI_API_KEY not set"}

        # Map aspect ratios to DALL-E sizes
        size_map = {
            "1:1": "1024x1024",
            "16:9": "1792x1024",
            "9:16": "1024x1792",
            "4:3": "1024x1024",  # closest supported
            "3:4": "1024x1792",  # closest supported
        }
        size = size_map.get(aspect_ratio, "1024x1024")

        start = time.time()
        client = AsyncOpenAI(api_key=openai_key)

        self.logger.info(
            "DALL-E 3 fallback: prompt='%s...', size=%s", prompt[:60], size
        )

        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size=size,
            quality="standard",
        )

        image_url = response.data[0].url
        if not image_url:
            return {"success": False, "error": "DALL-E returned no image URL"}

        # Download the image
        async with httpx.AsyncClient(timeout=30) as http:
            img_resp = await http.get(image_url)
            img_resp.raise_for_status()

        os.makedirs("generated_images", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join("generated_images", f"dalle_{timestamp}.png")

        with open(output_path, "wb") as f:
            f.write(img_resp.content)

        self.logger.info(
            "DALL-E fallback image saved: %s (%.1fs)", output_path, time.time() - start
        )

        return {
            "success": True,
            "image_paths": [output_path],
            "image_path": output_path,
            "model_used": "dall-e-3",
            "prompt": prompt,
            "count": 1,
            "fallback": True,
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
