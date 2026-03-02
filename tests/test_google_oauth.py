# -*- coding: utf-8 -*-
"""
Tests for GoogleOAuthService.

Verifies OAuth2 flow helpers: is_configured, auth URL generation,
token storage, token retrieval, connection check, and disconnect.
All Supabase and httpx calls are mocked.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.auth.google_oauth_service import GoogleOAuthService


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def oauth_configured():
    """GoogleOAuthService with client_id + client_secret set."""
    svc = GoogleOAuthService()
    svc.client_id = "test-client-id"
    svc.client_secret = "test-client-secret"
    svc.redirect_uri = "http://localhost:8000/api/auth/google/callback"
    return svc


@pytest.fixture
def oauth_unconfigured():
    """GoogleOAuthService without credentials."""
    svc = GoogleOAuthService()
    svc.client_id = ""
    svc.client_secret = ""
    return svc


# ── is_configured ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_is_configured_true(oauth_configured):
    """is_configured returns True when both client_id and secret are set."""
    assert oauth_configured.is_configured is True


@pytest.mark.unit
def test_is_configured_false(oauth_unconfigured):
    """is_configured returns False when credentials are missing."""
    assert oauth_unconfigured.is_configured is False


# ── get_auth_url ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_auth_url_contains_required_params(oauth_configured):
    """Auth URL contains client_id, redirect_uri, scope, state."""
    url = oauth_configured.get_auth_url(user_id="user_42")

    assert "accounts.google.com" in url
    assert "client_id=test-client-id" in url
    assert "redirect_uri=" in url
    assert "scope=" in url
    assert "state=" in url
    assert "access_type=offline" in url


@pytest.mark.unit
def test_get_auth_url_state_encodes_user_id(oauth_configured):
    """State parameter is base64-encoded JSON containing user_id."""
    import base64
    from urllib.parse import parse_qs, urlparse

    url = oauth_configured.get_auth_url(user_id="user_42")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    state_b64 = qs["state"][0]
    state_data = json.loads(base64.urlsafe_b64decode(state_b64))

    assert state_data["user_id"] == "user_42"


# ── save_tokens ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_tokens_calls_supabase_upsert(oauth_configured):
    """save_tokens upserts token row into Supabase."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.upsert.return_value = mock_table
    mock_table.execute.return_value = None

    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=mock_sb,
    ):
        await oauth_configured.save_tokens(
            user_id="u1",
            email="test@gmail.com",
            access_token="at_123",
            refresh_token="rt_456",
            expires_in=3600,
        )

    mock_sb.table.assert_called_once_with("user_oauth_tokens")
    mock_table.upsert.assert_called_once()
    upserted = mock_table.upsert.call_args[0][0]
    assert upserted["user_id"] == "u1"
    assert upserted["access_token"] == "at_123"
    assert upserted["refresh_token"] == "rt_456"
    assert upserted["active"] is True


# ── get_valid_access_token ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_valid_access_token_returns_token(oauth_configured):
    """Returns access_token when token is still valid."""
    future = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).isoformat()

    token_row = {
        "access_token": "valid_token",
        "refresh_token": "rt",
        "expires_at": future,
        "email": "test@gmail.com",
    }

    with patch.object(
        oauth_configured, "_get_token_row", new_callable=AsyncMock,
        return_value=token_row,
    ):
        result = await oauth_configured.get_valid_access_token("u1")

    assert result == "valid_token"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_valid_access_token_returns_none_if_not_connected(
    oauth_configured,
):
    """Returns None when user has no token row."""
    with patch.object(
        oauth_configured, "_get_token_row", new_callable=AsyncMock,
        return_value=None,
    ):
        result = await oauth_configured.get_valid_access_token("u1")

    assert result is None


# ── is_connected ─────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_connected_true(oauth_configured):
    """is_connected returns True when token row exists."""
    with patch.object(
        oauth_configured, "_get_token_row", new_callable=AsyncMock,
        return_value={"access_token": "x"},
    ):
        assert await oauth_configured.is_connected("u1") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_connected_false(oauth_configured):
    """is_connected returns False when no token row."""
    with patch.object(
        oauth_configured, "_get_token_row", new_callable=AsyncMock,
        return_value=None,
    ):
        assert await oauth_configured.is_connected("u1") is False


# ── disconnect ───────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_sets_active_false(oauth_configured):
    """disconnect updates active=False in Supabase."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.execute.return_value = None

    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=mock_sb,
    ):
        result = await oauth_configured.disconnect("u1")

    assert result is True
    mock_table.update.assert_called_once_with({"active": False})
