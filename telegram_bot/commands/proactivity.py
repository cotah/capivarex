"""Toggle proactive notifications for the current user."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services import get_service

logger = logging.getLogger("capivarex.telegram.commands.proactivity")


async def toggle_proactivity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle proactive notifications on/off for the calling user.

    Uses the ``proactivity_preferences`` table in Supabase to persist the
    setting across bot restarts.
    """
    user_id = str(update.effective_user.id)

    try:
        db = get_service("database")
        if not db:
            await update.message.reply_text("❌ Serviço de banco de dados indisponível.")
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
                    "✅ Notificações proativas **ativadas**!\n\n"
                    "Você receberá alertas sobre:\n"
                    "📅 Compromissos próximos\n"
                    "🌤️ Mudanças no clima\n"
                    "🚗 Condições de trânsito\n"
                    "🏠 Status de dispositivos\n"
                    "🚙 Alertas do carro\n\n"
                    "Use /proatividade para desativar.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "✅ Notificações proativas **desativadas**.\n\n"
                    "Use /proatividade para reativar.",
                    parse_mode="Markdown",
                )
        else:
            await update.message.reply_text(
                "❌ Erro ao atualizar preferências de proatividade."
            )

    except Exception as e:
        logger.error("Error toggling proactivity for user %s: %s", user_id, e, exc_info=True)
        await update.message.reply_text(
            "❌ Erro ao alterar configuração de proatividade. Tente novamente."
        )
