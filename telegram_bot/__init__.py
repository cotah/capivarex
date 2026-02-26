"""CapivaraX Telegram Bot Package."""

__version__ = "2.0.0"

import os
import logging
from telegram import Bot

logger = logging.getLogger("capivarex.telegram")


async def send_proactive_message(chat_id: str, text: str) -> bool:
    """Send a proactive message to a Telegram chat.

    Used by the proactivity loop to push notifications
    to users without them initiating a conversation.

    Args:
        chat_id: The Telegram chat ID to send to.
        text: The message text.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN missing; cannot send proactive message.")
        return False

    try:
        bot_client = Bot(token=token)
        await bot_client.send_message(chat_id=chat_id, text=text)
        return True
    except Exception:
        logger.exception("Failed to send proactive message to chat %s", chat_id)
        return False


__all__ = [
    "__version__",
    "send_proactive_message",
]
