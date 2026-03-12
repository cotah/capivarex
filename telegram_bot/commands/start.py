"""Start command for the refactored Telegram bot."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("capivarex.telegram.commands.start")

WELCOME_MESSAGE: str = """
🤖 **Bem-vindo ao CAPIVAREX Bot!**

Sou seu assistente de IA pessoal. Posso te ajudar com:

• 💬 Conversas e perguntas gerais
• 📅 Gerenciamento de calendário
• 🌤️ Informações de clima
• 📊 Dados financeiros
• 🚗 Controle do seu carro
• 🏠 Smart home
• E muito mais!

Digite qualquer coisa para começar ou use /help para ver todos os comandos.
"""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start command.

    Sends a welcome message describing bot capabilities.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    logger.info(
        "/start from user_id=%s chat_id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
    )
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode="Markdown")
