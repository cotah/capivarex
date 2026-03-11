# -*- coding: utf-8 -*-
"""Tests for GmailService.send_email_with_attachment()."""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.integrations.gmail_service import GmailService


@pytest.fixture
def gmail_svc():
    svc = GmailService.__new__(GmailService)
    svc.name = "gmail"
    svc.logger = MagicMock()
    svc._api = AsyncMock(
        return_value={"id": "msg123", "threadId": "t1", "labelIds": ["SENT"]}
    )
    return svc


@pytest.mark.asyncio
async def test_send_with_xlsx_attachment(gmail_svc):
    """Sends email with .xlsx attachment — raw payload contains base64-encoded attachment."""
    xlsx_bytes = b"\x50\x4b\x03\x04" + b"\x00" * 100  # PK signature + padding

    result = await gmail_svc.send_email_with_attachment(
        user_id="user-1",
        to="dest@example.com",
        subject="Monthly Report",
        body="Here is your report.",
        attachment_bytes=xlsx_bytes,
        attachment_filename="report.xlsx",
    )

    assert result["id"] == "msg123"

    # Verify _api was called with POST messages/send and raw payload
    gmail_svc._api.assert_called_once()
    call_args = gmail_svc._api.call_args
    assert call_args[0][1] == "POST"
    assert call_args[0][2] == "messages/send"

    raw_b64 = call_args[1]["json_data"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    raw_str = raw_bytes.decode("utf-8", errors="replace")

    # Attachment filename present in MIME
    assert "report.xlsx" in raw_str
    # Base64 of the attachment bytes should be embedded (MIME wraps at 76 chars)
    attachment_b64 = base64.b64encode(xlsx_bytes).decode()
    # Strip whitespace from both sides for comparison (MIME adds line breaks)
    raw_no_ws = raw_str.replace("\n", "").replace("\r", "").replace(" ", "")
    assert attachment_b64 in raw_no_ws


@pytest.mark.asyncio
async def test_body_text_preserved_with_attachment(gmail_svc):
    """Body text is present alongside the attachment."""
    result = await gmail_svc.send_email_with_attachment(
        user_id="user-1",
        to="dest@example.com",
        subject="Test",
        body="Important body text here.",
        attachment_bytes=b"fake-data",
        attachment_filename="file.xlsx",
    )

    raw_b64 = gmail_svc._api.call_args[1]["json_data"]["raw"]
    raw_str = base64.urlsafe_b64decode(raw_b64).decode("utf-8", errors="replace")

    assert "Important body text here." in raw_str
    assert result["id"] == "msg123"


@pytest.mark.asyncio
async def test_mime_type_in_header(gmail_svc):
    """MIME type for xlsx appears in the raw email."""
    await gmail_svc.send_email_with_attachment(
        user_id="user-1",
        to="dest@example.com",
        subject="Test",
        body="body",
        attachment_bytes=b"data",
        attachment_filename="report.xlsx",
        attachment_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    raw_b64 = gmail_svc._api.call_args[1]["json_data"]["raw"]
    raw_str = base64.urlsafe_b64decode(raw_b64).decode("utf-8", errors="replace")

    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in raw_str
    )
