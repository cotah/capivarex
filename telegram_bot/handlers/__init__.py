"""Handlers for the refactored Telegram bot."""

import logging
from typing import Any

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .email_callback import handle_email_callback
from .mercado_callback import handle_mercado_callback
from .message import handle_message
from .voice import handle_voice
from .document import handle_document
from .photo import handle_photo
from .location import handle_location
from ..commands import (
    start_command,
    help_command,
    status_command,
)

logger = logging.getLogger("capivarex.telegram.handlers")


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
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))

    # Email inline-button callbacks (pattern: er:action:email_id)
    application.add_handler(
        CallbackQueryHandler(handle_email_callback, pattern=r"^er:")
    )

    # Mercado inline-button callbacks (pattern: mr:action:params)
    application.add_handler(
        CallbackQueryHandler(handle_mercado_callback, pattern=r"^mr:")
    )

    # Store bot instance in application context
    application.bot_data["capivarax_bot"] = bot
    logger.info("All handlers registered successfully")


__all__ = ["register_all_handlers"]
