"""
Image Agent - Generates images using AI.
Refactored to use new BaseAgent architecture.
Supports background generation via arq task queue.

FIX [2025-02]: Imagen 4 prompt engineering
  - Prevent text/labels on generated images
  - Force single clean image (no collages)
"""

import logging
import os
import re
from typing import Any, Dict, List

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang

logger = logging.getLogger(__name__)

# ── Prompt enhancement ────────────────────────────────────────────────────────

_NEGATIVE_SUFFIX = (
    "Do not include any text, words, letters, labels, captions, titles, "
    "watermarks, signatures, or writing on the image. "
    "Single subject, clean composition, no collage, no grid, no split image, "
    "no multiple panels."
)

_CLEANUP_PATTERNS = [
    r"\b(crie?|cria|gere?|gera|faz|faça|faze?r|criar?)\b",
    r"\b(uma?\s+)?imagem\s+(de|do|da|dos|das)?\b",
    r"\b(uma?\s+)?foto\s+(de|do|da|dos|das)?\b",
    r"\b(uma?\s+)?ilustração\s+(de|do|da|dos|das)?\b",
    r"\b(por favor|please|pf)\b",
]


def _enhance_prompt(raw_prompt: str) -> str:
    """
    Limpa o prompt do utilizador antes de enviar ao Imagen 4.

    1. Remove verbos de comando (crie, gere, faça) que confundem o modelo
    2. Adiciona instrução para NÃO colocar texto/labels na imagem
    3. Adiciona instrução para NÃO fazer colagem/grid
    """
    cleaned = raw_prompt.strip()

    # Remove palavras de comando em português
    for pattern in _CLEANUP_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    # Remove espaços duplos
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

    # Se ficou vazio depois da limpeza, usa o original
    if len(cleaned) < 3:
        cleaned = raw_prompt.strip()

    # Adiciona instrução anti-texto e anti-colagem
    enhanced = f"{cleaned}. {_NEGATIVE_SUFFIX}"

    return enhanced


@register_agent("image")
class ImageAgent(BaseAgent):
    """
    Image agent for AI image generation.

    Handles:
    - Image generation from text prompts
    - Different aspect ratios
    - Plan-based model selection
    - Prompt enhancement (no text overlays, no collages)
    """

    def __init__(self):
        """Initialise the image agent."""
        super().__init__(name="image", description="Generates images using AI")

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Generate an image from a text prompt."""
        lang = get_user_lang(context)
        image_prompt = str(context.get("prompt") or prompt).strip()
        user_plan = str(context.get("user_plan") or "basic")
        aspect_ratio = str(context.get("aspect_ratio") or "1:1")
        user_id = str(context.get("user_id", "unknown"))
        use_queue = context.get("use_queue", False)

        if not image_prompt:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("image_empty_prompt", lang=lang),
                error="Empty image prompt",
            )

        # ── LIMPA O PROMPT ─────────────────────────────────────────────
        enhanced_prompt = _enhance_prompt(image_prompt)
        self.logger.info(
            "Image prompt enhanced: '%s' → '%s'",
            image_prompt[:60],
            enhanced_prompt[:80],
        )
        # ───────────────────────────────────────────────────────────────

        # If queue mode is requested and Redis is available, enqueue the task
        if use_queue:
            return await self._enqueue_image_task(
                enhanced_prompt, user_id, user_plan, aspect_ratio
            )

        try:
            # Get image service from registry
            image_svc = get_service("image")
            if not image_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("image_service_unavailable", lang=lang),
                    error="Image service not available",
                )

            await image_svc.initialize()

            # Gera a imagem com o prompt limpo
            result = await image_svc.generate_image(
                prompt=enhanced_prompt,
                user_plan=user_plan,
                aspect_ratio=aspect_ratio,
            )

            if isinstance(result, dict):
                success = result.get("success", True)
                if not success:
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response=result.get("error", "Erro ao gerar imagem."),
                        error=result.get("error", "Image generation failed"),
                        data=result,
                    )

                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response="Imagem gerada com sucesso!",
                    data=result,
                    metadata={
                        "type": "image",
                        "file_path": result.get("image_path"),
                        "format": "png",
                    },
                )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Imagem gerada com sucesso!",
                data={"success": True, "result": result},
                metadata={"type": "image"},
            )

        except Exception as e:
            self.logger.error(f"ImageAgent failed: {e}", exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao gerar imagem: {str(e)}",
                error=str(e),
            )

    async def _enqueue_image_task(
        self,
        prompt: str,
        user_id: str,
        user_plan: str,
        aspect_ratio: str,
    ) -> AgentResponse:
        """Enqueue image generation as a background task via arq + Upstash REST."""
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            redis_settings = RedisSettings.from_dsn(redis_url)
            redis = await create_pool(redis_settings)

            await redis.enqueue_job(
                "generate_image_task",
                prompt=prompt,
                user_id=user_id,
                user_plan=user_plan,
                aspect_ratio=aspect_ratio,
            )

            self.logger.info(f"Image generation task enqueued for user {user_id}")

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Entendido! Estou gerando sua imagem em segundo plano. Avisarei quando estiver pronta!",
                data={"queued": True, "prompt": prompt},
                metadata={"type": "image_queued"},
            )

        except Exception as e:
            # Try the Upstash REST adapter as fallback
            try:
                from utils.worker_redis_adapter import ArqRedisRestAdapter
                import json
                import time

                adapter = ArqRedisRestAdapter()
                await adapter.initialize()
                payload = json.dumps(
                    {
                        "function": "generate_image_task",
                        "args": [],
                        "kwargs": {
                            "prompt": prompt,
                            "user_id": user_id,
                            "user_plan": user_plan,
                            "aspect_ratio": aspect_ratio,
                        },
                    }
                ).encode()
                job_id = f"img_{user_id}_{int(time.time())}"
                await adapter.enqueue_job("default", job_id, payload, int(time.time()))

                self.logger.info(
                    f"Image task enqueued via REST adapter for user {user_id}"
                )

                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response="Entendido! Estou gerando sua imagem em segundo plano. Avisarei quando estiver pronta!",
                    data={"queued": True, "prompt": prompt},
                    metadata={"type": "image_queued"},
                )
            except Exception as adapter_err:
                self.logger.warning(
                    f"Failed to enqueue via both socket ({e}) and REST adapter ({adapter_err}). "
                    "Falling back to direct generation."
                )
                return await self.execute(
                    prompt,
                    {
                        "prompt": prompt,
                        "user_plan": user_plan,
                        "aspect_ratio": aspect_ratio,
                        "user_id": user_id,
                        "use_queue": False,
                    },
                )

    def get_capabilities(self) -> List[str]:
        """Get image agent capabilities."""
        return ["image_generation", "ai_art", "text_to_image"]
