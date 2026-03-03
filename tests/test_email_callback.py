# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""
Tests for email callback handler, keyboard builder, draft storage, and LLM analysis.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.business.email_polling_service import EmailPollingService
from telegram_bot.handlers.email_callback import (
    _DRAFT_PREFIX,
    _DRAFT_TTL,
    build_confirm_keyboard,
    build_email_keyboard,
    handle_email_callback,
    store_email_draft,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_service() -> EmailPollingService:
    """Instantiate service without triggering registry."""
    svc = object.__new__(EmailPollingService)
    svc.name = "email_polling"
    svc.config = {}
    svc._initialized = True
    svc._status = None
    svc._call_count = 0
    svc._error_count = 0
    svc._total_latency = 0.0
    import logging

    svc.logger = logging.getLogger("test.email_polling")
    return svc


def _make_query(data: str, chat_id: int = 100, from_id: int = 42):
    """Build a minimal CallbackQuery-like mock."""
    query = AsyncMock()
    query.data = data
    query.from_user = MagicMock()
    query.from_user.id = from_id
    query.message = MagicMock()
    query.message.chat_id = chat_id
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    return query


def _make_update(query):
    """Build an Update mock wrapping a CallbackQuery."""
    update = MagicMock()
    update.callback_query = query
    return update


_DRAFT = {
    "to": "sender@test.com",
    "subject": "Test Subject",
    "thread_id": "thread1",
    "message_id": "<msg1@test.com>",
    "from_name": "Sender",
    "user_id": "uuid-1",
    "lang": "en",
    "suggested_reply": "Thanks for your email!",
}


# ═══════════════════════════════════════════════════════════════════════════════
# TestParseAnalysis
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseAnalysis:
    """Tests for EmailPollingService._parse_analysis."""

    def test_valid_json(self):
        raw = '{"needs_reply": true, "suggested_reply": "Hi!", "urgency": "high"}'
        result = EmailPollingService._parse_analysis(raw)
        assert result.needs_reply is True
        assert result.suggested_reply == "Hi!"
        assert result.urgency == "high"

    def test_markdown_fenced_json(self):
        raw = '```json\n{"needs_reply": false, "suggested_reply": "", "urgency": "low"}\n```'
        result = EmailPollingService._parse_analysis(raw)
        assert result.needs_reply is False
        assert result.urgency == "low"

    def test_invalid_json_returns_defaults(self):
        result = EmailPollingService._parse_analysis("not json at all")
        assert result.needs_reply is False
        assert result.suggested_reply == ""
        assert result.urgency == "low"

    def test_partial_json_fills_defaults(self):
        raw = '{"needs_reply": true}'
        result = EmailPollingService._parse_analysis(raw)
        assert result.needs_reply is True
        assert result.suggested_reply == ""
        assert result.urgency == "low"

    def test_meeting_fields_parsed(self):
        raw = (
            '{"needs_reply": true, "suggested_reply": "OK", '
            '"urgency": "high", "meeting_request": true, '
            '"proposed_datetime": "2026-03-04T15:00:00", '
            '"proposed_location": "office"}'
        )
        result = EmailPollingService._parse_analysis(raw)
        assert result.meeting_request is True
        assert result.proposed_datetime == "2026-03-04T15:00:00"
        assert result.proposed_location == "office"

    def test_no_meeting_fields_default(self):
        raw = '{"needs_reply": false, "suggested_reply": "", "urgency": "low"}'
        result = EmailPollingService._parse_analysis(raw)
        assert result.meeting_request is False
        assert result.proposed_datetime is None
        assert result.proposed_location == ""


# ═══════════════════════════════════════════════════════════════════════════════
# TestBuildEmailKeyboard
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildEmailKeyboard:
    """Tests for build_email_keyboard."""

    def test_reply_keyboard_has_three_buttons(self):
        kb = build_email_keyboard("msg123", needs_reply=True, lang="en")
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 3
        # Send, Edit, Ignore
        assert "er:send:msg123" in buttons[0].callback_data
        assert "er:edit:msg123" in buttons[1].callback_data
        assert "er:ignore:msg123" in buttons[2].callback_data

    def test_noreply_keyboard_has_two_buttons(self):
        kb = build_email_keyboard("msg456", needs_reply=False, lang="pt")
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 2
        # Read full, Archive
        assert "er:read:msg456" in buttons[0].callback_data
        assert "er:archive:msg456" in buttons[1].callback_data

    def test_callback_data_under_64_bytes(self):
        """Telegram limit: callback_data must be ≤ 64 bytes."""
        long_id = "a" * 50
        kb = build_email_keyboard(long_id, needs_reply=True, lang="en")
        for row in kb.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode()) <= 64

    def test_meeting_keyboard_two_rows(self):
        """Meeting request adds a second row with calendar buttons."""
        kb = build_email_keyboard(
            "msg789", needs_reply=True, lang="en", meeting_request=True
        )
        assert len(kb.inline_keyboard) == 2
        # First row: Send, Edit, Ignore
        assert len(kb.inline_keyboard[0]) == 3
        # Second row: Calendar, Add event
        cal_row = kb.inline_keyboard[1]
        assert len(cal_row) == 2
        assert "er:cal_view:msg789" in cal_row[0].callback_data
        assert "er:cal_add:msg789" in cal_row[1].callback_data

    def test_meeting_callback_data_size(self):
        """Calendar callback_data must be ≤ 64 bytes."""
        long_id = "a" * 50
        kb = build_email_keyboard(
            long_id, needs_reply=True, lang="en", meeting_request=True
        )
        for row in kb.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode()) <= 64

    def test_meeting_noreply_no_calendar_row(self):
        """No calendar row when needs_reply is False even with meeting."""
        kb = build_email_keyboard(
            "msg1", needs_reply=False, lang="en", meeting_request=True
        )
        assert len(kb.inline_keyboard) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TestBuildConfirmKeyboard
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildConfirmKeyboard:
    """Tests for build_confirm_keyboard."""

    def test_confirm_keyboard_has_two_buttons(self):
        kb = build_confirm_keyboard("msg123", lang="en")
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 2
        assert "er:confirm:msg123" in buttons[0].callback_data
        assert "er:cancel:msg123" in buttons[1].callback_data


# ═══════════════════════════════════════════════════════════════════════════════
# TestDraftStorage
# ═══════════════════════════════════════════════════════════════════════════════


class TestDraftStorage:
    """Tests for store_email_draft."""

    @pytest.mark.asyncio
    async def test_store_draft_sets_redis_key(self):
        mock_redis = AsyncMock()

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            return_value=mock_redis,
        ):
            await store_email_draft("user1", "msg1", {"to": "a@b.com"})

        mock_redis.set.assert_called_once_with(
            f"{_DRAFT_PREFIX}:user1:msg1",
            {"to": "a@b.com"},
            expire_seconds=_DRAFT_TTL,
        )

    @pytest.mark.asyncio
    async def test_store_draft_no_redis_does_not_raise(self):
        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            return_value=None,
        ):
            await store_email_draft("user1", "msg1", {})  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# TestAnalyzeEmail
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalyzeEmail:
    """Tests for EmailPollingService._analyze_email."""

    @pytest.mark.asyncio
    async def test_success_returns_analysis(self):
        svc = _build_service()

        mock_ai = AsyncMock()
        mock_ai.is_initialized.return_value = True
        mock_ai.generate_text = AsyncMock(
            return_value='{"needs_reply": true, "suggested_reply": "Got it!", "urgency": "medium"}'
        )

        email = {"from_name": "Alice", "subject": "Meeting", "id": "m1"}

        with patch.object(svc, "_get_ai", return_value=mock_ai):
            result = await svc._analyze_email(email, "u1", "Summary text", "en")

        assert result.needs_reply is True
        assert result.suggested_reply == "Got it!"
        assert result.urgency == "medium"

    @pytest.mark.asyncio
    async def test_no_ai_returns_defaults(self):
        svc = _build_service()

        with patch.object(svc, "_get_ai", return_value=None):
            result = await svc._analyze_email({}, "u1", "Summary", "en")

        assert result.needs_reply is False
        assert result.suggested_reply == ""


# ═══════════════════════════════════════════════════════════════════════════════
# TestEmailCallbackHandler
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmailCallbackHandler:
    """Tests for the main handle_email_callback dispatcher."""

    @pytest.mark.asyncio
    async def test_send_sends_reply_and_marks_read(self):
        """send action: sends email, marks read, edits msg."""
        query = _make_query("er:send:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_gmail = AsyncMock()
        mock_gmail.is_initialized.return_value = True
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_redis.delete = AsyncMock()
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "gmail": mock_gmail,
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        mock_gmail.send_email.assert_called_once()
        mock_gmail.mark_as_read.assert_called_once_with("uuid-1", "msg1")
        mock_redis.delete.assert_called()
        query.edit_message_text.assert_called_once()
        assert "Sender" in query.edit_message_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_send_with_expired_draft(self):
        """send action with no draft shows expiry message."""
        query = _make_query("er:send:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "expired" in text.lower() or "expirou" in text.lower()

    @pytest.mark.asyncio
    async def test_edit_sets_redis_state(self):
        """edit action: stores edit state in Redis."""
        query = _make_query("er:edit:msg1", chat_id=999)
        update = _make_update(query)
        context = MagicMock()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        # Verify edit state was stored
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert "email:editing:999" in call_args[0][0]
        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignore_marks_as_read(self):
        """ignore action: marks email as read."""
        query = _make_query("er:ignore:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_gmail = AsyncMock()
        mock_gmail.is_initialized.return_value = True
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_redis.delete = AsyncMock()
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "gmail": mock_gmail,
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        mock_gmail.mark_as_read.assert_called_once_with("uuid-1", "msg1")
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_archive_archives_email(self):
        """archive action: archives email."""
        query = _make_query("er:archive:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_gmail = AsyncMock()
        mock_gmail.is_initialized.return_value = True
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_redis.delete = AsyncMock()
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "gmail": mock_gmail,
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        mock_gmail.archive.assert_called_once_with("uuid-1", "msg1")
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_unknown_action_answers_silently(self):
        """Unknown action just answers the query."""
        query = _make_query("er:unknown:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_user_resolved_shows_error(self):
        """When user cannot be resolved, shows error."""
        query = _make_query("er:send:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(return_value=None)

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.answer.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# TestUrgencyEmoji
# ═══════════════════════════════════════════════════════════════════════════════


class TestUrgencyEmoji:
    """Tests for _urgency_emoji static method."""

    def test_high_returns_red(self):
        assert EmailPollingService._urgency_emoji("high") == "\U0001f534"

    def test_medium_returns_yellow(self):
        assert EmailPollingService._urgency_emoji("medium") == "\U0001f7e1"

    def test_low_returns_green(self):
        assert EmailPollingService._urgency_emoji("low") == "\U0001f7e2"

    def test_unknown_returns_green(self):
        assert EmailPollingService._urgency_emoji("xyz") == "\U0001f7e2"


# ═══════════════════════════════════════════════════════════════════════════════
# TestCalendarCallbacks
# ═══════════════════════════════════════════════════════════════════════════════


class TestCalendarCallbacks:
    """Tests for cal_view and cal_add callback handlers."""

    @pytest.mark.asyncio
    async def test_cal_view_shows_events(self):
        """cal_view: shows today's events."""
        query = _make_query("er:cal_view:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_cal = AsyncMock()
        mock_cal.async_get_today_events = AsyncMock(
            return_value=[
                {"summary": "Standup", "start": "2026-03-03T09:00:00+00:00", "end": "2026-03-03T09:30:00+00:00", "location": ""},
                {"summary": "Lunch", "start": "2026-03-03T12:00:00+00:00", "end": "2026-03-03T13:00:00+00:00", "location": ""},
            ]
        )
        mock_cal.format_event_for_briefing = MagicMock(
            side_effect=lambda ev: f"* {ev['summary']}"
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "calendar": mock_cal,
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "Standup" in text
        assert "Lunch" in text

    @pytest.mark.asyncio
    async def test_cal_view_no_events(self):
        """cal_view: shows no-events message."""
        query = _make_query("er:cal_view:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_cal = AsyncMock()
        mock_cal.async_get_today_events = AsyncMock(return_value=[])
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "calendar": mock_cal,
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.edit_message_text.assert_called_once()
        # Should say no events
        text = query.edit_message_text.call_args[0][0]
        assert "no event" in text.lower() or "nenhum" in text.lower()

    @pytest.mark.asyncio
    async def test_cal_view_not_connected(self):
        """cal_view: shows not-connected when ServiceUnavailableError."""
        from services.core import ServiceUnavailableError

        query = _make_query("er:cal_view:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_cal = AsyncMock()
        mock_cal.async_get_today_events = AsyncMock(
            side_effect=ServiceUnavailableError("not connected")
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_DRAFT)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "calendar": mock_cal,
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "not connected" in text.lower() or "não conectado" in text.lower() or "Calendar" in text

    @pytest.mark.asyncio
    async def test_cal_add_creates_event(self):
        """cal_add: creates event from draft."""
        query = _make_query("er:cal_add:msg1")
        update = _make_update(query)
        context = MagicMock()

        draft_with_meeting = {
            **_DRAFT,
            "proposed_datetime": "2026-03-04T15:00:00",
            "proposed_location": "office",
        }
        mock_cal = AsyncMock()
        mock_cal.async_create_event = AsyncMock(
            return_value={"id": "event1"}
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=draft_with_meeting)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "calendar": mock_cal,
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        mock_cal.async_create_event.assert_called_once()
        call_kw = mock_cal.async_create_event.call_args[1]
        assert call_kw["user_id"] == "uuid-1"
        assert call_kw["location"] == "office"
        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "\u2705" in text  # success emoji

    @pytest.mark.asyncio
    async def test_cal_add_no_datetime(self):
        """cal_add: shows error when no proposed_datetime in draft."""
        query = _make_query("er:cal_add:msg1")
        update = _make_update(query)
        context = MagicMock()

        draft_no_dt = {**_DRAFT}  # no proposed_datetime
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=draft_no_dt)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "date" in text.lower() or "hora" in text.lower()

    @pytest.mark.asyncio
    async def test_cal_add_expired_draft(self):
        """cal_add: shows expired when draft is gone."""
        query = _make_query("er:cal_add:msg1")
        update = _make_update(query)
        context = MagicMock()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": "uuid-1"}
        )

        with patch(
            "telegram_bot.handlers.email_callback.get_service",
            side_effect=lambda name: {
                "redis": mock_redis,
                "database": mock_db,
            }.get(name),
        ):
            await handle_email_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "expired" in text.lower() or "expirou" in text.lower()
