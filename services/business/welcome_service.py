"""
Welcome Service — Sends welcome message after user registration.

When a user registers with a phone number, automatically sends a
personalized welcome message on their preferred channel (WhatsApp or Telegram).

This runs in the background (non-blocking) so registration is instant.
"""

import logging

logger = logging.getLogger(__name__)


async def send_welcome_message(
    user_id: str,
    phone: str,
    name: str = "",
    channel: str = "telegram",
) -> bool:
    """
    Send a welcome message to a newly registered user.

    Args:
        user_id: The new user's ID
        phone: Phone number (with country code)
        name: User's name for personalization
        channel: "telegram", "whatsapp", or "both"

    Returns: True if at least one message was sent.
    """
    first_name = name.split()[0] if name else ""
    sent = False

    if channel in ("whatsapp", "both"):
        sent = await _send_whatsapp_welcome(phone, first_name) or sent

    if channel in ("telegram", "both"):
        sent = await _send_telegram_welcome(phone, first_name) or sent

    if sent:
        logger.info("Welcome sent to user=%s on %s", user_id[:8], channel)
    else:
        logger.warning("Welcome failed for user=%s on %s", user_id[:8], channel)

    return sent


async def _send_whatsapp_welcome(phone: str, name: str) -> bool:
    """Send WhatsApp welcome message with interactive buttons."""
    try:
        from services.integrations.whatsapp_service import (
            is_configured,
            send_interactive_buttons,
        )

        if not is_configured():
            logger.info("WhatsApp not configured, skipping welcome")
            return False

        greeting = f"Olá {name}! " if name else "Olá! "

        await send_interactive_buttons(
            to=phone,
            body_text=(
                f"{greeting}Bem-vindo ao *Capivarex*! 🎉🧠\n\n"
                "Sua conta foi criada com sucesso! "
                "Agora você tem acesso ao seu assistente pessoal "
                "com inteligência artificial.\n\n"
                "O que posso fazer por você:\n\n"
                "📅 Gerenciar sua agenda\n"
                "💰 Acompanhar finanças\n"
                "📧 Organizar emails\n"
                "🏠 Controlar sua casa inteligente\n"
                "🌤️ Previsão do tempo\n"
                "📦 Rastrear encomendas\n\n"
                "Comece me perguntando qualquer coisa!"
            ),
            buttons=[
                {"id": "btn_start", "title": "🚀 Começar"},
                {"id": "btn_help", "title": "❓ O que posso fazer?"},
                {"id": "btn_settings", "title": "⚙️ Configurações"},
            ],
            header="Bem-vindo ao Capivarex! 🎉",
            footer="app.capivarex.com",
        )
        return True

    except Exception as e:
        logger.warning("WhatsApp welcome failed: %s", e)
        return False


async def _send_telegram_welcome(phone: str, name: str) -> bool:
    """
    Send Telegram welcome message.

    Note: Telegram bots can only message users who started a conversation first.
    So this tries to find the user's chat_id and send if available.
    If not, the user will need to start the bot on Telegram first.
    """
    try:
        from services.core import get_service

        # Look up telegram chat_id by phone
        db = get_service("database")
        if not db or not db.is_initialized():
            return False

        client = db.get_client()
        clean_phone = phone.replace("+", "").replace(" ", "")

        result = (
            client.table("users")
            .select("telegram_chat_id")
            .or_(f"phone.eq.{clean_phone},phone.eq.+{clean_phone}")
            .limit(1)
            .execute()
        )

        if not result.data or not result.data[0].get("telegram_chat_id"):
            logger.info("No Telegram chat_id for phone %s, user needs to /start bot first", clean_phone[-4:])
            return False

        chat_id = str(result.data[0]["telegram_chat_id"])
        greeting = f"Olá {name}! " if name else "Olá! "

        notif = get_service("notification")
        if notif:
            if not notif.is_initialized():
                await notif.initialize()

            msg = (
                f"{greeting}Bem-vindo ao *Capivarex*! 🎉🧠\n\n"
                "Sua conta foi criada com sucesso! "
                "Agora você tem acesso ao seu assistente pessoal.\n\n"
                "Me pergunte qualquer coisa ou use /help para ver os comandos."
            )
            await notif.send_message("telegram", chat_id, msg)
            return True

    except Exception as e:
        logger.warning("Telegram welcome failed: %s", e)

    return False
