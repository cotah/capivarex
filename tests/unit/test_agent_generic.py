"""Unit tests for api/routes/agent_generic.py."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.agent_generic import router
from api.dependencies import get_current_user

_app = FastAPI()
_app.dependency_overrides[get_current_user] = lambda: {"id": "user123"}
_app.include_router(router)
client = TestClient(_app, raise_server_exceptions=False)


class TestProcessAgentRequest:
    def test_dedicated_agent_returns_400(self):
        resp = client.post("/chat", json={"message": "hello"})
        assert resp.status_code == 400
        assert "dedicated route" in resp.json()["detail"]

    def test_agent_not_found_returns_404(self):
        with patch("api.routes.agent_generic.get_agent", return_value=None):
            resp = client.post("/unknown_agent_xyz", json={"message": "hello"})
        assert resp.status_code == 404

    def test_success_returns_response(self):
        agent = MagicMock()
        result = MagicMock()
        result.status = MagicMock()
        result.status.value = "success"
        result.response = "Timer set"
        result.data = {"seconds": 300}
        agent.process = AsyncMock(return_value=result)

        with patch("api.routes.agent_generic.get_agent", return_value=agent):
            resp = client.post("/timer", json={"message": "set timer 5min"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"] == "timer"
        assert data["status"] == "success"
        assert data["response"] == "Timer set"

    def test_success_with_context(self):
        agent = MagicMock()
        result = MagicMock()
        result.status = MagicMock()
        result.status.value = "success"
        result.response = "done"
        result.data = {}
        agent.process = AsyncMock(return_value=result)

        with patch("api.routes.agent_generic.get_agent", return_value=agent):
            resp = client.post(
                "/reminder",
                json={"message": "remind me at 8am", "context": {"timezone": "UTC"}},
            )
        assert resp.status_code == 200

    def test_agent_exception_returns_500(self):
        agent = MagicMock()
        agent.process = AsyncMock(side_effect=RuntimeError("unexpected"))
        with patch("api.routes.agent_generic.get_agent", return_value=agent):
            resp = client.post("/timer", json={"message": "hello"})
        assert resp.status_code == 500


class TestListAvailableAgents:
    def test_returns_structure(self):
        resp = client.get("/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "dedicated_route_agents" in data
        assert "generic_agents" in data
        assert "total" in data
        assert "chat" in data["dedicated_route_agents"]
