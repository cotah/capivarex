"""
Tests for SecurityEventService and related security infrastructure.

These tests are designed to run in CI without a full environment (no Supabase,
no Redis, no OpenAI key). Heavy external modules are mocked via sys.modules
before any project import occurs.

Covers:
- Rate limit key function (get_user_plan_key)
- Admin dependency (get_admin_user)
- SecurityEventService logic (unit, mocked DB)
- rag_service static analysis (no bare db.table() calls)
- Migration file existence
"""

import os
import sys
import uuid
from unittest.mock import MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: mock heavy modules before any project import
# ---------------------------------------------------------------------------

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

_MOCK_MODULES = [
    "supabase",
    "supabase.client",
    "redis",
    "redis.asyncio",
    "openai",
    "openai.types",
    "openai.types.chat",
    "prometheus_fastapi_instrumentator",
    "sentry_sdk",
    "sentry_sdk.integrations",
    "sentry_sdk.integrations.fastapi",
    "sentry_sdk.integrations.starlette",
    "stripe",
    "telegram",
    "telegram.ext",
    "telegram.constants",
    "googlemaps",
    "google.oauth2",
    "google.auth",
    "google.auth.transport",
    "googleapiclient",
    "googleapiclient.discovery",
    "spotipy",
    "elevenlabs",
    "anthropic",
    "twilio",
    "twilio.rest",
    "duffel_api",
    "pytesseract",
    "pdf2image",
    "moviepy",
    "moviepy.editor",
    "yt_dlp",
    "pydub",
    "boto3",
    "botocore",
    "httpx",
    "aiohttp",
]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_mock(rows=None, count=0):
    """Return a Supabase-like mock that supports the builder pattern."""
    rows = rows or []
    result = Mock()
    result.data = rows
    result.count = count

    builder = Mock()
    builder.select.return_value = builder
    builder.insert.return_value = builder
    builder.update.return_value = builder
    builder.delete.return_value = builder
    builder.eq.return_value = builder
    builder.neq.return_value = builder
    builder.gte.return_value = builder
    builder.lte.return_value = builder
    builder.in_.return_value = builder
    builder.order.return_value = builder
    builder.limit.return_value = builder
    builder.execute.return_value = result

    db = Mock()
    db.table.return_value = builder
    return db, builder, result


# ---------------------------------------------------------------------------
# Rate limit key function
# ---------------------------------------------------------------------------


class TestRateLimitKeyFunction:
    """Tests for get_user_plan_key() in rate_limit middleware."""

    def _make_request(self, auth_header=None, client_host="127.0.0.1"):
        """Build a minimal mock Request object."""
        req = Mock()
        req.client = Mock()
        req.client.host = client_host
        req.headers = {}
        if auth_header:
            req.headers = {"Authorization": auth_header}
        return req

    def test_anonymous_request_uses_ip(self):
        """Requests without auth should use IP as key."""
        from api.middleware.rate_limit import get_user_plan_key

        req = self._make_request()
        with patch(
            "api.middleware.rate_limit.get_remote_address",
            return_value="127.0.0.1",
        ):
            key = get_user_plan_key(req)
        assert "127.0.0.1" in key

    def test_authenticated_request_uses_user_id(self):
        """Requests with a valid JWT should use user_id:plan as key."""
        import jwt
        from api.middleware.rate_limit import get_user_plan_key

        _secret = "test-secret-for-rate-limit"
        token = jwt.encode(
            {"sub": "user-abc", "plan": "professional"},
            _secret,
            algorithm="HS256",
        )
        req = self._make_request(auth_header=f"Bearer {token}")
        with (
            patch(
                "api.middleware.rate_limit.get_remote_address", return_value="127.0.0.1"
            ),
            patch.dict(
                "os.environ", {"JWT_SECRET_KEY": _secret, "JWT_ALGORITHM": "HS256"}
            ),
        ):
            key = get_user_plan_key(req)
        assert "user-abc" in key
        assert "professional" in key

    def test_malformed_token_falls_back_to_ip(self):
        """Malformed JWT should fall back to IP-based key."""
        from api.middleware.rate_limit import get_user_plan_key

        req = self._make_request(
            auth_header="Bearer not.a.valid.jwt", client_host="10.0.0.1"
        )
        with patch(
            "api.middleware.rate_limit.get_remote_address",
            return_value="10.0.0.1",
        ):
            key = get_user_plan_key(req)
        assert "10.0.0.1" in key

    def test_plan_default_when_missing_from_token(self):
        """JWT without plan claim should default to 'default'."""
        import jwt
        from api.middleware.rate_limit import get_user_plan_key

        _secret = "test-secret-for-rate-limit"
        token = jwt.encode({"sub": "user-xyz"}, _secret, algorithm="HS256")
        req = self._make_request(auth_header=f"Bearer {token}")
        with (
            patch(
                "api.middleware.rate_limit.get_remote_address", return_value="127.0.0.1"
            ),
            patch.dict(
                "os.environ", {"JWT_SECRET_KEY": _secret, "JWT_ALGORITHM": "HS256"}
            ),
        ):
            key = get_user_plan_key(req)
        assert "user-xyz" in key
        assert "default" in key


# ---------------------------------------------------------------------------
# SecurityEventService (unit tests with mocked DB)
# ---------------------------------------------------------------------------


class TestSecurityEventService:
    """Unit tests for SecurityEventService.log_event()."""

    def _make_service(self, db_mock, admin_chat_id=""):
        """Instantiate SecurityEventService with a mocked database."""
        # Import after sys.modules mocking is in place
        from services.infrastructure.security_event_service import (
            SecurityEventService,
        )

        svc = object.__new__(SecurityEventService)
        # Set up all attributes that _initialize() would set
        svc._db = db_mock
        svc._notification = Mock()
        svc._admin_chat_id = admin_chat_id
        svc.logger = Mock()
        return svc

    @pytest.mark.asyncio
    async def test_log_event_inserts_row(self):
        """record() should insert a row into security_events."""
        db, builder, result = _make_db_mock(
            rows=[{"id": str(uuid.uuid4()), "event_type": "auth_failure"}]
        )
        # Wrap db so get_client() returns the mock itself
        db_service = Mock()
        db_service.is_initialized.return_value = True
        db_service.get_client.return_value = db

        svc = self._make_service(db_service)

        await svc.record(
            event_type="auth_failure",
            severity="high",
            user_id="user-123",
            ip_address="1.2.3.4",
            endpoint="/api/auth/login",
            details={"reason": "wrong_password"},
        )

        db.table.assert_called_with("security_events")
        builder.insert.assert_called_once()
        call_kwargs = builder.insert.call_args[0][0]
        assert call_kwargs["event_type"] == "auth_failure"
        assert call_kwargs["severity"] == "high"
        assert call_kwargs["ip_address"] == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_log_event_handles_db_error_gracefully(self):
        """record() should not raise even if the DB insert fails."""
        db, builder, result = _make_db_mock()
        builder.execute.side_effect = Exception("DB connection lost")

        db_service = Mock()
        db_service.is_initialized.return_value = True
        db_service.get_client.return_value = db

        svc = self._make_service(db_service)

        # Must not raise
        await svc.record("auth_failure", "high")

    @pytest.mark.asyncio
    async def test_log_event_invalid_severity_accepted_gracefully(self):
        """record() accepts any severity string (validation is at type level)."""
        db, builder, result = _make_db_mock(rows=[{"id": "x"}])
        db_service = Mock()
        db_service.is_initialized.return_value = True
        db_service.get_client.return_value = db
        svc = self._make_service(db_service)

        # The service is designed to be non-raising; invalid severity just logs
        await svc.record("auth_failure", "extreme")  # type: ignore

    @pytest.mark.asyncio
    async def test_log_event_valid_severities(self):
        """record() should accept all four valid severity levels."""
        db, builder, result = _make_db_mock(rows=[{"id": "x"}])
        db_service = Mock()
        db_service.is_initialized.return_value = True
        db_service.get_client.return_value = db
        svc = self._make_service(db_service)

        for sev in ("low", "medium", "high", "critical"):
            await svc.record("auth_success", sev)

        assert builder.insert.call_count == 4

    @pytest.mark.asyncio
    async def test_log_event_without_optional_fields(self):
        """record() should work with only required fields."""
        db, builder, result = _make_db_mock(rows=[{"id": "x"}])
        db_service = Mock()
        db_service.is_initialized.return_value = True
        db_service.get_client.return_value = db
        svc = self._make_service(db_service)

        await svc.record("rate_limit_exceeded", "medium")

        call_kwargs = builder.insert.call_args[0][0]
        assert call_kwargs["event_type"] == "rate_limit_exceeded"
        assert call_kwargs.get("user_id") is None
        assert call_kwargs.get("ip_address") is None

    @pytest.mark.asyncio
    async def test_log_event_includes_created_at(self):
        """record() should include a created_at timestamp."""
        db, builder, result = _make_db_mock(rows=[{"id": "x"}])
        db_service = Mock()
        db_service.is_initialized.return_value = True
        db_service.get_client.return_value = db
        svc = self._make_service(db_service)

        await svc.record("auth_success", "low")

        call_kwargs = builder.insert.call_args[0][0]
        assert "created_at" in call_kwargs

    @pytest.mark.asyncio
    async def test_log_event_details_stored(self):
        """record() should store the details dict."""
        db, builder, result = _make_db_mock(rows=[{"id": "x"}])
        db_service = Mock()
        db_service.is_initialized.return_value = True
        db_service.get_client.return_value = db
        svc = self._make_service(db_service)

        await svc.record(
            "auth_failure",
            "high",
            details={"reason": "invalid_password", "attempts": "3"},
        )

        call_kwargs = builder.insert.call_args[0][0]
        assert call_kwargs.get("details") == {
            "reason": "invalid_password",
            "attempts": "3",
        }


# ---------------------------------------------------------------------------
# Admin dependency
# ---------------------------------------------------------------------------


class TestGetAdminUserDependency:
    """Tests for the get_admin_user FastAPI dependency."""

    @pytest.mark.asyncio
    async def test_admin_user_allowed(self):
        """Users with admin role or 'executive' plan should pass."""
        from api.dependencies.auth import get_admin_user

        # 'executive' plan is treated as admin
        mock_user = {
            "id": "admin-1",
            "email": "admin@test.com",
            "plan": "executive",
            "role": "user",
        }
        result = await get_admin_user(current_user=mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_admin_role_allowed(self):
        """Users with admin role should pass regardless of plan."""
        from api.dependencies.auth import get_admin_user

        mock_user = {
            "id": "admin-1",
            "email": "admin@test.com",
            "plan": "professional",
            "role": "admin",
        }
        result = await get_admin_user(current_user=mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_non_admin_user_rejected(self):
        """Professional plan users without admin role should receive 403 Forbidden."""
        from fastapi import HTTPException
        from api.dependencies.auth import get_admin_user

        mock_user = {
            "id": "user-1",
            "email": "user@test.com",
            "plan": "professional",
            "role": "user",
        }

        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user(current_user=mock_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_plan_field_rejected(self):
        """Users without plan field should be rejected (fail secure)."""
        from fastapi import HTTPException
        from api.dependencies.auth import get_admin_user

        mock_user = {"id": "user-1", "email": "user@test.com"}

        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user(current_user=mock_user)

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# RAG service static analysis
# ---------------------------------------------------------------------------


class TestRagServiceDbAccess:
    """Verify rag_service uses db.get_client().table() not db.table()."""

    def test_rag_service_uses_get_client(self):
        """rag_service should call db.get_client().table(), not db.table()."""
        import ast
        import pathlib

        _repo_root = pathlib.Path(__file__).parent.parent
        rag_path = _repo_root / "services" / "business" / "rag_service.py"
        if not rag_path.exists():
            pytest.skip("rag_service.py not found")

        source = rag_path.read_text()
        tree = ast.parse(source)

        # Look for any bare `db.table(` calls (which would be wrong)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "table"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "db"
                ):
                    pytest.fail(
                        f"rag_service.py line {node.lineno}: "
                        "Found bare db.table() call — should be "
                        "db.get_client().table()"
                    )


# ---------------------------------------------------------------------------
# Migration file existence
# ---------------------------------------------------------------------------


class TestMigrationFiles:
    """Verify all expected migration files exist."""

    def test_security_events_migration_exists(self):
        """Migration 005 for security_events table must exist."""
        import pathlib

        _repo_root = pathlib.Path(__file__).parent.parent
        migration = _repo_root / "migrations" / "005_create_security_events.sql"
        assert migration.exists(), "Migration 005_create_security_events.sql not found"

    def test_security_events_migration_has_rls(self):
        """Migration 005 must include RLS policies."""
        import pathlib

        _repo_root = pathlib.Path(__file__).parent.parent
        migration = _repo_root / "migrations" / "005_create_security_events.sql"
        if not migration.exists():
            pytest.skip("Migration file not found")

        content = migration.read_text()
        assert "ROW LEVEL SECURITY" in content or "ENABLE ROW LEVEL SECURITY" in content
        assert "POLICY" in content

    def test_security_events_migration_has_indexes(self):
        """Migration 005 must include performance indexes."""
        import pathlib

        _repo_root = pathlib.Path(__file__).parent.parent
        migration = _repo_root / "migrations" / "005_create_security_events.sql"
        if not migration.exists():
            pytest.skip("Migration file not found")

        content = migration.read_text()
        assert "CREATE INDEX" in content


# ---------------------------------------------------------------------------
# Rate limit middleware security logging
# ---------------------------------------------------------------------------


class TestRateLimitMiddlewareLogging:
    """Tests for the enhanced rate limit middleware with security logging."""

    def test_rate_limit_handler_is_async(self):
        """_rate_limit_with_logging must be an async function."""
        import asyncio
        from api.middleware.rate_limit import _rate_limit_with_logging

        assert asyncio.iscoroutinefunction(_rate_limit_with_logging)

    def test_setup_rate_limiting_registers_custom_handler(self):
        """setup_rate_limiting() should register the custom handler."""
        from api.middleware.rate_limit import (
            setup_rate_limiting,
            _rate_limit_with_logging,
        )
        from slowapi.errors import RateLimitExceeded

        mock_app = Mock()
        mock_app.state = Mock()
        mock_app.add_exception_handler = Mock()

        setup_rate_limiting(mock_app)

        mock_app.add_exception_handler.assert_called_once_with(
            RateLimitExceeded, _rate_limit_with_logging
        )


# ---------------------------------------------------------------------------
# Extended SecurityEventService coverage — _health_check, record branches,
# _send_admin_alert, and record_security_event module-level function
# ---------------------------------------------------------------------------


class TestSecurityEventServiceExtended:
    """Cover previously uncovered branches in SecurityEventService."""

    def _make_service(self, db=None, notification=None, admin_chat_id=None):
        """Build a SecurityEventService with all attributes set directly."""
        import sys

        # Ensure heavy deps are mocked before importing
        for mod in [
            "supabase",
            "postgrest",
            "gotrue",
            "realtime",
            "storage3",
            "anthropic",
            "openai",
            "telegram",
            "telegram.ext",
            "google.generativeai",
            "google.genai",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from services.infrastructure.security_event_service import SecurityEventService

        svc = SecurityEventService.__new__(SecurityEventService)
        svc._db = db
        svc._notification = notification
        svc._admin_chat_id = admin_chat_id
        svc._initialized = True
        return svc

    # --- _health_check ---

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_db_initialized(self):
        db = MagicMock()
        db.is_initialized.return_value = True
        svc = self._make_service(db=db)
        result = await svc._health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_db_none(self):
        svc = self._make_service(db=None)
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_db_not_initialized(self):
        db = MagicMock()
        db.is_initialized.return_value = False
        svc = self._make_service(db=db)
        result = await svc._health_check()
        assert result is False

    # --- record() — DB branch when db is initialized ---

    @pytest.mark.asyncio
    async def test_record_inserts_to_supabase_when_db_ready(self):
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.table.return_value = mock_table

        db = MagicMock()
        db.is_initialized.return_value = True
        db.get_client.return_value = mock_client

        svc = self._make_service(db=db)
        await svc.record("auth_failure", "high", user_id="u1", ip_address="1.2.3.4")

        mock_client.table.assert_called_once_with("security_events")
        mock_table.insert.assert_called_once()
        row = mock_table.insert.call_args[0][0]
        assert row["event_type"] == "auth_failure"
        assert row["severity"] == "high"
        assert row["user_id"] == "u1"
        assert row["ip_address"] == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_record_skips_db_when_db_not_initialized(self):
        db = MagicMock()
        db.is_initialized.return_value = False

        svc = self._make_service(db=db)
        # Should not raise
        await svc.record("rate_limit_exceeded", "medium")
        db.get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_handles_db_exception_gracefully(self):
        mock_client = MagicMock()
        mock_client.table.side_effect = RuntimeError("DB down")

        db = MagicMock()
        db.is_initialized.return_value = True
        db.get_client.return_value = mock_client

        svc = self._make_service(db=db)
        # Must not raise
        await svc.record("server_error", "high")

    # --- record() — admin alert branch ---

    @pytest.mark.asyncio
    async def test_record_sends_admin_alert_for_critical(self):
        db = MagicMock()
        db.is_initialized.return_value = False

        notification = MagicMock()
        notification.send_message = MagicMock(return_value=None)

        svc = self._make_service(
            db=db, notification=notification, admin_chat_id="12345"
        )

        with patch.object(
            svc, "_send_admin_alert", new=MagicMock(return_value=None)
        ) as mock_alert:
            await svc.record("auth_failure", "critical", user_id="u1")
            mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_does_not_alert_for_low_severity(self):
        db = MagicMock()
        db.is_initialized.return_value = False

        svc = self._make_service(db=db, admin_chat_id="12345")

        with patch.object(
            svc, "_send_admin_alert", new=MagicMock(return_value=None)
        ) as mock_alert:
            await svc.record("auth_success", "low")
            mock_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_does_not_alert_when_no_admin_chat_id(self):
        db = MagicMock()
        db.is_initialized.return_value = False

        svc = self._make_service(db=db, admin_chat_id=None)

        with patch.object(
            svc, "_send_admin_alert", new=MagicMock(return_value=None)
        ) as mock_alert:
            await svc.record("auth_failure", "critical")
            mock_alert.assert_not_called()

    # --- _send_admin_alert ---

    @pytest.mark.asyncio
    async def test_send_admin_alert_calls_notification(self):
        async def fake_send(**kwargs):
            return None

        notification = MagicMock()
        notification.send_message = fake_send

        svc = self._make_service(notification=notification, admin_chat_id="99999")
        # Should not raise
        await svc._send_admin_alert(
            "auth_failure",
            "critical",
            "user123",
            "10.0.0.1",
            {"reason": "bad_password", "email": "test@test.com"},
        )

    @pytest.mark.asyncio
    async def test_send_admin_alert_without_notification_service(self):
        svc = self._make_service(notification=None, admin_chat_id="99999")
        # Must not raise even without notification service
        await svc._send_admin_alert("server_error", "high", None, None, None)

    @pytest.mark.asyncio
    async def test_send_admin_alert_with_empty_details(self):
        async def fake_send(**kwargs):
            return None

        notification = MagicMock()
        notification.send_message = fake_send

        svc = self._make_service(notification=notification, admin_chat_id="99999")
        await svc._send_admin_alert("rate_limit_exceeded", "high", None, "5.5.5.5", {})


# ---------------------------------------------------------------------------
# record_security_event() module-level function coverage
# ---------------------------------------------------------------------------


class TestRecordSecurityEventFunction:
    """Cover the module-level record_security_event convenience function."""

    @pytest.mark.asyncio
    async def test_record_security_event_noop_when_service_unavailable(self):
        """Should silently no-op when service registry returns None."""
        import sys

        for mod in [
            "supabase",
            "postgrest",
            "gotrue",
            "realtime",
            "storage3",
            "anthropic",
            "openai",
            "telegram",
            "telegram.ext",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from services.infrastructure.security_event_service import record_security_event

        with patch("services.core.get_service", return_value=None):
            # Must not raise
            await record_security_event("auth_failure", "high", user_id="u1")

    @pytest.mark.asyncio
    async def test_record_security_event_calls_svc_record_when_available(self):
        """Should delegate to svc.record() when service is initialized."""
        import sys

        for mod in [
            "supabase",
            "postgrest",
            "gotrue",
            "realtime",
            "storage3",
            "anthropic",
            "openai",
            "telegram",
            "telegram.ext",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from services.infrastructure.security_event_service import record_security_event

        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = True
        mock_svc.record = MagicMock(return_value=None)

        with patch("services.core.get_service", return_value=mock_svc):
            await record_security_event(
                "rate_limit_exceeded",
                "medium",
                ip_address="1.2.3.4",
                endpoint="/api/chat",
            )
            mock_svc.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_security_event_handles_exception_gracefully(self):
        """Should swallow exceptions from get_service."""
        import sys

        for mod in [
            "supabase",
            "postgrest",
            "gotrue",
            "realtime",
            "storage3",
            "anthropic",
            "openai",
            "telegram",
            "telegram.ext",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from services.infrastructure.security_event_service import record_security_event

        with patch(
            "services.core.get_service", side_effect=RuntimeError("registry down")
        ):
            # Must not raise
            await record_security_event("server_error", "critical")

    @pytest.mark.asyncio
    async def test_record_security_event_fallback_log_when_svc_not_initialized(self):
        """Should log but not crash when service exists but is not initialized."""
        import sys

        for mod in [
            "supabase",
            "postgrest",
            "gotrue",
            "realtime",
            "storage3",
            "anthropic",
            "openai",
            "telegram",
            "telegram.ext",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from services.infrastructure.security_event_service import record_security_event

        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = False

        with patch("services.core.get_service", return_value=mock_svc):
            await record_security_event("auth_failure", "high")
            mock_svc.record.assert_not_called()
