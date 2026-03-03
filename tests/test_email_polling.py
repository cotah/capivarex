# -*- coding: utf-8 -*-
"""
Tests for EmailPollingService — email polling & notifications.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.core import ServiceUnavailableError
from services.business.email_polling_service import (
    MAX_NOTIFICATIONS_PER_CYCLE,
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
    """Tests for summarize_for_notification."""

    @pytest.mark.asyncio
    async def test_single_email_with_llm_summary(self):
        svc = _build_service()

        email = _make_email(subject="Reunião Q3", sender_name="Maria")
        mock_ai = AsyncMock()
        mock_ai.is_initialized.return_value = True
        mock_ai.generate_text = AsyncMock(
            return_value="Meeting about Q3 goals."
        )

        mock_gmail = AsyncMock()
        mock_gmail.get_email_body = AsyncMock(return_value="Full body text here...")

        with (
            patch.object(svc, "_get_ai", return_value=mock_ai),
            patch.object(svc, "_get_gmail", return_value=mock_gmail),
        ):
            result = await svc.summarize_for_notification(
                [email], "user1", "en"
            )

        assert "Maria" in result
        assert "Reunião Q3" in result
        assert "Meeting about Q3 goals" in result

    @pytest.mark.asyncio
    async def test_multiple_emails_compact_list(self):
        svc = _build_service()

        emails = [
            _make_email(email_id="1", sender_name="João", subject="Reunião Q3"),
            _make_email(email_id="2", sender_name="Maria", subject="Orçamento"),
            _make_email(email_id="3", sender_name="GitHub", subject="PR #42"),
        ]

        result = await svc.summarize_for_notification(emails, "user1", "en")

        assert "3 new emails" in result
        assert "João" in result
        assert "Maria" in result
        assert "GitHub" in result
        assert "PR #42" in result

    @pytest.mark.asyncio
    async def test_empty_emails_returns_empty(self):
        svc = _build_service()
        result = await svc.summarize_for_notification([], "user1", "en")
        assert result == ""

    @pytest.mark.asyncio
    async def test_single_email_no_ai_uses_snippet(self):
        """Falls back to snippet when AI is unavailable."""
        svc = _build_service()

        email = _make_email(
            subject="Test", sender_name="Ana", snippet="Quick snippet"
        )

        with (
            patch.object(svc, "_get_ai", return_value=None),
            patch.object(svc, "_get_gmail", return_value=None),
        ):
            result = await svc.summarize_for_notification(
                [email], "user1", "pt"
            )

        assert "Ana" in result
        assert "Quick snippet" in result

    @pytest.mark.asyncio
    async def test_multiple_emails_pt_locale(self):
        svc = _build_service()

        emails = [
            _make_email(email_id="1", sender_name="João", subject="A"),
            _make_email(email_id="2", sender_name="Maria", subject="B"),
        ]

        result = await svc.summarize_for_notification(emails, "user1", "pt")

        assert "2 novos emails" in result


# ═══════════════════════════════════════════════════════════════════════════════
# TestTogglePolling
# ═══════════════════════════════════════════════════════════════════════════════


class TestTogglePolling:
    """Tests for enable_polling, disable_polling, is_polling_enabled."""

    @pytest.mark.asyncio
    async def test_enable_polling(self):
        svc = _build_service()

        mock_sb = MagicMock()
        mock_sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

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
        mock_sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

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
        """New emails trigger a Telegram notification."""
        from proactivity_loop import _run_email_polling

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
        mock_eps.summarize_for_notification = AsyncMock(
            return_value="New email from João"
        )
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

        with patch(
            "proactivity_loop.get_service",
            side_effect=lambda name: {
                "email_polling": mock_eps,
                "database": mock_db,
                "notification": mock_notif,
            }.get(name),
        ):
            await _run_email_polling()

        mock_notif.send_message.assert_called_once_with(
            "telegram", "chat_u1", "New email from João"
        )
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
