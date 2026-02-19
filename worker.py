# worker.py
"""
Arq Worker - Background task processing.

Handles long-running tasks like image generation in the background,
keeping the bot responsive.

Usage:
    arq worker.WorkerSettings
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Trigger service/agent registration
import services.registration  # noqa: F401
import agents.registration  # noqa: F401

from arq.connections import RedisSettings
from services.core import get_service
from utils.logger import get_logger

worker_logger = get_logger("arq_worker")


# --- TAREFAS DO WORKER ---

async def generate_image_task(ctx, prompt: str, user_id: str, user_plan: str = "basic", aspect_ratio: str = "1:1"):
    """
    Background task to generate an image using the Image service (Google Imagen 4).

    Args:
        ctx: Arq context dictionary
        prompt: Text prompt for image generation
        user_id: User identifier
        user_plan: User subscription plan (basic, pro, enterprise)
        aspect_ratio: Image aspect ratio (1:1, 16:9, etc.)
    """
    logger = ctx.get("logger", worker_logger)
    logger.info(f"Starting image generation for user {user_id} with prompt: {prompt}")

    image_service = get_service("image")
    if not image_service:
        logger.error("Image service not available for image generation.")
        return {"error": "Image service not available"}

    if not image_service.is_initialized():
        await image_service.initialize()

    try:
        result = await image_service.generate_image(
            prompt=prompt,
            user_plan=user_plan,
            aspect_ratio=aspect_ratio,
        )
        logger.info(f"Image generated successfully for user {user_id}")

        # Notify user via Telegram if possible
        try:
            from telegram_bot import send_proactive_message
            if isinstance(result, dict) and result.get("success"):
                image_path = result.get("image_path", "")
                await send_proactive_message(
                    user_id,
                    f"Sua imagem foi gerada com sucesso! Caminho: {image_path}"
                )
        except Exception as notify_err:
            logger.warning(f"Could not notify user {user_id}: {notify_err}")

        return result
    except Exception as e:
        logger.exception(f"Failed to generate image for user {user_id}: {e}")
        return {"error": str(e)}


# --- WORKER LIFECYCLE ---

async def startup(ctx):
    """Initialize services when the worker starts."""
    ctx["logger"] = worker_logger
    ctx["logger"].info("Starting arq worker and initializing services...")

    image_service = get_service("image")
    if image_service:
        await image_service.initialize()
        ctx["logger"].info("Image service initialized.")

    ctx["logger"].info("Arq worker started successfully.")


async def shutdown(ctx):
    """Cleanup when the worker shuts down."""
    logger = ctx.get("logger", worker_logger)
    logger.info("Shutting down arq worker.")


class WorkerSettings:
    """
    Arq worker settings.

    Defines available tasks, lifecycle hooks, and Redis connection.
    """
    functions = [generate_image_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379")
    )
