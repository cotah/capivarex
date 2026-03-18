# utils/rate_limiter.py
"""
Simple in-memory rate limiter for Telegram bot handlers.

Limits each user to one message every RATE_LIMIT_SECONDS.
"""

import time
import logging

logger = logging.getLogger("capivarex.rate_limiter")

# Per-user last message timestamp
_user_last_message_time: dict = {}

# Minimum interval between messages per user (seconds)
RATE_LIMIT_SECONDS = 2


def is_rate_limited(user_id: int) -> bool:
    """
    Check if a user is currently rate-limited.

    Args:
        user_id: Telegram user ID

    Returns:
        True if the user should be rate-limited (message ignored)
    """
    current_time = time.time()
    last_time = _user_last_message_time.get(user_id)

    if last_time is not None and (current_time - last_time) < RATE_LIMIT_SECONDS:
        logger.debug(
            "Rate limited user_id=%s (%.1fs since last message)",
            user_id,
            current_time - last_time,
        )
        return True

    _user_last_message_time[user_id] = current_time
    return False
