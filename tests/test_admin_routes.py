# -*- coding: utf-8 -*-
"""
Tests for admin API routes (api/routes/admin.py).

Uses unittest.TestCase + FastAPI TestClient to avoid pytest-asyncio
event-loop conflicts.  Heavy third-party modules are pre-mocked in
sys.modules so the import chain stays lightweight.

IMPORTANT: httpx and aiohttp are NOT mocked here.
starlette.testclient creates WebSocketDenialResponse(httpx.Response,
WebSocketDisconnect) at class-definition time. If httpx is a MagicMock
the metaclass conflicts with WebSocketDisconnect → TypeError in
test_billing.py when both test files run in the same pytest session.
admin.py does not import httpx directly, so no mock is needed.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Environment setup (before any app imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

# ---------------------------------------------------------------------------
# Import admin module
# ---------------------------------------------------------------------------
# admin.py has a lightweight import chain (fastapi, pydantic, loguru,
# api.dependencies.auth, api.routes._helpers) — no sys.modules mocking
# needed.  Previous versions mocked heavy modules here, but that
# polluted sys.modules for the entire pytest session and broke
# test_billing.py (starlette.testclient needs the real httpx, loguru,
# etc.).  Since admin.py never imports supabase/telegram/openai/etc.
# directly, the mocks are unnecessary.

import api.routes.admin as _admin_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_result(data, count=None):
    """Create a mock Supabase query result."""
    r = MagicMock()
    r.data = data
    r.count = count
    return r


def _mock_db():
    """Build a chainable Supabase client mock with per-table persistence."""
    db = MagicMock()
    _tables: dict = {}

    def _table(name):
        if name not in _tables:
            t = MagicMock()
            t.select.return_value = t
            t.eq.return_value = t
            t.order.return_value = t
            t.limit.return_value = t
            t.range.return_value = t
            t.update.return_value = t
            t.execute.return_value = _make_result([])
            _tables[name] = t
        return _tables[name]

    db.table = _table
    return db


def _fake_admin_token():
    """No-op dependency override — skips ADMIN_SECRET_TOKEN check."""
    return None


def _get_test_app():
    """Create a minimal FastAPI app with just the admin router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(_admin_mod.router, prefix="/api/admin")
    # Override auth dependency so no real token is needed
    app.dependency_overrides[_admin_mod.verify_admin_token] = _fake_admin_token
    return app


def _get_client():
    """Return a TestClient for the admin-only app."""
    from starlette.testclient import TestClient

    return TestClient(_get_test_app(), raise_server_exceptions=False)


# ===========================================================================
# Test Cases
# ===========================================================================


class TestListTenants(unittest.TestCase):
    """GET /api/admin/tenants"""

    def test_list_tenants_success(self):
        db = _mock_db()
        tenant_data = [
            {
                "id": "user-1",
                "email": "u1@test.com",
                "plan": "professional",
                "messages_used": 5,
                "messages_limit": 30,
                "stripe_customer_id": None,
                "role": "user",
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": "user-2",
                "email": "u2@test.com",
                "plan": "professional",
                "messages_used": 10,
                "messages_limit": 300,
                "stripe_customer_id": "cus_123",
                "role": "user",
                "created_at": "2026-01-02T00:00:00",
            },
        ]
        # The users table mock handles both the count query and the data query.
        # Since select() is chained, both paths go through the same mock.
        # Set up the final execute for the data path (order→range→execute).
        users_mock = db.table("users")
        users_mock.execute.return_value = _make_result([], count=2)
        users_mock.select.return_value.execute.return_value = _make_result([], count=2)
        users_mock.select.return_value.order.return_value.range.return_value.execute.return_value = _make_result(
            tenant_data
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.get("/api/admin/tenants?page=1&per_page=50")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["tenants"]), 2)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["per_page"], 50)

    def test_list_tenants_pagination(self):
        db = _mock_db()
        db.table("users").select.return_value.execute.return_value = _make_result(
            [], count=100
        )
        db.table(
            "users"
        ).select.return_value.order.return_value.range.return_value.execute.return_value = _make_result(
            [{"id": "user-51", "email": "u51@test.com"}]
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.get("/api/admin/tenants?page=2&per_page=50")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page"], 2)

    def test_list_tenants_empty(self):
        db = _mock_db()
        db.table("users").select.return_value.execute.return_value = _make_result(
            [], count=0
        )
        db.table(
            "users"
        ).select.return_value.order.return_value.range.return_value.execute.return_value = _make_result(
            []
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.get("/api/admin/tenants")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["tenants"], [])

    def test_list_tenants_db_error(self):
        with patch("api.routes.admin._get_db", side_effect=Exception("db down")):
            client = _get_client()
            resp = client.get("/api/admin/tenants")

        self.assertEqual(resp.status_code, 500)


class TestGetTenant(unittest.TestCase):
    """GET /api/admin/tenants/{uid}"""

    def test_get_tenant_found(self):
        db = _mock_db()
        tenant = {
            "id": "user-1",
            "email": "u1@test.com",
            "plan": "professional",
            "messages_used": 42,
            "messages_limit": 300,
        }
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_result(
            [tenant]
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.get("/api/admin/tenants/user-1")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["tenant"]["id"], "user-1")
        self.assertEqual(resp.json()["tenant"]["plan"], "professional")

    def test_get_tenant_not_found(self):
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_result(
            []
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.get("/api/admin/tenants/nonexistent")

        self.assertEqual(resp.status_code, 404)

    def test_get_tenant_db_error(self):
        with patch("api.routes.admin._get_db", side_effect=Exception("db down")):
            client = _get_client()
            resp = client.get("/api/admin/tenants/user-1")

        self.assertEqual(resp.status_code, 500)


class TestOverrideQuota(unittest.TestCase):
    """POST /api/admin/tenants/{uid}/quota"""

    def test_override_quota_success(self):
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_result(
            [{"id": "user-1", "plan": "professional", "messages_limit": 30}]
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.post(
                "/api/admin/tenants/user-1/quota",
                json={"messages_limit": 500},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["old_limit"], 30)
        self.assertEqual(body["new_limit"], 500)

    def test_override_quota_tenant_not_found(self):
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_result(
            []
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.post(
                "/api/admin/tenants/nonexistent/quota",
                json={"messages_limit": 500},
            )

        self.assertEqual(resp.status_code, 404)

    def test_override_quota_invalid_limit(self):
        client = _get_client()
        resp = client.post(
            "/api/admin/tenants/user-1/quota",
            json={"messages_limit": -1},
        )
        self.assertEqual(resp.status_code, 422)

    def test_override_quota_missing_body(self):
        client = _get_client()
        resp = client.post("/api/admin/tenants/user-1/quota")
        self.assertEqual(resp.status_code, 422)

    def test_override_quota_db_error(self):
        with patch("api.routes.admin._get_db", side_effect=Exception("db down")):
            client = _get_client()
            resp = client.post(
                "/api/admin/tenants/user-1/quota",
                json={"messages_limit": 100},
            )

        self.assertEqual(resp.status_code, 500)


class TestResetUsage(unittest.TestCase):
    """POST /api/admin/tenants/{uid}/reset-usage"""

    def test_reset_usage_success(self):
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_result(
            [{"id": "user-1", "messages_used": 25}]
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.post("/api/admin/tenants/user-1/reset-usage")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["old_usage"], 25)
        self.assertEqual(body["new_usage"], 0)

    def test_reset_usage_tenant_not_found(self):
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_result(
            []
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.post("/api/admin/tenants/nonexistent/reset-usage")

        self.assertEqual(resp.status_code, 404)

    def test_reset_usage_db_error(self):
        with patch("api.routes.admin._get_db", side_effect=Exception("db down")):
            client = _get_client()
            resp = client.post("/api/admin/tenants/user-1/reset-usage")

        self.assertEqual(resp.status_code, 500)


class TestListSecurityEvents(unittest.TestCase):
    """GET /api/admin/security-events"""

    def test_list_security_events_success(self):
        db = _mock_db()
        events = [
            {
                "id": "ev-1",
                "event_type": "brute_force",
                "user_id": "user-1",
                "created_at": "2026-03-10T12:00:00",
            },
            {
                "id": "ev-2",
                "event_type": "sql_injection",
                "user_id": "user-2",
                "created_at": "2026-03-10T13:00:00",
            },
        ]
        db.table(
            "security_events"
        ).select.return_value.order.return_value.limit.return_value.execute.return_value = _make_result(
            events
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.get("/api/admin/security-events?limit=10")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["events"]), 2)

    def test_list_security_events_empty(self):
        db = _mock_db()
        db.table(
            "security_events"
        ).select.return_value.order.return_value.limit.return_value.execute.return_value = _make_result(
            []
        )

        with patch("api.routes.admin._get_db", return_value=db):
            client = _get_client()
            resp = client.get("/api/admin/security-events")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_list_security_events_db_error(self):
        with patch("api.routes.admin._get_db", side_effect=Exception("db down")):
            client = _get_client()
            resp = client.get("/api/admin/security-events")

        self.assertEqual(resp.status_code, 500)


class TestListAutofixTickets(unittest.TestCase):
    """GET /api/admin/autofix/tickets"""

    def test_list_autofix_tickets_success(self):
        tickets = [
            {
                "id": "ABC12345",
                "fingerprint": "fp1",
                "error_type": "ValueError",
                "count": 3,
                "status": "new",
                "last_seen": "2026-03-10T12:00:00",
            },
        ]

        # get_last_tickets is imported lazily inside the endpoint function,
        # so we patch it at its source module.
        with patch("autofix.core.get_last_tickets", return_value=tickets):
            client = _get_client()
            resp = client.get("/api/admin/autofix/tickets?n=5")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["tickets"][0]["id"], "ABC12345")

    def test_list_autofix_tickets_empty(self):
        with patch("autofix.core.get_last_tickets", return_value=[]):
            client = _get_client()
            resp = client.get("/api/admin/autofix/tickets")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_list_autofix_tickets_error(self):
        with patch(
            "autofix.core.get_last_tickets",
            side_effect=Exception("file not found"),
        ):
            client = _get_client()
            resp = client.get("/api/admin/autofix/tickets")

        self.assertEqual(resp.status_code, 500)


class TestAdminHealth(unittest.TestCase):
    """GET /api/admin/health"""

    def test_admin_health_success(self):
        mock_service_registry = MagicMock()
        mock_service_registry.get_all_metrics.return_value = {
            "database": {
                "status": "healthy",
                "initialized": True,
                "call_count": 100,
                "error_rate": 0.01,
            },
            "openai": {
                "status": "healthy",
                "initialized": True,
                "call_count": 50,
                "error_rate": 0.0,
            },
        }

        mock_agent_registry = MagicMock()
        mock_agent_registry.list_agents.return_value = [
            "chat",
            "weather",
            "orchestrator",
        ]

        # Registries are imported lazily inside the endpoint function via
        # "from services.core import registry" / "from agents.core import registry".
        # Patch them at the source modules so the lazy import picks up the mocks.
        with (
            patch.object(
                sys.modules.get("services.core", MagicMock()),
                "registry",
                mock_service_registry,
            ),
            patch.object(
                sys.modules.get("agents.core", MagicMock()),
                "registry",
                mock_agent_registry,
            ),
        ):
            client = _get_client()
            resp = client.get("/api/admin/health")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "healthy")
        self.assertIn("services", body)
        self.assertIn("agents", body)
        self.assertIn("environment", body)

    def test_admin_health_partial_failure(self):
        mock_service_registry = MagicMock()
        mock_service_registry.get_all_metrics.side_effect = RuntimeError(
            "registry error"
        )

        mock_agent_registry = MagicMock()
        mock_agent_registry.list_agents.return_value = []

        with (
            patch.object(
                sys.modules.get("services.core", MagicMock()),
                "registry",
                mock_service_registry,
            ),
            patch.object(
                sys.modules.get("agents.core", MagicMock()),
                "registry",
                mock_agent_registry,
            ),
        ):
            client = _get_client()
            resp = client.get("/api/admin/health")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "healthy")
        self.assertIn("_error", body["services"])


# ===========================================================================
# Tests for new billing webhook events
# ===========================================================================


class TestBillingWebhookNewEvents(unittest.TestCase):
    """Tests for the 3 new Stripe webhook events added in Sprint 9."""

    def _mock_billing_db(self):
        return _mock_db()

    def _webhook_call(self, client, event_payload):
        with (
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event_payload),
        ):
            return client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

    def test_subscription_updated_upgrades_plan(self):
        from starlette.testclient import TestClient
        from api.routes.billing import router as billing_router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(billing_router, prefix="/api/billing")

        db = self._mock_billing_db()
        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "customer": "cus_updated_123",
                    "items": {
                        "data": [
                            {"price": {"id": os.getenv("STRIPE_PRICE_ME", "price_me")}}
                        ]
                    },
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing._plan_from_price", return_value="professional"),
            patch("api.routes.billing._notify_admin"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = self._webhook_call(client, event)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_invoice_payment_succeeded(self):
        from starlette.testclient import TestClient
        from api.routes.billing import router as billing_router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(billing_router, prefix="/api/billing")

        db = self._mock_billing_db()
        event = {
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "customer": "cus_pay_ok",
                    "amount_paid": 2990,
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing._notify_admin"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = self._webhook_call(client, event)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_invoice_payment_failed(self):
        from starlette.testclient import TestClient
        from api.routes.billing import router as billing_router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(billing_router, prefix="/api/billing")

        db = self._mock_billing_db()
        event = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_pay_fail",
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing._notify_admin"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = self._webhook_call(client, event)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class TestPlanFromPrice(unittest.TestCase):
    """Tests for the _plan_from_price helper."""

    def test_none_returns_none(self):
        from api.routes.billing import _plan_from_price

        self.assertIsNone(_plan_from_price(None))

    def test_empty_returns_none(self):
        from api.routes.billing import _plan_from_price

        self.assertIsNone(_plan_from_price(""))

    def test_unknown_price_returns_none(self):
        from api.routes.billing import _plan_from_price

        self.assertIsNone(_plan_from_price("price_unknown_xyz"))

    def test_professional_price(self):
        from api.routes.billing import _plan_from_price, STRIPE_PRICE_PROFESSIONAL

        if STRIPE_PRICE_PROFESSIONAL:
            self.assertEqual(
                _plan_from_price(STRIPE_PRICE_PROFESSIONAL), "professional"
            )

    def test_executive_price(self):
        from api.routes.billing import _plan_from_price, STRIPE_PRICE_EXECUTIVE

        if STRIPE_PRICE_EXECUTIVE:
            self.assertEqual(_plan_from_price(STRIPE_PRICE_EXECUTIVE), "executive")


class TestNotifyAdmin(unittest.TestCase):
    """Tests for the _notify_admin billing helper."""

    def test_notify_admin_no_chat_id(self):
        """When TELEGRAM_ADMIN_CHAT_ID is empty, _notify_admin does nothing."""
        from api.routes.billing import _notify_admin

        with patch("api.routes.billing.TELEGRAM_ADMIN_CHAT_ID", ""):
            asyncio.run(_notify_admin("test message"))
        # Should not raise

    def test_notify_admin_sends_message(self):
        """When chat ID is set and notification service exists, sends message."""
        from api.routes.billing import _notify_admin

        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = True
        mock_svc.send_message = AsyncMock()

        with (
            patch("api.routes.billing.TELEGRAM_ADMIN_CHAT_ID", "12345"),
            patch("services.core.get_service", return_value=mock_svc),
        ):
            asyncio.run(_notify_admin("test message"))

        mock_svc.send_message.assert_called_once()

    def test_notify_admin_service_error(self):
        """When notification service raises, _notify_admin logs and moves on."""
        from api.routes.billing import _notify_admin

        with (
            patch("api.routes.billing.TELEGRAM_ADMIN_CHAT_ID", "12345"),
            patch(
                "services.core.get_service",
                side_effect=RuntimeError("svc error"),
            ),
        ):
            # Should not raise
            asyncio.run(_notify_admin("test"))

    def test_notify_admin_initializes_service(self):
        """When service is not initialized, _notify_admin initializes it."""
        from api.routes.billing import _notify_admin

        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = False
        mock_svc.initialize = AsyncMock()
        mock_svc.send_message = AsyncMock()

        with (
            patch("api.routes.billing.TELEGRAM_ADMIN_CHAT_ID", "12345"),
            patch("services.core.get_service", return_value=mock_svc),
        ):
            asyncio.run(_notify_admin("test"))

        mock_svc.initialize.assert_called_once()


class TestSubscriptionUpdatedWebhook(unittest.TestCase):
    """More detailed tests for subscription.updated webhook event."""

    def test_subscription_updated_no_items(self):
        """subscription.updated with empty items does nothing."""
        from starlette.testclient import TestClient
        from api.routes.billing import router as billing_router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(billing_router, prefix="/api/billing")
        db = _mock_db()

        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "customer": "cus_no_items",
                    "items": {"data": []},
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch("api.routes.billing._notify_admin"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/billing/webhook",
                content=b"raw",
                headers={"stripe-signature": "sig"},
            )

        self.assertEqual(resp.status_code, 200)

    def test_subscription_updated_unknown_price(self):
        """subscription.updated with unknown price_id returns None plan."""
        from starlette.testclient import TestClient
        from api.routes.billing import router as billing_router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(billing_router, prefix="/api/billing")
        db = _mock_db()

        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "customer": "cus_unknown_price",
                    "items": {"data": [{"price": {"id": "price_unknown"}}]},
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch("api.routes.billing._notify_admin"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/billing/webhook",
                content=b"raw",
                headers={"stripe-signature": "sig"},
            )

        self.assertEqual(resp.status_code, 200)
        # plan is None → no DB update
        db.table("users").update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
