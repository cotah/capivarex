# -*- coding: utf-8 -*-
"""
Tests for GmailService.

Verifies import, helper functions (_extract_email, _extract_name),
and the list_emails guard when user is not connected.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.integrations.gmail_service import (
    GmailService,
    _extract_email,
    _extract_name,
)


# ── Import / instantiation ──────────────────────────────────────────────────


@pytest.mark.unit
def test_gmail_service_can_be_imported():
    """GmailService can be imported and instantiated."""
    svc = GmailService()
    assert svc.name == "gmail"


# ── list_emails guard ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_emails_raises_when_not_connected():
    """list_emails raises ServiceUnavailableError when user has no token."""
    from services.core import ServiceUnavailableError

    svc = GmailService()

    mock_oauth = AsyncMock()
    mock_oauth.get_valid_access_token = AsyncMock(return_value=None)

    with patch(
        "services.integrations.gmail_service.get_google_oauth",
        return_value=mock_oauth,
    ):
        with pytest.raises(ServiceUnavailableError):
            await svc.list_emails(user_id="u1", max_results=5)


# ── _extract_email helper ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "header, expected",
    [
        ("John Doe <john@example.com>", "john@example.com"),
        ("<jane@test.com>", "jane@test.com"),
        ("plain@email.com", "plain@email.com"),
        ("  spaced@email.com  ", "spaced@email.com"),
    ],
)
def test_extract_email(header, expected):
    """_extract_email extracts email from various From header formats."""
    assert _extract_email(header) == expected


# ── _extract_name helper ────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "header, expected",
    [
        ("John Doe <john@example.com>", "John Doe"),
        ('"Jane Smith" <jane@test.com>', "Jane Smith"),
        ("plain@email.com", "plain@email.com"),
    ],
)
def test_extract_name(header, expected):
    """_extract_name extracts display name from various From header formats."""
    assert _extract_name(header) == expected
