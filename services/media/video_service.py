"""
Video Service - Gemini Veo 3.1 video generation.

Provides:
- Text-to-video generation via Gemini Veo 3.1
- Image-to-video generation via Gemini Veo 3.1
- Plan-based access control
- Metrics tracking
"""

import asyncio
import base64
import mimetypes
import os
import logging
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

# Veo 3.1 model variants by plan tier
PLAN_VIDEO_MODELS: Dict[str, Dict[str, Any]] = {
    "basic": {
        "model": "veo-3.1-fast-generate-preview",
        "max_duration": 5,
        "allowed_ratios": ["16:9", "9:16"],
    },
    "pro": {
        "model": "veo-3.1-generate-preview",
        "max_duration": 8,
        "allowed_ratios": ["16:9", "9:16"],
    },
    "enterprise": {
        "model": "veo-3.1-generate-preview",
        "max_duration": 8,
        "allowed_ratios": ["16:9", "9:16"],
    },
}

# Polling configuration
POLL_INTERVAL_SECONDS = 10
MAX_POLL_ATTEMPTS = 60  # 10 minutes max


@register_service("video")
class VideoService(BaseService):
    """
    Video service using Google Gemini Veo 3.1.

    Features:
    - Text-to-video (Veo 3.1 / Veo 3.1 Fast)
    - Image-to-video (Veo 3.1)
    - Plan-based access control
    - Metrics tracking
    """

    def __init__(self, name: str = "video", config: Optional[Dict[str, Any]] = None):
        """Initialise the video generation service."""
        super().__init__(name, config)
        self.client: Optional[Any] = None

    async def _initialize(self) -> None:
        """Initialize Gemini client for Veo 3.1."""
        api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            raise ServiceUnavailableError(
                "GEMINI_API_KEY must be set for video generation"
            )

        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            self.logger.info("Gemini Veo 3.1 client initialized successfully")
        except Exception as e:
            raise ServiceUnavailableError(f"Failed to initialize Gemini client: {e}")

    async def _health_check(self) -> bool:
        """Check if Video service is healthy."""
        return self.client is not None

    def validate_access(self, user_plan: str, duration: int, ratio: str) -> Dict[str, Any]:
        """
        Validate duration and ratio based on plan.

        Args:
            user_plan: User plan name
            duration: Requested duration in seconds
            ratio: Requested aspect ratio

        Returns:
            Dict with 'allowed' bool and optional 'error' string
        """
        if user_plan not in PLAN_VIDEO_MODELS:
            return {"allowed": False, "error": f"Invalid plan: {user_plan}"}

        plan_cfg = PLAN_VIDEO_MODELS[user_plan]
        if duration <= 0:
            return {"allowed": False, "error": "Duration must be greater than 0"}
        if duration > plan_cfg["max_duration"]:
            return {
                "allowed": False,
                "error": (
                    f"Duration {duration}s exceeds plan limit ({plan_cfg['max_duration']}s) "
                    f"for {user_plan} plan"
                ),
            }
        if ratio not in plan_cfg["allowed_ratios"]:
            return {
                "allowed": False,
                "error": f"Ratio '{ratio}' not allowed for {user_plan} plan",
            }

        return {"allowed": True}

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def generate_text_to_video(
        self,
        prompt: str,
        user_plan: str,
        duration: int = 5,
        ratio: str = "16:9",
    ) -> Dict[str, Any]:
        """
        Generate video from text using Gemini Veo 3.1.

        Args:
            prompt: Video generation prompt
            user_plan: User plan name
            duration: Video duration in seconds
            ratio: Aspect ratio (16:9 or 9:16)

        Returns:
            Dict with success status and video path
        """
        if not self.client:
            await self.initialize()

        access = self.validate_access(user_plan=user_plan, duration=duration, ratio=ratio)
        if not access["allowed"]:
            return {"success": False, "error": access["error"]}

        start_time = time.time()
        plan_cfg = PLAN_VIDEO_MODELS[user_plan]
        model_name = plan_cfg["model"]

        try:
            from google.genai import types

            self.logger.info(
                "Generating text-to-video with %s, prompt: %s...",
                model_name, prompt[:100]
            )

            operation = self.client.models.generate_videos(
                model=model_name,
                prompt=prompt,
                config=types.GenerateVideosConfig(
                    aspect_ratio=ratio,
                ),
            )

            # Poll until generation completes
            operation = await self._poll_operation(operation)

            # Download and save the video
            video_path = await self._save_video(operation, prefix="txt2vid")

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "success": True,
                "video_path": video_path,
                "model_used": model_name,
                "duration": duration,
                "ratio": ratio,
            }
        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("Text-to-video generation failed: %s", e, exc_info=True)
            return {"success": False, "error": f"Video generation failed: {str(e)}"}

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def generate_image_to_video(
        self,
        image_path: str,
        prompt: str,
        user_plan: str,
        duration: int = 5,
        ratio: str = "16:9",
    ) -> Dict[str, Any]:
        """
        Generate video from image using Gemini Veo 3.1.

        Args:
            image_path: Path to local image or URL
            prompt: Video generation prompt
            user_plan: User plan name
            duration: Video duration in seconds
            ratio: Aspect ratio (16:9 or 9:16)

        Returns:
            Dict with success status and video path
        """
        if not self.client:
            await self.initialize()

        access = self.validate_access(user_plan=user_plan, duration=duration, ratio=ratio)
        if not access["allowed"]:
            return {"success": False, "error": access["error"]}

        start_time = time.time()
        plan_cfg = PLAN_VIDEO_MODELS[user_plan]
        model_name = plan_cfg["model"]

        try:
            from google.genai import types

            self.logger.info(
                "Generating image-to-video with %s, image: %s",
                model_name, image_path[:80]
            )

            # Load image
            image = self._load_image(image_path)

            operation = self.client.models.generate_videos(
                model=model_name,
                prompt=prompt,
                image=image,
                config=types.GenerateVideosConfig(
                    aspect_ratio=ratio,
                ),
            )

            # Poll until generation completes
            operation = await self._poll_operation(operation)

            # Download and save the video
            video_path = await self._save_video(operation, prefix="img2vid")

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "success": True,
                "video_path": video_path,
                "model_used": model_name,
                "duration": duration,
                "ratio": ratio,
            }
        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("Image-to-video generation failed: %s", e, exc_info=True)
            return {"success": False, "error": f"Video generation failed: {str(e)}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _poll_operation(self, operation: Any) -> Any:
        """Poll a Veo operation until it completes or times out."""
        attempts = 0
        while not operation.done:
            if attempts >= MAX_POLL_ATTEMPTS:
                raise TimeoutError(
                    f"Video generation timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s"
                )
            self.logger.debug("Polling video generation... attempt %d", attempts + 1)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            operation = self.client.operations.get(operation)
            attempts += 1
        return operation

    async def _save_video(self, operation: Any, prefix: str = "vid") -> str:
        """Download and save a generated video to disk."""
        generated_video = operation.response.generated_videos[0]

        # Download the video data
        self.client.files.download(file=generated_video.video)

        # Save to generated_videos directory
        os.makedirs("generated_videos", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join("generated_videos", f"{prefix}_{timestamp}.mp4")

        generated_video.video.save(output_path)
        self.logger.info("Video saved: %s", output_path)
        return output_path

    def _load_image(self, image_path: str) -> Any:
        """Load an image for use with Veo image-to-video."""
        from google.genai import types

        if image_path.startswith(("http://", "https://")):
            # For URLs, use the image directly
            return types.Image(image_url=image_path)

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        mime_type, _ = mimetypes.guess_type(image_path)
        mime_type = mime_type or "image/png"

        return types.Image(image_bytes=image_bytes, mime_type=mime_type)


# Singleton getter
_video_service: Optional[VideoService] = None


def get_video_service() -> VideoService:
    """Get global video service instance."""
    global _video_service
    if _video_service is None:
        from services.core import get_service
        _video_service = get_service("video")
    return _video_service
