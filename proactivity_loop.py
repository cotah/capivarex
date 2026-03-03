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

    try:
        pref_users = await db_service.get_all_users_with_proactivity_enabled()
    except Exception as e:
        logger.exception(
            f"CRITICAL: Failed to get users with proactivity enabled from DB. Cycle aborted. Error: {e}"
        )
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
        _ = pref  # FIX F841: pref retained for future per-user preference filtering

        try:
            context = await proactivity_service.gather_context(user_context)
            insight = await proactivity_service.analyze_context_for_insights(context)
            notifications: List[Dict[str, Any]] = []

            if insight:
                notifications.append({"type": "insight", "message": insight})

            smartthings_alert = await proactivity_service.check_smartthings_status(
                user_id
            )
            if smartthings_alert:
                notifications.append(smartthings_alert)

            if not notifications:
                logger.info(f"No proactive insights for user {user_id} in this cycle.")
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
                    logger.info(f"Sending proactive notification to user {user_id}")
                    notification_service = get_service("notification")
                    if (
                        notification_service
                        and not notification_service.is_initialized()
                    ):
                        await notification_service.initialize()
                    if notification_service:
                        await notification_service.send_message(
                            "telegram", chat_id, message
                        )
                    else:
                        logger.warning("NotificationService not available.")
                    await proactivity_service.record_notification_sent(user_id, message)
                else:
                    logger.info(f"Notification for {user_id} blocked by filters.")

        except Exception as e:
            logger.exception(f"Proactivity cycle failed for user {user_id}: {e}")

    # ── Email polling step ───────────────────────────────────────────────────
    try:
        await _run_email_polling()
    except Exception as e:
        logger.error("Email polling step failed: %s", e)


async def _run_email_polling() -> None:
    """Poll Gmail for new emails and send Telegram notifications."""
    eps = get_service("email_polling")
    if not eps:
        logger.debug("EmailPollingService not available — skipping.")
        return

    if not eps.is_initialized():
        try:
            await eps.initialize()
        except Exception as e:
            logger.warning("Failed to initialise email polling: %s", e)
            return

    db_service = get_service("database")
    if not db_service or not db_service.is_initialized():
        return

    try:
        pollable = await eps.get_pollable_users()
    except Exception as e:
        logger.error("get_pollable_users failed: %s", e)
        return

    polled = 0
    notified = 0

    for row in pollable:
        user_id = row["user_id"]
        try:
            new_emails = await asyncio.wait_for(
                eps.poll_new_emails(user_id),
                timeout=10,
            )
            polled += 1

            if not new_emails:
                continue

            # Resolve user data for lang + chat_id
            user_data = await db_service.get_user_by_id(user_id)
            lang = (user_data or {}).get("preferred_language", "en")
            chat_id = (user_data or {}).get(
                "telegram_chat_id", user_id
            )

            message = await eps.summarize_for_notification(
                new_emails, user_id, lang
            )
            if not message:
                continue

            notification_service = get_service("notification")
            if notification_service:
                if not notification_service.is_initialized():
                    await notification_service.initialize()
                await notification_service.send_message(
                    "telegram", chat_id, message
                )
                notified += 1

            await eps.mark_as_notified(
                user_id, [e["id"] for e in new_emails]
            )

        except asyncio.TimeoutError:
            logger.warning(
                "Email polling timed out for user %s", user_id
            )
        except Exception as e:
            logger.error(
                "Email polling failed for user %s: %s",
                user_id,
                e,
            )

    if polled:
        logger.info(
            "Email polling: %d users polled, %d notifications sent",
            polled,
            notified,
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
