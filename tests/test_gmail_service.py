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


# ── _extract_body helper ────────────────────────────────────────────────────


@pytest.mark.unit
def test_extract_body_text_plain():
    """_extract_body returns decoded text/plain."""
    import base64

    from services.integrations.gmail_service import _extract_body

    text = "Hello world!"
    encoded = base64.urlsafe_b64encode(text.encode()).decode()
    payload = {"mimeType": "text/plain", "body": {"data": encoded}}
    assert _extract_body(payload) == "Hello world!"


@pytest.mark.unit
def test_extract_body_multipart():
    """_extract_body finds text/plain in multipart parts."""
    import base64

    from services.integrations.gmail_service import _extract_body

    text = "Nested text"
    encoded = base64.urlsafe_b64encode(text.encode()).decode()
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": encoded}},
            {"mimeType": "text/html", "body": {"data": ""}},
        ],
    }
    assert _extract_body(payload) == "Nested text"


@pytest.mark.unit
def test_extract_body_html_fallback():
    """_extract_body falls back to text/html and strips tags."""
    import base64

    from services.integrations.gmail_service import _extract_body

    html = "<p>Hello <b>world</b></p>"
    encoded = base64.urlsafe_b64encode(html.encode()).decode()
    payload = {"mimeType": "text/html", "body": {"data": encoded}}
    assert "Hello" in _extract_body(payload)
    assert "<p>" not in _extract_body(payload)


@pytest.mark.unit
def test_extract_body_empty():
    """_extract_body returns empty string for unknown mime type."""
    from services.integrations.gmail_service import _extract_body

    assert _extract_body({"mimeType": "application/octet-stream"}) == ""


# ── _initialize / _health_check ─────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_success():
    """_initialize succeeds when OAuth is configured."""
    from unittest.mock import Mock

    mock_oauth = Mock()
    mock_oauth.is_configured = True

    svc = GmailService()
    with patch(
        "services.integrations.gmail_service.get_google_oauth",
        return_value=mock_oauth,
    ):
        await svc._initialize()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_not_configured():
    """_initialize raises ServiceUnavailableError when OAuth not configured."""
    from unittest.mock import Mock

    from services.core import ServiceUnavailableError

    mock_oauth = Mock()
    mock_oauth.is_configured = False

    svc = GmailService()
    with (
        patch(
            "services.integrations.gmail_service.get_google_oauth",
            return_value=mock_oauth,
        ),
        pytest.raises(ServiceUnavailableError),
    ):
        await svc._initialize()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_configured():
    """_health_check returns True when OAuth is configured."""
    from unittest.mock import Mock

    mock_oauth = Mock()
    mock_oauth.is_configured = True

    svc = GmailService()
    with patch(
        "services.integrations.gmail_service.get_google_oauth",
        return_value=mock_oauth,
    ):
        assert await svc._health_check() is True


# ── _api helper ─────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_success():
    """_api returns JSON on 200 response."""
    from unittest.mock import MagicMock

    svc = GmailService()
    svc._initialized = True

    mock_oauth = AsyncMock()
    mock_oauth.get_valid_access_token = AsyncMock(return_value="token_ok")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": []}

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "services.integrations.gmail_service.get_google_oauth",
            return_value=mock_oauth,
        ),
        patch(
            "services.integrations.gmail_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await svc._api("u1", "GET", "messages")

    assert result == {"messages": []}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_401_raises_service_unavailable():
    """_api raises ServiceUnavailableError on 401."""
    from unittest.mock import MagicMock

    from services.core import ServiceUnavailableError

    svc = GmailService()
    svc._initialized = True

    mock_oauth = AsyncMock()
    mock_oauth.get_valid_access_token = AsyncMock(return_value="token_ok")

    mock_resp = MagicMock()
    mock_resp.status_code = 401

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "services.integrations.gmail_service.get_google_oauth",
            return_value=mock_oauth,
        ),
        patch(
            "services.integrations.gmail_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
        pytest.raises(ServiceUnavailableError),
    ):
        await svc._api("u1", "GET", "messages")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_204_returns_success():
    """_api returns {success: True} on 204 response."""
    from unittest.mock import MagicMock

    svc = GmailService()
    svc._initialized = True

    mock_oauth = AsyncMock()
    mock_oauth.get_valid_access_token = AsyncMock(return_value="token_ok")

    mock_resp = MagicMock()
    mock_resp.status_code = 204

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "services.integrations.gmail_service.get_google_oauth",
            return_value=mock_oauth,
        ),
        patch(
            "services.integrations.gmail_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await svc._api("u1", "POST", "messages/123/modify")

    assert result == {"success": True}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_500_raises_runtime_error():
    """_api raises RuntimeError on non-200/204/401 responses."""
    from unittest.mock import MagicMock

    svc = GmailService()
    svc._initialized = True

    mock_oauth = AsyncMock()
    mock_oauth.get_valid_access_token = AsyncMock(return_value="token_ok")

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "services.integrations.gmail_service.get_google_oauth",
            return_value=mock_oauth,
        ),
        patch(
            "services.integrations.gmail_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
        pytest.raises(RuntimeError, match="Gmail API 500"),
    ):
        await svc._api("u1", "GET", "messages")


# ── Gmail operations via mocked _api ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_emails_calls_api():
    """list_emails calls _api for message list + metadata."""
    svc = GmailService()

    async def mock_api(user_id, method, endpoint, **kwargs):
        if endpoint == "messages":
            return {"messages": [{"id": "m1"}]}
        if endpoint == "messages/m1":
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "Hello",
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Test <test@x.com>"},
                        {"name": "Subject", "value": "Hi"},
                        {"name": "Date", "value": "Mon, 1 Jan 2026"},
                        {"name": "To", "value": "me@x.com"},
                        {"name": "Message-ID", "value": "<mid@x>"},
                    ]
                },
            }
        return {}

    with patch.object(svc, "_api", side_effect=mock_api):
        emails = await svc.list_emails("u1", max_results=5)

    assert len(emails) == 1
    assert emails[0]["from_email"] == "test@x.com"
    assert emails[0]["subject"] == "Hi"
    assert emails[0]["is_unread"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_email_calls_api():
    """send_email builds MIME message and posts to API."""
    svc = GmailService()

    with patch.object(
        svc, "_api", new_callable=AsyncMock,
        return_value={"id": "sent_1", "threadId": "t1", "labelIds": ["SENT"]},
    ) as mock_api:
        result = await svc.send_email(
            user_id="u1", to="to@x.com", subject="Test", body="Hello"
        )

    assert result["id"] == "sent_1"
    mock_api.assert_called_once()
    call_kwargs = mock_api.call_args
    assert call_kwargs[0][1] == "POST"
    assert call_kwargs[0][2] == "messages/send"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_email_with_reply():
    """send_email includes In-Reply-To and threadId for replies."""
    svc = GmailService()

    with patch.object(
        svc, "_api", new_callable=AsyncMock,
        return_value={"id": "sent_2"},
    ) as mock_api:
        await svc.send_email(
            user_id="u1",
            to="to@x.com",
            subject="Re: Test",
            body="Reply",
            reply_to_message_id="<orig@x>",
            thread_id="t1",
        )

    payload = mock_api.call_args.kwargs.get("json_data", {})
    assert "threadId" in payload
    assert payload["threadId"] == "t1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_email_body_calls_api():
    """get_email_body fetches full message and extracts body."""
    import base64

    svc = GmailService()
    text = "Email body content"
    encoded = base64.urlsafe_b64encode(text.encode()).decode()

    with patch.object(
        svc, "_api", new_callable=AsyncMock,
        return_value={
            "payload": {"mimeType": "text/plain", "body": {"data": encoded}}
        },
    ):
        body = await svc.get_email_body("u1", "m1")

    assert body == "Email body content"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mark_as_read_calls_api():
    """mark_as_read posts modify with removeLabelIds=['UNREAD']."""
    svc = GmailService()

    with patch.object(svc, "_api", new_callable=AsyncMock) as mock_api:
        await svc.mark_as_read("u1", "m1")

    mock_api.assert_called_once_with(
        "u1", "POST", "messages/m1/modify",
        json_data={"removeLabelIds": ["UNREAD"]},
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mark_as_unread_calls_api():
    """mark_as_unread posts modify with addLabelIds=['UNREAD']."""
    svc = GmailService()

    with patch.object(svc, "_api", new_callable=AsyncMock) as mock_api:
        await svc.mark_as_unread("u1", "m1")

    mock_api.assert_called_once_with(
        "u1", "POST", "messages/m1/modify",
        json_data={"addLabelIds": ["UNREAD"]},
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_archive_calls_api():
    """archive removes INBOX label."""
    svc = GmailService()

    with patch.object(svc, "_api", new_callable=AsyncMock) as mock_api:
        await svc.archive("u1", "m1")

    mock_api.assert_called_once_with(
        "u1", "POST", "messages/m1/modify",
        json_data={"removeLabelIds": ["INBOX"]},
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trash_calls_api():
    """trash posts to messages/id/trash."""
    svc = GmailService()

    with patch.object(svc, "_api", new_callable=AsyncMock) as mock_api:
        await svc.trash("u1", "m1")

    mock_api.assert_called_once_with(
        "u1", "POST", "messages/m1/trash",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_profile_calls_api():
    """get_profile returns profile data."""
    svc = GmailService()

    with patch.object(
        svc, "_api", new_callable=AsyncMock,
        return_value={"emailAddress": "test@gmail.com", "messagesTotal": 100},
    ):
        result = await svc.get_profile("u1")

    assert result["emailAddress"] == "test@gmail.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_unread_count():
    """get_unread_count returns resultSizeEstimate."""
    svc = GmailService()

    with patch.object(
        svc, "_api", new_callable=AsyncMock,
        return_value={"resultSizeEstimate": 7},
    ):
        count = await svc.get_unread_count("u1")

    assert count == 7


# ── auth helpers ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_auth_url():
    """get_auth_url delegates to GoogleOAuthService."""
    from unittest.mock import Mock

    svc = GmailService()
    mock_oauth = Mock()
    mock_oauth.get_auth_url.return_value = "https://auth.url"

    with patch(
        "services.integrations.gmail_service.get_google_oauth",
        return_value=mock_oauth,
    ):
        url = svc.get_auth_url("u1")

    assert url == "https://auth.url"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_connected():
    """is_connected delegates to GoogleOAuthService."""
    svc = GmailService()
    mock_oauth = AsyncMock()
    mock_oauth.is_connected = AsyncMock(return_value=True)

    with patch(
        "services.integrations.gmail_service.get_google_oauth",
        return_value=mock_oauth,
    ):
        assert await svc.is_connected("u1") is True
