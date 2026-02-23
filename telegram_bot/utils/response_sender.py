"""Utility for sending agent responses with file support."""
import logging
import os
from typing import Union

from telegram import Update

from agents.core import AgentResponse

logger = logging.getLogger("capivarex.telegram.utils.response_sender")


async def send_agent_response(
    update: Update,
    result: Union[AgentResponse, str],
) -> None:
    """
    Send an agent response to the Telegram user.

    Inspects the AgentResponse metadata/data for file paths and sends
    the appropriate media type (audio, image, video). Falls back to
    plain text if no media is detected.

    Args:
        update: Telegram update object.
        result: AgentResponse or plain string.
    """
    # Plain string fallback (shouldn't happen normally)
    if isinstance(result, str):
        await update.message.reply_text(result)
        return

    # Check metadata for explicit type hints
    media_type = result.metadata.get("type") if result.metadata else None
    file_path = result.metadata.get("file_path") if result.metadata else None

    # Also check data dict for file paths (voice/image/video agents)
    if not file_path and result.data:
        file_path = (
            result.data.get("audio_path")
            or result.data.get("image_path")
            or result.data.get("video_path")
        )

    # Infer media type from data keys if metadata doesn't specify it
    if not media_type and result.data:
        if result.data.get("audio_path"):
            media_type = "audio"
        elif result.data.get("image_path") or result.data.get("image_paths"):
            media_type = "image"
        elif result.data.get("video_path") or result.data.get("video_paths"):
            media_type = "video"

    # Send media if we have a valid file
    if file_path and os.path.isfile(file_path):
        try:
            if media_type == "audio":
                with open(file_path, "rb") as f:
                    await update.message.reply_voice(voice=f)
                logger.info("Sent audio file: %s", file_path)
                return

            elif media_type == "image":
                with open(file_path, "rb") as f:
                    await update.message.reply_photo(photo=f)
                # Send additional images if available
                extra_paths = result.data.get("image_paths", [])
                for extra in extra_paths:
                    if extra != file_path and os.path.isfile(extra):
                        with open(extra, "rb") as f:
                            await update.message.reply_photo(photo=f)
                logger.info("Sent image file(s): %s", file_path)
                return

            elif media_type == "video":
                with open(file_path, "rb") as f:
                    await update.message.reply_video(video=f)
                logger.info("Sent video file: %s", file_path)
                return

        except Exception as e:
            logger.error("Failed to send media file %s: %s", file_path, e, exc_info=True)
            await update.message.reply_text(
                f"{result.response}\n\n(Erro ao enviar arquivo: {e})"
            )
            return

    # Default: send as text
    response_text = result.response or "Concluido."
    await update.message.reply_text(response_text)
