"""
Unified Identity Resolution
============================

Resolve any user_id (Telegram numeric ID or UUID) to the internal
Supabase UUID. Must be called at ALL OAuth entry points and anywhere
that receives user_id from external sources.

Golden rule:
  - UUID received → return as-is
  - Numeric ID (Telegram) → resolve to UUID via DB lookup
  - Not found → return original with warning (never crash)
"""

import uuid as _uuid_mod
from typing import Optional

from loguru import logger


def _is_uuid(value: str) -> bool:
    """Check if *value* is a valid UUID string."""
    try:
        _uuid_mod.UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False


async def resolve_user_uuid(raw_id: str, context: str = "") -> str:
    """Resolve *raw_id* to an internal Supabase UUID.

    Args:
        raw_id: May be a UUID (webapp/mobile) or a numeric Telegram ID.
        context: Label for logging (e.g. ``"spotify_callback"``).

    Returns:
        UUID string if resolved, *raw_id* unchanged otherwise.
    """
    if not raw_id:
        return raw_id

    raw_id = str(raw_id).strip()

    # Already a UUID — return directly
    if _is_uuid(raw_id):
        return raw_id

    # Numeric → likely a Telegram ID — resolve via DB
    if raw_id.isdigit():
        try:
            from services.core import get_service

            db = get_service("database")
            if db and db.is_initialized():
                row = await db.get_user_by_telegram_id(raw_id)
                if row:
                    uuid = row["id"]
                    logger.info(
                        "[identity] {} telegram_id {} → UUID {}",
                        context or "resolve",
                        raw_id,
                        uuid,
                    )
                    return uuid
                else:
                    logger.warning(
                        "[identity] {} telegram_id {} not found in public.users",
                        context or "resolve",
                        raw_id,
                    )
        except Exception as exc:
            logger.warning(
                "[identity] {} could not resolve {}: {}",
                context or "resolve",
                raw_id,
                exc,
            )

    # Fallback: return original (never crash)
    return raw_id


def resolve_user_uuid_sync(raw_id: str) -> Optional[str]:
    """Synchronous variant — validates UUID format only (no DB lookup).

    Returns:
        *raw_id* if it is a valid UUID, ``None`` otherwise.
    """
    if not raw_id:
        return None
    raw_id = str(raw_id).strip()
    return raw_id if _is_uuid(raw_id) else None
