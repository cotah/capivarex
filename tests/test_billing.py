# -*- coding: utf-8 -*-
"""Tests for Billing API endpoints and quota enforcement."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.core import AgentResponse, AgentStatus
from api.middleware.webapp_auth import verify_webapp_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_supabase_result(data, count=None):
    """Create a mock Supabase query result."""
    result = MagicMock()
    result.data = data
    result.count = count
    return result


def _mock_db():
    """Build a chainable Supabase client mock with per-table persistence."""
    db = MagicMock()
    _tables: dict = {}

    def _table(name):
        if name not in _tables:
            t = MagicMock()
            t.select.return_value = t
            t.eq.return_value = t
            t.in_.return_value = t
            t.gte.return_value = t
            t.lt.return_value = t
            t.order.return_value = t
            t.limit.return_value = t
            t.range.return_value = t
            t.insert.return_value = t
            t.update.return_value = t
            t.upsert.return_value = t
            t.delete.return_value = t
            t.execute.return_value = _make_supabase_result([])
            _tables[name] = t
        return _tables[name]

    db.table = _table
    return db


def _auth_header():
    return {"Authorization": "Bearer test-jwt-token"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client():
    """TestClient with webapp auth overridden to return a fixed user_id."""
    from fastapi.testclient import TestClient
    from api.main import app

    app.dependency_overrides[verify_webapp_user] = lambda: "user-1"
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(verify_webapp_user, None)


# ===========================================================================
# POST /api/billing/create-checkout
# ===========================================================================


class TestCreateCheckout:
    """Tests for the create-checkout endpoint."""

    def test_create_checkout_professional_plan(self, app_client):
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_supabase_result(
            [
                {
                    "email": "user@test.com",
                    "stripe_customer_id": "cus_existing123",
                }
            ]
        )

        mock_session = MagicMock()
        mock_session.id = "cs_test_session_id_12345"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test"

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch(
                "stripe.checkout.Session.create",
                return_value=mock_session,
            ),
        ):
            resp = app_client.post(
                "/api/billing/create-checkout",
                json={"plan": "professional"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == (
            "https://checkout.stripe.com/pay/cs_test"
        )

    def test_create_checkout_invalid_plan(self, app_client):
        resp = app_client.post(
            "/api/billing/create-checkout",
            json={"plan": "invalid_plan"},
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ===========================================================================
# POST /api/billing/webhook
# ===========================================================================


class TestStripeWebhook:
    """Tests for the Stripe webhook endpoint."""

    def test_webhook_completed_upgrades_plan(self, app_client):
        db = _mock_db()

        event_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"user_id": "user-1", "plan": "professional"},
                    "customer": "cus_abc123",
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch(
                "stripe.Webhook.construct_event",
                return_value=event_payload,
            ),
        ):
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        # Verify DB was updated with correct plan
        db.table("users").update.assert_called_once()
        update_args = db.table("users").update.call_args[0][0]
        assert update_args["plan"] == "professional"
        assert update_args["messages_limit"] == 300
        assert update_args["stripe_customer_id"] == "cus_abc123"

    def test_webhook_invalid_signature_returns_400(self, app_client):
        with patch(
            "stripe.Webhook.construct_event",
            side_effect=ValueError("Invalid payload"),
        ):
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"bad_body",
                headers={"stripe-signature": "bad_sig"},
            )

        assert resp.status_code == 400


# ===========================================================================
# GET /api/billing/status
# ===========================================================================


class TestBillingStatus:
    """Tests for the billing status endpoint."""

    def test_billing_status_professional_user(self, app_client):
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_supabase_result(
            [
                {
                    "plan": "professional",
                    "messages_used": 5,
                    "messages_limit": 30,
                }
            ]
        )

        with patch("api.routes.billing._get_db", return_value=db):
            resp = app_client.get("/api/billing/status", headers=_auth_header())

        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "professional"
        assert body["messages_used"] == 5
        assert body["messages_limit"] == 30
        assert body["quota_pct"] == 16.7
        assert body["is_unlimited"] is False


# ===========================================================================
# Quota Enforcement in webapp_chat
# ===========================================================================


class TestQuotaEnforcement:
    """Tests for QuotaService enforcement in the chat endpoint."""

    def test_quota_exceeded_returns_429(self, app_client):
        from services.business.quota_service import QuotaExceededError

        db = _mock_db()
        mock_quota = MagicMock()
        mock_quota.check_and_consume = AsyncMock(
            side_effect=QuotaExceededError("gpt_tokens", 5000, 5000, "professional")
        )

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_service", return_value=mock_quota),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "Hello"},
                headers=_auth_header(),
            )

        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"]["error"] == "quota_exceeded"
        assert body["detail"]["upgrade_url"] == "/pricing"

    def test_quota_ok_processes_message(self, app_client):
        db = _mock_db()
        mock_quota = MagicMock()
        mock_quota.check_and_consume = AsyncMock(
            return_value={"used": 1, "limit": 5000}
        )

        # Conversation creation
        db.table(
            "webapp_conversations"
        ).insert.return_value.execute.return_value = _make_supabase_result(
            [{"id": "conv-1", "user_id": "user-1"}]
        )
        # Message insert
        db.table(
            "webapp_messages"
        ).insert.return_value.execute.return_value = _make_supabase_result(
            [{"id": "msg-1"}]
        )

        orch = MagicMock()
        orch.process = AsyncMock(
            return_value=AgentResponse(status=AgentStatus.SUCCESS, response="chat")
        )
        chat_agent = MagicMock()
        chat_agent.process = AsyncMock(
            return_value=AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Hi there!",
                metadata={"type": "text"},
            )
        )

        def fake_get_agent(name):
            if name == "orchestrator":
                return orch
            return chat_agent

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_service", return_value=mock_quota),
            patch(
                "api.routes.webapp.get_agent",
                side_effect=fake_get_agent,
            ),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "Hello"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["response"] == "Hi there!"
