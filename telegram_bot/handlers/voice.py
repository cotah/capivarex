"""Voice message handler for the refactored Telegram bot."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.core import get_service
from telegram_bot.utils.response_sender import send_agent_response
from utils.request_processor import RequestProcessor

logger = logging.getLogger("capivarex.telegram.handlers.voice")


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
    processor = RequestProcessor(user_identifier=update.effective_user.id)
    if not await processor.process():
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
        if not whisper:
            await update.message.reply_text("Servico de transcricao nao disponivel.")
            return

        # FIX BUG 1: Inicializa o serviço se ainda não foi inicializado.
        # Antes, o handler verificava is_initialized() e retornava sem tentar inicializar,
        # causando sempre "Servico de transcricao nao disponivel."
        if not whisper.is_initialized():
            try:
                await whisper.initialize()
            except Exception as init_err:
                logger.error("Falha ao inicializar WhisperService: %s", init_err)
                await update.message.reply_text(
                    "Servico de transcricao nao disponivel."
                )
                return

        # Transcribe
        # FIX BUG 2: speech_to_text_from_bytes() retorna um Dict {"text": ..., ...}.
        # Antes, o dict inteiro era passado para process_message() ao invés do texto.
        transcription_result = await whisper.speech_to_text_from_bytes(
            audio_bytes=bytes(voice_bytes),
            filename="audio.ogg",
            language="pt",
        )
        transcription_text = (transcription_result or {}).get("text", "").strip()

        if not transcription_text:
            await update.message.reply_text("Nao foi possivel transcrever o audio.")
            return

        logger.info("Transcription successful: %d chars", len(transcription_text))

        # Process as text message — use "source":"voice" (not "input_type")
        # so the orchestrator routes to chat, NOT voice agent
        user_context = {
            "user_id": update.effective_user.id,
            "chat_id": update.effective_chat.id,
            "username": update.effective_user.username,
            "source": "voice",  # FIXED: era "input_type": "voice" → causava loop no voice agent
        }

        result = await bot.process_message(transcription_text, user_context)

        # Se a resposta é texto (sem áudio), converter para voz via TTS
        has_audio = result.data and result.data.get("audio_path")
        if not has_audio and result.response:
            try:
                voice_pipeline = get_service("voice_pipeline")
                if voice_pipeline:
                    if not voice_pipeline.is_initialized():
                        await voice_pipeline.initialize()
                    tts_result = await voice_pipeline.text_to_speech(
                        text=result.response,
                        language="pt",
                    )
                    audio_path = tts_result.get("audio_path")
                    if audio_path:
                        from agents.core import AgentResponse  # noqa: F811

                        result = AgentResponse(
                            status=result.status,
                            response=result.response,
                            data={"audio_path": audio_path},
                            metadata={"type": "audio", "file_path": audio_path},
                        )
            except Exception as tts_err:
                logger.warning("TTS failed, falling back to text: %s", tts_err)

        await send_agent_response(update, result)

    except Exception as e:
        logger.error("Error processing voice: %s", e, exc_info=True)
        await update.message.reply_text("Erro ao processar audio.")
