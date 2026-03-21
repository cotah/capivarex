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
                "api.routes.billing.PLAN_PRICES",
                {"professional": "price_test_pro", "executive": "price_test_exec"},
            ),
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
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
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
        with (
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "stripe.Webhook.construct_event",
                side_effect=ValueError("Invalid payload"),
            ),
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


# ===========================================================================
# Capivara Plan Checkout Tests
# ===========================================================================


class TestCapivaraCheckout:
    """Tests for new Capivara plan checkout flows."""

    @pytest.mark.parametrize(
        "plan,expected_limit",
        [
            ("ara", 300),
            ("ara_plus_1", 500),
            ("capivarex_pro", 1000),
            ("capivarex_ultimate", 999999),
        ],
    )
    def test_create_checkout_capivara_plans(self, app_client, plan, expected_limit):
        """Each Capivara plan should create a Stripe checkout session."""
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result(
                [{"email": "user@test.com", "stripe_customer_id": "cus_test"}]
            )
        )

        mock_session = MagicMock()
        mock_session.id = "cs_test_123"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test_123"

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch(
                "api.routes.billing.PLAN_PRICES",
                {
                    "ara": "price_ara",
                    "ara_plus_1": "price_ara_plus_1",
                    "capivarex_pro": "price_pro",
                    "capivarex_ultimate": "price_ult",
                    "professional": "price_prof",
                    "executive": "price_exec",
                },
            ),
            patch("stripe.checkout.Session.create", return_value=mock_session),
        ):
            resp = app_client.post(
                "/api/billing/create-checkout",
                json={"plan": plan},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_123"

    def test_checkout_rejects_unconfigured_price(self, app_client):
        """If Stripe price env var is not set (None), return 400 not 500."""
        db = _mock_db()
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result(
                [{"email": "user@test.com", "stripe_customer_id": "cus_test"}]
            )
        )

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch(
                "api.routes.billing.PLAN_PRICES",
                {"ara": None, "professional": None, "executive": None},
            ),
        ):
            resp = app_client.post(
                "/api/billing/create-checkout",
                json={"plan": "ara"},
                headers=_auth_header(),
            )

        assert resp.status_code == 400
        assert "not yet available" in resp.json()["detail"]

    def test_checkout_rejects_module_name_as_plan(self, app_client):
        """Individual module names (ivi, oka, etc.) should be rejected by regex."""
        resp = app_client.post(
            "/api/billing/create-checkout",
            json={"plan": "ivi"},
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ===========================================================================
# Capivara Webhook Tests — checkout.session.completed with modules
# ===========================================================================


class TestCapivaraWebhook:
    """Tests for Stripe webhooks handling new Capivara plans."""

    def _make_checkout_event(self, plan, user_id="user-1", extra_meta=None):
        meta = {"user_id": user_id, "plan": plan}
        if extra_meta:
            meta.update(extra_meta)
        return {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": meta,
                    "customer": "cus_capivara_123",
                }
            },
        }

    def test_webhook_ara_plan_sets_correct_limits(self, app_client):
        """ARA plan should set 300 message limit."""
        db = _mock_db()
        event = self._make_checkout_event("ara")

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

        assert resp.status_code == 200
        update_args = db.table("users").update.call_args[0][0]
        assert update_args["plan"] == "ara"
        assert update_args["messages_limit"] == 300

    def test_webhook_ultimate_plan_sets_unlimited(self, app_client):
        """CAPIVAREX Ultimate should set 999999 limit."""
        db = _mock_db()
        event = self._make_checkout_event("capivarex_ultimate")

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(
                "api.routes.billing.get_module_access_service",
            ) as mock_access_svc,
        ):
            svc = AsyncMock()
            mock_access_svc.return_value = svc
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

        assert resp.status_code == 200
        update_args = db.table("users").update.call_args[0][0]
        assert update_args["plan"] == "capivarex_ultimate"
        assert update_args["messages_limit"] == 999999

        # Ultimate should unlock all 7 modules
        assert svc.unlock_module.call_count == 7
        unlocked = {call.args[1] for call in svc.unlock_module.call_args_list}
        assert unlocked == {"ara", "ivi", "oka", "yara", "ayvu", "mbae", "pora"}

    def test_webhook_module_addon_unlocks_single_module(self, app_client):
        """Checkout with module_name metadata should unlock that module."""
        db = _mock_db()
        event = self._make_checkout_event("ara", extra_meta={"module_name": "ivi"})

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch("api.routes.billing.get_module_access_service") as mock_access_svc,
        ):
            svc = AsyncMock()
            mock_access_svc.return_value = svc
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

        assert resp.status_code == 200
        svc.unlock_module.assert_any_call("user-1", "ivi")

    def test_webhook_modules_csv_unlocks_multiple(self, app_client):
        """Checkout with modules CSV metadata should unlock each module."""
        db = _mock_db()
        event = self._make_checkout_event(
            "capivarex_pro", extra_meta={"modules": "ivi,yara,mbae"}
        )

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch("api.routes.billing.get_module_access_service") as mock_access_svc,
        ):
            svc = AsyncMock()
            mock_access_svc.return_value = svc
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

        assert resp.status_code == 200
        unlocked = {call.args[1] for call in svc.unlock_module.call_args_list}
        assert {"ivi", "yara", "mbae"}.issubset(unlocked)

    def test_webhook_subscription_deleted_resets_plan(self, app_client):
        """Subscription deletion should reset user to professional plan."""
        db = _mock_db()
        # Return user when looking up by stripe_customer_id
        db.table(
            "users"
        ).select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"id": "user-1"}])
        )
        db.table(
            "user_modules"
        ).select.return_value.eq.return_value.in_.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        event = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_capivara_123",
                    "items": {"data": [{"id": "si_item_1"}]},
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

        assert resp.status_code == 200
        # Verify plan was reset to professional
        update_args = db.table("users").update.call_args[0][0]
        assert update_args["plan"] == "professional"
        assert update_args["messages_limit"] == 300

    def test_webhook_subscription_updated_syncs_plan(self, app_client):
        """Subscription update should sync plan based on Stripe price ID."""
        db = _mock_db()
        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "customer": "cus_capivara_123",
                    "items": {
                        "data": [{"price": {"id": "price_pro_test"}}]
                    },
                }
            },
        }

        with (
            patch("api.routes.billing._get_db", return_value=db),
            patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(
                "api.routes.billing.PLAN_PRICES",
                {"capivarex_pro": "price_pro_test", "ara": "price_ara_test"},
            ),
            patch("api.routes.billing._notify_admin", new_callable=AsyncMock),
        ):
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "valid_sig"},
            )

        assert resp.status_code == 200
        update_args = db.table("users").update.call_args[0][0]
        assert update_args["plan"] == "capivarex_pro"
        assert update_args["messages_limit"] == 1000

    def test_webhook_no_secret_returns_500(self, app_client):
        """If STRIPE_WEBHOOK_SECRET is not configured, reject with 500."""
        with patch("api.routes.billing.STRIPE_WEBHOOK_SECRET", ""):
            resp = app_client.post(
                "/api/billing/webhook",
                content=b"raw_body",
                headers={"stripe-signature": "sig"},
            )

        assert resp.status_code == 500


# ===========================================================================
# POST /api/billing/activate-bundle-modules
# ===========================================================================


class TestActivateBundleModules:
    """Tests for the post-purchase module activation endpoint."""

    def test_activate_valid_modules(self, app_client):
        """Should unlock specified modules and return them."""
        mock_svc = AsyncMock()
        mock_svc.unlock_module = AsyncMock(return_value=True)

        with patch(
            "api.routes.billing.get_module_access_service", return_value=mock_svc
        ):
            resp = app_client.post(
                "/api/billing/activate-bundle-modules",
                json={"modules": ["ivi", "yara"]},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert set(body["unlocked"]) == {"ivi", "yara"}
        assert mock_svc.unlock_module.call_count == 2

    def test_activate_rejects_invalid_module(self, app_client):
        """Should reject invalid module names with 400."""
        resp = app_client.post(
            "/api/billing/activate-bundle-modules",
            json={"modules": ["invalid_module"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "invalid_module" in resp.json()["detail"]

    def test_activate_rejects_ara(self, app_client):
        """ARA is always included — cannot be selected as add-on."""
        resp = app_client.post(
            "/api/billing/activate-bundle-modules",
            json={"modules": ["ara"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 400

    def test_activate_rejects_empty_list(self, app_client):
        """Empty module list should return 400."""
        resp = app_client.post(
            "/api/billing/activate-bundle-modules",
            json={"modules": []},
            headers=_auth_header(),
        )
        assert resp.status_code == 400

    def test_activate_all_valid_modules(self, app_client):
        """Should accept all 6 selectable modules."""
        mock_svc = AsyncMock()
        mock_svc.unlock_module = AsyncMock(return_value=True)

        with patch(
            "api.routes.billing.get_module_access_service", return_value=mock_svc
        ):
            resp = app_client.post(
                "/api/billing/activate-bundle-modules",
                json={"modules": ["ivi", "oka", "yara", "ayvu", "mbae", "pora"]},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert len(resp.json()["unlocked"]) == 6
