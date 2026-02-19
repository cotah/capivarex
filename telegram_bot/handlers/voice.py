"""Voice message handler for the refactored Telegram bot."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.core import get_service
from telegram_bot.utils.response_sender import send_agent_response
from utils.rate_limiter import is_rate_limited
from utils.request_context import bind_request_id

logger = logging.getLogger("capivarax.telegram.handlers.voice")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle voice messages with transcription and orchestrator processing.

    Downloads the voice file from Telegram, transcribes it using the Whisper
    service, then processes the transcribed text through the bot orchestrator.
    Sends media files when the agent response contains audio/image/video.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    bind_request_id()

    if is_rate_limited(update.effective_user.id):
        return

    logger.info(
        "Voice message received from user_id=%s chat_id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
    )

    bot = context.application.bot_data.get("capivarax_bot")
    if not bot:
        await update.message.reply_text("Bot nao inicializado.")
        return

    try:
        # Download voice file
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        # Get whisper service
        whisper = get_service("whisper")

        if not whisper or not whisper.is_initialized():
            await update.message.reply_text("Servico de transcricao nao disponivel.")
            return

        # Transcribe
        transcription = await whisper.transcribe(voice_bytes)

        if not transcription:
            await update.message.reply_text("Nao foi possivel transcrever o audio.")
            return

        # Process as text message
        user_context = {
            "user_id": update.effective_user.id,
            "chat_id": update.effective_chat.id,
            "username": update.effective_user.username,
            "input_type": "voice",
        }

        result = await bot.process_message(transcription, user_context)
        await send_agent_response(update, result)

    except Exception as e:
        logger.error("Error processing voice: %s", e, exc_info=True)
        await update.message.reply_text("Erro ao processar audio.")
