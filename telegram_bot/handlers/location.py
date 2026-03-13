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
        # Try auto-registering the user (they may not have done /start)
        try:
            from telegram_bot.commands.start import _ensure_user_registered
            if update.effective_user:
                registered = await _ensure_user_registered(update.effective_user)
                if registered:
                    user_uuid = await _resolve_uuid(telegram_id)
        except Exception:
            pass

    if not user_uuid:
        logger.warning("Cannot save location: no UUID for telegram_id=%s (unregistered user)", telegram_id)
        await update.message.reply_text(
            "❌ Não consegui guardar a localização.\n"
            "Usa /start para te registares primeiro.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Tipo de localização (last, home, work)
    location_type = context.user_data.pop("pending_location_type", "last")

    result = await save_location(user_uuid, lat, lng, location_type=location_type)

    # Reverse geocode for human-readable address & save to user_context
    address = None
    try:
        maps_svc = get_service("maps")
        if maps_svc:
            if not maps_svc.is_initialized():
                await maps_svc.initialize()
            address = await maps_svc.reverse_geocode(lat, lng)
    except Exception:
        pass

    # Save structured location context for agents
    db = get_service("database")
    if db and user_uuid:
        try:
            from datetime import datetime

            await db.save_user_context(user_uuid, "location", {
                "latitude": lat,
                "longitude": lng,
                "address": address or f"{lat},{lng}",
                "updated_at": datetime.now().isoformat(),
            })
        except Exception as exc:
            logger.error("Error saving location context: %s", exc)

    if location_type == "home":
        addr_line = f"\n📍 {address}" if address else f"\n📍 `{lat:.5f}, {lng:.5f}`"
        msg = (
            f"🏠 Localização de *casa* guardada!{addr_line}\n\n"
            f"Agora posso calcular rotas a partir de casa automaticamente."
        )
    elif location_type == "work":
        addr_line = f"\n📍 {address}" if address else f"\n📍 `{lat:.5f}, {lng:.5f}`"
        msg = (
            f"🏢 Localização de *trabalho* guardada!{addr_line}\n\n"
            f"Agora posso calcular rotas a partir do trabalho automaticamente."
        )
    else:
        addr_line = address if address else f"{lat:.4f}, {lng:.4f}"
        msg = (
            f"📍 Localização atualizada: *{addr_line}*\n\n"
            f"Agora posso calcular rotas a partir daqui!"
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
