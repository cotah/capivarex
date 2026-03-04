"""
Utility for sending agent responses with file support.

FIX [2025-02] — MESSAGE TOO LONG:
  Telegram tem limite de 4096 caracteres por mensagem.
  DevAgent gera código longo que excede este limite.
  ANTES: reply_text(response_text) → BadRequest: Message is too long
  DEPOIS: Divide em chunks de 4096 chars, respeitando quebras de linha.
"""

import logging
import os
from typing import List, Union

from telegram import Update
from telegram.constants import MessageLimit

from agents.core import AgentResponse

logger = logging.getLogger("capivarex.telegram.utils.response_sender")

# Telegram max message length
_MAX_MESSAGE_LENGTH = MessageLimit.MAX_TEXT_LENGTH  # 4096


def _split_message(text: str, max_length: int = _MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Split a long message into chunks that fit Telegram's limit.

    Tries to split at newlines first, then at spaces, then hard-cuts
    as a last resort. Preserves code blocks when possible.

    Args:
        text: The full message text.
        max_length: Maximum characters per chunk (default: 4096).

    Returns:
        List of message chunks, each ≤ max_length.
    """
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to find a good split point
        chunk = remaining[:max_length]

        # Priority 1: Split at double newline (paragraph break)
        split_pos = chunk.rfind("\n\n")
        if split_pos > max_length // 4:  # Don't split too early
            chunks.append(remaining[:split_pos].rstrip())
            remaining = remaining[split_pos:].lstrip("\n")
            continue

        # Priority 2: Split at single newline
        split_pos = chunk.rfind("\n")
        if split_pos > max_length // 4:
            chunks.append(remaining[:split_pos].rstrip())
            remaining = remaining[split_pos + 1 :]
            continue

        # Priority 3: Split at space
        split_pos = chunk.rfind(" ")
        if split_pos > max_length // 4:
            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos + 1 :]
            continue

        # Priority 4: Hard cut (last resort)
        chunks.append(remaining[:max_length])
        remaining = remaining[max_length:]

    return [c for c in chunks if c.strip()]


async def send_agent_response(
    update: Update,
    result: Union[AgentResponse, str],
) -> None:
    """
    Send an agent response to the Telegram user.

    Inspects the AgentResponse metadata/data for file paths and sends
    the appropriate media type (audio, image, video). Falls back to
    plain text if no media is detected.

    FIX: Long messages are automatically split into chunks of 4096
    characters to avoid Telegram's "Message is too long" error.

    Args:
        update: Telegram update object.
        result: AgentResponse or plain string.
    """
    # Plain string fallback (shouldn't happen normally)
    if isinstance(result, str):
        for chunk in _split_message(result):
            await update.message.reply_text(chunk)
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
        elif result.data.get("document_path"):
            media_type = "document"
            file_path = result.data.get("document_path")

    # Inline keyboard response (no file needed)
    if media_type == "inline_keyboard":
        reply_markup = result.metadata.get("reply_markup") if result.metadata else None
        if reply_markup:
            await update.message.reply_text(
                result.response or "📊",
                reply_markup=reply_markup,
            )
            logger.info("Sent inline keyboard response")
            return

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

            elif media_type == "document":
                with open(file_path, "rb") as f:
                    filename = (
                        result.metadata.get("filename", os.path.basename(file_path))
                        if result.metadata
                        else os.path.basename(file_path)
                    )
                    await update.message.reply_document(
                        document=f,
                        filename=filename,
                        caption=result.response or "",
                    )
                logger.info("Sent document file: %s", file_path)
                return

        except Exception as e:
            logger.error(
                "Failed to send media file %s: %s", file_path, e, exc_info=True
            )
            # FIX: Split the error message too if needed
            error_text = f"{result.response}\n\n(Erro ao enviar arquivo: {e})"
            for chunk in _split_message(error_text):
                await update.message.reply_text(chunk)
            return

    # Default: send as text — FIX: split long messages
    response_text = result.response or "Concluido."

    chunks = _split_message(response_text)

    if len(chunks) > 1:
        logger.info(
            "Splitting long response (%d chars) into %d chunks",
            len(response_text),
            len(chunks),
        )

    for chunk in chunks:
        try:
            await update.message.reply_text(chunk)
        except Exception as e:
            logger.error("Failed to send message chunk: %s", e)
            # Try sending a truncated version as last resort
            try:
                await update.message.reply_text(
                    chunk[:4000] + "\n\n⚠️ (mensagem truncada)"
                )
            except Exception:
                logger.error("Failed to send even truncated chunk")
