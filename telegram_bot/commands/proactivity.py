"""Toggle proactive notifications for the current user."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services import get_service

logger = logging.getLogger("capivarex.telegram.commands.proactivity")


async def toggle_proactivity(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Toggle proactive notifications on/off for the calling user.

    Uses the ``proactivity_preferences`` table in Supabase to persist the
    setting across bot restarts.
    """
    user_id = str(update.effective_user.id)

    try:
        db = get_service("database")
        if not db:
            await update.message.reply_text("❌ Database service unavailable.")
            return

        if not db.is_initialized():
            await db.initialize()

        # Read current preference from the dedicated table
        prefs = await db.get_proactivity_preferences(user_id)

        if prefs:
            new_status = not prefs.get("enabled", False)
        else:
            new_status = True

        success = await db.update_proactivity_preferences(user_id, new_status)

        if success:
            if new_status:
                await update.message.reply_text(
                    "✅ Proactive notifications **enabled**!\n\n"
                    "You'll receive alerts about:\n"
                    "📅 Upcoming appointments\n"
                    "🌤️ Weather changes\n"
                    "🚗 Traffic conditions\n"
                    "🏠 Device status\n"
                    "🚙 Car alerts\n\n"
                    "Use /proactivity to disable.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "✅ Proactive notifications **disabled**.\n\n"
                    "Use /proactivity to re-enable.",
                    parse_mode="Markdown",
                )
        else:
            await update.message.reply_text(
                "❌ Error updating proactivity preferences."
            )

    except Exception as e:
        logger.error(
            "Error toggling proactivity for user %s: %s", user_id, e, exc_info=True
        )
        await update.message.reply_text(
            "❌ Error changing proactivity settings. Please try again."
        )
