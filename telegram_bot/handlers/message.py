"""Message handler for the refactored Telegram bot."""

import logging
from typing import Dict, Any

from telegram import Update
from telegram.ext import ContextTypes

from services import get_service
from telegram_bot.utils.response_sender import send_agent_response
from utils.request_processor import RequestProcessor

logger = logging.getLogger("capivarex.telegram.handlers.message")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages by routing them through the CapivaraX bot core.

    Sends audio/image/video files when the agent response contains media,
    otherwise sends the response as text.

    Enriches the context with GPS coordinates from Supabase when available,
    so that agents like TransportAgent can use them automatically.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    processor = RequestProcessor(user_identifier=update.effective_user.id)
    if not await processor.process():
        return

    bot = context.application.bot_data.get("capivarax_bot")
    if not bot:
        logger.warning("Message received but bot not initialized yet")
        await update.message.reply_text("Bot não inicializado.")
        return

    text: str = update.message.text
    user_context: Dict[str, Any] = {
        "user_id": update.effective_user.id,
        "chat_id": update.effective_chat.id,
        "username": update.effective_user.username,
    }

    # ── Enrich context with GPS coordinates from Supabase ───────────────
    try:
        db_svc = get_service("database")
        if db_svc and db_svc.is_initialized():
            user_row = await db_svc.get_user_by_telegram_id(
                str(update.effective_user.id)
            )
            if user_row:
                from services.business.user_preferences_service import get_location

                loc = await get_location(user_row["id"], prefer="last")
                if loc:
                    user_context["latitude"] = loc[0]
                    user_context["longitude"] = loc[1]
                    logger.info(
                        "GPS enriched for user %s: %s,%s",
                        update.effective_user.id,
                        loc[0],
                        loc[1],
                    )
    except Exception as e:
        logger.warning("Could not enrich context with GPS: %s", e)

    logger.info(
        "Message from user_id=%s chat_id=%s length=%d",
        user_context["user_id"],
        user_context["chat_id"],
        len(text),
    )

    result = await bot.process_message(text, user_context)
    await send_agent_response(update, result)
