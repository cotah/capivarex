"""Location handler — saves user GPS coordinates to user_preferences."""

import logging
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from utils.request_processor import RequestProcessor
from services.business.user_preferences_service import save_location
from services.core import get_service
from bot.core.tenancy import TenancyManager

logger = logging.getLogger("capivarex.telegram.handlers.location")


async def _resolve_uuid(telegram_id: str) -> str | None:
    """Resolve Telegram ID → UUID via identity_map."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return None
        tenancy = TenancyManager(db)
        ctx = await tenancy.get_context_for_telegram(telegram_id)
        return ctx.user_id if ctx else None
    except Exception as e:
        logger.error("Failed to resolve UUID for telegram_id=%s: %s", telegram_id, e)
        return None


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle location messages sent by the user.

    Saves coordinates to user_preferences.last_latitude/last_longitude.
    If context.user_data has 'pending_location_type', saves as home or work.
    """
    processor = RequestProcessor(user_identifier=update.effective_user.id)
    if not await processor.process():
        return

    location = update.message.location
    if not location:
        return

    lat = location.latitude
    lng = location.longitude
    telegram_id = str(update.effective_user.id)

    # Resolver Telegram ID → UUID (necessário para FK em user_preferences)
    user_uuid = None

    # Primeiro tenta via processor (já resolveu durante process())
    if processor.tenant_context:
        user_uuid = processor.tenant_context.user_id

    # Fallback: resolve directamente
    if not user_uuid:
        user_uuid = await _resolve_uuid(telegram_id)

    if not user_uuid:
        logger.error("Cannot save location: no UUID for telegram_id=%s", telegram_id)
        await update.message.reply_text(
            "❌ Não consegui guardar a localização. Contacta o suporte.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Tipo de localização (last, home, work)
    location_type = context.user_data.pop("pending_location_type", "last")

    result = await save_location(user_uuid, lat, lng, location_type=location_type)

    if location_type == "home":
        msg = (
            f"🏠 Localização de *casa* guardada!\n"
            f"📍 `{lat:.5f}, {lng:.5f}`\n\n"
            f"Agora posso calcular rotas a partir de casa automaticamente."
        )
    elif location_type == "work":
        msg = (
            f"🏢 Localização de *trabalho* guardada!\n"
            f"📍 `{lat:.5f}, {lng:.5f}`\n\n"
            f"Agora posso calcular rotas a partir do trabalho automaticamente."
        )
    else:
        msg = (
            f"📍 Localização guardada!\n"
            f"`{lat:.5f}, {lng:.5f}`\n\n"
            f"Vou usar esta posição para transportes, restaurantes e muito mais."
        )

    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    logger.info(
        "Location saved for user uuid=%s telegram=%s lat=%.5f lng=%.5f type=%s result=%s",
        user_uuid,
        telegram_id,
        lat,
        lng,
        location_type,
        bool(result),
    )
