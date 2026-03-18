# -*- coding: utf-8 -*-
"""
Tests for EmailPollingService — email polling & notifications.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.core import ServiceUnavailableError
from services.business.email_polling_service import (
    MAX_NOTIFICATIONS_PER_CYCLE,
    EmailAnalysis,
    EmailNotification,
    EmailNotificationBatch,
    EmailPollingService,
)

_SB_PATCH = "services.infrastructure.database.get_supabase_client"
_OAUTH_PATCH = "services.auth.google_oauth_service.get_google_oauth"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_email(
    email_id: str = "msg1",
    labels: list | None = None,
    sender_name: str = "João",
    sender_email: str = "joao@gmail.com",
    subject: str = "Test",
    snippet: str = "Hello there",
) -> dict:
    """Build a minimal email dict matching GmailService output."""
    return {
        "id": email_id,
        "labels": labels if labels is not None else ["INBOX", "CATEGORY_PRIMARY"],
        "from_name": sender_name,
        "from_email": sender_email,
        "subject": subject,
        "snippet": snippet,
        "thread_id": "thread1",
        "is_unread": True,
    }


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


# ═══════════════════════════════════════════════════════════════════════════════
# TestFilterByLabels
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilterByLabels:
    """Tests for the static filter_by_labels method."""

    def test_primary_inbox_passes(self):
        email = _make_email(labels=["INBOX", "CATEGORY_PRIMARY"])
        assert EmailPollingService.filter_by_labels([email]) == [email]

    def test_updates_inbox_passes(self):
        email = _make_email(labels=["INBOX", "CATEGORY_UPDATES"])
        assert EmailPollingService.filter_by_labels([email]) == [email]

    def test_no_category_inbox_passes(self):
        email = _make_email(labels=["INBOX", "UNREAD"])
        assert EmailPollingService.filter_by_labels([email]) == [email]

    def test_personal_inbox_passes(self):
        email = _make_email(labels=["INBOX", "CATEGORY_PERSONAL"])
        assert EmailPollingService.filter_by_labels([email]) == [email]

    def test_spam_excluded(self):
        email = _make_email(labels=["INBOX", "SPAM"])
        assert EmailPollingService.filter_by_labels([email]) == []

    def test_promotions_excluded(self):
        email = _make_email(labels=["INBOX", "CATEGORY_PROMOTIONS"])
        assert EmailPollingService.filter_by_labels([email]) == []

    def test_social_excluded(self):
        email = _make_email(labels=["INBOX", "CATEGORY_SOCIAL"])
        assert EmailPollingService.filter_by_labels([email]) == []

    def test_forums_excluded(self):
        email = _make_email(labels=["INBOX", "CATEGORY_FORUMS"])
        assert EmailPollingService.filter_by_labels([email]) == []

    def test_not_inbox_excluded(self):
        email = _make_email(labels=["SENT", "CATEGORY_PRIMARY"])
        assert EmailPollingService.filter_by_labels([email]) == []

    def test_trash_excluded(self):
        email = _make_email(labels=["INBOX", "TRASH"])
        assert EmailPollingService.filter_by_labels([email]) == []

    def test_mixed_batch(self):
        """Batch with good and bad emails filters correctly."""
        good = _make_email(email_id="good", labels=["INBOX", "CATEGORY_PRIMARY"])
        spam = _make_email(email_id="spam", labels=["INBOX", "SPAM"])
        promo = _make_email(email_id="promo", labels=["INBOX", "CATEGORY_PROMOTIONS"])
        result = EmailPollingService.filter_by_labels([good, spam, promo])
        assert result == [good]


# ═══════════════════════════════════════════════════════════════════════════════
# TestPollNewEmails
# ═══════════════════════════════════════════════════════════════════════════════


class TestPollNewEmails:
    """Tests for poll_new_emails method."""

    @pytest.mark.asyncio
    async def test_returns_only_new_emails(self):
        """Already-known IDs are excluded."""
        svc = _build_service()

        mock_gmail = AsyncMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.list_emails = AsyncMock(
            return_value=[
                _make_email(email_id="old1"),
                _make_email(email_id="new1"),
                _make_email(email_id="new2"),
            ]
        )

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"last_message_ids": ["old1"]}]
        )

        with (
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
            patch(_SB_PATCH, return_value=mock_sb),
        ):
            result = await svc.poll_new_emails("user1")

        assert len(result) == 2
        assert all(e["id"] in ("new1", "new2") for e in result)

    @pytest.mark.asyncio
    async def test_empty_inbox_returns_empty(self):
        svc = _build_service()

        mock_gmail = AsyncMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.list_emails = AsyncMock(return_value=[])

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        with (
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
            patch(_SB_PATCH, return_value=mock_sb),
        ):
            result = await svc.poll_new_emails("user1")

        assert result == []

    @pytest.mark.asyncio
    async def test_max_per_cycle_cap(self):
        """At most MAX_NOTIFICATIONS_PER_CYCLE emails returned."""
        svc = _build_service()

        emails = [_make_email(email_id=f"msg{i}") for i in range(10)]

        mock_gmail = AsyncMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.list_emails = AsyncMock(return_value=emails)

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        with (
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
            patch(_SB_PATCH, return_value=mock_sb),
        ):
            result = await svc.poll_new_emails("user1")

        assert len(result) == MAX_NOTIFICATIONS_PER_CYCLE

    @pytest.mark.asyncio
    async def test_token_expired_disables_polling(self):
        """ServiceUnavailableError disables polling and returns []."""
        svc = _build_service()

        mock_gmail = AsyncMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.list_emails = AsyncMock(
            side_effect=ServiceUnavailableError("expired")
        )

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with (
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
            patch(_SB_PATCH, return_value=mock_sb),
        ):
            result = await svc.poll_new_emails("user1")

        assert result == []
        # Verify disable was called on the Supabase table
        mock_sb.table.return_value.update.assert_called()

    @pytest.mark.asyncio
    async def test_no_gmail_service_returns_empty(self):
        """Returns [] when GmailService is unavailable."""
        svc = _build_service()

        with patch.object(svc, "_get_gmail", return_value=None):
            result = await svc.poll_new_emails("user1")

        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# TestSummarizeForNotification
# ═══════════════════════════════════════════════════════════════════════════════


class TestSummarize:
    """Tests for summarize_for_notification (returns EmailNotificationBatch)."""

    @pytest.mark.asyncio
    async def test_single_email_with_llm_summary(self):
        svc = _build_service()

        email = _make_email(subject="Reunião Q3", sender_name="Maria")
        mock_ai = AsyncMock()
        mock_ai.is_initialized.return_value = True
        mock_ai.chat_completion = AsyncMock(return_value="Meeting about Q3 goals.")

        mock_gmail = AsyncMock()
        mock_gmail.get_email_body = AsyncMock(return_value="Full body text here...")

        with (
            patch.object(svc, "_get_ai", return_value=mock_ai),
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
        ):
            batch = await svc.summarize_for_notification([email], "user1", "en")

        assert isinstance(batch, EmailNotificationBatch)
        assert len(batch.notifications) == 1
        assert not batch.is_multiple
        notif = batch.notifications[0]
        assert "Maria" in notif.text
        assert "Reunião Q3" in notif.text
        assert notif.email_id == "msg1"
        assert isinstance(notif.analysis, EmailAnalysis)

    @pytest.mark.asyncio
    async def test_multiple_emails_compact_list(self):
        svc = _build_service()

        emails = [
            _make_email(email_id="1", sender_name="João", subject="Reunião Q3"),
            _make_email(email_id="2", sender_name="Maria", subject="Orçamento"),
            _make_email(email_id="3", sender_name="GitHub", subject="PR #42"),
        ]

        batch = await svc.summarize_for_notification(emails, "user1", "en")

        assert isinstance(batch, EmailNotificationBatch)
        assert batch.is_multiple
        assert "3 new emails" in batch.grouped_text
        assert "João" in batch.grouped_text
        assert "Maria" in batch.grouped_text
        assert "GitHub" in batch.grouped_text
        assert "PR #42" in batch.grouped_text
        assert len(batch.notifications) == 3

    @pytest.mark.asyncio
    async def test_empty_emails_returns_empty_batch(self):
        svc = _build_service()
        batch = await svc.summarize_for_notification([], "user1", "en")
        assert isinstance(batch, EmailNotificationBatch)
        assert batch.notifications == []
        assert batch.grouped_text == ""

    @pytest.mark.asyncio
    async def test_single_email_no_ai_uses_snippet(self):
        """Falls back to snippet when AI is unavailable."""
        svc = _build_service()

        email = _make_email(subject="Test", sender_name="Ana", snippet="Quick snippet")

        with (
            patch.object(svc, "_get_ai", return_value=None),
            patch.object(svc, "_get_gmail", return_value=None),
        ):
            batch = await svc.summarize_for_notification([email], "user1", "pt")

        assert len(batch.notifications) == 1
        assert "Ana" in batch.notifications[0].text
        assert "Quick snippet" in batch.notifications[0].text

    @pytest.mark.asyncio
    async def test_multiple_emails_pt_locale(self):
        svc = _build_service()

        emails = [
            _make_email(email_id="1", sender_name="João", subject="A"),
            _make_email(email_id="2", sender_name="Maria", subject="B"),
        ]

        batch = await svc.summarize_for_notification(emails, "user1", "pt")

        assert batch.is_multiple
        assert "2 novos emails" in batch.grouped_text


# ═══════════════════════════════════════════════════════════════════════════════
# TestTogglePolling
# ═══════════════════════════════════════════════════════════════════════════════


class TestTogglePolling:
    """Tests for enable_polling, disable_polling, is_polling_enabled."""

    @pytest.mark.asyncio
    async def test_enable_polling(self):
        svc = _build_service()

        mock_sb = MagicMock()
        mock_sb.table.return_value.upsert.return_value.execute.return_value = (
            MagicMock()
        )

        with patch(_SB_PATCH, return_value=mock_sb):
            result = await svc.enable_polling("user1")

        assert result is True
        mock_sb.table.assert_called_with("email_poll_state")

    @pytest.mark.asyncio
    async def test_disable_polling(self):
        svc = _build_service()

        mock_sb = MagicMock()
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch(_SB_PATCH, return_value=mock_sb):
            result = await svc.disable_polling("user1")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_polling_enabled_true(self):
        svc = _build_service()

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"notify_enabled": True}]
        )

        with patch(_SB_PATCH, return_value=mock_sb):
            result = await svc.is_polling_enabled("user1")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_polling_enabled_false(self):
        svc = _build_service()

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"notify_enabled": False}]
        )

        with patch(_SB_PATCH, return_value=mock_sb):
            result = await svc.is_polling_enabled("user1")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_polling_enabled_no_row(self):
        svc = _build_service()

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        with patch(_SB_PATCH, return_value=mock_sb):
            result = await svc.is_polling_enabled("user1")

        assert result is False

    @pytest.mark.asyncio
    async def test_enable_no_db_returns_false(self):
        svc = _build_service()

        with patch(_SB_PATCH, return_value=None):
            result = await svc.enable_polling("user1")

        assert result is False

    @pytest.mark.asyncio
    async def test_disable_no_db_returns_false(self):
        svc = _build_service()

        with patch(_SB_PATCH, return_value=None):
            result = await svc.disable_polling("user1")

        assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# TestCreatePollState
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreatePollState:
    """Tests for create_poll_state."""

    @pytest.mark.asyncio
    async def test_create_poll_state(self):
        svc = _build_service()

        mock_sb = MagicMock()
        mock_sb.table.return_value.upsert.return_value.execute.return_value = (
            MagicMock()
        )

        with patch(_SB_PATCH, return_value=mock_sb):
            await svc.create_poll_state("user1")

        call_args = mock_sb.table.return_value.upsert.call_args
        data = call_args[0][0]
        assert data["user_id"] == "user1"
        assert data["notify_enabled"] is True
        assert data["check_interval_minutes"] == 5
        assert data["last_message_ids"] == []

    @pytest.mark.asyncio
    async def test_create_poll_state_no_db(self):
        """Does not raise when DB unavailable."""
        svc = _build_service()

        with patch(_SB_PATCH, return_value=None):
            await svc.create_poll_state("user1")  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# TestMarkAsNotified
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarkAsNotified:
    """Tests for mark_as_notified."""

    @pytest.mark.asyncio
    async def test_merges_ids_and_updates(self):
        svc = _build_service()

        mock_sb = MagicMock()
        # _get_known_ids returns existing IDs
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"last_message_ids": ["old1", "old2"]}]
        )
        # mark_as_notified update
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch(_SB_PATCH, return_value=mock_sb):
            await svc.mark_as_notified("user1", ["new1", "new2"])

        update_call = mock_sb.table.return_value.update.call_args
        data = update_call[0][0]
        ids = data["last_message_ids"]
        assert "old1" in ids
        assert "old2" in ids
        assert "new1" in ids
        assert "new2" in ids
        assert "last_checked_at" in data

    @pytest.mark.asyncio
    async def test_no_db_does_not_raise(self):
        svc = _build_service()

        with patch(_SB_PATCH, return_value=None):
            await svc.mark_as_notified("user1", ["id1"])  # no raise


# ═══════════════════════════════════════════════════════════════════════════════
# TestGetPollableUsers
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetPollableUsers:
    """Tests for get_pollable_users."""

    @pytest.mark.asyncio
    async def test_returns_users_with_gmail_connected(self):
        svc = _build_service()

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {"user_id": "u1", "check_interval_minutes": 5, "last_checked_at": None},
                {"user_id": "u2", "check_interval_minutes": 5, "last_checked_at": None},
            ]
        )

        mock_oauth = AsyncMock()
        mock_oauth.is_connected = AsyncMock(side_effect=[True, False])

        with (
            patch.object(svc, "_get_db", return_value=mock_db),
            patch(_SB_PATCH, return_value=mock_sb),
            patch(_OAUTH_PATCH, return_value=mock_oauth),
        ):
            result = await svc.get_pollable_users()

        assert len(result) == 1
        assert result[0]["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_empty_when_no_users(self):
        svc = _build_service()

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        with (
            patch.object(svc, "_get_db", return_value=mock_db),
            patch(_SB_PATCH, return_value=mock_sb),
        ):
            result = await svc.get_pollable_users()

        assert result == []

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self):
        svc = _build_service()

        with patch.object(svc, "_get_db", return_value=None):
            result = await svc.get_pollable_users()

        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# TestProactivityIntegration
# ═══════════════════════════════════════════════════════════════════════════════


class TestProactivityIntegration:
    """Tests for _run_email_polling (in proactivity_loop)."""

    @pytest.mark.asyncio
    async def test_run_email_polling_with_new_emails(self):
        """New emails trigger a Telegram notification with keyboard."""
        from proactivity_loop import _run_email_polling

        batch = EmailNotificationBatch(
            notifications=[
                EmailNotification(
                    text="New email from João",
                    email_id="new1",
                    thread_id="t1",
                    from_email="joao@test.com",
                    from_name="João",
                    subject="Test",
                    analysis=EmailAnalysis(needs_reply=False),
                    user_id="u1",
                    lang="en",
                )
            ],
            is_multiple=False,
        )

        mock_eps = AsyncMock()
        mock_eps.is_initialized.return_value = True
        mock_eps.get_pollable_users = AsyncMock(
            return_value=[
                {"user_id": "u1", "check_interval_minutes": 5, "last_checked_at": None}
            ]
        )
        mock_eps.poll_new_emails = AsyncMock(
            return_value=[_make_email(email_id="new1")]
        )
        mock_eps.summarize_for_notification = AsyncMock(return_value=batch)
        mock_eps.mark_as_notified = AsyncMock()

        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_id = AsyncMock(
            return_value={
                "id": "u1",
                "preferred_language": "en",
                "telegram_chat_id": "chat_u1",
            }
        )

        mock_notif = AsyncMock()
        mock_notif.is_initialized.return_value = True

        mock_redis = AsyncMock()

        with patch(
            "proactivity_loop.get_service",
            side_effect=lambda name: {
                "email_polling": mock_eps,
                "database": mock_db,
                "notification": mock_notif,
                "redis": mock_redis,
            }.get(name),
        ):
            await _run_email_polling()

        mock_notif.send_message.assert_called_once()
        call_args = mock_notif.send_message.call_args
        assert call_args[0][0] == "telegram"
        assert call_args[0][1] == "chat_u1"
        assert call_args[0][2] == "New email from João"
        # reply_markup keyword should be present
        assert "reply_markup" in call_args[1]
        mock_eps.mark_as_notified.assert_called_once_with("u1", ["new1"])

    @pytest.mark.asyncio
    async def test_run_email_polling_no_service_is_noop(self):
        """When email_polling service unavailable, does nothing."""
        from proactivity_loop import _run_email_polling

        with patch("proactivity_loop.get_service", return_value=None):
            await _run_email_polling()  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# TestPollToggleIntent
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# TestCheckCalendarConflicts
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckCalendarConflicts:
    """Tests for _check_calendar_conflicts."""

    @pytest.mark.asyncio
    async def test_conflict_detected(self):
        svc = _build_service()
        mock_cal = AsyncMock()
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                {
                    "summary": "Team standup",
                    "start": "2026-03-04T15:00:00+00:00",
                    "end": "2026-03-04T16:00:00+00:00",
                },
            ]
        )
        with patch.object(svc, "_get_calendar", return_value=mock_cal):
            result = await svc._check_calendar_conflicts("u1", "2026-03-04T15:00:00")
        assert result is not None
        assert result["has_conflict"] is True
        assert result["conflicting_event"] == "Team standup"
        assert "15:00" in result["conflict_time"]

    @pytest.mark.asyncio
    async def test_no_conflict(self):
        svc = _build_service()
        mock_cal = AsyncMock()
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                {
                    "summary": "Early meeting",
                    "start": "2026-03-04T09:00:00+00:00",
                    "end": "2026-03-04T10:00:00+00:00",
                },
            ]
        )
        with patch.object(svc, "_get_calendar", return_value=mock_cal):
            result = await svc._check_calendar_conflicts("u1", "2026-03-04T15:00:00")
        assert result is not None
        assert result["has_conflict"] is False
        assert result["conflicting_event"] == ""

    @pytest.mark.asyncio
    async def test_calendar_unavailable(self):
        svc = _build_service()
        with patch.object(svc, "_get_calendar", return_value=None):
            result = await svc._check_calendar_conflicts("u1", "2026-03-04T15:00:00")
        assert result is None

    @pytest.mark.asyncio
    async def test_user_not_connected(self):
        svc = _build_service()
        mock_cal = AsyncMock()
        mock_cal.async_get_upcoming_events = AsyncMock(
            side_effect=ServiceUnavailableError("not connected")
        )
        with patch.object(svc, "_get_calendar", return_value=mock_cal):
            result = await svc._check_calendar_conflicts("u1", "2026-03-04T15:00:00")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_datetime(self):
        svc = _build_service()
        mock_cal = AsyncMock()
        with patch.object(svc, "_get_calendar", return_value=mock_cal):
            result = await svc._check_calendar_conflicts("u1", "not-a-date")
        assert result is None

    @pytest.mark.asyncio
    async def test_free_slots_found(self):
        from datetime import datetime as real_datetime, timezone

        svc = _build_service()
        mock_cal = AsyncMock()
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                {
                    "summary": "Blocked",
                    "start": "2026-03-04T15:00:00+00:00",
                    "end": "2026-03-04T16:00:00+00:00",
                },
            ]
        )

        # Fix time at 10:00 UTC so slots after 10:00 are not filtered as past
        class _FrozenDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2026, 3, 4, 10, 0, 0, tzinfo=timezone.utc)

        with (
            patch.object(svc, "_get_calendar", return_value=mock_cal),
            patch(
                "services.business.email_polling_service.datetime",
                _FrozenDatetime,
            ),
        ):
            result = await svc._check_calendar_conflicts("u1", "2026-03-04T15:00:00")
        assert result is not None
        assert isinstance(result["free_slots_today"], list)
        assert len(result["free_slots_today"]) > 0
        # 15:00 and 15:30 should NOT be in free slots
        assert "15:00" not in result["free_slots_today"]
        assert "15:30" not in result["free_slots_today"]


# ═══════════════════════════════════════════════════════════════════════════════
# TestFormatSingleRichMeeting
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatSingleRichMeeting:
    """Tests for _format_single_rich with meeting requests."""

    @pytest.mark.asyncio
    async def test_meeting_with_conflict(self):
        svc = _build_service()
        email = _make_email(
            subject="Reunião amanhã",
            sender_name="João",
        )
        mock_ai = AsyncMock()
        mock_ai.is_initialized.return_value = True
        # 1st call: _get_llm_summary, 2nd: _analyze_email, 3rd: _reprompt
        mock_ai.chat_completion = AsyncMock(
            side_effect=[
                "João wants to meet tomorrow at 3pm",
                '{"needs_reply": true, "suggested_reply": "OK", '
                '"urgency": "high", "event_request": true, '
                '"proposed_datetime": "2026-03-04T15:00:00", '
                '"proposed_location": "office"}',
                '{"suggested_reply": "Tenho compromisso às 15h. Podemos às 16h?"}',
            ]
        )
        mock_gmail = AsyncMock()
        mock_gmail.get_email_body = AsyncMock(return_value="Meeting tomorrow at 3pm?")
        conflict = {
            "has_conflict": True,
            "conflicting_event": "Team standup",
            "conflict_time": "15:00-16:00",
            "next_free_slot": "16:00",
            "free_slots_today": ["16:00", "17:00"],
        }
        with (
            patch.object(svc, "_get_ai", return_value=mock_ai),
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
            patch.object(
                svc,
                "_check_calendar_conflicts",
                return_value=conflict,
            ),
        ):
            notif = await svc._format_single_rich(email, "u1", "en")

        assert notif.analysis.event_request is True
        assert "Team standup" in notif.text
        assert "16:00" in notif.text

    @pytest.mark.asyncio
    async def test_meeting_no_conflict(self):
        svc = _build_service()
        email = _make_email(
            subject="Meeting",
            sender_name="Maria",
        )
        mock_ai = AsyncMock()
        mock_ai.is_initialized.return_value = True
        # 1st: summary, 2nd: analysis (no reprompt needed)
        mock_ai.chat_completion = AsyncMock(
            side_effect=[
                "Maria wants to meet at 10am",
                '{"needs_reply": true, "suggested_reply": "Sure!", '
                '"urgency": "medium", "event_request": true, '
                '"proposed_datetime": "2026-03-04T10:00:00", '
                '"proposed_location": ""}',
            ]
        )
        mock_gmail = AsyncMock()
        mock_gmail.get_email_body = AsyncMock(return_value="Can we meet at 10am?")
        no_conflict = {
            "has_conflict": False,
            "conflicting_event": "",
            "conflict_time": "",
            "next_free_slot": "10:00",
            "free_slots_today": ["10:00", "11:00"],
        }
        with (
            patch.object(svc, "_get_ai", return_value=mock_ai),
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
            patch.object(
                svc,
                "_check_calendar_conflicts",
                return_value=no_conflict,
            ),
        ):
            notif = await svc._format_single_rich(email, "u1", "en")

        assert notif.analysis.event_request is True
        # Should contain the "free" indicator
        assert "\u2705" in notif.text

    @pytest.mark.asyncio
    async def test_meeting_no_calendar(self):
        """Meeting detected but calendar unavailable — no cal text appended."""
        svc = _build_service()
        email = _make_email(subject="Lunch?", sender_name="Ana")
        mock_ai = AsyncMock()
        mock_ai.is_initialized.return_value = True
        # 1st: summary, 2nd: analysis
        mock_ai.chat_completion = AsyncMock(
            side_effect=[
                "Ana wants to have lunch at noon",
                '{"needs_reply": true, "suggested_reply": "Sure!", '
                '"urgency": "low", "event_request": true, '
                '"proposed_datetime": "2026-03-04T12:00:00", '
                '"proposed_location": ""}',
            ]
        )
        mock_gmail = AsyncMock()
        mock_gmail.get_email_body = AsyncMock(return_value="Lunch at noon?")
        with (
            patch.object(svc, "_get_ai", return_value=mock_ai),
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
            patch.object(
                svc,
                "_check_calendar_conflicts",
                return_value=None,
            ),
        ):
            notif = await svc._format_single_rich(email, "u1", "en")

        assert notif.analysis.event_request is True
        # No conflict/free text since calendar was unavailable
        assert "CONFLICT" not in notif.text.upper().replace("\u26a0\ufe0f", "")

    @pytest.mark.asyncio
    async def test_non_meeting_unchanged(self):
        """Non-meeting email is unchanged from previous behavior."""
        svc = _build_service()
        email = _make_email(subject="FYI Report", sender_name="Carlos")
        mock_ai = AsyncMock()
        mock_ai.is_initialized.return_value = True
        # 1st: summary, 2nd: analysis
        mock_ai.chat_completion = AsyncMock(
            side_effect=[
                "Carlos sent a report",
                '{"needs_reply": false, "suggested_reply": "", '
                '"urgency": "low", "event_request": false, '
                '"proposed_datetime": null, "proposed_location": ""}',
            ]
        )
        mock_gmail = AsyncMock()
        mock_gmail.get_email_body = AsyncMock(return_value="Attached is the report.")
        with (
            patch.object(svc, "_get_ai", return_value=mock_ai),
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
        ):
            notif = await svc._format_single_rich(email, "u1", "en")

        assert notif.analysis.event_request is False
        assert "Carlos" in notif.text
        assert "FYI Report" in notif.text


class TestPollToggleIntent:
    """Tests for email notification toggle via EmailAgent."""

    def test_enable_regex_matches(self):
        from agents.specialized.email_agent import _RE_POLL_ENABLE

        assert _RE_POLL_ENABLE.search("ativar notificac\u00f5es de email")
        assert _RE_POLL_ENABLE.search("enable email notifications")
        assert _RE_POLL_ENABLE.search("ligar alertas de email")
        assert _RE_POLL_ENABLE.search("activar notificaciones email")

    def test_disable_regex_matches(self):
        from agents.specialized.email_agent import _RE_POLL_DISABLE

        assert _RE_POLL_DISABLE.search("desativar notificac\u00f5es de email")
        assert _RE_POLL_DISABLE.search("disable email notifications")
        assert _RE_POLL_DISABLE.search("parar alertas de email")
        assert _RE_POLL_DISABLE.search("desactivar notificaciones")
        assert _RE_POLL_DISABLE.search("stop email alerts")

    @pytest.mark.asyncio
    async def test_enable_via_email_agent(self):
        from agents.specialized.email_agent import EmailAgent

        agent = EmailAgent()
        agent._initialized = True
        agent._db = MagicMock()
        agent._ai = None

        mock_eps = AsyncMock()
        mock_eps.is_initialized.return_value = True
        mock_eps.is_polling_enabled = AsyncMock(return_value=False)
        mock_eps.enable_polling = AsyncMock(return_value=True)

        mock_gmail = AsyncMock()
        mock_gmail.is_connected = AsyncMock(return_value=True)

        with (
            patch(
                "agents.specialized.email_agent.get_service",
                side_effect=lambda name: {
                    "email_polling": mock_eps,
                    "gmail": mock_gmail,
                }.get(name),
            ),
            patch(
                "agents.specialized.email_agent.edb.get_email_accounts",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await agent.execute(
                "ativar notificac\u00f5es de email",
                {"user_id": "u1", "lang": "pt"},
            )

        assert result.is_success()
        assert (
            "ativadas" in result.response.lower()
            or "activated" in result.response.lower()
        )

    @pytest.mark.asyncio
    async def test_disable_via_email_agent(self):
        from agents.specialized.email_agent import EmailAgent

        agent = EmailAgent()
        agent._initialized = True
        agent._db = MagicMock()
        agent._ai = None

        mock_eps = AsyncMock()
        mock_eps.is_initialized.return_value = True
        mock_eps.is_polling_enabled = AsyncMock(return_value=True)
        mock_eps.disable_polling = AsyncMock(return_value=True)

        with (
            patch(
                "agents.specialized.email_agent.get_service",
                side_effect=lambda name: {
                    "email_polling": mock_eps,
                }.get(name),
            ),
            patch(
                "agents.specialized.email_agent.edb.get_email_accounts",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await agent.execute(
                "desativar notificac\u00f5es de email",
                {"user_id": "u1", "lang": "pt"},
            )

        assert result.is_success()
        assert (
            "desativadas" in result.response.lower()
            or "deactivated" in result.response.lower()
        )
