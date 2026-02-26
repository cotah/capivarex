"""
Message handler for the refactored Telegram bot.

FIX [2025-02] — DEV AGENT SEM RESPOSTA:
  Problema: DevAgent levava 90s (Anthropic) + 60s (OpenAI) = 150s.
  Telegram connection morre em ~60s. User não recebia NADA.

  Correções neste arquivo:
  1. Typing indicator ("digitando...") antes de processar — feedback imediato
  2. Global safety timeout de 55s — garante SEMPRE uma resposta ao user
  3. Logging melhorado com duração da execução
"""

import asyncio
import logging
import time
from typing import Dict, Any

from telegram import Update
from telegram.ext import ContextTypes

from services import get_service
from telegram_bot.utils.response_sender import send_agent_response
from utils.request_processor import RequestProcessor

logger = logging.getLogger("capivarex.telegram.handlers.message")

# Timeout máximo para process_message — deve ser menor que o timeout HTTP
# do Telegram (que é ~60s). 55s dá margem para enviar a resposta de erro.
_MESSAGE_TIMEOUT_SECONDS = 55


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages by routing them through the CapivaraX bot core.

    Sends audio/image/video files when the agent response contains media,
    otherwise sends the response as text.

    Enriches the context with GPS coordinates from Supabase when available,
    so that agents like TransportAgent can use them automatically.

    FIX: Envia typing indicator e aplica timeout global de 55s para
    garantir que o user SEMPRE recebe uma resposta.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    processor = RequestProcessor(user_identifier=update.effective_user.id)
    if not await processor.process():
        return

    bot = context.application.bot_data.get("capivarax_bot")
    if not bot:
        logger.warning("Message received but bot not initialized yet")
        await update.message.reply_text("Bot não inicializado.")
        return

    text: str = update.message.text
    user_context: Dict[str, Any] = {
        "user_id": update.effective_user.id,
        "chat_id": update.effective_chat.id,
        "username": update.effective_user.username,
        "language_code": getattr(update.effective_user, "language_code", None) or "en",
    }

    # ── Enrich context with GPS coordinates from Supabase ───────────────
    try:
        db_svc = get_service("database")
        if db_svc and db_svc.is_initialized():
            user_row = await db_svc.get_user_by_telegram_id(
                str(update.effective_user.id)
            )
            if user_row:
                from services.business.user_preferences_service import get_location

                loc = await get_location(user_row["id"], prefer="last")
                if loc:
                    user_context["latitude"] = loc[0]
                    user_context["longitude"] = loc[1]
                    logger.info(
                        "GPS enriched for user %s: %s,%s",
                        update.effective_user.id,
                        loc[0],
                        loc[1],
                    )
    except Exception as e:
        logger.warning("Could not enrich context with GPS: %s", e)

    logger.info(
        "Message from user_id=%s chat_id=%s length=%d",
        user_context["user_id"],
        user_context["chat_id"],
        len(text),
    )

    # ── FIX: Typing indicator — feedback imediato ao user ───────────────
    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass  # Não bloquear se typing falhar

    # ── FIX: Global safety timeout — SEMPRE responde ────────────────────
    start_time = time.monotonic()
    try:
        result = await asyncio.wait_for(
            bot.process_message(text, user_context),
            timeout=_MESSAGE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start_time
        logger.error(
            "GLOBAL TIMEOUT after %.1fs for message from user %s: %s",
            elapsed,
            user_context["user_id"],
            text[:80],
        )
        await update.message.reply_text(
            "⚠️ O processamento demorou demais e foi interrompido.\n"
            "Tenta novamente — se persistir, pode ser lentidão nos "
            "serviços de IA externos."
        )
        return
    except Exception as e:
        elapsed = time.monotonic() - start_time
        logger.error(
            "Unhandled error after %.1fs processing message: %s",
            elapsed,
            e,
            exc_info=True,
        )
        await update.message.reply_text(f"⚠️ Erro inesperado ao processar mensagem: {e}")
        return

    elapsed = time.monotonic() - start_time
    logger.info(
        "Message processed in %.1fs for user %s",
        elapsed,
        user_context["user_id"],
    )

    await send_agent_response(update, result)
