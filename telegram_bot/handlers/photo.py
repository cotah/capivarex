"""Photo handler for the Telegram bot — receipt scanning and image processing."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot.utils.response_sender import send_agent_response
from utils.request_processor import RequestProcessor

logger = logging.getLogger("capivarex.telegram.handlers.photo")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle photo messages sent by the user.

    Downloads the highest-resolution version of the photo, passes the raw
    bytes to the bot orchestrator via ``context["image_data"]``, and sends
    the agent response back to the user.

    Primary use-case: receipt / grocery-bill scanning by MercadoAgent.
    The image bytes are forwarded to the orchestrator so any agent that
    understands images (MercadoAgent, ImageAgent, DevAgent, …) can handle them.

    Args:
        update: Telegram update object containing the photo message.
        context: Telegram context object with application bot_data.
    """
    processor = RequestProcessor(user_identifier=update.effective_user.id)
    if not await processor.process():
        return

    bot = context.application.bot_data.get("capivarax_bot")
    if not bot:
        logger.warning("Photo received but bot not initialised yet")
        await update.message.reply_text("Bot não inicializado.")
        return

    # Telegram sends multiple resolutions — pick the largest (last in list)
    photos = update.message.photo
    if not photos:
        return

    photo = photos[-1]  # highest resolution

    logger.info(
        "Photo received from user_id=%s chat_id=%s file_id=%s size=%dx%d",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
        photo.file_id,
        photo.width,
        photo.height,
    )

    try:
        # Send typing indicator while processing
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="upload_photo",
        )

        # Download photo bytes
        photo_file = await photo.get_file()
        image_bytes = await photo_file.download_as_bytearray()

        # Caption (optional text the user may have added to the photo)
        caption: str = update.message.caption or ""

        user_context = {
            "user_id":    update.effective_user.id,
            "chat_id":    update.effective_chat.id,
            "username":   update.effective_user.username,
            "input_type": "photo",
            "image_data": bytes(image_bytes),
            "image_mime": "image/jpeg",
        }

        # Route through the orchestrator — MercadoAgent will pick it up
        # if the caption mentions "nota" / "recibo", otherwise falls back
        # to a generic image description via ImageAgent.
        prompt = caption if caption else "processar imagem"

        result = await bot.process_message(prompt, user_context)
        await send_agent_response(update, result)

    except Exception as e:
        logger.error("Error processing photo: %s", e, exc_info=True)
        await update.message.reply_text(
            "❌ Erro ao processar a imagem. Tenta novamente com uma foto mais nítida."
        )
