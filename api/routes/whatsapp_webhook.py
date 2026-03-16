"""
WhatsApp Webhook Route.

Handles:
1. GET /api/webhooks/whatsapp — Meta webhook verification (challenge-response)
2. POST /api/webhooks/whatsapp — Incoming messages from WhatsApp users

Messages are processed by the same orchestrator as Telegram/WebApp.
"""

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from services.integrations.whatsapp_service import (
    extract_message_from_webhook,
    mark_as_read,
    send_text_message,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook Verification (Meta sends GET to verify your endpoint)
# ---------------------------------------------------------------------------

@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta webhook verification.

    When you configure the webhook in Meta dashboard, Meta sends a GET
    request with hub.mode, hub.verify_token, and hub.challenge.
    We must return hub.challenge if the verify_token matches.
    """
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        logger.info("WhatsApp webhook verified successfully")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning("WhatsApp webhook verification failed: mode=%s", hub_mode)
    raise HTTPException(status_code=403, detail="Verification failed")


# ---------------------------------------------------------------------------
# Incoming Messages (Meta sends POST when user sends a message)
# ---------------------------------------------------------------------------

@router.post("/whatsapp")
async def receive_message(request: Request):
    """
    Receive incoming WhatsApp messages.

    Meta sends a POST with the message payload.
    We extract the message, process it via orchestrator, and reply.
    """
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Meta sends status updates too (delivered, read, etc.) — ignore those
    msg_data = extract_message_from_webhook(body)
    if not msg_data:
        # Acknowledge but don't process (status updates, etc.)
        return {"status": "ok"}

    sender_phone = msg_data["from"]
    sender_name = msg_data["name"]
    user_text = msg_data["text"]
    message_id = msg_data["message_id"]

    logger.info(
        "WhatsApp message from %s (%s): %s",
        sender_name or "unknown",
        sender_phone[-4:],
        user_text[:50],
    )

    # Mark as read (blue ticks)
    await mark_as_read(message_id)

    # Process the message via AI orchestrator
    response_text = await _process_message(sender_phone, sender_name, user_text)

    # Send reply
    if response_text:
        await send_text_message(sender_phone, response_text)

    return {"status": "ok"}


async def _process_message(phone: str, name: str, text: str) -> str:
    """
    Process a WhatsApp message through the AI orchestrator.

    Uses the same pipeline as Telegram: orchestrator → agent → response.
    Maps WhatsApp phone number to a Capivarex user (or creates guest session).
    """
    try:
        # Try to find user by phone number
        user_id = await _get_user_id_by_phone(phone)
        user_name = name

        if not user_id:
            # No account linked — respond with helpful message
            return (
                f"Hey{' ' + name.split()[0] if name else ''}! 👋 "
                f"I'm Capivarex, your AI assistant.\n\n"
                f"To use all features, create an account at app.capivarex.com "
                f"and link your WhatsApp number in Settings.\n\n"
                f"For now, ask me anything and I'll do my best to help!"
            )

        # Get user data for context
        from services.core import get_service
        db = get_service("database")
        user_data = None
        if db and db.is_initialized():
            user_data = await db.get_user_by_id(user_id)
            if user_data:
                user_name = user_data.get("full_name", name)

        # Process via orchestrator (same as Telegram/WebApp)
        from agents.core import get_agent
        orchestrator = get_agent("orchestrator")
        if not orchestrator:
            return "I'm having trouble right now. Please try again in a moment."

        context = {
            "user_id": user_id,
            "user_name": user_name,
            "interface": "whatsapp",
            "phone": phone,
        }

        # Get conversation history from Redis
        try:
            redis = get_service("redis")
            if redis and redis.is_initialized():
                context["history"] = await redis.get_conversation_context(user_id, limit=10)
        except Exception:
            pass

        result = await orchestrator.execute(text, context)

        if result and result.response:
            # Save to conversation history
            try:
                from utils.safe_task import safe_create_task
                from services.business.rag_service import extract_and_save_memory

                redis = get_service("redis")
                if redis and redis.is_initialized():
                    safe_create_task(
                        redis.save_conversation_message(user_id, {"role": "user", "content": text}),
                        name="wa_redis_user",
                    )
                    safe_create_task(
                        redis.save_conversation_message(user_id, {"role": "assistant", "content": result.response}),
                        name="wa_redis_assistant",
                    )
                safe_create_task(
                    extract_and_save_memory(user_id, text),
                    name="wa_rag_memory",
                )
            except Exception:
                pass

            return result.response

        return "I couldn't process that. Could you try rephrasing?"

    except Exception as e:
        logger.error("WhatsApp process error: %s", e, exc_info=True)
        return "Something went wrong. Please try again."


async def _get_user_id_by_phone(phone: str) -> str:
    """
    Look up Capivarex user ID by WhatsApp phone number.

    Checks user_preferences or users table for matching phone number.
    """
    from services.core import get_service

    db = get_service("database")
    if not db or not db.is_initialized():
        return ""

    try:
        client = db.get_client()

        # Check users table for phone number match
        # Phone stored as: "353891234567" or "+353891234567"
        clean_phone = phone.replace("+", "").replace(" ", "")

        result = (
            client.table("users")
            .select("id")
            .or_(f"phone.eq.{clean_phone},phone.eq.+{clean_phone}")
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]["id"]

        # Also check user_preferences for whatsapp_phone
        result2 = (
            client.table("user_preferences")
            .select("user_id")
            .eq("whatsapp_phone", clean_phone)
            .limit(1)
            .execute()
        )

        if result2.data:
            return result2.data[0]["user_id"]

    except Exception as e:
        logger.warning("WhatsApp user lookup failed: %s", e)

    return ""
