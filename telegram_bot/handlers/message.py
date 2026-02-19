"""Message handler for the refactored Telegram bot."""
import logging
from typing import Dict, Any

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot.utils.response_sender import send_agent_response
from utils.request_context import bind_request_id

logger = logging.getLogger("capivarax.telegram.handlers.message")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages by routing them through the CapivaraX bot core.

    Sends audio/image/video files when the agent response contains media,
    otherwise sends the response as text.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    bind_request_id()

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

    logger.info(
        "Message from user_id=%s chat_id=%s length=%d",
        user_context["user_id"],
        user_context["chat_id"],
        len(text),
    )

    result = await bot.process_message(text, user_context)
    await send_agent_response(update, result)
