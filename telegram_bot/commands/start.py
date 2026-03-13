"""Start command for the refactored Telegram bot."""

import logging
import uuid

from telegram import Update
from telegram.ext import ContextTypes

from services.core import get_service
from bot.core.tenancy import TenancyManager

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


async def _ensure_user_registered(telegram_user) -> bool:
    """Create user + identity_map entry if they don't exist yet.

    Returns True if the user exists (or was created), False on failure.
    """
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    telegram_id = str(telegram_user.id)

    # Check if user already exists
    existing = await db.get_user_by_telegram_id(telegram_id)
    if existing:
        # Ensure identity_map entry exists too
        tenancy = TenancyManager(db)
        await tenancy.register_telegram_user(telegram_id, str(existing["id"]))
        return True

    # Create new user
    try:
        user_id = str(uuid.uuid4())
        full_name = telegram_user.full_name or telegram_user.first_name or "Telegram User"

        db.client.table("users").insert({
            "id": user_id,
            "email": f"tg_{telegram_id}@telegram.capivarex.com",
            "full_name": full_name,
            "display_name": full_name,
            "telegram_chat_id": telegram_id,
            "plan": "free",
            "hashed_password": "",
        }).execute()

        # Create identity_map entry
        tenancy = TenancyManager(db)
        await tenancy.register_telegram_user(telegram_id, user_id)

        logger.info(
            "Auto-registered Telegram user: telegram_id=%s uuid=%s name=%s",
            telegram_id, user_id[:8], full_name,
        )
        return True
    except Exception as e:
        logger.error("Failed to auto-register telegram_id=%s: %s", telegram_id, e)
        return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start command.

    Auto-registers the user if they don't exist, then sends welcome message.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    logger.info(
        "/start from user_id=%s chat_id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
    )

    # Auto-register user on /start
    if update.effective_user:
        await _ensure_user_registered(update.effective_user)

    await update.message.reply_text(WELCOME_MESSAGE, parse_mode="Markdown")
