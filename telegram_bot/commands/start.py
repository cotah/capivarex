"""Start command for the refactored Telegram bot.

Freemium model: user must register with email before using the bot.
Flow:
  1. /start → check if already registered
  2. If YES → welcome back
  3. If NO → ask for email → ask for name → create account → ready
"""

import logging
import re
import uuid

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from services.core import get_service
from bot.core.tenancy import TenancyManager

logger = logging.getLogger("capivarex.telegram.commands.start")

WELCOME_BACK_MESSAGE = """
🤖 **Welcome back, {name}!**

Your CAPIVAREX assistant is ready. Just type anything to get started.

Plan: **{plan}** | Use /help for all commands.
"""

REGISTRATION_ASK_EMAIL = """
🤖 **Welcome to CAPIVAREX!**

I'm your personal AI assistant — I can help with calendar, weather, finance, smart home, notes, reminders, and much more.

To get started, I need your **email address** so I can create your free account.

✉️ Please type your email:
"""

REGISTRATION_ASK_NAME = """
✅ Got it! Now, what's your **name**?

(This is how I'll address you)
"""

REGISTRATION_COMPLETE = """
🎉 **Welcome, {name}!**

Your free CAPIVAREX account is ready!

**Free plan includes:**
• 💬 ~50 AI conversations/month
• 📅 Calendar & reminders
• 🌤️ Weather & traffic
• 📊 Finance & crypto tracking
• 📝 Notes
• 🔍 5 deep research queries

Type anything to start, or use /help for all commands.

💡 _Upgrade anytime for more features: app.capivarex.com_
"""

INVALID_EMAIL = """
❌ That doesn't look like a valid email. Please try again:

✉️ Type your email address:
"""

# Simple email regex
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Registration state keys (stored in context.user_data)
STATE_KEY = "registration_state"
EMAIL_KEY = "registration_email"

# States
STATE_AWAITING_EMAIL = "awaiting_email"
STATE_AWAITING_NAME = "awaiting_name"


async def is_user_registered(telegram_id: str) -> dict | None:
    """Check if a Telegram user is registered. Returns user row or None."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return None

    return await db.get_user_by_telegram_id(telegram_id)


async def register_user(telegram_id: str, email: str, full_name: str) -> bool:
    """Create a new user account linked to Telegram.

    Returns True on success.
    """
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        user_id = str(uuid.uuid4())

        db.client.table("users").insert({
            "id": user_id,
            "email": email,
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
            "Registered Telegram user: telegram_id=%s uuid=%s email=%s name=%s",
            telegram_id, user_id[:8], email, full_name,
        )
        return True
    except Exception as e:
        logger.error("Failed to register telegram_id=%s: %s", telegram_id, e)
        return False


async def handle_registration_flow(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Handle registration conversation flow.

    Returns True if the message was consumed by registration (don't process further).
    Returns False if user is registered and message should be processed normally.
    """
    telegram_id = str(update.effective_user.id)
    state = context.user_data.get(STATE_KEY)

    # No registration in progress — check if user exists
    if not state:
        user = await is_user_registered(telegram_id)
        if user:
            return False  # Registered — process normally

        # Not registered and no state — tell them to /start
        await update.message.reply_text(
            "👋 Hi! Please use /start to create your free account first.",
            parse_mode="Markdown",
        )
        return True

    text = (update.message.text or "").strip()

    # State: waiting for email
    if state == STATE_AWAITING_EMAIL:
        if not EMAIL_PATTERN.match(text):
            await update.message.reply_text(INVALID_EMAIL, parse_mode="Markdown")
            return True

        # Check if email already exists
        db = get_service("database")
        if db and db.is_initialized():
            try:
                existing = (
                    db.client.table("users")
                    .select("id, telegram_chat_id")
                    .eq("email", text.lower())
                    .limit(1)
                    .execute()
                )
                if existing.data:
                    existing_user = existing.data[0]
                    if existing_user.get("telegram_chat_id"):
                        await update.message.reply_text(
                            "⚠️ This email is already linked to another Telegram account.\n"
                            "Please use a different email, or contact support.",
                            parse_mode="Markdown",
                        )
                        return True

                    # Email exists but no Telegram linked — link it
                    db.client.table("users").update({
                        "telegram_chat_id": telegram_id,
                    }).eq("id", existing_user["id"]).execute()

                    tenancy = TenancyManager(db)
                    await tenancy.register_telegram_user(
                        telegram_id, existing_user["id"]
                    )

                    context.user_data.pop(STATE_KEY, None)
                    context.user_data.pop(EMAIL_KEY, None)

                    await update.message.reply_text(
                        "✅ **Account linked!** Your existing CAPIVAREX account is now "
                        "connected to Telegram. Type anything to get started!",
                        parse_mode="Markdown",
                        reply_markup=ReplyKeyboardRemove(),
                    )
                    return True
            except Exception as e:
                logger.warning("Email check failed: %s", e)

        context.user_data[EMAIL_KEY] = text.lower()
        context.user_data[STATE_KEY] = STATE_AWAITING_NAME
        await update.message.reply_text(REGISTRATION_ASK_NAME, parse_mode="Markdown")
        return True

    # State: waiting for name
    if state == STATE_AWAITING_NAME:
        name = text[:100]  # Max 100 chars
        if len(name) < 2:
            await update.message.reply_text(
                "Please enter at least 2 characters for your name:"
            )
            return True

        email = context.user_data.get(EMAIL_KEY, "")
        success = await register_user(telegram_id, email, name)

        # Clear registration state
        context.user_data.pop(STATE_KEY, None)
        context.user_data.pop(EMAIL_KEY, None)

        if success:
            await update.message.reply_text(
                REGISTRATION_COMPLETE.format(name=name),
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await update.message.reply_text(
                "❌ Registration failed. Please try again with /start.",
                reply_markup=ReplyKeyboardRemove(),
            )
        return True

    return False


async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /start command.

    If user is already registered → welcome back.
    If not → start registration flow (ask for email).
    """
    logger.info(
        "/start from user_id=%s chat_id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
    )

    if not update.effective_user:
        return

    telegram_id = str(update.effective_user.id)

    # Check if already registered
    user = await is_user_registered(telegram_id)
    if user:
        name = (
            user.get("display_name") or user.get("full_name") or "there"
        )
        plan = (user.get("plan") or "free").capitalize()
        await update.message.reply_text(
            WELCOME_BACK_MESSAGE.format(name=name, plan=plan),
            parse_mode="Markdown",
        )
        return

    # Start registration flow
    context.user_data[STATE_KEY] = STATE_AWAITING_EMAIL
    await update.message.reply_text(
        REGISTRATION_ASK_EMAIL, parse_mode="Markdown"
    )


# Legacy compatibility — kept for bot.py auto-register flow
async def _ensure_user_registered(telegram_user) -> bool:
    """Check if user is registered. Does NOT auto-create anymore.

    Returns True if user exists, False if not registered.
    """
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    telegram_id = str(telegram_user.id)
    existing = await db.get_user_by_telegram_id(telegram_id)
    if existing:
        tenancy = TenancyManager(db)
        await tenancy.register_telegram_user(telegram_id, str(existing["id"]))
        return True

    return False
