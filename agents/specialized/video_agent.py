"""
Video Agent - Generates videos using AI.

Refactored to use new BaseAgent architecture.
"""

import logging
from typing import Any, Dict, List

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)


@register_agent("video")
class VideoAgent(BaseAgent):
    """
    Video agent for AI video generation.

    Handles:
    - Text-to-video generation
    - Image-to-video generation
    - Different aspect ratios and durations
    """

    def __init__(self):
        super().__init__(
            name="video",
            description="Generates videos using AI"
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Generate a video from a text prompt or image.

        Args:
            prompt: User's video description
            context: Execution context with optional parameters:
                - prompt: Override video prompt
                - image_path: Path to source image (for image-to-video)
                - user_plan: User subscription plan
                - ratio: Video aspect ratio (16:9, 9:16, etc.)
                - duration: Video duration in seconds

        Returns:
            AgentResponse with video generation result
        """
        video_prompt = str(context.get("prompt") or prompt).strip()
        image_path = context.get("image_path")
        user_plan = str(context.get("user_plan") or "basic")
        ratio = str(context.get("ratio") or "16:9")

        try:
            duration = int(context.get("duration") or 5)
        except (TypeError, ValueError):
            duration = 5

        if not video_prompt:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Prompt de video vazio.",
                error="Empty video prompt"
            )

        try:
            # Get video service from registry
            video_svc = get_service("video")
            if not video_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Servico de geracao de video nao disponivel.",
                    error="Video service not available"
                )

            await video_svc.initialize()

            # Use video service's methods directly
            if image_path:
                result = await video_svc.generate_image_to_video(
                    image_path=str(image_path),
                    prompt=video_prompt,
                    user_plan=user_plan,
                    duration=duration,
                    ratio=ratio,
                )
            else:
                result = await video_svc.generate_text_to_video(
                    prompt=video_prompt,
                    user_plan=user_plan,
                    duration=duration,
                    ratio=ratio,
                )

            if isinstance(result, dict):
                success = result.get("success", True)
                if not success:
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response=result.get("error", "Erro ao gerar video."),
                        error=result.get("error", "Video generation failed"),
                        data=result
                    )

                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response="Video gerado com sucesso!",
                    data=result,
                    metadata={
                        "type": "video",
                        "file_path": result.get("video_path"),
                        "format": "mp4"
                    }
                )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Video gerado com sucesso!",
                data={"success": True, "result": result},
                metadata={"type": "video"}
            )

        except Exception as e:
            self.logger.error(
                f"VideoAgent failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao gerar video: {str(e)}",
                error=str(e)
            )

    def get_capabilities(self) -> List[str]:
        """Get video agent capabilities."""
        return [
            "text_to_video",
            "image_to_video",
            "video_generation"
        ]
