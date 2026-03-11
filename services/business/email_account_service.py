"""
Email Account Service.

Persistence layer for email accounts and reply tracking.

Tables:
    email_accounts — linked email accounts per user
    email_replies  — log of emails sent/replied by the bot
"""

import logging
from typing import Any, Dict, List, Optional

from services.infrastructure.database import get_supabase_client

logger = logging.getLogger(__name__)


async def get_email_accounts(user_id: str) -> List[Dict[str, Any]]:
    """Return active email accounts linked to the user."""
    sb = get_supabase_client()
    if not sb:
        return []
    try:
        res = (
            sb.table("email_accounts")
            .select("*")
            .eq("user_id", user_id)
            .eq("active", True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("Failed to get email accounts: %s", e)
        return []


async def add_email_account(
    user_id: str,
    account: str,
    email_address: str,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a new email account for the user."""
    sb = get_supabase_client()
    if not sb:
        return {}
    try:
        res = (
            sb.table("email_accounts")
            .insert(
                {
                    "user_id": user_id,
                    "account": account,
                    "email_address": email_address,
                    "display_name": display_name,
                }
            )
            .execute()
        )
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.error("Failed to add email account: %s", e)
        return {}


async def save_reply(
    user_id: str,
    account: str,
    to_email: str,
    subject: str,
    body: str,
    inbox_id: Optional[str] = None,
    status: str = "sent",
) -> None:
    """Log an email replied/sent by the bot."""
    sb = get_supabase_client()
    if not sb:
        return
    try:
        sb.table("email_replies").insert(
            {
                "user_id": user_id,
                "account": account,
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "inbox_id": inbox_id,
                "status": status,
            }
        ).execute()
    except Exception as e:
        logger.error("Failed to save email reply: %s", e)


async def get_sent_replies(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return emails sent/replied by the bot, newest first."""
    sb = get_supabase_client()
    if not sb:
        return []
    try:
        res = (
            sb.table("email_replies")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "sent")
            .order("sent_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("Failed to get sent replies: %s", e)
        return []
