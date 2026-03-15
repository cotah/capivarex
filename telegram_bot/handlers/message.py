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

import sentry_sdk
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
    Handle text messages by routing them through the CAPIVAREX bot core.

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

    # ── Registration gate — unregistered users must complete signup first ──
    try:
        from telegram_bot.commands.start import handle_registration_flow
        consumed = await handle_registration_flow(update, context)
        if consumed:
            return  # Message was part of registration flow
    except Exception as e:
        logger.warning("Registration check failed: %s", e)

    bot = context.application.bot_data.get("capivarax_bot")
    if not bot:
        logger.warning("Message received but bot not initialized yet")
        await update.message.reply_text("Bot não inicializado.")
        return

    text: str = update.message.text

    # ── Email edit-mode interception ──────────────────────────────────────
    try:
        redis = get_service("redis")
        if redis:
            edit_key = f"email:editing:{update.effective_chat.id}"
            edit_state = await redis.get(edit_key, parse_json=True)
            if edit_state and isinstance(edit_state, dict):
                await redis.delete(edit_key)
                await _handle_email_edit_reply(update, edit_state, text)
                return
    except Exception as e:
        logger.debug("Email edit-mode check failed: %s", e)

    # ── Pending location save interception ──────────────────────────────
    # Same pattern as email edit-mode: if a maps agent asked "where is
    # your home?", the user's next message is the address answer.
    try:
        redis = get_service("redis")
        if redis:
            pending_key = f"pending:location:{update.effective_chat.id}"
            pending = await redis.get(pending_key, parse_json=True)
            if pending and isinstance(pending, dict):
                await redis.delete(pending_key)
                await _handle_pending_location_save(
                    update, context, pending, text
                )
                return
    except Exception as e:
        logger.warning("Pending location check failed: %s", e)

    user_context: Dict[str, Any] = {
        "user_id": update.effective_user.id,
        "chat_id": update.effective_chat.id,
        "username": update.effective_user.username,
        "language_code": getattr(update.effective_user, "language_code", None) or "en",
        "message_text": text,
    }

    # ── Enrich context with GPS coordinates from Supabase ───────────────
    db_svc = None
    user_row = None
    try:
        db_svc = get_service("database")
        if db_svc and db_svc.is_initialized():
            user_row = await db_svc.get_user_by_telegram_id(
                str(update.effective_user.id)
            )
            if user_row:
                user_uuid = user_row.get("id") or user_row.get("user_id")

                # Inject preferred_language so agents use correct lang
                pref_lang = user_row.get("preferred_language")
                if pref_lang:
                    user_context["user_preferences"] = {
                        "preferred_language": pref_lang,
                    }

                # Location preference (text address from profile)
                loc_pref = user_row.get("location_preference", "")
                if loc_pref:
                    user_context["user_location"] = loc_pref

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

                # Saved location context (from Telegram location share)
                if user_uuid and not user_context.get("latitude"):
                    saved_loc = await db_svc.get_user_context(
                        user_uuid, "location"
                    )
                    if saved_loc and isinstance(saved_loc, dict):
                        user_context.setdefault(
                            "latitude", saved_loc.get("latitude")
                        )
                        user_context.setdefault(
                            "longitude", saved_loc.get("longitude")
                        )
                        if (
                            not user_context.get("user_location")
                            and saved_loc.get("address")
                        ):
                            user_context["user_location"] = saved_loc[
                                "address"
                            ]
    except Exception as e:
        logger.warning("Could not enrich context with GPS: %s", e)

    # ── Auto-detect and persist language ──────────────────────────────
    try:
        from services.i18n.strings import get_user_lang

        detected_lang = get_user_lang(user_context)
        user_context["lang"] = detected_lang

        # If detected a non-EN lang different from saved pref, persist it
        if (
            detected_lang != "en"
            and db_svc
            and db_svc.is_initialized()
            and user_row
        ):
            user_uuid_lang = user_row.get("id") or user_row.get("user_id")
            current_pref = user_row.get("preferred_language")
            if (
                user_uuid_lang
                and (not current_pref or current_pref[:2].lower() != detected_lang)
            ):
                await db_svc.update_user_preferences(
                    user_uuid_lang, {"preferred_language": detected_lang}
                )
                logger.info(
                    "Auto-saved preferred_language=%s for user %s",
                    detected_lang,
                    str(user_uuid_lang)[:8],
                )
    except Exception as exc:
        logger.debug("Could not auto-detect/save language: %s", exc)

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
            "Tente novamente — se persistir, pode ser lentidão nos "
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
        sentry_sdk.capture_exception(e)
        await update.message.reply_text(f"⚠️ Erro inesperado ao processar mensagem: {e}")
        return

    elapsed = time.monotonic() - start_time
    logger.info(
        "Message processed in %.1fs for user %s",
        elapsed,
        user_context["user_id"],
    )

    # ── Save pending location if agent asks for it ──────────────────────
    # When MapsAgent returns data={"ask_location": "home"}, save state
    # in Redis so next user message is captured as the address answer.
    logger.info(
        "Result check: has_data=%s, data_keys=%s",
        bool(result and result.data),
        list(result.data.keys()) if result and result.data else "none",
    )
    if result and hasattr(result, "data") and result.data:
        if result.data.get("ask_location"):
            try:
                redis_svc = get_service("redis")
                if redis_svc:
                    pending_key = (
                        f"pending:location:{update.effective_chat.id}"
                    )
                    await redis_svc.set(
                        pending_key,
                        {
                            "key": result.data["ask_location"],
                            "direction": result.data.get(
                                "direction", "origin"
                            ),
                            "original_query": text,
                            "user_id": (
                                str(
                                    user_row.get("id")
                                    or user_row.get("user_id")
                                )
                                if user_row
                                else str(
                                    user_context.get("user_id", "")
                                )
                            ),
                            "lang": user_context.get("lang", "en"),
                        },
                        expire_seconds=300,  # 5 minutes TTL
                    )
                    logger.info(
                        "Saved pending location '%s' for chat %s"
                        " (original: %s)",
                        result.data["ask_location"],
                        update.effective_chat.id,
                        text[:40],
                    )
            except Exception as e:
                logger.warning("Could not save pending location: %s", e)

    await send_agent_response(update, result)


async def _handle_email_edit_reply(
    update: Update,
    edit_state: Dict[str, Any],
    user_text: str,
) -> None:
    """Process a user-typed email reply from edit mode.

    Updates the draft in Redis with the custom reply text and shows
    a confirmation keyboard.
    """
    from services.i18n import t
    from telegram_bot.handlers.email_callback import (
        build_confirm_keyboard,
        store_email_draft,
        _DRAFT_PREFIX,
    )

    user_id = edit_state.get("user_id", "")
    email_id = edit_state.get("email_id", "")
    lang = edit_state.get("lang", "en")

    # Update draft with custom reply
    redis = get_service("redis")
    if redis:
        draft = await redis.get(
            f"{_DRAFT_PREFIX}:{user_id}:{email_id}",
            parse_json=True,
        )
        if draft and isinstance(draft, dict):
            draft["custom_reply"] = user_text
            await store_email_draft(user_id, email_id, draft)

    # Show confirmation preview
    to = edit_state.get("to", "")
    preview = t(
        "email_cb_send_confirm",
        lang=lang,
        reply_text=user_text[:500],
        to=to,
    )
    keyboard = build_confirm_keyboard(email_id, lang)
    await update.message.reply_text(preview, reply_markup=keyboard)


async def _handle_pending_location_save(
    update: Update,
    tg_context: ContextTypes.DEFAULT_TYPE,
    pending: Dict[str, Any],
    address_text: str,
) -> None:
    """
    Handle user's address reply when bot asked for a location.

    Saves the location, confirms to user, then re-runs the original
    query so the conversation flows naturally.

    Example flow:
        User: "rota de casa ao trabalho"
        Bot:  "Onde e sua Casa? Qual o endereco?"    ← pending saved
        User: "Swords, Dublin"                        ← intercepted HERE
        Bot:  "Salvei Casa como: Swords, Dublin"      ← confirm
        Bot:  "Onde e seu Trabalho? Qual o endereco?" ← re-run next gap
    """
    from services.business.saved_locations_service import (
        get_saved_locations_service,
        get_label,
    )
    from services.i18n import t

    key = pending.get("key", "")
    user_id = str(pending.get("user_id", ""))
    lang = pending.get("lang", "en")
    original_query = pending.get("original_query", "")

    if not key or not user_id:
        logger.warning("Invalid pending location data: %s", pending)
        return

    # ── 1. Save the location ─────────────────────────────────────────
    loc_svc = get_saved_locations_service()
    location_data = await loc_svc.save_location(
        user_id, key, address_text
    )
    label = get_label(key, lang)

    # ── 2. Confirm to user ───────────────────────────────────────────
    if location_data.get("latitude"):
        confirm_msg = t(
            "maps_location_saved",
            lang=lang,
            alias=label,
            address=address_text,
        )
    else:
        confirm_msg = t(
            "maps_location_saved_no_coords",
            lang=lang,
            alias=label,
            address=address_text,
        )
    await update.message.reply_text(confirm_msg)

    # ── 3. Re-run original query (location now saved) ────────────────
    if not original_query:
        return

    bot = tg_context.application.bot_data.get("capivarax_bot")
    if not bot:
        return

    logger.info(
        "Re-running original query after location save: '%s'",
        original_query[:60],
    )

    # Send typing indicator for natural feel
    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    # Build fresh user_context (same as handle_message does)
    user_context: Dict[str, Any] = {
        "user_id": update.effective_user.id,
        "chat_id": update.effective_chat.id,
        "username": update.effective_user.username,
        "language_code": getattr(
            update.effective_user, "language_code", None
        )
        or "en",
        "message_text": original_query,
        "lang": lang,
    }

    # Enrich with DB data (simplified — GPS + preferences)
    try:
        db_svc = get_service("database")
        if db_svc and db_svc.is_initialized():
            user_row = await db_svc.get_user_by_telegram_id(
                str(update.effective_user.id)
            )
            if user_row:
                pref_lang = user_row.get("preferred_language")
                if pref_lang:
                    user_context["user_preferences"] = {
                        "preferred_language": pref_lang,
                    }
                loc_pref = user_row.get("location_preference", "")
                if loc_pref:
                    user_context["user_location"] = loc_pref

                user_uuid = (
                    user_row.get("id") or user_row.get("user_id")
                )
                if user_uuid:
                    # Fetch saved GPS location
                    saved_loc = await db_svc.get_user_context(
                        user_uuid, "location"
                    )
                    if saved_loc and isinstance(saved_loc, dict):
                        user_context.setdefault(
                            "latitude", saved_loc.get("latitude")
                        )
                        user_context.setdefault(
                            "longitude", saved_loc.get("longitude")
                        )
    except Exception as e:
        logger.debug("Could not enrich re-run context: %s", e)

    # Re-process the original query
    try:
        result = await bot.process_message(
            original_query, user_context
        )
    except Exception as e:
        logger.error(
            "Error re-running query after location save: %s", e
        )
        return

    if not result:
        return

    # ── 4. Check if the NEW result also asks for a location ──────────
    # e.g., "casa" is now saved but "trabalho" still unknown
    if (
        hasattr(result, "data")
        and result.data
        and result.data.get("ask_location")
    ):
        try:
            redis_svc = get_service("redis")
            if redis_svc:
                new_pending_key = (
                    f"pending:location:{update.effective_chat.id}"
                )
                await redis_svc.set(
                    new_pending_key,
                    {
                        "key": result.data["ask_location"],
                        "direction": result.data.get(
                            "direction", "origin"
                        ),
                        "original_query": original_query,
                        "user_id": user_id,
                        "lang": lang,
                    },
                    expire_seconds=300,
                )
                logger.info(
                    "Chained pending location: now asking for '%s'",
                    result.data["ask_location"],
                )
        except Exception as e:
            logger.debug("Could not save chained pending: %s", e)

    # ── 5. Send the result ───────────────────────────────────────────
    await send_agent_response(update, result)
