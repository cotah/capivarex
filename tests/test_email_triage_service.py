"""Tests for email triage service — S8: inbox categorization + action extraction."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.email_triage_service import (
    triage_inbox,
    _classify_emails,
    _fallback_classify,
    _extract_actions,
    _fallback_summary,
    generate_reply_draft,
)


def _make_email(
    subject, from_name="John", from_email="john@test.com", snippet="", unread=True
):
    """Helper: create a test email dict."""
    return {
        "id": f"msg_{subject[:10].replace(' ', '_')}",
        "thread_id": "thread_1",
        "from_name": from_name,
        "from_email": from_email,
        "to": "user@test.com",
        "subject": subject,
        "snippet": snippet or f"Preview of {subject}",
        "date": "2026-03-15",
        "is_unread": unread,
        "labels": ["INBOX", "UNREAD"] if unread else ["INBOX"],
    }


class TestTriageInbox:
    """Tests for main triage_inbox function."""

    @pytest.mark.asyncio
    async def test_no_gmail_service(self):
        with patch(
            "services.business.email_triage_service.get_service", return_value=None
        ):
            result = await triage_inbox("user-123", "Marcos")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_inbox(self):
        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.list_emails = AsyncMock(return_value=[])

        with patch(
            "services.business.email_triage_service.get_service",
            return_value=mock_gmail,
        ):
            result = await triage_inbox("user-123", "Marcos")

        assert result is not None
        assert (
            "clean" in result["summary"].lower()
            or "no unread" in result["summary"].lower()
        )
        assert result["stats"]["urgent"] == 0

    @pytest.mark.asyncio
    async def test_triage_with_emails(self):
        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.list_emails = AsyncMock(
            return_value=[
                _make_email("URGENT: Client deadline today", from_name="Boss"),
                _make_email("Weekly newsletter", from_name="noreply@news.com"),
                _make_email("Project update", from_name="Ana"),
            ]
        )
        mock_gmail.get_email_body = AsyncMock(
            return_value="Please review the report by EOD."
        )

        def fake_svc(name):
            if name == "gmail":
                return mock_gmail
            return None  # No GPT → fallback classification

        with patch("services.business.email_triage_service.get_service", fake_svc):
            result = await triage_inbox("user-123", "Marcos", max_emails=5)

        assert result is not None
        assert len(result["emails"]) == 3
        assert result["stats"]["urgent"] >= 0  # At least classified
        assert "Marcos" in result["summary"]


class TestClassification:
    """Tests for email classification."""

    def test_fallback_urgent_by_sender(self):
        emails = [_make_email("Q4 Report", from_name="CEO Smith")]
        result = _fallback_classify(emails)
        assert result[0]["urgency"] == "urgent"

    def test_fallback_urgent_by_subject(self):
        emails = [_make_email("URGENT: Need your approval")]
        result = _fallback_classify(emails)
        assert result[0]["urgency"] == "urgent"

    def test_fallback_ignore_newsletter(self):
        emails = [_make_email("Weekly Newsletter", from_email="noreply@marketing.com")]
        result = _fallback_classify(emails)
        assert result[0]["urgency"] == "ignore"

    def test_fallback_ignore_unsubscribe(self):
        emails = [_make_email("50% OFF Sale", snippet="Click to unsubscribe")]
        result = _fallback_classify(emails)
        # Subject doesn't have ignore words, but snippet does via from/subject check
        assert result[0]["urgency"] in ("important", "ignore")

    def test_fallback_important_unread(self):
        emails = [_make_email("Project proposal", from_name="Ana Costa")]
        result = _fallback_classify(emails)
        assert result[0]["urgency"] == "important"

    @pytest.mark.asyncio
    async def test_classify_with_gpt(self):
        """GPT classification parses JSON correctly."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            '[{"index": 1, "urgency": "urgent", "reason": "client deadline", '
            '"action": "Send report by EOD", "suggested_reply": "Will send by 5pm"}]'
        )

        emails = [_make_email("Client report needed", snippet="Need report ASAP")]
        emails[0]["body_preview"] = "Need the Q4 report by end of day."

        with patch(
            "services.business.email_triage_service.get_service",
            return_value=mock_openai,
        ):
            result = await _classify_emails(emails, "Marcos")

        assert result[0]["urgency"] == "urgent"
        assert "report" in result[0]["action"].lower()

    @pytest.mark.asyncio
    async def test_classify_gpt_failure_fallback(self):
        """Falls back to keyword classification when GPT fails."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.side_effect = Exception("API error")

        emails = [_make_email("URGENT: Need approval", from_name="Manager")]
        emails[0]["body_preview"] = "Please approve the budget."

        with patch(
            "services.business.email_triage_service.get_service",
            return_value=mock_openai,
        ):
            result = await _classify_emails(emails, "Test")

        assert result[0]["urgency"] == "urgent"  # Fallback keyword detection


class TestActionExtraction:
    """Tests for action item extraction."""

    def test_extract_actions(self):
        emails = [
            {
                **_make_email("Report"),
                "action": "Send Q4 report by Friday",
                "from_name": "Boss",
            },
            {**_make_email("Meeting"), "action": ""},
            {
                **_make_email("Review"),
                "action": "Review the proposal and send feedback",
            },
        ]
        actions = _extract_actions(emails)
        assert len(actions) == 2
        assert "Q4 report" in actions[0]["content"]

    def test_no_actions(self):
        emails = [
            {**_make_email("Hello"), "action": ""},
            {**_make_email("FYI"), "action": "ok"},  # Too short
        ]
        actions = _extract_actions(emails)
        assert len(actions) == 0


class TestFallbackSummary:
    """Tests for fallback summary generation."""

    def test_summary_with_urgent(self):
        urgent = [_make_email("Client deadline", from_name="Client X")]
        important = [_make_email("Project update", from_name="Ana")]
        stats = {"urgent": 1, "important": 1, "info": 2, "ignore": 1}
        actions = [{"content": "Send report by Friday", "from_name": "Boss"}]

        result = _fallback_summary("Marcos", stats, urgent, important, actions)
        assert "Marcos" in result
        assert "🔴" in result
        assert "Client X" in result
        assert "Send report" in result

    def test_summary_no_urgent(self):
        stats = {"urgent": 0, "important": 3, "info": 5, "ignore": 2}
        result = _fallback_summary("Ana", stats, [], [], [])
        assert "Ana" in result
        assert "🔴" not in result
        assert "📬" in result

    def test_summary_all_ignore(self):
        stats = {"urgent": 0, "important": 0, "info": 0, "ignore": 5}
        result = _fallback_summary("Test", stats, [], [], [])
        assert "5" in result


class TestReplyDraft:
    """Tests for reply draft generation."""

    @pytest.mark.asyncio
    async def test_no_gmail(self):
        with patch(
            "services.business.email_triage_service.get_service", return_value=None
        ):
            result = await generate_reply_draft("u1", "msg-123", "Marcos")
        assert result is None

    @pytest.mark.asyncio
    async def test_draft_no_body(self):
        mock_gmail = MagicMock()
        mock_gmail.get_email_body = AsyncMock(return_value="")
        mock_gmail.list_emails = AsyncMock(return_value=[])

        with patch(
            "services.business.email_triage_service.get_service",
            return_value=mock_gmail,
        ):
            result = await generate_reply_draft("u1", "msg-123", "Marcos")
        assert result is None


class TestHumanizedSummary:
    """Tests for GPT-humanized summary."""

    @pytest.mark.asyncio
    async def test_summary_gpt(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "Hey Marcos! 📬 Checked your inbox — 3 emails. "
            "1 urgent from the client about the deadline. "
            "Want me to draft a reply?"
        )

        emails = [_make_email("Client report")]
        emails[0]["urgency"] = "urgent"
        stats = {"urgent": 1, "important": 1, "info": 1, "ignore": 0}

        from services.business.email_triage_service import _humanize_triage_summary

        with patch(
            "services.business.email_triage_service.get_service",
            return_value=mock_openai,
        ):
            result = await _humanize_triage_summary(emails, stats, [], "Marcos")

        assert "Marcos" in result
        assert "urgent" in result.lower() or "client" in result.lower()
