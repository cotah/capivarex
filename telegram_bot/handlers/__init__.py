"""Handlers for the refactored Telegram bot."""
import logging
from typing import Any

from telegram.ext import Application, MessageHandler, CommandHandler, filters

from .message import handle_message
from .voice import handle_voice
from .document import handle_document
from ..commands import (
    start_command,
    help_command,
    status_command,
)

logger = logging.getLogger("capivarax.telegram.handlers")


def register_all_handlers(application: Application, bot: Any) -> None:
    """
    Register all handlers with the Telegram application.

    Args:
        application: The python-telegram-bot Application instance.
        bot: The CapivaraXBot instance to store in bot_data.
    """
    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Store bot instance in application context
    application.bot_data["capivarax_bot"] = bot

    logger.info("All handlers registered successfully")


__all__ = ["register_all_handlers"]
