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


# ── handle_callback ─────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_callback_success(oauth_configured):
    """handle_callback exchanges code for tokens, fetches profile, saves."""
    import base64

    state_data = json.dumps({"user_id": "u42", "extra": ""})
    state_b64 = base64.urlsafe_b64encode(state_data.encode()).decode()

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "at_new",
        "refresh_token": "rt_new",
        "expires_in": 3600,
    }

    profile_response = MagicMock()
    profile_response.status_code = 200
    profile_response.json.return_value = {
        "email": "user@gmail.com",
        "name": "Test User",
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_response)
    mock_client.get = AsyncMock(return_value=profile_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("services.auth.google_oauth_service.httpx.AsyncClient", return_value=mock_client),
        patch.object(oauth_configured, "save_tokens", new_callable=AsyncMock) as mock_save,
    ):
        result = await oauth_configured.handle_callback(
            code="auth_code_123", state_b64=state_b64
        )

    assert result["success"] is True
    assert result["user_id"] == "u42"
    assert result["email"] == "user@gmail.com"
    assert result["name"] == "Test User"
    mock_save.assert_called_once_with(
        user_id="u42",
        email="user@gmail.com",
        access_token="at_new",
        refresh_token="rt_new",
        expires_in=3600,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_callback_invalid_state(oauth_configured):
    """handle_callback raises ValueError on invalid state."""
    with pytest.raises(ValueError, match="(Invalid state|State inválido)"):
        await oauth_configured.handle_callback(
            code="code", state_b64="not-valid-base64!!!"
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_callback_token_exchange_failure(oauth_configured):
    """handle_callback returns error dict when token exchange fails (400)."""
    import base64

    state_data = json.dumps({"user_id": "u1", "extra": ""})
    state_b64 = base64.urlsafe_b64encode(state_data.encode()).decode()

    error_response = MagicMock()
    error_response.status_code = 400
    error_response.text = '{"error": "invalid_grant"}'
    error_response.json.return_value = {"error": "invalid_grant"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=error_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "services.auth.google_oauth_service.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await oauth_configured.handle_callback(
            code="bad_code", state_b64=state_b64
        )
    assert result["error"] == "authorization_expired"


# ── _refresh_token ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_token_success(oauth_configured):
    """_refresh_token exchanges refresh_token for new access_token."""
    refresh_response = MagicMock()
    refresh_response.status_code = 200
    refresh_response.json.return_value = {
        "access_token": "new_at",
        "expires_in": 3600,
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=refresh_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("services.auth.google_oauth_service.httpx.AsyncClient", return_value=mock_client),
        patch.object(oauth_configured, "save_tokens", new_callable=AsyncMock) as mock_save,
    ):
        result = await oauth_configured._refresh_token(
            user_id="u1", email="test@gmail.com", refresh_token="old_rt"
        )

    assert result == "new_at"
    mock_save.assert_called_once_with(
        user_id="u1",
        email="test@gmail.com",
        access_token="new_at",
        refresh_token="old_rt",
        expires_in=3600,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_token_failure(oauth_configured):
    """_refresh_token raises RuntimeError on failure."""
    error_response = MagicMock()
    error_response.status_code = 401
    error_response.text = "invalid_token"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=error_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("services.auth.google_oauth_service.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(RuntimeError, match="Token refresh failed"),
    ):
        await oauth_configured._refresh_token(
            user_id="u1", email="test@gmail.com", refresh_token="bad_rt"
        )


# ── get_valid_access_token with expired token ───────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_valid_access_token_refreshes_expired_token(oauth_configured):
    """get_valid_access_token calls _refresh_token when token is expired."""
    expired = (
        datetime.now(timezone.utc) - timedelta(minutes=10)
    ).isoformat()

    token_row = {
        "access_token": "expired_token",
        "refresh_token": "rt_good",
        "expires_at": expired,
        "email": "test@gmail.com",
    }

    with (
        patch.object(
            oauth_configured, "_get_token_row", new_callable=AsyncMock,
            return_value=token_row,
        ),
        patch.object(
            oauth_configured, "_refresh_token", new_callable=AsyncMock,
            return_value="new_fresh_token",
        ) as mock_refresh,
    ):
        result = await oauth_configured.get_valid_access_token("u1")

    assert result == "new_fresh_token"
    mock_refresh.assert_called_once_with("u1", "test@gmail.com", "rt_good")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_valid_access_token_expired_no_refresh_token(oauth_configured):
    """get_valid_access_token returns None when expired and no refresh_token."""
    expired = (
        datetime.now(timezone.utc) - timedelta(minutes=10)
    ).isoformat()

    token_row = {
        "access_token": "expired_token",
        "refresh_token": "",
        "expires_at": expired,
        "email": "test@gmail.com",
    }

    with patch.object(
        oauth_configured, "_get_token_row", new_callable=AsyncMock,
        return_value=token_row,
    ):
        result = await oauth_configured.get_valid_access_token("u1")

    assert result is None


# ── get_user_email ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_user_email_returns_email(oauth_configured):
    """get_user_email returns email from token row."""
    with patch.object(
        oauth_configured, "_get_token_row", new_callable=AsyncMock,
        return_value={"email": "test@gmail.com", "access_token": "x"},
    ):
        result = await oauth_configured.get_user_email("u1")

    assert result == "test@gmail.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_user_email_returns_none_if_not_connected(oauth_configured):
    """get_user_email returns None when no token row."""
    with patch.object(
        oauth_configured, "_get_token_row", new_callable=AsyncMock,
        return_value=None,
    ):
        result = await oauth_configured.get_user_email("u1")

    assert result is None


# ── get_connected_accounts ──────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_connected_accounts_returns_list(oauth_configured):
    """get_connected_accounts returns list of accounts from Supabase."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_result = MagicMock()
    mock_result.data = [{"email": "a@gmail.com", "active": True}]
    mock_table.execute.return_value = mock_result

    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=mock_sb,
    ):
        result = await oauth_configured.get_connected_accounts("u1")

    assert len(result) == 1
    assert result[0]["email"] == "a@gmail.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_connected_accounts_no_supabase(oauth_configured):
    """get_connected_accounts returns [] when Supabase not available."""
    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=None,
    ):
        result = await oauth_configured.get_connected_accounts("u1")

    assert result == []


# ── _get_token_row ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_token_row_returns_row(oauth_configured):
    """_get_token_row returns first row from Supabase query."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.order.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_result = MagicMock()
    mock_result.data = [{"access_token": "at", "email": "test@gmail.com"}]
    mock_table.execute.return_value = mock_result

    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=mock_sb,
    ):
        result = await oauth_configured._get_token_row("u1")

    assert result["access_token"] == "at"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_token_row_no_supabase(oauth_configured):
    """_get_token_row returns None when Supabase not available."""
    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=None,
    ):
        result = await oauth_configured._get_token_row("u1")

    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_token_row_empty_result(oauth_configured):
    """_get_token_row returns None when query returns no data."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.order.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_result = MagicMock()
    mock_result.data = []
    mock_table.execute.return_value = mock_result

    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=mock_sb,
    ):
        result = await oauth_configured._get_token_row("u1")

    assert result is None


# ── save_tokens error ───────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_tokens_raises_when_no_supabase(oauth_configured):
    """save_tokens raises RuntimeError when Supabase is not available."""
    with (
        patch(
            "services.infrastructure.database.get_supabase_client",
            return_value=None,
        ),
        pytest.raises(RuntimeError, match="Supabase not available"),
    ):
        await oauth_configured.save_tokens(
            user_id="u1",
            email="test@gmail.com",
            access_token="at",
            refresh_token="rt",
            expires_in=3600,
        )


# ── disconnect error ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_returns_false_on_no_supabase(oauth_configured):
    """disconnect returns False when Supabase is not available."""
    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=None,
    ):
        result = await oauth_configured.disconnect("u1")

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_returns_false_on_exception(oauth_configured):
    """disconnect returns False when Supabase raises."""
    mock_sb = MagicMock()
    mock_sb.table.side_effect = RuntimeError("DB error")

    with patch(
        "services.infrastructure.database.get_supabase_client",
        return_value=mock_sb,
    ):
        result = await oauth_configured.disconnect("u1")

    assert result is False


# ── singleton ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_google_oauth_singleton():
    """get_google_oauth returns the same instance."""
    import services.auth.google_oauth_service as mod

    mod._google_oauth = None
    from services.auth.google_oauth_service import get_google_oauth

    first = get_google_oauth()
    second = get_google_oauth()
    assert first is second
    mod._google_oauth = None  # cleanup
