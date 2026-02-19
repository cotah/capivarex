"""Integration tests for FastAPI endpoints."""

import pytest
from unittest.mock import patch, Mock, AsyncMock
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
        assert data["service"] == "CapivaraX Bot API"


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
        response = client.get("/debug/services")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "services" in data

    def test_debug_agents(self):
        response = client.get("/debug/agents")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "agents" in data


# -------------------------------------------------------------------
# Metrics endpoint (Prometheus)
# -------------------------------------------------------------------

class TestMetrics:
    def test_metrics_endpoint_exists(self):
        response = client.get("/metrics")
        assert response.status_code == 200
        # Prometheus text format
        assert "http_request" in response.text or "process_" in response.text
