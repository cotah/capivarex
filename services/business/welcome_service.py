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
    plan: str = "professional",
) -> bool:
    """
    Send a welcome message to a newly registered user.

    Args:
        user_id: The new user's ID
        phone: Phone number (with country code)
        name: User's name for personalization
        channel: "telegram", "whatsapp", or "both"
        plan: User's plan (professional, executive, family)

    Returns: True if at least one message was sent.
    """
    first_name = name.split()[0] if name else ""
    sent = False

    if channel in ("whatsapp", "both"):
        if plan in ("executive", "family"):
            sent = await _send_whatsapp_welcome(phone, first_name) or sent
        else:
            # Professional plan — send FOMO teaser on WhatsApp
            sent = await _send_whatsapp_fomo(phone, first_name) or sent

    if channel in ("telegram", "both"):
        sent = await _send_telegram_welcome(phone, first_name) or sent

    if sent:
        logger.info(
            "Welcome sent to user=%s on %s (plan=%s)", user_id[:8], channel, plan
        )
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

        greeting = f"Hello {name}! " if name else "Hello! "

        await send_interactive_buttons(
            to=phone,
            body_text=(
                f"{greeting}Welcome to *Capivarex*! 🎉🧠\n\n"
                "Your account was created successfully! "
                "You now have access to your personal "
                "AI assistant.\n\n"
                "What I can do for you:\n\n"
                "📅 Manage your calendar\n"
                "💰 Track finances\n"
                "📧 Organize emails\n"
                "🏠 Control your smart home\n"
                "🌤️ Weather forecast\n"
                "📦 Track packages\n\n"
                "Start by asking me anything!"
            ),
            buttons=[
                {"id": "btn_start", "title": "🚀 Get Started"},
                {"id": "btn_help", "title": "❓ What can I do?"},
                {"id": "btn_settings", "title": "⚙️ Settings"},
            ],
            header="Welcome to Capivarex! 🎉",
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
            logger.info(
                "No Telegram chat_id for phone %s, user needs to /start bot first",
                clean_phone[-4:],
            )
            return False

        chat_id = str(result.data[0]["telegram_chat_id"])
        greeting = f"Hello {name}! " if name else "Hello! "

        notif = get_service("notification")
        if notif:
            if not notif.is_initialized():
                await notif.initialize()

            msg = (
                f"{greeting}Welcome to *Capivarex*! 🎉🧠\n\n"
                "Your account was created successfully! "
                "You now have access to your personal assistant.\n\n"
                "Ask me anything or use /help to see commands."
            )
            await notif.send_message("telegram", chat_id, msg)
            return True

    except Exception as e:
        logger.warning("Telegram welcome failed: %s", e)

    return False


async def _send_whatsapp_fomo(phone: str, name: str) -> bool:
    """Send FOMO teaser to free-plan users who registered with WhatsApp."""
    try:
        from services.integrations.whatsapp_service import (
            is_configured,
            send_interactive_buttons,
        )

        if not is_configured():
            return False

        greeting = f"Hi {name}! " if name else "Hi! "

        await send_interactive_buttons(
            to=phone,
            body_text=(
                f"{greeting}Thank you for creating your *Capivarex* account! 🎉\n\n"
                "Your registration was completed successfully! 🧠\n\n"
                "Your current plan includes Capivarex on *Telegram*. "
                "To have your personal assistant here on *WhatsApp* 24/7, "
                "check out the *Everywhere* plan! 🚀\n\n"
                "✅ WhatsApp Assistant\n"
                "✅ Smart Home (voice control)\n"
                "✅ Unlimited agents\n\n"
                "Meanwhile, message me on *Telegram* — "
                "I'm waiting for you there! 💬"
            ),
            buttons=[
                {"id": "btn_upgrade", "title": "🚀 Discover Everywhere"},
                {"id": "btn_telegram", "title": "💬 Open on Telegram"},
            ],
            header="Account created successfully! 🎉",
            footer="app.capivarex.com/pricing",
        )
        return True

    except Exception as e:
        logger.warning("WhatsApp FOMO welcome failed: %s", e)
        return False
