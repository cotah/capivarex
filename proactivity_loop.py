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
    """Execute a proactive verification cycle for all users.

    Runs two independent steps:
    1. Proactivity checks (insights, SmartThings alerts)
    2. Email polling (Gmail → Telegram notifications)

    Each step is isolated — a failure or early exit in one
    does NOT prevent the other from running.
    """
    logger.info("Starting proactivity cycle...")

    # ── Step 1: Proactivity checks ────────────────────────────────────────
    try:
        await _run_proactivity_checks()
    except Exception as e:
        logger.error("Proactivity checks failed: %s", e)

    # ── Step 2: Email polling (independent — always runs) ─────────────────
    try:
        await _run_email_polling()
    except Exception as e:
        logger.error("Email polling step failed: %s", e)


async def _run_proactivity_checks() -> None:
    """Run proactivity insight checks for all users with enabled preferences."""
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

    logger.info("Email polling: checking %d users", len(pollable))

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

            batch = await eps.summarize_for_notification(
                new_emails, user_id, lang
            )
            if not batch.notifications and not batch.grouped_text:
                continue

            notification_service = get_service("notification")
            if not notification_service:
                continue
            if not notification_service.is_initialized():
                await notification_service.initialize()

            if batch.is_multiple:
                # Multiple emails: send grouped summary, no buttons
                if batch.grouped_text:
                    await notification_service.send_message(
                        "telegram", chat_id, batch.grouped_text
                    )
                    notified += 1
                # Store basic drafts for future interaction
                for notif in batch.notifications:
                    await _store_email_draft(user_id, notif)
            else:
                # Single email: rich notification + inline keyboard
                for notif in batch.notifications:
                    if not notif.text:
                        continue
                    needs_reply = (
                        notif.analysis.needs_reply
                        if notif.analysis
                        else False
                    )
                    event_req = (
                        notif.analysis.event_request
                        if notif.analysis
                        else False
                    )
                    keyboard = _build_email_keyboard(
                        notif.email_id,
                        needs_reply,
                        lang,
                        event_request=event_req,
                    )
                    await notification_service.send_message(
                        "telegram",
                        chat_id,
                        notif.text,
                        reply_markup=keyboard,
                    )
                    notified += 1
                    await _store_email_draft(user_id, notif)

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


def _build_email_keyboard(
    email_id: str,
    needs_reply: bool,
    lang: str,
    event_request: bool = False,
):
    """Build inline keyboard for email notification."""
    from telegram_bot.handlers.email_callback import build_email_keyboard

    return build_email_keyboard(
        email_id, needs_reply, lang, event_request=event_request
    )


async def _store_email_draft(user_id: str, notif) -> None:
    """Store email draft data in Redis for callback handler use."""
    from telegram_bot.handlers.email_callback import store_email_draft

    analysis = notif.analysis
    draft_data = {
        "to": notif.from_email,
        "subject": notif.subject,
        "thread_id": notif.thread_id,
        "message_id": notif.message_id,
        "from_name": notif.from_name,
        "user_id": notif.user_id,
        "lang": notif.lang,
        "suggested_reply": (
            analysis.suggested_reply if analysis else ""
        ),
        "proposed_datetime": (
            analysis.proposed_datetime if analysis else None
        ),
        "proposed_location": (
            analysis.proposed_location if analysis else ""
        ),
    }
    await store_email_draft(user_id, notif.email_id, draft_data)


async def main_loop() -> None:
    """Main loop that runs the proactivity cycle every 5 minutes."""
    while True:
        await run_proactivity_cycle()
        logger.info("Proactivity cycle completed. Waiting 5 minutes...")
        await asyncio.sleep(300)


if __name__ == "__main__":
    logger.info("Starting SuperBot God proactivity loop...")
    asyncio.run(main_loop())
