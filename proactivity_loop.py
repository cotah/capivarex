# flake8: noqa: E501
"""
Proactivity Loop - Refactored to use services architecture.

Runs periodic proactivity checks for all users with enabled preferences.
"""

import asyncio
from typing import Any, Dict, List

import sentry_sdk
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

    Runs three independent steps:
    1. Proactivity checks (insights, smart home alerts)
    2. Email polling (Gmail → Telegram notifications)
    3. News fetching (2x/day at 07:00 and 18:00 UTC via Perplexity)

    Each step is isolated — a failure or early exit in one
    does NOT prevent the other from running.
    """
    logger.info("Starting proactivity cycle...")

    # ── Step 1: Proactivity checks ────────────────────────────────────────
    try:
        await _run_proactivity_checks()
    except Exception as e:
        logger.error("Proactivity checks failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 2: Email polling (independent — always runs) ─────────────────
    try:
        await _run_email_polling()
    except Exception as e:
        logger.error("Email polling step failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 3: News fetching (2x/day — 07:00 and 18:00 UTC) ─────────────
    try:
        await _run_news_fetch_if_due()
    except Exception as e:
        logger.error("News fetch step failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 4: Finance price alerts (every cycle — ~5 min) ───────────────
    try:
        from services.business.finance_alert_service import check_price_alerts
        alerts = await check_price_alerts()
        if alerts:
            logger.info("Finance alerts: %d alerts sent this cycle", alerts)
    except Exception as e:
        logger.error("Finance alerts step failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 5: Morning briefing (once/day per user, ~08:00 UTC) ──────────
    try:
        await _run_morning_briefings()
    except Exception as e:
        logger.error("Morning briefing step failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 6: Meeting briefings (2h before meetings) ────────────────────
    try:
        await _run_meeting_briefings()
    except Exception as e:
        logger.error("Meeting briefing step failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 7: Weekly finance recap (Mondays ~09:00 UTC) ─────────────────
    try:
        await _run_weekly_recap()
    except Exception as e:
        logger.error("Weekly recap step failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 8: Travel planner detection (once/day, 10:00-12:00 UTC) ──────
    try:
        await _run_travel_detection()
    except Exception as e:
        logger.error("Travel detection step failed: %s", e)
        sentry_sdk.capture_exception(e)

    # ── Step 9: Birthday detection (once/day, 08:00-10:00 UTC) ────────────
    try:
        await _run_birthday_detection()
    except Exception as e:
        logger.error("Birthday detection step failed: %s", e)
        sentry_sdk.capture_exception(e)


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
        sentry_sdk.capture_exception(e)
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

            # Smart home alerts (Tuya) — future: check device status
            # tuya_alert = await proactivity_service.check_smart_home_status(user_id)
            # if tuya_alert:
            #     notifications.append(tuya_alert)

            if not notifications:
                logger.info(f"No proactive insights for user {user_id} in this cycle.")
                continue

            for notification in notifications:
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
            sentry_sdk.capture_exception(e)


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
            sentry_sdk.capture_exception(e)

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


async def _run_news_fetch_if_due() -> None:
    """Fetch financial news 2x/day at 07:00 and 18:00 UTC.

    Since the proactivity loop runs every 5 minutes, we check if the
    current time falls within a 5-minute window of the target hours.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    hour = now.hour
    minute = now.minute

    # Only run at 07:00-07:04 or 18:00-18:04 UTC
    if not ((hour == 7 and minute < 5) or (hour == 18 and minute < 5)):
        return

    logger.info("News: time window hit (%02d:%02d UTC), fetching news...", hour, minute)

    try:
        from services.business.finance_news_service import fetch_and_store_news
        articles = await fetch_and_store_news()
        logger.info("News: fetched %d articles", len(articles))
    except Exception as e:
        logger.error("News: fetch_and_store_news failed: %s", e)
        raise


async def _run_morning_briefings() -> None:
    """Generate morning briefings for all users (once/day, ~06:00-10:00 UTC window)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Only run between 06:00 and 10:00 UTC
    if not (6 <= now.hour <= 10):
        return

    db_service = get_service("database")
    if not db_service or not db_service.is_initialized():
        return

    try:
        pref_users = await db_service.get_all_users_with_proactivity_enabled()
    except Exception:
        return

    if not pref_users:
        return

    from services.business.morning_briefing_service import generate_morning_briefing

    for pref in pref_users:
        user_id = pref["user_id"]
        try:
            user_data = await db_service.get_user_by_id(user_id)
            if not user_data:
                continue

            user_name = user_data.get("full_name", "")
            location = user_data.get("location_preference", "Dublin")
            chat_id = user_data.get("telegram_chat_id")

            result = await generate_morning_briefing(
                user_id=user_id,
                user_name=user_name,
                location=location,
                chat_id=str(chat_id) if chat_id else None,
            )
            if result:
                logger.info("Morning briefing sent for user={}", user_id[:8])
        except Exception as e:
            logger.warning("Morning briefing failed for user={}: {}", user_id[:8], e)


async def _run_meeting_briefings() -> None:
    """Check upcoming meetings and generate briefings for all users."""
    db_service = get_service("database")
    if not db_service or not db_service.is_initialized():
        return

    try:
        pref_users = await db_service.get_all_users_with_proactivity_enabled()
    except Exception:
        return

    if not pref_users:
        return

    from services.business.meeting_briefing_service import check_upcoming_meetings

    for pref in pref_users:
        user_id = pref["user_id"]
        try:
            user_data = await db_service.get_user_by_id(user_id)
            if not user_data:
                continue

            chat_id = user_data.get("telegram_chat_id")
            briefings = await check_upcoming_meetings(
                user_id=user_id,
                chat_id=str(chat_id) if chat_id else None,
            )
            if briefings:
                logger.info(
                    "Meeting briefings: {} sent for user={}",
                    len(briefings), user_id[:8],
                )
        except Exception as e:
            logger.warning("Meeting briefing failed for user={}: {}", user_id[:8], e)


async def _run_weekly_recap() -> None:
    """Generate weekly finance recaps on Mondays 08:00-10:00 UTC."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Only run on Mondays between 08:00-10:00 UTC
    if now.weekday() != 0 or not (8 <= now.hour <= 10):
        return

    db_service = get_service("database")
    if not db_service or not db_service.is_initialized():
        return

    try:
        pref_users = await db_service.get_all_users_with_proactivity_enabled()
    except Exception:
        return

    if not pref_users:
        return

    from services.business.weekly_recap_service import generate_weekly_recap

    for pref in pref_users:
        user_id = pref["user_id"]
        try:
            user_data = await db_service.get_user_by_id(user_id)
            if not user_data:
                continue

            result = await generate_weekly_recap(
                user_id=user_id,
                user_name=user_data.get("full_name", ""),
                chat_id=str(user_data.get("telegram_chat_id")) if user_data.get("telegram_chat_id") else None,
            )
            if result:
                logger.info("Weekly recap sent for user={}", user_id[:8])
        except Exception as e:
            logger.warning("Weekly recap failed for user={}: {}", user_id[:8], e)


async def _run_birthday_detection() -> None:
    """Detect upcoming birthdays (once/day, 08:00-10:00 UTC)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    if not (8 <= now.hour <= 10):
        return

    from services.business.birthday_service import check_birthdays_for_all_users
    alerts = await check_birthdays_for_all_users()
    if alerts:
        logger.info("Birthday detection: %d alerts sent", alerts)


async def _run_travel_detection() -> None:
    """Detect upcoming trips in calendar (once/day, 10:00-12:00 UTC)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Only run between 10:00-12:00 UTC (once per day)
    if not (10 <= now.hour <= 12):
        return

    from services.business.travel_planner_service import check_travel_for_all_users
    alerts = await check_travel_for_all_users()
    if alerts:
        logger.info("Travel detection: %d trip alerts sent", alerts)


async def main_loop() -> None:
    """Main loop that runs the proactivity cycle every 5 minutes."""
    while True:
        await run_proactivity_cycle()
        logger.info("Proactivity cycle completed. Waiting 5 minutes...")
        await asyncio.sleep(300)


if __name__ == "__main__":
    logger.info("Starting SuperBot God proactivity loop...")
    asyncio.run(main_loop())
