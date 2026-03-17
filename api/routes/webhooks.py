"""
Webhook Routes

Receives external webhook calls for email notifications.
Protected by HMAC signature verification (WEBHOOK_SECRET env var).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from agents import get_agent

router = APIRouter()
logger = logging.getLogger(__name__)

_WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


def _verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature of webhook payload."""
    if not _WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not configured — webhook auth disabled")
        return True  # Allow in dev if no secret set
    expected = hmac.new(
        _WEBHOOK_SECRET.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


@router.post("/email")
async def email_webhook(request: Request):
    """
    Receive email notification webhook.

    Requires X-Webhook-Signature header with HMAC-SHA256 of the payload.
    """
    # Verify signature
    payload_bytes = await request.body()
    signature = request.headers.get("X-Webhook-Signature", "")
    if _WEBHOOK_SECRET and not _verify_webhook_signature(payload_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    email_agent = get_agent("email")
    if not email_agent:
        raise HTTPException(status_code=503, detail="Email agent not available")

    user_id = payload.get("user_id", "")
    subject = payload.get("subject", "")
    sender = payload.get("from", payload.get("from_email", ""))

    logger.info("Email webhook received: from=%s subject=%s", sender, subject)

    try:
        context = {
            "user_id": user_id,
            "intent": "incoming_email",
            "email_data": payload,
        }
        response = await email_agent.process(
            f"New email from {sender}: {subject}", context
        )
        return {"status": "processed", "agent_response": response.response}
    except Exception as e:
        logger.exception("Error processing email webhook")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────
# 17TRACK Webhook — Package tracking push updates
# ──────────────────────────────────────────────────────────────────────────

@router.post("/tracking")
async def tracking_webhook(request: Request):
    """
    Receive 17TRACK push notifications when tracking status changes.

    17TRACK sends POST with tracking updates (V2.4 format).
    We match the tracking number to a user and notify them.

    Configure at: admin.17track.net → Settings → Package Webhook
    URL: https://capivarex-production.up.railway.app/api/v1/webhooks/tracking
    """
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("event", "")
    data = payload.get("data", {})

    if event_type == "TRACKING_UPDATED":
        tracking_number = data.get("number", "")
        track_info = data.get("track", {})
        status_code = track_info.get("b", 0)

        logger.info(
            "17TRACK webhook: %s status=%s",
            tracking_number[-6:] if tracking_number else "?",
            status_code,
        )

        # TODO: Match tracking number to user and send notification
        # This will be connected to package_tracking_service when users
        # have active tracked packages

    elif event_type == "TRACKING_STOPPED":
        tracking_number = data.get("number", "")
        logger.info("17TRACK stopped tracking: %s", tracking_number[-6:] if tracking_number else "?")

    return {"status": "ok"}
