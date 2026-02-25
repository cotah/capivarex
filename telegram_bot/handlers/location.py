"""Location handler — saves user GPS coordinates to user_preferences."""

import logging
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from utils.request_processor import RequestProcessor
from services.business.user_preferences_service import save_location

logger = logging.getLogger("capivarex.telegram.handlers.location")


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle location messages sent by the user.

    Saves coordinates to user_preferences.last_latitude/last_longitude.
    If context.user_data has 'location_type', saves as home or work instead.
    """
    processor = RequestProcessor(user_identifier=update.effective_user.id)
    if not await processor.process():
        return

    location = update.message.location
    if not location:
        return

    lat = location.latitude
    lng = location.longitude
    user_id = str(update.effective_user.id)

    # Check if user was setting home or work location
    location_type = context.user_data.pop("pending_location_type", "last")

    await save_location(user_id, lat, lng, location_type=location_type)

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
        "Location saved for user %s: lat=%.5f lng=%.5f type=%s",
        user_id,
        lat,
        lng,
        location_type,
    )
