# -*- coding: utf-8 -*-
"""
Tests for Google OAuth2 auth routes.

Uses FastAPI TestClient to verify route behaviour.
All GoogleOAuthService calls are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.routes.google_auth import router


def _build_app():
    """Build minimal FastAPI app with google_auth router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return app


# ── /connect ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_connect_redirects_to_google():
    """/connect redirects to Google consent screen (302)."""
    mock_oauth = MagicMock()
    mock_oauth.is_configured = True
    mock_oauth.get_auth_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?test=1"
    )

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app(), follow_redirects=False)
        resp = client.get("/api/auth/google/connect?user_id=u1")

    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers["location"]


# ── /status ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_status_not_connected():
    """/status returns connected=False when user has no token."""
    mock_oauth = AsyncMock()
    mock_oauth.is_connected = AsyncMock(return_value=False)
    mock_oauth.get_user_email = AsyncMock(return_value=None)
    mock_oauth.get_connected_accounts = AsyncMock(return_value=[])

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.get("/api/auth/google/status?user_id=u1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["services"] == []


# ── /connect not configured ─────────────────────────────────────────────────


@pytest.mark.unit
def test_connect_not_configured():
    """/connect returns 503 when OAuth is not configured."""
    mock_oauth = MagicMock()
    mock_oauth.is_configured = False

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.get("/api/auth/google/connect?user_id=u1")

    assert resp.status_code == 503


# ── /callback success ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_callback_success():
    """/callback returns success HTML on valid code+state."""
    mock_oauth = AsyncMock()
    mock_oauth.handle_callback = AsyncMock(
        return_value={
            "success": True,
            "user_id": "u1",
            "email": "test@gmail.com",
            "name": "Test User",
        }
    )

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.get(
            "/api/auth/google/callback?code=auth_code&state=valid_state"
        )

    assert resp.status_code == 200
    assert "Conectado" in resp.text
    assert "test@gmail.com" in resp.text


# ── /callback with Google error ─────────────────────────────────────────────


@pytest.mark.unit
def test_callback_google_error():
    """/callback returns error HTML when Google sends error param."""
    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=MagicMock(),
    ):
        client = TestClient(_build_app())
        resp = client.get(
            "/api/auth/google/callback?error=access_denied"
        )

    assert resp.status_code == 400
    assert "access_denied" in resp.text


# ── /callback missing params ────────────────────────────────────────────────


@pytest.mark.unit
def test_callback_missing_params():
    """/callback returns 400 when code or state is missing."""
    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=MagicMock(),
    ):
        client = TestClient(_build_app())
        resp = client.get("/api/auth/google/callback")

    assert resp.status_code == 400
    assert "falta" in resp.text.lower() or "Parâmetros" in resp.text


# ── /callback ValueError ────────────────────────────────────────────────────


@pytest.mark.unit
def test_callback_value_error():
    """/callback returns 400 on ValueError (invalid state)."""
    mock_oauth = AsyncMock()
    mock_oauth.handle_callback = AsyncMock(
        side_effect=ValueError("State inválido")
    )

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.get(
            "/api/auth/google/callback?code=code&state=bad_state"
        )

    assert resp.status_code == 400
    assert "State" in resp.text or "inválido" in resp.text


# ── /callback generic exception ─────────────────────────────────────────────


@pytest.mark.unit
def test_callback_generic_exception():
    """/callback returns 500 on unexpected exception."""
    mock_oauth = AsyncMock()
    mock_oauth.handle_callback = AsyncMock(
        side_effect=RuntimeError("Token exchange boom")
    )

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.get(
            "/api/auth/google/callback?code=code&state=state"
        )

    assert resp.status_code == 500
    assert "Erro" in resp.text


# ── /status connected ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_status_connected():
    """/status returns connected=True with services when user is connected."""
    mock_oauth = AsyncMock()
    mock_oauth.is_connected = AsyncMock(return_value=True)
    mock_oauth.get_user_email = AsyncMock(return_value="test@gmail.com")
    mock_oauth.get_connected_accounts = AsyncMock(
        return_value=[{"email": "test@gmail.com", "active": True}]
    )

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.get("/api/auth/google/status?user_id=u1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["email"] == "test@gmail.com"
    assert "calendar" in data["services"]
    assert "gmail" in data["services"]


# ── /disconnect success ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_disconnect_success():
    """/disconnect returns success message."""
    mock_oauth = AsyncMock()
    mock_oauth.disconnect = AsyncMock(return_value=True)

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.post("/api/auth/google/disconnect?user_id=u1")

    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── /disconnect failure ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_disconnect_failure():
    """/disconnect returns 500 when disconnect fails."""
    mock_oauth = AsyncMock()
    mock_oauth.disconnect = AsyncMock(return_value=False)

    with patch(
        "api.routes.google_auth.get_google_oauth",
        return_value=mock_oauth,
    ):
        client = TestClient(_build_app())
        resp = client.post("/api/auth/google/disconnect?user_id=u1")

    assert resp.status_code == 500
