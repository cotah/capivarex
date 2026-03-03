# flake8: noqa: E501
"""
Callback handler for email inline-keyboard buttons.

Handles callbacks with pattern ``er:{action}:{email_id}``
where *action* is one of: send, edit, ignore, read, archive, confirm, cancel.

Draft data is stored in Redis with key ``email:draft:{user_id}:{email_id}``
(TTL 1 h).  Edit-mode state is ``email:editing:{chat_id}`` (TTL 5 min).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from services.core import ServiceUnavailableError, get_service
from services.i18n import t

logger = logging.getLogger("capivarex.telegram.handlers.email_callback")

_DRAFT_PREFIX = "email:draft"
_EDIT_PREFIX = "email:editing"
_DRAFT_TTL = 3600  # 1 hour
_EDIT_TTL = 300  # 5 minutes


# ── Main dispatcher ─────────────────────────────────────────────────────────


async def handle_email_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch ``er:{action}:{email_id}`` callback queries."""
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split(":", 2)
    if len(parts) < 3 or parts[0] != "er":
        return

    action = parts[1]
    email_id = parts[2]

    user_id = await _resolve_user_id(query.from_user.id)
    if not user_id:
        await query.answer(t("email_cb_error", lang="en"))
        return

    # Determine user language from draft or DB
    draft = await _get_draft(user_id, email_id)
    lang = (draft or {}).get("lang", "en")

    handlers = {
        "send": _handle_send,
        "edit": _handle_edit,
        "ignore": _handle_ignore,
        "read": _handle_read,
        "archive": _handle_archive,
        "confirm": _handle_confirm,
        "cancel": _handle_cancel,
        "cal_view": _handle_cal_view,
        "cal_add": _handle_cal_add,
    }

    handler = handlers.get(action)
    if not handler:
        await query.answer()
        return

    try:
        await handler(
            query=query,
            context=context,
            user_id=user_id,
            email_id=email_id,
            draft=draft,
            lang=lang,
        )
    except Exception as e:
        logger.exception("Email callback %s failed: %s", action, e)
        await query.answer(t("email_cb_error", lang=lang))


# ── Action handlers ──────────────────────────────────────────────────────────


async def _handle_send(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Send the suggested reply immediately."""
    await query.answer()

    if not draft:
        await query.edit_message_text(
            t("email_cb_draft_expired", lang=lang)
        )
        return

    gmail = get_service("gmail")
    if not gmail:
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return
    if not gmail.is_initialized():
        await gmail.initialize()

    reply_body = draft.get("suggested_reply", "")
    if not reply_body:
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return

    try:
        await gmail.send_email(
            user_id=user_id,
            to=draft["to"],
            subject=f"Re: {draft.get('subject', '')}",
            body=reply_body,
            reply_to_message_id=draft.get("message_id"),
            thread_id=draft.get("thread_id"),
        )
        await gmail.mark_as_read(user_id, email_id)
    except Exception as e:
        logger.error("send_email failed: %s", e)
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return

    await _delete_draft(user_id, email_id)
    sender = draft.get("from_name", draft.get("to", ""))
    await query.edit_message_text(
        t("email_cb_sent", lang=lang, sender=sender)
    )


async def _handle_edit(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Enter edit mode — store state in Redis and prompt user to type."""
    await query.answer()

    if not draft:
        await query.edit_message_text(
            t("email_cb_draft_expired", lang=lang)
        )
        return

    chat_id = query.message.chat_id
    edit_state = {
        "user_id": user_id,
        "email_id": email_id,
        "to": draft.get("to", ""),
        "subject": draft.get("subject", ""),
        "thread_id": draft.get("thread_id", ""),
        "message_id": draft.get("message_id", ""),
        "from_name": draft.get("from_name", ""),
        "lang": lang,
    }

    redis = get_service("redis")
    if redis:
        await redis.set(
            f"{_EDIT_PREFIX}:{chat_id}",
            edit_state,
            expire_seconds=_EDIT_TTL,
        )

    sender = draft.get("from_name", draft.get("to", ""))
    subject = draft.get("subject", "")
    await query.edit_message_text(
        t(
            "email_cb_edit_prompt",
            lang=lang,
            sender=sender,
            subject=subject,
        )
    )


async def _handle_ignore(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Mark email as read and dismiss."""
    await query.answer()

    gmail = get_service("gmail")
    if gmail:
        if not gmail.is_initialized():
            await gmail.initialize()
        try:
            await gmail.mark_as_read(user_id, email_id)
        except Exception as e:
            logger.warning("mark_as_read failed: %s", e)

    await _delete_draft(user_id, email_id)
    await query.edit_message_text(t("email_cb_ignored", lang=lang))


async def _handle_read(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Show full email body (truncated)."""
    await query.answer()

    gmail = get_service("gmail")
    if not gmail:
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return
    if not gmail.is_initialized():
        await gmail.initialize()

    try:
        body = await gmail.get_email_body(user_id, email_id)
    except Exception as e:
        logger.error("get_email_body failed: %s", e)
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return

    if not body:
        body = "(empty)"

    # Telegram message limit ~4096; leave room for subject header
    max_len = 3800
    if len(body) > max_len:
        body = body[:max_len] + "\n\n[...]"

    subject = (draft or {}).get("subject", "")
    header = f"Subject: {subject}\n\n" if subject else ""
    await query.edit_message_text(f"{header}{body}")


async def _handle_archive(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Archive email (remove from inbox)."""
    await query.answer()

    gmail = get_service("gmail")
    if gmail:
        if not gmail.is_initialized():
            await gmail.initialize()
        try:
            await gmail.archive(user_id, email_id)
        except Exception as e:
            logger.warning("archive failed: %s", e)

    await _delete_draft(user_id, email_id)
    await query.edit_message_text(t("email_cb_archived", lang=lang))


async def _handle_confirm(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Send user-edited reply (after edit mode)."""
    await query.answer()

    if not draft:
        await query.edit_message_text(
            t("email_cb_draft_expired", lang=lang)
        )
        return

    gmail = get_service("gmail")
    if not gmail:
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return
    if not gmail.is_initialized():
        await gmail.initialize()

    custom_reply = draft.get("custom_reply", "")
    if not custom_reply:
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return

    try:
        await gmail.send_email(
            user_id=user_id,
            to=draft["to"],
            subject=f"Re: {draft.get('subject', '')}",
            body=custom_reply,
            reply_to_message_id=draft.get("message_id"),
            thread_id=draft.get("thread_id"),
        )
        await gmail.mark_as_read(user_id, email_id)
    except Exception as e:
        logger.error("confirm send_email failed: %s", e)
        await query.edit_message_text(t("email_cb_error", lang=lang))
        return

    await _delete_draft(user_id, email_id)
    sender = draft.get("from_name", draft.get("to", ""))
    await query.edit_message_text(
        t("email_cb_sent", lang=lang, sender=sender)
    )


async def _handle_cancel(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Cancel edited reply — remove edit state."""
    await query.answer()

    chat_id = query.message.chat_id
    redis = get_service("redis")
    if redis:
        await redis.delete(f"{_EDIT_PREFIX}:{chat_id}")

    await query.edit_message_text(t("email_cb_ignored", lang=lang))


async def _handle_cal_view(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Show today's calendar events."""
    await query.answer()

    cal = get_service("calendar")
    if not cal:
        await query.edit_message_text(
            t("email_cal_unavailable", lang=lang)
        )
        return

    try:
        events = await cal.async_get_today_events(user_id)
    except ServiceUnavailableError:
        await query.edit_message_text(
            t("email_cal_not_connected", lang=lang)
        )
        return
    except Exception as e:
        logger.warning("cal_view failed: %s", e)
        await query.edit_message_text(
            t("email_cal_unavailable", lang=lang)
        )
        return

    if not events:
        await query.edit_message_text(
            t("email_cal_no_events", lang=lang)
        )
        return

    lines = [t("email_cal_today_header", lang=lang)]
    for ev in events:
        lines.append(cal.format_event_for_briefing(ev))
    await query.edit_message_text("\n".join(lines))


async def _handle_cal_add(
    *, query, context, user_id, email_id, draft, lang, **_kw
) -> None:
    """Create a calendar event from the meeting request."""
    await query.answer()

    if not draft:
        await query.edit_message_text(
            t("email_cb_draft_expired", lang=lang)
        )
        return

    proposed_dt = draft.get("proposed_datetime")
    if not proposed_dt:
        await query.edit_message_text(
            t("email_cal_no_datetime", lang=lang)
        )
        return

    cal = get_service("calendar")
    if not cal:
        await query.edit_message_text(
            t("email_cal_unavailable", lang=lang)
        )
        return

    try:
        start_time = datetime.fromisoformat(proposed_dt)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        end_time = start_time + timedelta(hours=1)
    except (ValueError, TypeError):
        await query.edit_message_text(
            t("email_cal_no_datetime", lang=lang)
        )
        return

    sender = draft.get("from_name", draft.get("to", ""))
    subject = draft.get("subject", "")
    location = draft.get("proposed_location", "")
    summary = f"{subject}" if subject else f"Meeting with {sender}"

    try:
        result = await cal.async_create_event(
            user_id=user_id,
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            location=location,
        )
    except ServiceUnavailableError:
        await query.edit_message_text(
            t("email_cal_not_connected", lang=lang)
        )
        return
    except Exception as e:
        logger.warning("cal_add failed: %s", e)
        await query.edit_message_text(
            t("email_cb_error", lang=lang)
        )
        return

    if result:
        await query.edit_message_text(
            t(
                "email_cal_event_created",
                lang=lang,
                summary=summary,
            )
        )
    else:
        await query.edit_message_text(
            t("email_cb_error", lang=lang)
        )


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _resolve_user_id(telegram_id: int) -> Optional[str]:
    """Convert Telegram user ID to internal UUID."""
    db = get_service("database")
    if not db:
        return None
    if not db.is_initialized():
        await db.initialize()

    try:
        user = await db.get_user_by_telegram_id(str(telegram_id))
        if user:
            return user.get("id")
    except Exception as e:
        logger.warning("_resolve_user_id failed: %s", e)
    return None


async def _get_draft(
    user_id: str, email_id: str
) -> Optional[Dict[str, Any]]:
    """Retrieve draft data from Redis."""
    redis = get_service("redis")
    if not redis:
        return None
    try:
        return await redis.get(
            f"{_DRAFT_PREFIX}:{user_id}:{email_id}",
            parse_json=True,
        )
    except Exception:
        return None


async def _delete_draft(user_id: str, email_id: str) -> None:
    """Remove draft from Redis."""
    redis = get_service("redis")
    if not redis:
        return
    try:
        await redis.delete(f"{_DRAFT_PREFIX}:{user_id}:{email_id}")
    except Exception:
        pass


def build_email_keyboard(
    email_id: str,
    needs_reply: bool,
    lang: str = "en",
    meeting_request: bool = False,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for an email notification.

    Args:
        email_id: Gmail message ID (used in callback_data).
        needs_reply: Whether the email needs a reply.
        lang: Language code for button labels.
        meeting_request: Whether this email is a meeting request.

    Returns:
        InlineKeyboardMarkup with action buttons.
    """
    if needs_reply:
        buttons = [
            InlineKeyboardButton(
                t("email_btn_send", lang=lang),
                callback_data=f"er:send:{email_id}",
            ),
            InlineKeyboardButton(
                t("email_btn_edit", lang=lang),
                callback_data=f"er:edit:{email_id}",
            ),
            InlineKeyboardButton(
                t("email_btn_ignore", lang=lang),
                callback_data=f"er:ignore:{email_id}",
            ),
        ]
    else:
        buttons = [
            InlineKeyboardButton(
                t("email_btn_read", lang=lang),
                callback_data=f"er:read:{email_id}",
            ),
            InlineKeyboardButton(
                t("email_btn_archive", lang=lang),
                callback_data=f"er:archive:{email_id}",
            ),
        ]

    rows = [buttons]

    # Add calendar row for meeting requests
    if meeting_request and needs_reply:
        cal_row = [
            InlineKeyboardButton(
                t("email_btn_cal_view", lang=lang),
                callback_data=f"er:cal_view:{email_id}",
            ),
            InlineKeyboardButton(
                t("email_btn_cal_add", lang=lang),
                callback_data=f"er:cal_add:{email_id}",
            ),
        ]
        rows.append(cal_row)

    return InlineKeyboardMarkup(rows)


def build_confirm_keyboard(
    email_id: str,
    lang: str = "en",
) -> InlineKeyboardMarkup:
    """Build confirm/cancel keyboard for edited reply."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("email_btn_send_now", lang=lang),
                    callback_data=f"er:confirm:{email_id}",
                ),
                InlineKeyboardButton(
                    t("email_btn_cancel", lang=lang),
                    callback_data=f"er:cancel:{email_id}",
                ),
            ]
        ]
    )


async def store_email_draft(
    user_id: str,
    email_id: str,
    draft_data: Dict[str, Any],
) -> None:
    """Store draft data in Redis with TTL."""
    redis = get_service("redis")
    if not redis:
        logger.warning("Redis unavailable — cannot store email draft")
        return
    try:
        await redis.set(
            f"{_DRAFT_PREFIX}:{user_id}:{email_id}",
            draft_data,
            expire_seconds=_DRAFT_TTL,
        )
    except Exception as e:
        logger.warning("Failed to store email draft: %s", e)
