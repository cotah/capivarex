# -*- coding: utf-8 -*-
"""Tests for Email Agent — send flow (Gmail + Outlook)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.specialized.email_agent import EmailAgent


def _make_agent():
    """Create an EmailAgent with mocked dependencies."""
    agent = EmailAgent()
    agent._db = MagicMock()
    agent._ai = MagicMock()
    agent._ai.complete = AsyncMock(return_value="Draft reply text")
    agent._initialized = True
    return agent


# ===========================================================================
# _send_email — provider resolution
# ===========================================================================


class TestSendEmail:
    """Tests for the unified _send_email method."""

    @pytest.mark.asyncio
    async def test_send_via_gmail_when_connected(self):
        agent = _make_agent()

        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.is_connected = AsyncMock(return_value=True)
        mock_gmail.send_email = AsyncMock(return_value={"id": "msg_123", "threadId": "th_1"})

        with patch("agents.specialized.email_agent.get_service", return_value=mock_gmail):
            result = await agent._send_email(
                to="test@example.com",
                subject="Hello",
                body="Test body",
                user_id="user-1",
            )

        assert result["success"] is True
        assert result["provider"] == "gmail"
        mock_gmail.send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_via_outlook_when_explicitly_requested(self):
        agent = _make_agent()

        mock_outlook = MagicMock()
        mock_outlook.is_initialized.return_value = True
        mock_outlook.send_email = AsyncMock(return_value={"id": "", "threadId": ""})

        mock_ms_oauth = MagicMock()
        mock_ms_oauth.is_connected = AsyncMock(return_value=True)

        with (
            patch(
                "agents.specialized.email_agent.get_service",
                side_effect=lambda name: mock_outlook if name == "outlook" else None,
            ),
            patch(
                "services.auth.microsoft_oauth_service.get_microsoft_oauth",
                return_value=mock_ms_oauth,
            ),
        ):
            result = await agent._send_email(
                to="test@example.com",
                subject="Hello",
                body="Test body",
                user_id="user-1",
                provider="outlook",
            )

        assert result["success"] is True
        assert result["provider"] == "outlook"
        mock_outlook.send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_fails_without_user_id(self):
        agent = _make_agent()

        result = await agent._send_email(
            to="test@example.com",
            subject="Hello",
            body="Test body",
            user_id="",
        )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_send_fails_when_no_provider_connected(self):
        agent = _make_agent()

        with patch(
            "agents.specialized.email_agent.EmailAgent._resolve_email_service",
            new_callable=AsyncMock,
            return_value=(None, None),
        ):
            result = await agent._send_email(
                to="test@example.com",
                subject="Hello",
                body="Test body",
                user_id="user-1",
            )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_send_returns_auth_url_when_gmail_not_connected(self):
        agent = _make_agent()

        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.is_connected = AsyncMock(return_value=False)
        mock_gmail.get_auth_url = MagicMock(return_value="https://accounts.google.com/auth")

        with patch(
            "agents.specialized.email_agent.EmailAgent._resolve_email_service",
            new_callable=AsyncMock,
            return_value=(mock_gmail, "gmail"),
        ):
            result = await agent._send_email(
                to="test@example.com",
                subject="Hello",
                body="Test body",
                user_id="user-1",
            )

        assert result["success"] is False
        assert "auth_url" in result

    @pytest.mark.asyncio
    async def test_send_handles_api_exception(self):
        agent = _make_agent()

        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.is_connected = AsyncMock(return_value=True)
        mock_gmail.send_email = AsyncMock(side_effect=Exception("API error"))

        with patch(
            "agents.specialized.email_agent.EmailAgent._resolve_email_service",
            new_callable=AsyncMock,
            return_value=(mock_gmail, "gmail"),
        ):
            result = await agent._send_email(
                to="test@example.com",
                subject="Hello",
                body="Test body",
                user_id="user-1",
            )

        assert result["success"] is False
        assert "API error" in result["error"]

    @pytest.mark.asyncio
    async def test_send_passes_reply_params(self):
        agent = _make_agent()

        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.is_connected = AsyncMock(return_value=True)
        mock_gmail.send_email = AsyncMock(return_value={"id": "msg_1", "threadId": "th_1"})

        with patch(
            "agents.specialized.email_agent.EmailAgent._resolve_email_service",
            new_callable=AsyncMock,
            return_value=(mock_gmail, "gmail"),
        ):
            await agent._send_email(
                to="test@example.com",
                subject="Re: Hello",
                body="Reply text",
                user_id="user-1",
                reply_to_message_id="msg_original",
                thread_id="th_original",
            )

        call_kwargs = mock_gmail.send_email.call_args[1]
        assert call_kwargs["reply_to_message_id"] == "msg_original"
        assert call_kwargs["thread_id"] == "th_original"


# ===========================================================================
# Outlook send_email_with_attachment
# ===========================================================================


class TestOutlookSendWithAttachment:
    """Tests for the Outlook attachment sending method."""

    @pytest.mark.asyncio
    async def test_sends_attachment_via_graph(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()

        with patch.object(svc, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"status": "ok"}

            result = await svc.send_email_with_attachment(
                user_id="user-1",
                to="test@example.com",
                subject="Report",
                body="See attached",
                attachment_bytes=b"PDF content here",
                attachment_filename="report.pdf",
                attachment_mime="application/pdf",
            )

        assert result is True
        call_args = mock_api.call_args
        assert call_args[0][1] == "POST"
        assert call_args[0][2] == "/me/sendMail"

        # Verify attachment structure
        json_body = call_args[1]["json_body"]
        attachments = json_body["message"]["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["name"] == "report.pdf"
        assert attachments[0]["contentType"] == "application/pdf"
        assert attachments[0]["@odata.type"] == "#microsoft.graph.fileAttachment"

    @pytest.mark.asyncio
    async def test_attachment_returns_false_on_failure(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()

        with patch.object(svc, "_api", new_callable=AsyncMock, return_value=None):
            result = await svc.send_email_with_attachment(
                user_id="user-1",
                to="test@example.com",
                subject="Report",
                body="See attached",
                attachment_bytes=b"content",
                attachment_filename="file.txt",
            )

        assert result is False


# ===========================================================================
# Outlook send_email signature compatibility
# ===========================================================================


class TestOutlookSendSignature:
    """Tests that Outlook send_email accepts email_agent's parameter names."""

    @pytest.mark.asyncio
    async def test_accepts_reply_to_message_id_param(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()

        with patch.object(svc, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"status": "ok"}

            result = await svc.send_email(
                user_id="user-1",
                to="test@example.com",
                subject="Re: Hello",
                body="Reply",
                reply_to_message_id="msg_abc123",
                thread_id="th_xyz",  # should be accepted without error
            )

        assert result  # not empty dict = success
        # Should have called the reply endpoint
        call_args = mock_api.call_args
        assert "/reply" in call_args[0][2]

    @pytest.mark.asyncio
    async def test_new_email_without_reply_id(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()

        with patch.object(svc, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"status": "ok"}

            result = await svc.send_email(
                user_id="user-1",
                to="test@example.com",
                subject="New email",
                body="Content",
            )

        assert result
        call_args = mock_api.call_args
        assert call_args[0][2] == "/me/sendMail"
