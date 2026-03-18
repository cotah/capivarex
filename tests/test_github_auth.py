"""Tests for GitHub OAuth routes."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from api.routes.github_auth import router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestGitHubConnect:
    def test_connect_redirect(self, client):
        with patch.dict("os.environ", {"GITHUB_CLIENT_ID": "test_id_123"}):
            resp = client.get(
                "/github/connect",
                params={"user_id": "user-abc"},
                follow_redirects=False,
            )
        assert resp.status_code == 307
        assert "github.com/login/oauth/authorize" in resp.headers["location"]
        assert "test_id_123" in resp.headers["location"]
        assert "user-abc" in resp.headers["location"]

    def test_connect_not_configured(self, client):
        with patch.dict("os.environ", {"GITHUB_CLIENT_ID": ""}):
            resp = client.get("/github/connect", params={"user_id": "user-abc"})
        assert resp.status_code == 503


class TestGitHubCallback:
    def test_callback_error(self, client):
        resp = client.get("/github/callback", params={"error": "access_denied"})
        assert resp.status_code == 200
        assert "failed" in resp.text.lower()

    def test_callback_missing_code(self, client):
        resp = client.get("/github/callback")
        assert resp.status_code == 200
        assert "Missing" in resp.text

    def test_callback_not_configured(self, client):
        with patch.dict(
            "os.environ", {"GITHUB_CLIENT_ID": "", "GITHUB_CLIENT_SECRET": ""}
        ):
            resp = client.get(
                "/github/callback", params={"code": "abc", "state": "user-1"}
            )
        assert resp.status_code == 200
        assert "not configured" in resp.text

    def test_callback_success(self, client):
        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"access_token": "gho_test123"}

        mock_user_resp = MagicMock()
        mock_user_resp.json.return_value = {"login": "testuser"}

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.save_github_connection = AsyncMock(return_value=True)

        with (
            patch.dict(
                "os.environ",
                {"GITHUB_CLIENT_ID": "id", "GITHUB_CLIENT_SECRET": "secret"},
            ),
            patch("api.routes.github_auth.httpx.AsyncClient") as mock_cls,
            patch("services.core.get_service", return_value=mock_db),
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_token_resp
            mock_client.get.return_value = mock_user_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            resp = client.get(
                "/github/callback",
                params={"code": "auth_code_123", "state": "user-uuid"},
            )

        assert resp.status_code == 200
        assert "testuser" in resp.text
        assert "✅" in resp.text

    def test_callback_token_exchange_fails(self, client):
        with (
            patch.dict(
                "os.environ",
                {"GITHUB_CLIENT_ID": "id", "GITHUB_CLIENT_SECRET": "secret"},
            ),
            patch("api.routes.github_auth.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Network error")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            resp = client.get(
                "/github/callback", params={"code": "abc", "state": "user-1"}
            )

        assert resp.status_code == 200
        assert "Failed" in resp.text

    def test_callback_no_token_returned(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": "bad_verification_code",
            "error_description": "Code expired",
        }

        with (
            patch.dict(
                "os.environ",
                {"GITHUB_CLIENT_ID": "id", "GITHUB_CLIENT_SECRET": "secret"},
            ),
            patch("api.routes.github_auth.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            resp = client.get(
                "/github/callback", params={"code": "expired", "state": "user-1"}
            )

        assert resp.status_code == 200
        assert "expired" in resp.text.lower()


class TestAdminStatus:
    def test_admin_configured(self, client):
        with patch.dict("os.environ", {"GITHUB_ADMIN_TOKEN": "ghp_admin123"}):
            resp = client.get("/github/admin-status")
        assert resp.json()["configured"] is True

    def test_admin_not_configured(self, client):
        with patch.dict("os.environ", {"GITHUB_ADMIN_TOKEN": ""}):
            resp = client.get("/github/admin-status")
        assert resp.json()["configured"] is False
