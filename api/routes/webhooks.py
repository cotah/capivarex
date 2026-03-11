"""
Webhook Routes

Receives external webhook calls for email notifications.
Can be called by any email monitoring service (Gmail API, Microsoft Graph, etc).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from agents import get_agent

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/email")
async def email_webhook(request: Request):
    """
    Receive email notification webhook.

    Expected payload:
    {
        "from": "sender@example.com",
        "subject": "Email subject",
        "body": "Email body text",
        "user_id": "telegram_user_id",
        "account": "gmail" | "hotmail"  (optional)
    }
    """
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
