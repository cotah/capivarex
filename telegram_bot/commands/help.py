"""Help command for the refactored Telegram bot."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("capivarex.telegram.commands.help")

HELP_MESSAGE: str = """
📖 **Available Commands:**

/start - Start the bot
/help - Show this message
/status - View bot status

**How to use:**
Just send a text message and I'll process it using specialized agents!
"""


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /help command.

    Sends a message listing available commands and usage instructions.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    logger.info(
        "/help from user_id=%s chat_id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
    )
    await update.message.reply_text(HELP_MESSAGE, parse_mode="Markdown")
