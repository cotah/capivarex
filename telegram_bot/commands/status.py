"""Status command for the refactored Telegram bot."""

import logging
from typing import List

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("capivarex.telegram.commands.status")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /status command.

    Shows the current status of all initialized services and agents.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    logger.info(
        "/status from user_id=%s chat_id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
    )

    bot = context.application.bot_data.get("capivarax_bot")
    if not bot:
        logger.warning("/status called but bot not initialized")
        await update.message.reply_text("Bot não inicializado.")
        return

    services_status: List[str] = []
    for name, service in bot.services.items():
        try:
            status_icon = "✅" if service.is_initialized() else "❌"
        except Exception:
            status_icon = "⚠️"
        services_status.append(f"{status_icon} {name}")

    agents_status: List[str] = []
    for name in bot.agents.keys():
        agents_status.append(f"✅ {name}")

    services_text: str = (
        chr(10).join(services_status)
        if services_status
        else "Nenhum serviço inicializado"
    )
    agents_text: str = (
        chr(10).join(agents_status) if agents_status else "Nenhum agente inicializado"
    )

    status_message: str = f"""
🤖 **Status do CapivaraX Bot**

**Serviços:**
{services_text}

**Agentes:**
{agents_text}

**Versão:** 2.0.0 (Refatorado)
"""
    await update.message.reply_text(status_message, parse_mode="Markdown")
