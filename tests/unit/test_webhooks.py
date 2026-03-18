"""Unit tests for api/routes/webhooks.py."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.webhooks import router

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app, raise_server_exceptions=False)


class TestEmailWebhook:
    def test_success_returns_processed(self):
        agent = MagicMock()
        resp_obj = MagicMock()
        resp_obj.response = "Email handled"
        agent.process = AsyncMock(return_value=resp_obj)

        with patch("api.routes.webhooks.get_agent", return_value=agent):
            resp = client.post(
                "/email",
                json={
                    "from": "sender@example.com",
                    "subject": "Test",
                    "body": "Body text",
                    "user_id": "user123",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processed"
        assert data["agent_response"] == "Email handled"

    def test_agent_not_available_returns_503(self):
        with patch("api.routes.webhooks.get_agent", return_value=None):
            resp = client.post("/email", json={"user_id": "u1"})
        assert resp.status_code == 503

    def test_agent_exception_returns_500(self):
        agent = MagicMock()
        agent.process = AsyncMock(side_effect=Exception("agent crashed"))
        with patch("api.routes.webhooks.get_agent", return_value=agent):
            resp = client.post(
                "/email",
                json={
                    "from": "a@b.com",
                    "subject": "Hi",
                    "body": "Body",
                    "user_id": "u1",
                },
            )
        assert resp.status_code == 500

    def test_missing_fields_still_processes(self):
        agent = MagicMock()
        resp_obj = MagicMock()
        resp_obj.response = "ok"
        agent.process = AsyncMock(return_value=resp_obj)
        with patch("api.routes.webhooks.get_agent", return_value=agent):
            resp = client.post("/email", json={})
        assert resp.status_code == 200
