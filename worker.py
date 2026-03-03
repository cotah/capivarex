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

from services.infrastructure.sentry_service import init_sentry  # noqa: E402

init_sentry()

from services.registration import register_all_services  # noqa: E402
from agents.registration import register_all_agents  # noqa: E402

register_all_services()
register_all_agents()

from arq.connections import RedisSettings  # noqa: E402
from arq import cron  # noqa: E402
from services.core import get_service  # noqa: E402
from utils.logger import get_logger  # noqa: E402

worker_logger = get_logger("arq_worker")


# --- TAREFAS DO WORKER ---


async def generate_image_task(
    ctx, prompt: str, user_id: str, user_plan: str = "basic", aspect_ratio: str = "1:1"
):
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

        # Notify user via NotificationService if possible
        try:
            notification_service = get_service("notification")
            if notification_service:
                if not notification_service.is_initialized():
                    await notification_service.initialize()
                if isinstance(result, dict) and result.get("success"):
                    image_path = result.get("image_path", "")
                    await notification_service.send_message(
                        "telegram",
                        user_id,
                        f"Sua imagem foi gerada com sucesso! Caminho: {image_path}",
                    )
        except Exception as notify_err:
            logger.warning(f"Could not notify user {user_id}: {notify_err}")

        return result
    except Exception as e:
        logger.exception(f"Failed to generate image for user {user_id}: {e}")
        return {"error": str(e)}


async def check_timers(ctx):
    """
    Verifica timers vencidos e envia notificações Telegram.
    Executada a cada 10 segundos pelo arq cron.
    """
    logger = ctx.get("logger", worker_logger)

    timer_service = get_service("timer")
    if not timer_service:
        return

    if not timer_service.is_initialized():
        await timer_service.initialize()

    notification_service = get_service("notification")
    if notification_service and not notification_service.is_initialized():
        await notification_service.initialize()

    async def notify(timer):
        """Notifica o usuário quando o timer vence."""
        icons = {"timer": "⏱️", "alarm": "⏰", "remind": "🔔"}
        icon = icons.get(timer.timer_type, "⏱️")

        if timer.timer_type == "alarm":
            message = f"{icon} **Bom dia!** Seu alarme disparou!"
        elif timer.timer_type == "remind":
            message = f"{icon} **Lembrete:** {timer.label}"
        else:
            message = f"{icon} **Timer concluído!** {timer.label}"

        if notification_service:
            try:
                await notification_service.send_message(
                    "telegram",
                    timer.chat_id,
                    message,
                )
                logger.info(
                    "Timer %s fired for user %s",
                    timer.timer_id,
                    timer.user_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to notify timer %s: %s",
                    timer.timer_id,
                    e,
                )

    fired = await timer_service.check_and_fire_due(notify_fn=notify)
    if fired:
        logger.info("check_timers: %d timer(s) fired", len(fired))


async def check_reminders(ctx):
    """
    Verifica lembretes vencidos e envia notificações Telegram.
    Executada a cada 30 segundos pelo arq cron.
    """
    logger = ctx.get("logger", worker_logger)

    reminder_service = get_service("reminder")
    if not reminder_service:
        return
    if not reminder_service.is_initialized():
        await reminder_service.initialize()

    notification_service = get_service("notification")
    if notification_service and not notification_service.is_initialized():
        await notification_service.initialize()

    async def notify(reminder):
        message = f"🔔 **Lembrete:** {reminder['message']}"
        if reminder.get("recurrence"):
            from services.business.reminder_service import ReminderService

            rec_label = ReminderService.format_recurrence(reminder["recurrence"])
            message += f"\n🔁 _{rec_label}_"

        if notification_service:
            try:
                await notification_service.send_message(
                    "telegram",
                    reminder["chat_id"],
                    message,
                )
                logger.info(
                    "Reminder %s fired for user %s",
                    reminder["id"][:8],
                    reminder["user_id"],
                )
            except Exception as e:
                logger.error("Failed to notify reminder %s: %s", reminder["id"][:8], e)

    fired = await reminder_service.check_and_fire_due(notify_fn=notify)
    if fired:
        logger.info("check_reminders: %d reminder(s) fired", len(fired))


# --- WORKER LIFECYCLE ---


async def startup(ctx):
    """Initialize services when the worker starts."""
    ctx["logger"] = worker_logger
    ctx["logger"].info("Starting arq worker and initializing services...")

    image_service = get_service("image")
    if image_service:
        await image_service.initialize()
        ctx["logger"].info("Image service initialized.")

    timer_service = get_service("timer")
    if timer_service:
        await timer_service.initialize()
        ctx["logger"].info("Timer service initialized.")

    reminder_service = get_service("reminder")
    if reminder_service:
        await reminder_service.initialize()
        ctx["logger"].info("Reminder service initialized.")

    ctx["logger"].info("Arq worker started successfully.")


async def shutdown(ctx):
    """Cleanup when the worker shuts down."""
    logger = ctx.get("logger", worker_logger)
    logger.info("Shutting down arq worker.")


class WorkerSettings:
    """
    Arq worker settings.

    Defines available tasks, lifecycle hooks, and Redis connection.
    Uses REDIS_URL for the arq socket connection (required by arq internals).
    The application code itself routes through Upstash REST via RedisService.
    """

    functions = [generate_image_task, check_timers, check_reminders]
    cron_jobs = [
        cron(check_timers, second={0, 10, 20, 30, 40, 50}),  # a cada 10s
        cron(check_reminders, second={0, 30}),  # a cada 30s
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379")
    )
