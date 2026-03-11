"""Photo handler for the Telegram bot — receipt scanning and image processing."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.i18n import t
from telegram_bot.utils.response_sender import send_agent_response
from utils.request_processor import RequestProcessor

logger = logging.getLogger("capivarex.telegram.handlers.photo")


async def _classify_photo(
    image_data: bytes, mime_type: str = "image/jpeg"
) -> str:
    """
    Use Gemini Flash to classify photo content for smart routing.

    Returns a descriptive prompt that helps the orchestrator route correctly.
    Cost: ~$0.001 per call, ~1s latency.
    """
    import base64
    import os

    import httpx

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning(
            "GEMINI_API_KEY not set, cannot classify photo"
        )
        return "processar imagem"

    b64 = base64.b64encode(image_data).decode()

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Classify this image in ONE short "
                            "sentence in English. "
                            "Be specific. Examples:\n"
                            "- 'This is a supermarket receipt "
                            "or grocery bill'\n"
                            "- 'This is a document or "
                            "invoice'\n"
                            "- 'This is a photo of a "
                            "person'\n"
                            "- 'This is a landscape or "
                            "scenery photo'\n"
                            "- 'This is a photo of food'\n"
                            "- 'This is a screenshot of a "
                            "code or app'\n"
                            "- 'This is a photo of an "
                            "object'\n"
                            "Respond with ONLY the "
                            "classification sentence, "
                            "nothing else."
                        )
                    },
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 256,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(
                "https://generativelanguage.googleapis.com"
                "/v1beta/models/"
                "gemini-2.5-flash"
                ":generateContent"
                f"?key={api_key}",
                json=payload,
            )

        if resp.status_code != 200:
            logger.warning(
                "Gemini classify HTTP %d",
                resp.status_code,
            )
            return "processar imagem"

        text = (
            resp.json()
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )

        if text:
            logger.info("Photo classified: %s", text)
            return (
                "The user sent a photo. "
                f"{text}. "
                "Process it accordingly."
            )

        return "processar imagem"

    except Exception as e:
        logger.warning(
            "Photo classification failed: %s", e
        )
        return "processar imagem"


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
        await update.message.reply_text(t("bot_not_initialized", lang="en"))
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
            "user_id": update.effective_user.id,
            "chat_id": update.effective_chat.id,
            "username": update.effective_user.username,
            "input_type": "photo",
            "image_data": bytes(image_bytes),
            "image_mime": "image/jpeg",
        }

        # Route through the orchestrator.
        # If caption exists, use it directly.
        # Otherwise, classify the photo via Gemini Flash for smart routing.
        if caption:
            prompt = caption
        else:
            prompt = await _classify_photo(bytes(image_bytes))

        result = await bot.process_message(prompt, user_context)
        await send_agent_response(update, result)

    except Exception as e:
        logger.error("Error processing photo: %s", e, exc_info=True)
        await update.message.reply_text(
            t("photo_processing_error", lang="en")
        )
