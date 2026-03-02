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
