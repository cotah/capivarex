# flake8: noqa: E501
"""
Proactivity Loop - Refactored to use services architecture.

Runs periodic proactivity checks for all users with enabled preferences.
"""

import asyncio
from typing import Any, Dict, List

from pydantic import ValidationError

from schemas.context import UserContext
from services.core import get_service
from utils.logger import get_logger

logger = get_logger(__name__)


async def _get_proactivity_service():
    """Get and initialize the proactivity service."""
    service = get_service("proactivity")
    if service and not service.is_initialized():
        await service.initialize()
    return service


async def run_proactivity_cycle() -> None:
    """Execute a proactive verification cycle for all users."""
    logger.info("Starting proactivity cycle...")

    db_service = get_service("database")
    if not db_service:
        logger.info("Database service not available.")
        return

    if not db_service.is_initialized():
        await db_service.initialize()

    # Get users from the proactivity_preferences table
    try:
        pref_users = await db_service.get_all_users_with_proactivity_enabled()
    except Exception as e:
        logger.exception(f"CRITICAL: Failed to get users with proactivity enabled from DB. Cycle aborted. Error: {e}")
        return

    if not pref_users:
        logger.info("No users with proactivity preferences found.")
        return

    proactivity_service = await _get_proactivity_service()
    if not proactivity_service:
        logger.warning("Proactivity service not available. Skipping cycle.")
        return

    for pref in pref_users:
        user_id = pref["user_id"]

        # Look up user details (telegram_chat_id) from users table
        user_data = await db_service.get_user_by_id(user_id)
        if not user_data:
            logger.warning(f"User {user_id} not found in database. Skipping.")
            continue

        try:
            user_context = UserContext.model_validate(user_data)
        except ValidationError as e:
            logger.error(f"User data for {user_id} is invalid: {e}")
            continue

        chat_id = user_data.get("telegram_chat_id", user_id)
        proactivity_prefs = pref

        try:
            context = await proactivity_service.gather_context(user_context)
            insight = await proactivity_service.analyze_context_for_insights(context)

            notifications: List[Dict[str, Any]] = []

            if insight:
                notifications.append({"type": "insight", "message": insight})

            # Check SmartThings
            smartthings_alert = await proactivity_service.check_smartthings_status(
                user_id
            )
            if smartthings_alert:
                notifications.append(smartthings_alert)

            if not notifications:
                logger.info(
                    f"No proactive insights for user {user_id} in this cycle."
                )
                continue

            for notification in notifications:
                if notification.get("type") == "smartthings_alert":
                    message = (
                        f"{notification.get('title', 'SmartThings Alert')}\n"
                        f"{notification.get('message', '')}"
                    ).strip()
                else:
                    message = notification.get("message", "")

                if not message:
                    continue

                if await proactivity_service.is_notification_allowed(user_id, message):
                    logger.info(
                        f"Sending proactive notification to user {user_id}: {message}"
                    )
                    # Local import to avoid circular dependency with telegram_bot
                    from telegram_bot import send_proactive_message

                    await send_proactive_message(chat_id, message)
                    await proactivity_service.record_notification_sent(user_id, message)
                else:
                    logger.info(f"Notification for {user_id} blocked by filters.")

        except Exception as e:
            logger.exception(
                f"Proactivity cycle failed for user {user_id}: {e}"
            )


async def main_loop() -> None:
    """Main loop that runs the proactivity cycle every 5 minutes."""
    while True:
        await run_proactivity_cycle()
        logger.info("Proactivity cycle completed. Waiting 5 minutes...")
        await asyncio.sleep(300)


if __name__ == "__main__":
    logger.info("Starting SuperBot God proactivity loop...")
    asyncio.run(main_loop())
