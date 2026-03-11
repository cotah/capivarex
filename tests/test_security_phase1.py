"""Tests for Security Phase 1 fixes."""

import os
import pathlib

import pytest
from unittest.mock import patch


# ══════════════════════════════════════════════════════════════════════════════
# FIX 1 — Debug endpoints blocked in production
# ══════════════════════════════════════════════════════════════════════════════


class TestDebugEndpoints:
    """Debug endpoints should be blocked in production."""

    def test_debug_services_blocked_in_production(self):
        """Debug endpoints return 404 when not in development."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            from fastapi.testclient import TestClient
            from api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/debug/services")
            assert response.status_code == 404

    def test_debug_agents_blocked_in_production(self):
        """Debug agents endpoint returns 404 when not in development."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            from fastapi.testclient import TestClient
            from api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/debug/agents")
            assert response.status_code == 404

    def test_debug_services_blocked_when_env_missing(self):
        """Debug endpoints return 404 when ENVIRONMENT is not set (fail secure)."""
        env = os.environ.copy()
        env.pop("ENVIRONMENT", None)
        with patch.dict(os.environ, env, clear=True):
            from fastapi.testclient import TestClient
            from api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/debug/services")
            assert response.status_code == 404

    def test_debug_agents_blocked_when_env_missing(self):
        """Debug agents endpoint returns 404 when ENVIRONMENT is not set."""
        env = os.environ.copy()
        env.pop("ENVIRONMENT", None)
        with patch.dict(os.environ, env, clear=True):
            from fastapi.testclient import TestClient
            from api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/debug/agents")
            assert response.status_code == 404

    def test_debug_services_allowed_in_development(self):
        """Debug endpoints return 200 in development environment."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            from fastapi.testclient import TestClient
            from api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/debug/services")
            assert response.status_code == 200

    def test_debug_agents_allowed_in_development(self):
        """Debug agents endpoint returns 200 in development environment."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            from fastapi.testclient import TestClient
            from api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/debug/agents")
            assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# FIX 2 — CORS should never fallback to allow-all
# ══════════════════════════════════════════════════════════════════════════════


class TestCORSFallback:
    """CORS should never fallback to allow-all."""

    def test_no_wildcard_in_cors(self):
        """CORS origins should never contain '*' as fallback."""
        import api.main as main_module

        with open(main_module.__file__, encoding="utf-8") as f:
            source = f.read()
        # After our fix, there should be no '= ["*"]' fallback
        assert '_cors_origins = ["*"]' not in source


# ══════════════════════════════════════════════════════════════════════════════
# FIX 3 — ENCRYPTION_KEY must be required
# ══════════════════════════════════════════════════════════════════════════════


class TestEncryptionKey:
    """ENCRYPTION_KEY must be required, not auto-generated."""

    def test_missing_encryption_key_raises(self):
        """EncryptionService should crash if ENCRYPTION_KEY is missing."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ENCRYPTION_KEY", None)
            with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
                from utils.encryption import EncryptionService

                EncryptionService()

    def test_encryption_key_present_works(self):
        """EncryptionService works when ENCRYPTION_KEY is set."""
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": test_key}):
            from utils.encryption import EncryptionService

            svc = EncryptionService()
            encrypted = svc.encrypt("test")
            assert svc.decrypt(encrypted) == "test"


# ══════════════════════════════════════════════════════════════════════════════
# FIX 5 — SECURITY.md
# ══════════════════════════════════════════════════════════════════════════════


class TestSecurityMd:
    """SECURITY.md should exist with proper content."""

    def test_security_md_exists(self):
        """SECURITY.md should be present in repo root."""
        root = pathlib.Path(__file__).parent.parent
        security_file = root / "SECURITY.md"
        assert security_file.exists(), "SECURITY.md not found in repo root"

    def test_security_md_has_content(self):
        """SECURITY.md should have meaningful content."""
        root = pathlib.Path(__file__).parent.parent
        content = (root / "SECURITY.md").read_text()
        assert "Reporting a Vulnerability" in content
        assert "security@capivarex.com" in content
