# -*- coding: utf-8 -*-
"""
Grok Imagine Video Service
==========================
Generates videos from images or text using xAI Grok Imagine API.

- Image-to-video: User sends photo -> animated video (6-15s) with audio
- Text-to-video: User describes scene -> generated video

Uses xai_sdk which handles async polling automatically.
"""

import base64
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

from services.core import BaseService, ServiceUnavailableError, register_service

logger = logging.getLogger(__name__)


@register_service("grok_video")
class GrokVideoService(BaseService):
    """
    Video generation service using xAI Grok Imagine.

    Requires XAI_API_KEY environment variable.
    """

    def __init__(
        self,
        name: str = "grok_video",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name, config)
        self.client: Optional[Any] = None

    async def _initialize(self) -> None:
        """Initialize xAI SDK client."""
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ServiceUnavailableError("XAI_API_KEY not set")
        try:
            import xai_sdk

            self.client = xai_sdk.Client(api_key=api_key)
            self.logger.info("Grok Imagine Video client initialized")
        except ImportError:
            raise ServiceUnavailableError(
                "xai-sdk not installed. Run: pip install xai-sdk"
            )
        except Exception as e:
            raise ServiceUnavailableError(f"Failed to init Grok client: {e}")

    async def _health_check(self) -> bool:
        return self.client is not None

    @staticmethod
    def _detect_aspect_ratio(image_data: bytes) -> str:
        """Detect closest supported aspect ratio from image bytes."""
        from io import BytesIO

        from PIL import Image

        try:
            img = Image.open(BytesIO(image_data))
            w, h = img.size
        except Exception:
            return "16:9"  # fallback

        ratio = w / h

        # Grok supported ratios and their numeric values
        supported = [
            ("1:1", 1.0),
            ("3:2", 1.5),
            ("4:3", 1.333),
            ("16:9", 1.778),
            ("2:3", 0.667),
            ("3:4", 0.75),
            ("9:16", 0.5625),
        ]

        # Find closest match
        closest = min(supported, key=lambda x: abs(x[1] - ratio))
        return closest[0]

    async def image_to_video(
        self,
        image_data: bytes,
        prompt: str = "",
        duration: int = 8,
        aspect_ratio: str = "auto",
        resolution: str = "720p",
        mime_type: str = "image/jpeg",
    ) -> Dict[str, Any]:
        """
        Generate a video from image bytes (photo from Telegram).

        Args:
            image_data: Raw image bytes
            prompt: Motion/style instructions (optional)
            duration: Video length 1-15 seconds
            aspect_ratio: "auto" to detect from image, or explicit
                          (16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3)
            resolution: 720p or 480p
            mime_type: Image MIME type

        Returns:
            Dict with success, video_path, duration, provider
        """
        if not self.client:
            await self.initialize()

        # Auto-detect aspect ratio from image dimensions
        if aspect_ratio == "auto" or not aspect_ratio:
            aspect_ratio = self._detect_aspect_ratio(image_data)

        start_time = time.time()
        try:
            # Convert bytes to base64 data URI (supported by xAI API)
            b64 = base64.b64encode(image_data).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{b64}"

            effective_prompt = (
                prompt.strip()
                if prompt
                else (
                    "Animate this image with gentle, natural motion and cinematic feel"
                )
            )

            self.logger.info(
                "Grok image-to-video: prompt='%s...', duration=%ds, res=%s",
                effective_prompt[:60],
                duration,
                resolution,
            )

            response = self.client.video.generate(
                prompt=effective_prompt,
                model="grok-imagine-video",
                image_url=data_uri,
                duration=min(max(duration, 1), 15),
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                timeout=timedelta(minutes=5),
                interval=timedelta(seconds=5),
            )

            # Check moderation
            if (
                hasattr(response, "respect_moderation")
                and not response.respect_moderation
            ):
                return {
                    "success": False,
                    "error": "Video filtered by content moderation",
                }

            # Download video from temporary URL
            video_path = await self._download_video(response.url, prefix="grok_i2v")

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "success": True,
                "video_path": video_path,
                "model_used": "grok-imagine-video",
                "duration": getattr(response, "duration", duration),
                "provider": "grok",
                "latency_seconds": round(latency, 1),
            }

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("Grok image-to-video failed: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    async def text_to_video(
        self,
        prompt: str,
        duration: int = 8,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
    ) -> Dict[str, Any]:
        """
        Generate a video from text prompt only.

        Args:
            prompt: Scene description
            duration: Video length 1-15 seconds
            aspect_ratio: Aspect ratio
            resolution: 720p or 480p

        Returns:
            Dict with success, video_path, etc.
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()
        try:
            self.logger.info(
                "Grok text-to-video: prompt='%s...', duration=%ds",
                prompt[:60],
                duration,
            )

            response = self.client.video.generate(
                prompt=prompt,
                model="grok-imagine-video",
                duration=min(max(duration, 1), 15),
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                timeout=timedelta(minutes=5),
                interval=timedelta(seconds=5),
            )

            if (
                hasattr(response, "respect_moderation")
                and not response.respect_moderation
            ):
                return {
                    "success": False,
                    "error": "Video filtered by content moderation",
                }

            video_path = await self._download_video(response.url, prefix="grok_t2v")

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "success": True,
                "video_path": video_path,
                "model_used": "grok-imagine-video",
                "duration": getattr(response, "duration", duration),
                "provider": "grok",
                "latency_seconds": round(latency, 1),
            }

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("Grok text-to-video failed: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    async def _download_video(self, url: str, prefix: str = "vid") -> str:
        """Download video from temporary xAI URL and save locally."""
        os.makedirs("generated_videos", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join("generated_videos", f"{prefix}_{timestamp}.mp4")

        async with httpx.AsyncClient(timeout=120) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(resp.content)

        size_kb = os.path.getsize(output_path) / 1024
        self.logger.info("Video saved: %s (%.1f KB)", output_path, size_kb)
        return output_path
