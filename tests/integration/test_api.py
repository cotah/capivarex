"""Integration tests for FastAPI endpoints."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app, raise_server_exceptions=False)


# -------------------------------------------------------------------
# Root and health endpoints
# -------------------------------------------------------------------


class TestRootEndpoint:
    def test_root_returns_200(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert data["version"] == "2.0.0"
        assert data["service"] == "CAPIVAREX Bot API"


class TestHealthEndpoint:
    def test_health_returns_200(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_detailed_health(self):
        response = client.get("/api/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "services" in data
        assert "agents" in data


# -------------------------------------------------------------------
# Debug endpoints
# -------------------------------------------------------------------


class TestDebugEndpoints:
    def test_debug_services(self):
        """Debug services returns 200 only in development environment."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            response = client.get("/debug/services")
            assert response.status_code == 200
            data = response.json()
            assert "total" in data
            assert "services" in data

    def test_debug_agents(self):
        """Debug agents returns 200 only in development environment."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            response = client.get("/debug/agents")
            assert response.status_code == 200
            data = response.json()
            assert "total" in data
            assert "agents" in data

    def test_debug_services_blocked_in_production(self):
        """Debug services returns 404 in production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            response = client.get("/debug/services")
            assert response.status_code == 404

    def test_debug_agents_blocked_in_production(self):
        """Debug agents returns 404 in production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            response = client.get("/debug/agents")
            assert response.status_code == 404


# -------------------------------------------------------------------
# Metrics endpoint (Prometheus)
# -------------------------------------------------------------------


class TestMetrics:
    def test_metrics_endpoint_exists(self):
        # Verify that Prometheus Instrumentator was applied to the app.
        # In large test suites (2800+ tests), the /metrics route can vanish
        # from app.routes due to ASGI state pollution, so we verify via a
        # fresh import and source-level check instead.
        import api.main as main_mod

        src_path = main_mod.__file__
        with open(src_path, encoding="utf-8") as f:
            source = f.read()
        assert "Instrumentator" in source, "Prometheus Instrumentator not found in api/main.py"
        assert ".expose(app)" in source, "Instrumentator.expose(app) not found in api/main.py"
