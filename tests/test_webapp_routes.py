# -*- coding: utf-8 -*-
"""Tests for WebApp API endpoints (chat + conversations)."""

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
    """Return a Bearer token header."""
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


@pytest.fixture
def raw_client():
    """TestClient WITHOUT auth override — for testing auth failures."""
    from fastapi.testclient import TestClient
    from api.main import app

    yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class TestVerifyWebappUser:
    """Tests for the Supabase JWT auth dependency."""

    def test_missing_auth_header_returns_error(self, raw_client):
        resp = raw_client.get("/api/webapp/conversations")
        assert resp.status_code in (401, 403)

    def test_invalid_token_returns_401(self, raw_client):
        resp = raw_client.get(
            "/api/webapp/conversations",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert resp.status_code == 401

    def test_forged_jwt_rejected(self, raw_client):
        """JWT well-formed but signed with wrong secret must return 401."""
        import jwt as pyjwt

        forged = pyjwt.encode(
            {"sub": "fake-user", "role": "authenticated"},
            "wrong-secret",
            algorithm="HS256",
        )
        resp = raw_client.get(
            "/api/webapp/conversations",
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert resp.status_code == 401

    def test_malformed_jwt_rejected(self, raw_client):
        """Token without 3 dot-separated parts must return 401."""
        resp = raw_client.get(
            "/api/webapp/conversations",
            headers={"Authorization": "Bearer not-a-jwt-at-all"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid token format"

    def test_malformed_jwt_with_prefix_stripped(self, raw_client):
        """Token with invalid prefix AND bad structure must return 401."""
        resp = raw_client.get(
            "/api/webapp/conversations",
            headers={"Authorization": "Bearer undefinedgarbage"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid token format"


# ---------------------------------------------------------------------------
# POST /api/webapp/chat
# ---------------------------------------------------------------------------


class TestWebappChat:
    """Tests for the chat endpoint."""

    def test_chat_creates_conversation_and_returns_response(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").insert.return_value.execute.return_value = (
            _make_supabase_result(
                [{"id": "conv-uuid-1", "user_id": "user-1"}]
            )
        )
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-uuid-1"}])
        )

        orch_response = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="chat",
        )
        chat_response = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Hello! How can I help?",
            data={"key": "value"},
            metadata={"type": "text"},
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.process = AsyncMock(return_value=orch_response)
        mock_chat_agent = MagicMock()
        mock_chat_agent.process = AsyncMock(return_value=chat_response)

        def fake_get_agent(name):
            if name == "orchestrator":
                return mock_orchestrator
            return mock_chat_agent

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_agent", side_effect=fake_get_agent),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "Hello"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "chat"
        assert body["response"] == "Hello! How can I help?"
        assert body["conversation_id"] == "conv-uuid-1"

    def test_chat_with_existing_conversation(self, app_client):
        db = _mock_db()

        # Conversation exists
        db.table("webapp_conversations").select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"id": "conv-existing"}])
        )
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-2"}])
        )

        orch_response = AgentResponse(
            status=AgentStatus.SUCCESS, response="weather"
        )
        weather_response = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Sunny, 22C",
            metadata={"type": "weather"},
        )

        mock_orch = MagicMock()
        mock_orch.process = AsyncMock(return_value=orch_response)
        mock_weather = MagicMock()
        mock_weather.process = AsyncMock(return_value=weather_response)

        def fake_get_agent(name):
            if name == "orchestrator":
                return mock_orch
            if name == "weather":
                return mock_weather
            return mock_weather

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_agent", side_effect=fake_get_agent),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={
                    "message": "What is the weather?",
                    "conversation_id": "conv-existing",
                },
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["agent"] == "weather"

    def test_chat_quota_exceeded_returns_429(self, app_client):
        """QuotaService raises QuotaExceededError → 429 with upgrade_url."""
        from services.business.quota_service import QuotaExceededError

        db = _mock_db()
        mock_quota = MagicMock()
        mock_quota.check_and_consume = AsyncMock(
            side_effect=QuotaExceededError("gpt_tokens", 5000, 5000, "free")
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

    def test_chat_quota_service_unavailable_allows_through(self, app_client):
        """If QuotaService is None, chat proceeds normally."""
        db = _mock_db()
        db.table("webapp_conversations").insert.return_value.execute.return_value = (
            _make_supabase_result(
                [{"id": "conv-no-quota", "user_id": "user-1"}]
            )
        )
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-no-quota"}])
        )

        orch_response = AgentResponse(
            status=AgentStatus.SUCCESS, response="chat"
        )
        chat_response = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="No quota check, still works",
            metadata={"type": "text"},
        )

        mock_orch = MagicMock()
        mock_orch.process = AsyncMock(return_value=orch_response)
        mock_chat = MagicMock()
        mock_chat.process = AsyncMock(return_value=chat_response)

        def fake_get_agent(name):
            return mock_orch if name == "orchestrator" else mock_chat

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_agent", side_effect=fake_get_agent),
            patch("api.routes.webapp.get_service", return_value=None),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "Hello"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["response"] == "No quota check, still works"

    def test_chat_empty_message_rejected(self, app_client):
        resp = app_client.post(
            "/api/webapp/chat",
            json={"message": ""},
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/webapp/conversations
# ---------------------------------------------------------------------------


class TestListConversations:
    """Tests for listing conversations."""

    def test_list_returns_conversations(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {
                        "id": "c1",
                        "title": "First chat",
                        "updated_at": "2026-03-07T10:00:00Z",
                        "created_at": "2026-03-07T09:00:00Z",
                    }
                ]
            )
        )
        # Batch messages query: .select().in_().order().execute()
        db.table("webapp_messages").select.return_value.in_.return_value.order.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {
                        "conversation_id": "c1",
                        "text": "Hello world",
                        "created_at": "2026-03-07T10:00:00Z",
                    }
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/conversations", headers=_auth_header()
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "conversations" in data

    def test_list_empty(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/conversations", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["conversations"] == []


# ---------------------------------------------------------------------------
# POST /api/webapp/conversations
# ---------------------------------------------------------------------------


class TestCreateConversation:
    """Tests for creating a conversation."""

    def test_create_returns_201(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").insert.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {
                        "id": "new-conv",
                        "user_id": "user-1",
                        "title": None,
                        "created_at": "2026-03-07T10:00:00Z",
                        "updated_at": "2026-03-07T10:00:00Z",
                    }
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.post(
                "/api/webapp/conversations", headers=_auth_header()
            )

        assert resp.status_code == 201
        assert resp.json()["id"] == "new-conv"


# ---------------------------------------------------------------------------
# GET /api/webapp/conversations/{id}
# ---------------------------------------------------------------------------


class TestGetConversation:
    """Tests for retrieving a conversation with messages."""

    def test_get_returns_messages(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result(
                [{"id": "c1", "title": "Test", "user_id": "user-1"}]
            )
        )
        db.table("webapp_messages").select.return_value.eq.return_value.order.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {
                        "id": "m1",
                        "role": "user",
                        "text": "Hi",
                        "created_at": "2026-03-07T10:00:00Z",
                    },
                    {
                        "id": "m2",
                        "role": "assistant",
                        "text": "Hello!",
                        "created_at": "2026-03-07T10:00:01Z",
                    },
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/conversations/c1", headers=_auth_header()
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == "c1"
        assert len(body["messages"]) == 2

    def test_get_not_found(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/conversations/nonexistent",
                headers=_auth_header(),
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/webapp/conversations/{id}
# ---------------------------------------------------------------------------


class TestDeleteConversation:
    """Tests for deleting a conversation."""

    def test_delete_returns_success(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.delete(
                "/api/webapp/conversations/c1", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True


# ---------------------------------------------------------------------------
# PATCH /api/webapp/conversations/{id}
# ---------------------------------------------------------------------------


class TestRenameConversation:
    """Tests for renaming a conversation."""

    def test_rename_returns_updated(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").update.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {
                        "id": "c1",
                        "title": "New Title",
                        "user_id": "user-1",
                    }
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/conversations/c1",
                json={"title": "New Title"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_rename_not_found(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").update.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/conversations/nonexistent",
                json={"title": "New Title"},
                headers=_auth_header(),
            )

        assert resp.status_code == 404

    def test_rename_empty_title_rejected(self, app_client):
        resp = app_client.patch(
            "/api/webapp/conversations/c1",
            json={"title": ""},
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/webapp/insights/grocery/stats
# ---------------------------------------------------------------------------


class TestGroceryStats:
    """Tests for grocery stats endpoint."""

    def test_stats_with_data(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123456"}])
        )
        db.table("mercado_compras").select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = (
            _make_supabase_result(
                [{"total": 50.0}, {"total": 75.5}, {"total": 62.0}]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/stats?month=2026-03",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_spent"] == 187.5
        assert body["trips"] == 3
        assert body["avg_per_trip"] == 62.5

    def test_stats_no_telegram_returns_zeros(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/stats",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["total_spent"] == 0
        assert resp.json()["trips"] == 0

    def test_stats_no_purchases(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("mercado_compras").select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/stats?month=2026-01",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["trips"] == 0


# ---------------------------------------------------------------------------
# GET /api/webapp/insights/grocery/monthly
# ---------------------------------------------------------------------------


class TestGroceryMonthly:
    """Tests for monthly grocery spending."""

    def test_monthly_returns_list(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("mercado_compras").select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = (
            _make_supabase_result([{"total": 100.0}])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/monthly?months=3",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert len(resp.json()["months"]) == 3

    def test_monthly_no_telegram(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/monthly",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["months"] == []


# ---------------------------------------------------------------------------
# GET /api/webapp/insights/grocery/stores
# ---------------------------------------------------------------------------


class TestGroceryStores:
    """Tests for store ranking endpoint."""

    def test_stores_with_data(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("mercado_compras").select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {"mercado": "Lidl", "total": 67.30},
                    {"mercado": "Lidl", "total": 40.00},
                    {"mercado": "Dunnes", "total": 55.20},
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/stores?month=2026-03",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        stores = resp.json()["stores"]
        assert len(stores) == 2
        assert stores[0]["name"] == "Lidl"
        assert stores[0]["trips"] == 2

    def test_stores_empty(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/stores",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["stores"] == []


# ---------------------------------------------------------------------------
# GET /api/webapp/insights/grocery/products
# ---------------------------------------------------------------------------


class TestGroceryProducts:
    """Tests for products endpoint."""

    def test_products_with_data(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("mercado_itens").select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {"produto": "Milk 1L", "quantidade": 2, "preco_total": 2.98, "preco_unitario": 1.49},
                    {"produto": "Milk 1L", "quantidade": 1, "preco_total": 1.49, "preco_unitario": 1.49},
                    {"produto": "Bread", "quantidade": 1, "preco_total": 1.20, "preco_unitario": 1.20},
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/products?month=2026-03",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        products = resp.json()["products"]
        assert len(products) == 2
        assert products[0]["name"] == "Milk 1L"
        assert products[0]["total"] == 4.47

    def test_products_empty(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/insights/grocery/products",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["products"] == []


# ---------------------------------------------------------------------------
# GET /api/webapp/services/status
# ---------------------------------------------------------------------------


class TestServicesStatus:
    """Tests for OAuth services status."""

    def test_services_with_connected_provider(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("user_oauth_tokens").select.return_value.in_.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {"provider": "google", "active": True, "updated_at": "2026-03-01T10:00:00Z"},
                    {"provider": "spotify", "active": False, "updated_at": "2026-02-01T10:00:00Z"},
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/services/status", headers=_auth_header()
            )

        assert resp.status_code == 200
        services = resp.json()["services"]
        assert services["google"]["connected"] is True
        assert services["spotify"]["connected"] is False
        assert services["smartthings"]["connected"] is False

    def test_services_no_telegram(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/services/status", headers=_auth_header()
            )

        assert resp.status_code == 200
        services = resp.json()["services"]
        for provider in ["google", "spotify", "smartthings", "smartcar", "github"]:
            assert services[provider]["connected"] is False

    def test_services_no_telegram_with_connected_oauth(self, app_client):
        """Webapp-only user (no Telegram) with OAuth tokens connected via UUID."""
        db = _mock_db()
        # User has no Telegram link (telegram_chat_id is None)
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": None}])
        )
        # But user HAS connected Google OAuth via webapp (stored with Supabase UUID)
        db.table("user_oauth_tokens").select.return_value.in_.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {
                        "provider": "google",
                        "active": True,
                        "updated_at": "2026-03-01T10:00:00Z",
                    }
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/services/status", headers=_auth_header()
            )

        assert resp.status_code == 200
        services = resp.json()["services"]
        assert services["google"]["connected"] is True
        assert services["spotify"]["connected"] is False


# ---------------------------------------------------------------------------
# GET /api/webapp/activity
# ---------------------------------------------------------------------------


class TestActivityFeed:
    """Tests for activity feed endpoint."""

    def test_activity_with_messages(self, app_client):
        db = _mock_db()
        db.table("webapp_messages").select.return_value.eq.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = (
            _make_supabase_result(
                [
                    {
                        "id": "m1",
                        "text": "Playing Candy Shop",
                        "agent": "music",
                        "type": "music",
                        "source": "webapp",
                        "created_at": "2026-03-07T10:00:00Z",
                        "role": "assistant",
                    },
                    {
                        "id": "m2",
                        "text": "Sunny, 22C in Dublin",
                        "agent": "weather",
                        "type": "weather",
                        "source": "webapp",
                        "created_at": "2026-03-07T09:00:00Z",
                        "role": "assistant",
                    },
                ]
            )
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/activity?limit=10",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["activities"]) == 2
        assert body["activities"][0]["service"] == "Spotify"
        assert body["has_more"] is False

    def test_activity_empty(self, app_client):
        db = _mock_db()
        db.table("webapp_messages").select.return_value.eq.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/activity", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["activities"] == []
        assert resp.json()["has_more"] is False


# ---------------------------------------------------------------------------
# GET /api/webapp/smarts/devices
# ---------------------------------------------------------------------------


class TestSmartDevices:
    """Tests for smart home devices endpoint."""

    def test_devices_not_connected(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("user_oauth_tokens").select.return_value.in_.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/smarts/devices", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["connected"] is False
        assert resp.json()["devices"] == []

    def test_devices_connected(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("user_oauth_tokens").select.return_value.in_.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"active": True}])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/smarts/devices", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["connected"] is True

    def test_devices_no_telegram(self, app_client):
        """Webapp-only user (no telegram_chat_id) still queries with UUID."""
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )
        db.table("user_oauth_tokens").select.return_value.in_.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/smarts/devices", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["connected"] is False


# ---------------------------------------------------------------------------
# GET /api/webapp/smarts/vehicles
# ---------------------------------------------------------------------------


class TestSmartVehicles:
    """Tests for smart vehicles endpoint."""

    def test_vehicles_not_connected(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("user_oauth_tokens").select.return_value.in_.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/smarts/vehicles", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["connected"] is False

    def test_vehicles_connected(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"telegram_chat_id": "123"}])
        )
        db.table("user_oauth_tokens").select.return_value.in_.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{"active": True}])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/smarts/vehicles", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json()["connected"] is True


# ---------------------------------------------------------------------------
# GET /api/webapp/finance/portfolio
# ---------------------------------------------------------------------------


class TestFinancePortfolio:
    """Tests for finance portfolio endpoint."""

    def test_portfolio_placeholder(self, app_client):
        resp = app_client.get(
            "/api/webapp/finance/portfolio", headers=_auth_header()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["stocks"] == []
        assert body["crypto"] == []


# ---------------------------------------------------------------------------
# GET /api/webapp/finance/news
# ---------------------------------------------------------------------------


class TestFinanceNews:
    """Tests for finance news endpoint."""

    def test_news_placeholder(self, app_client):
        resp = app_client.get(
            "/api/webapp/finance/news", headers=_auth_header()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["news"] == []


# ---------------------------------------------------------------------------
# GET /api/images/{filename} — static image serving
# ---------------------------------------------------------------------------


class TestServeImage:
    """Tests for the image serving endpoint."""

    def test_serve_existing_image(self, app_client, tmp_path):
        img_file = tmp_path / "test_image.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with patch("api.routes.images_serve._IMAGES_DIR", str(tmp_path)):
            resp = app_client.get("/api/images/test_image.png")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_serve_nonexistent_image_returns_404(self, app_client):
        resp = app_client.get("/api/images/nonexistent.png")
        assert resp.status_code == 404

    def test_serve_invalid_filename_rejected(self, app_client):
        resp = app_client.get("/api/images/../etc/passwd")
        assert resp.status_code in (400, 404, 422)

    def test_serve_jpeg_content_type(self, app_client, tmp_path):
        img_file = tmp_path / "photo.jpg"
        img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        with patch("api.routes.images_serve._IMAGES_DIR", str(tmp_path)):
            resp = app_client.get("/api/images/photo.jpg")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"


# ---------------------------------------------------------------------------
# GET /api/videos/{filename} — static video serving
# ---------------------------------------------------------------------------


class TestServeVideo:
    """Tests for the video serving endpoint."""

    def test_serve_existing_video(self, app_client, tmp_path):
        vid_file = tmp_path / "test_video.mp4"
        vid_file.write_bytes(b"\x00\x00\x00\x1cftyp" + b"\x00" * 100)

        with patch("api.routes.images_serve._VIDEOS_DIR", str(tmp_path)):
            resp = app_client.get("/api/videos/test_video.mp4")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp4"

    def test_serve_nonexistent_video_returns_404(self, app_client):
        resp = app_client.get("/api/videos/nonexistent.mp4")
        assert resp.status_code == 404

    def test_serve_invalid_video_filename_rejected(self, app_client):
        resp = app_client.get("/api/videos/../etc/passwd")
        assert resp.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# POST /api/webapp/chat — GPT-4o vision path
# ---------------------------------------------------------------------------


class TestChatVision:
    """Tests for the GPT-4o vision analysis path."""

    def test_chat_vision_with_image_attachment(self, app_client):
        """When message has [Imagem recebida:] + file_id, use GPT-4o vision."""
        db = _mock_db()
        db.table("webapp_conversations").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result(
                [{"id": "conv-1", "user_id": "user-1"}]
            )
        )
        # insert must be set LAST — _mock_db chains all to same .execute
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-vision-1"}])
        )

        orch_response = AgentResponse(
            response="image", status=AgentStatus.SUCCESS,
        )

        mock_vision_resp = MagicMock()
        mock_vision_resp.choices = [MagicMock()]
        mock_vision_resp.choices[0].message.content = "This is a photo of a cat"

        mock_oai = MagicMock()
        mock_oai.chat.completions.create.return_value = mock_vision_resp

        msg = "O que é esta imagem?\n\n[Imagem recebida: upload_abc-123-def.jpg]"
        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_agent") as mock_get_agent,
            patch("api.routes.webapp.glob.glob", return_value=["/tmp/capivarex_uploads/upload_abc-123-def.jpg"]),
            patch("builtins.open", MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"\xff\xd8\xff"))),
                __exit__=MagicMock(return_value=False),
            ))),
        ):
            mock_orch = MagicMock()
            mock_orch.process = AsyncMock(return_value=orch_response)
            mock_get_agent.return_value = mock_orch

            with patch.dict("sys.modules", {"openai": MagicMock(OpenAI=MagicMock(return_value=mock_oai))}):
                resp = app_client.post(
                    "/api/webapp/chat",
                    json={"message": msg, "conversation_id": "conv-1"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "This is a photo of a cat"
        assert data["data"]["method"] == "vision"

    def test_chat_vision_no_file_id_falls_through(self, app_client):
        """Message with [Imagem recebida:] but no file_id falls to normal chat."""
        db = _mock_db()
        db.table("webapp_conversations").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result(
                [{"id": "conv-1", "user_id": "user-1"}]
            )
        )
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-1"}])
        )

        orch_response = AgentResponse(
            response="chat", status=AgentStatus.SUCCESS,
        )
        chat_response = AgentResponse(
            response="Hello!", status=AgentStatus.SUCCESS,
        )

        with patch("api.routes.webapp._get_db", return_value=db), \
             patch("api.routes.webapp.get_agent") as mock_get_agent:
            mock_orch = MagicMock()
            mock_orch.process = AsyncMock(return_value=orch_response)
            mock_chat = MagicMock()
            mock_chat.process = AsyncMock(return_value=chat_response)
            mock_get_agent.side_effect = lambda name: mock_orch if name == "orchestrator" else mock_chat

            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "[Imagem recebida: photo.jpg] nice photo", "conversation_id": "conv-1"},
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/webapp/chat — image_path → image_url conversion
# ---------------------------------------------------------------------------


class TestChatImageUrlConversion:
    """Tests that image paths are converted to serveable URLs in chat."""

    def test_chat_converts_image_path_to_url(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "conv-img-1", "user_id": "user-1"}])
        )
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-img-1"}])
        )

        orch_response = AgentResponse(
            status=AgentStatus.SUCCESS, response="image"
        )
        image_response = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Here is your image",
            data={"image_path": "generated_images/img_abc123.png"},
            metadata={"type": "image"},
        )

        mock_orch = MagicMock()
        mock_orch.process = AsyncMock(return_value=orch_response)
        mock_img = MagicMock()
        mock_img.process = AsyncMock(return_value=image_response)

        def fake_get_agent(name):
            if name == "orchestrator":
                return mock_orch
            return mock_img

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_agent", side_effect=fake_get_agent),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "Generate an image of a capybara"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["image_url"] == "/api/images/img_abc123.png"
        assert body["data"]["image_path"] == "generated_images/img_abc123.png"

    def test_chat_converts_multiple_image_paths(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "conv-multi", "user_id": "user-1"}])
        )
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-multi"}])
        )

        orch_response = AgentResponse(
            status=AgentStatus.SUCCESS, response="image"
        )
        image_response = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Here are your images",
            data={
                "image_paths": [
                    "generated_images/img_001.png",
                    "generated_images/img_002.png",
                ]
            },
            metadata={"type": "image"},
        )

        mock_orch = MagicMock()
        mock_orch.process = AsyncMock(return_value=orch_response)
        mock_img = MagicMock()
        mock_img.process = AsyncMock(return_value=image_response)

        def fake_get_agent(name):
            if name == "orchestrator":
                return mock_orch
            return mock_img

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_agent", side_effect=fake_get_agent),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "Generate two images"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["image_urls"] == [
            "/api/images/img_001.png",
            "/api/images/img_002.png",
        ]
        # image_url should NOT be set when image_paths exists (no duplicates)
        assert "image_url" not in body["data"]

    def test_chat_converts_video_path_to_url(self, app_client):
        db = _mock_db()
        db.table("webapp_conversations").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "conv-vid-1", "user_id": "user-1"}])
        )
        db.table("webapp_messages").insert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "msg-vid-1"}])
        )

        orch_response = AgentResponse(
            status=AgentStatus.SUCCESS, response="video"
        )
        video_response = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Here is your video",
            data={"video_path": "generated_videos/txt2vid_20260308.mp4"},
            metadata={"type": "video"},
        )

        mock_orch = MagicMock()
        mock_orch.process = AsyncMock(return_value=orch_response)
        mock_vid = MagicMock()
        mock_vid.process = AsyncMock(return_value=video_response)

        def fake_get_agent(name):
            if name == "orchestrator":
                return mock_orch
            return mock_vid

        with (
            patch("api.routes.webapp._get_db", return_value=db),
            patch("api.routes.webapp.get_agent", side_effect=fake_get_agent),
        ):
            resp = app_client.post(
                "/api/webapp/chat",
                json={"message": "Generate a video of a capybara"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["video_url"] == "/api/videos/txt2vid_20260308.mp4"


# ===========================================================================
# Voice STT — POST /api/webapp/voice/transcribe
# ===========================================================================


class TestVoiceTranscribe:
    """Tests for the voice/transcribe endpoint."""

    def test_voice_transcribe_success(self, app_client):
        whisper_mock = MagicMock()
        whisper_mock.speech_to_text = AsyncMock(
            return_value={
                "text": "Olá, tudo bem?",
                "language": "pt",
                "model": "whisper-1",
            }
        )

        with (
            patch(
                "api.routes.webapp._get_service_or_503",
                return_value=whisper_mock,
            ),
            patch(
                "api.routes.webapp.temp_upload",
            ) as mock_temp,
        ):
            # Make temp_upload yield a fake path
            mock_temp.return_value.__aenter__ = AsyncMock(
                return_value="/tmp/voice_stt_test.mp3"
            )
            mock_temp.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            resp = app_client.post(
                "/api/webapp/voice/transcribe",
                files={"audio": ("test.mp3", b"fake-audio", "audio/mpeg")},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "Olá, tudo bem?"
        assert body["language"] == "pt"
        assert body["model"] == "whisper-1"

    def test_voice_transcribe_service_unavailable(self, app_client):
        from fastapi import HTTPException

        with patch(
            "api.routes.webapp._get_service_or_503",
            side_effect=HTTPException(
                status_code=503,
                detail="Whisper STT service unavailable",
            ),
        ):
            resp = app_client.post(
                "/api/webapp/voice/transcribe",
                files={"audio": ("test.mp3", b"fake-audio", "audio/mpeg")},
                headers=_auth_header(),
            )

        assert resp.status_code == 503


# ===========================================================================
# Voice TTS — POST /api/webapp/voice/synthesize
# ===========================================================================


class TestVoiceSynthesize:
    """Tests for the voice/synthesize endpoint."""

    def test_voice_synthesize_success(self, app_client):
        tts_mock = MagicMock()
        tts_mock.text_to_speech = AsyncMock(
            return_value=b"\xff\xfb\x90\x00fake-mp3-bytes"
        )

        with patch(
            "api.routes.webapp._get_service_or_503",
            return_value=tts_mock,
        ):
            resp = app_client.post(
                "/api/webapp/voice/synthesize",
                json={"text": "Olá mundo"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "audio_base64" in body
        assert body["content_type"] == "audio/mpeg"
        # Verify base64 is decodable
        import base64

        decoded = base64.b64decode(body["audio_base64"])
        assert decoded == b"\xff\xfb\x90\x00fake-mp3-bytes"

    def test_voice_synthesize_empty_text_returns_422(self, app_client):
        resp = app_client.post(
            "/api/webapp/voice/synthesize",
            json={"text": ""},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_voice_synthesize_service_unavailable(self, app_client):
        from fastapi import HTTPException

        with patch(
            "api.routes.webapp._get_service_or_503",
            side_effect=HTTPException(
                status_code=503,
                detail="ElevenLabs TTS service unavailable",
            ),
        ):
            resp = app_client.post(
                "/api/webapp/voice/synthesize",
                json={"text": "Hello"},
                headers=_auth_header(),
            )

        assert resp.status_code == 503


# ===========================================================================
# Memory — GET /api/webapp/memory
# ===========================================================================


class TestMemory:
    """Tests for the memory endpoint."""

    def test_get_memory_returns_entries(self, app_client):
        db = _mock_db()
        db.table("user_memory").select.return_value.eq.return_value.order.return_value.execute.return_value = (
            _make_supabase_result([
                {"id": "mem-1", "key": "name", "value": "Henrique", "source": "webapp", "updated_at": "2026-03-10T12:00:00Z"},
                {"id": "mem-2", "key": "city", "value": "Lisboa", "source": "telegram", "updated_at": "2026-03-10T13:00:00Z"},
            ])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/memory", headers=_auth_header()
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "memories" in body
        memories = body["memories"]
        assert len(memories) == 2
        assert memories[0]["key"] == "name"
        assert memories[0]["value"] == "Henrique"
        assert memories[0]["source"] == "webapp"
        assert memories[1]["key"] == "city"
        assert memories[1]["value"] == "Lisboa"

    def test_get_memory_empty(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/memory", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json() == {"memories": []}

    def test_delete_memory_success(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.delete(
                "/api/webapp/memory/mem-abc-123", headers=_auth_header()
            )

        assert resp.status_code == 204
        db.table("user_memory").delete.assert_called_once()

    def test_delete_memory_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("user_memory").delete.return_value.eq.return_value.eq.return_value.execute.side_effect = (
            Exception("DB failure")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.delete(
                "/api/webapp/memory/mem-abc-123", headers=_auth_header()
            )

        assert resp.status_code == 500
        assert "delete memory" in resp.json()["detail"].lower()

    def test_upsert_memory_success(self, app_client):
        mock_upsert = AsyncMock(return_value=True)

        with patch(
            "services.business.rag_service.upsert_memory_with_embedding",
            mock_upsert,
        ):
            resp = app_client.post(
                "/api/webapp/memory",
                json={"key": "favorite_color", "value": "blue"},
                headers=_auth_header(),
            )

        assert resp.status_code == 201
        assert resp.json() == {"ok": True}
        mock_upsert.assert_called_once()

    def test_upsert_memory_missing_key_returns_422(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.post(
                "/api/webapp/memory",
                json={"key": "", "value": "something"},
                headers=_auth_header(),
            )

        assert resp.status_code == 422

    def test_upsert_memory_missing_value_returns_422(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.post(
                "/api/webapp/memory",
                json={"key": "some_key", "value": "  "},
                headers=_auth_header(),
            )

        assert resp.status_code == 422

    def test_upsert_memory_db_error_returns_500(self, app_client):
        mock_upsert = AsyncMock(return_value=False)

        with patch(
            "services.business.rag_service.upsert_memory_with_embedding",
            mock_upsert,
        ):
            resp = app_client.post(
                "/api/webapp/memory",
                json={"key": "color", "value": "red"},
                headers=_auth_header(),
            )

        assert resp.status_code == 500
        assert "upsert memory" in resp.json()["detail"].lower()


# ===========================================================================
# Reminders — GET + PATCH /api/webapp/reminders
# ===========================================================================


class TestReminders:
    """Tests for the reminders endpoints."""

    def test_list_reminders_returns_entries(self, app_client):
        db = _mock_db()
        db.table("reminders").select.return_value.eq.return_value.order.return_value.execute.return_value = (
            _make_supabase_result([
                {
                    "id": "rem-1",
                    "text": "Tomar remédio",
                    "remind_at": "2026-03-10T09:00:00Z",
                    "enabled": True,
                },
                {
                    "id": "rem-2",
                    "text": "Reunião",
                    "remind_at": "2026-03-10T14:00:00Z",
                    "enabled": True,
                },
            ])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/reminders", headers=_auth_header()
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["text"] == "Tomar remédio"

    def test_list_reminders_empty(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/reminders", headers=_auth_header()
            )

        assert resp.status_code == 200
        assert resp.json() == []

    def test_update_reminder_toggle(self, app_client):
        db = _mock_db()
        db.table("reminders").update.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_supabase_result([
                {
                    "id": "rem-1",
                    "text": "Tomar remédio",
                    "remind_at": "2026-03-10T09:00:00Z",
                    "enabled": False,
                },
            ])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/reminders/rem-1",
                json={"enabled": False},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False

    def test_update_reminder_not_found(self, app_client):
        db = _mock_db()
        db.table("reminders").update.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_supabase_result([])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/reminders/nonexistent",
                json={"enabled": True},
                headers=_auth_header(),
            )

        assert resp.status_code == 404


# ===========================================================================
# Error-path coverage — voice, memory, reminders, notes
# ===========================================================================


class TestVoiceTranscribeErrors:
    """Error-path tests for voice/transcribe."""

    def test_transcribe_processing_error_returns_500(self, app_client):
        whisper_mock = MagicMock()
        whisper_mock.speech_to_text = AsyncMock(
            side_effect=RuntimeError("Whisper crashed")
        )

        with (
            patch(
                "api.routes.webapp._get_service_or_503",
                return_value=whisper_mock,
            ),
            patch("api.routes.webapp.temp_upload") as mock_temp,
        ):
            mock_temp.return_value.__aenter__ = AsyncMock(
                return_value="/tmp/voice_stt_err.mp3"
            )
            mock_temp.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = app_client.post(
                "/api/webapp/voice/transcribe",
                files={"audio": ("test.mp3", b"fake-audio", "audio/mpeg")},
                headers=_auth_header(),
            )

        assert resp.status_code == 500
        assert "transcribe" in resp.json()["detail"].lower()


class TestVoiceSynthesizeErrors:
    """Error-path tests for voice/synthesize."""

    def test_synthesize_processing_error_returns_500(self, app_client):
        tts_mock = MagicMock()
        tts_mock.text_to_speech = AsyncMock(
            side_effect=RuntimeError("ElevenLabs API down")
        )

        with patch(
            "api.routes.webapp._get_service_or_503",
            return_value=tts_mock,
        ):
            resp = app_client.post(
                "/api/webapp/voice/synthesize",
                json={"text": "Hello"},
                headers=_auth_header(),
            )

        assert resp.status_code == 500
        assert "synthesize" in resp.json()["detail"].lower()


class TestMemoryErrors:
    """Error-path tests for memory."""

    def test_memory_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("user_memory").select.return_value.eq.return_value.order.return_value.execute.side_effect = (
            RuntimeError("DB connection lost")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/memory", headers=_auth_header()
            )

        assert resp.status_code == 500
        assert "memory" in resp.json()["detail"].lower()


class TestRemindersErrors:
    """Error-path tests for reminders."""

    def test_list_reminders_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("reminders").select.return_value.eq.return_value.order.return_value.execute.side_effect = (
            RuntimeError("DB timeout")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/reminders", headers=_auth_header()
            )

        assert resp.status_code == 500
        assert "reminders" in resp.json()["detail"].lower()

    def test_update_reminder_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("reminders").update.return_value.eq.return_value.eq.return_value.execute.side_effect = (
            RuntimeError("DB write failed")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/reminders/rem-1",
                json={"enabled": False},
                headers=_auth_header(),
            )

        assert resp.status_code == 500
        assert "reminder" in resp.json()["detail"].lower()


class TestNotesErrors:
    """Error-path tests for notes CRUD."""

    def test_list_notes_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("notes").select.return_value.eq.return_value.order.return_value.execute.side_effect = (
            RuntimeError("DB error")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/notes", headers=_auth_header()
            )

        assert resp.status_code == 500

    def test_create_note_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("notes").insert.return_value.execute.side_effect = (
            RuntimeError("DB insert failed")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.post(
                "/api/webapp/notes",
                json={"title": "Test", "content": "Body"},
                headers=_auth_header(),
            )

        assert resp.status_code == 500

    def test_update_note_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("notes").update.return_value.eq.return_value.eq.return_value.execute.side_effect = (
            RuntimeError("DB update failed")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/notes/note-1",
                json={"title": "Updated"},
                headers=_auth_header(),
            )

        assert resp.status_code == 500

    def test_delete_note_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("notes").delete.return_value.eq.return_value.eq.return_value.execute.side_effect = (
            RuntimeError("DB delete failed")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.delete(
                "/api/webapp/notes/note-1",
                headers=_auth_header(),
            )

        assert resp.status_code == 500


# ===========================================================================
# Quota — GET /api/webapp/quota
# ===========================================================================


class TestQuota:
    """Tests for the daily message quota endpoint."""

    def test_quota_with_user_data(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{
                "plan": "me",
                "messages_used": 50,
                "messages_limit": 300,
            }])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/quota", headers=_auth_header()
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "me"
        assert body["messages_used"] == 50
        assert body["messages_limit"] == 300
        assert body["quota_pct"] == 16.7
        assert body["is_unlimited"] is False
        assert body["messages_remaining"] == 250

    def test_quota_user_not_found_returns_defaults(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/quota", headers=_auth_header()
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "free"
        assert body["messages_used"] == 0
        assert body["messages_limit"] == 30

    def test_quota_unlimited_plan(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result([{
                "plan": "everywhere",
                "messages_used": 100,
                "messages_limit": 999999,
            }])
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/quota", headers=_auth_header()
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_unlimited"] is True
        assert body["quota_pct"] == 0.0

    def test_quota_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("users").select.return_value.eq.return_value.limit.return_value.execute.side_effect = (
            RuntimeError("DB timeout")
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/quota", headers=_auth_header()
            )

        assert resp.status_code == 500


# ===========================================================================
# Weather — GET /api/webapp/weather
# ===========================================================================


class TestWeather:
    """Tests for the weather proxy endpoint."""

    def test_weather_success(self, app_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "location": {"name": "Lisboa"},
            "current": {"temp_c": 22.0},
        }

        with patch("api.routes.webapp.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(
                    get=AsyncMock(return_value=mock_response)
                )
            )
            mock_client.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            with patch.dict("os.environ", {"WEATHER_API_KEY": "test-key"}):
                resp = app_client.get(
                    "/api/webapp/weather?q=Lisboa",
                    headers=_auth_header(),
                )

        assert resp.status_code == 200

    def test_weather_no_api_key_returns_503(self, app_client):
        with patch.dict("os.environ", {}, clear=False):
            with patch("api.routes.webapp.os.getenv", return_value=None):
                resp = app_client.get(
                    "/api/webapp/weather?q=Lisboa",
                    headers=_auth_header(),
                )

        assert resp.status_code == 503

    def test_weather_missing_query_returns_422(self, app_client):
        resp = app_client.get(
            "/api/webapp/weather",
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Security Events
# ---------------------------------------------------------------------------


class TestSecurityEvents:
    """Tests for GET /security/events."""

    def test_security_events_success(self, app_client):
        db = _mock_db()
        events = [
            {"id": "e1", "event_type": "auth_success", "severity": "info",
             "ip_address": "1.2.3.4", "endpoint": "/login", "created_at": "2026-01-01T00:00:00Z",
             "details": {}},
        ]
        db.table("security_events").execute.return_value = _make_supabase_result(events)
        # failures count
        db.table("security_events").execute.side_effect = [
            _make_supabase_result(events),          # recent events
            _make_supabase_result([], count=0),      # failures 24h
            _make_supabase_result([{"created_at": "2026-01-01T00:00:00Z", "ip_address": "1.2.3.4"}]),  # last login
        ]

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get("/api/webapp/security/events", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "summary" in data

    def test_security_events_pgrst205_graceful(self, app_client):
        db = _mock_db()
        db.table("security_events").execute.side_effect = Exception(
            "PGRST205: schema cache lookup failed"
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get("/api/webapp/security/events", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["summary"]["total_events"] == 0


# ---------------------------------------------------------------------------
# Proactivity Feed
# ---------------------------------------------------------------------------


class TestProactivityFeed:
    """Tests for proactivity feed endpoints."""

    def test_feed_empty(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.return_value = _make_supabase_result([], count=0)

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get("/api/webapp/proactivity/feed", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["unread_count"] == 0
        assert data["has_more"] is False

    def test_feed_with_items(self, app_client):
        db = _mock_db()
        items = [
            {"id": "f1", "type": "insight", "title": "Weather", "message": "Rain expected",
             "metadata": {}, "is_read": False, "created_at": "2026-01-01T00:00:00Z", "read_at": None},
        ]
        db.table("proactivity_feed").execute.side_effect = [
            _make_supabase_result(items),        # feed query
            _make_supabase_result([], count=1),   # unread count
        ]

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get("/api/webapp/proactivity/feed", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["unread_count"] == 1

    def test_feed_unread_only_filter(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.return_value = _make_supabase_result([], count=0)

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/proactivity/feed?unread_only=true",
                headers=_auth_header(),
            )

        assert resp.status_code == 200

    def test_feed_pgrst205_graceful(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.side_effect = Exception(
            "PGRST205: schema cache lookup failed"
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get("/api/webapp/proactivity/feed", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    def test_feed_db_error_returns_500(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.side_effect = Exception("DB connection lost")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get("/api/webapp/proactivity/feed", headers=_auth_header())

        assert resp.status_code == 500


class TestProactivityFeedMarkRead:
    """Tests for PATCH /proactivity/feed/{item_id}/read."""

    def test_mark_read_success(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.return_value = _make_supabase_result(
            [{"id": "f1", "is_read": True}]
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/proactivity/feed/f1/read",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_mark_read_not_found(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.return_value = _make_supabase_result([])

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/proactivity/feed/nonexistent/read",
                headers=_auth_header(),
            )

        assert resp.status_code == 404

    def test_mark_read_error(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.side_effect = Exception("DB error")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/proactivity/feed/f1/read",
                headers=_auth_header(),
            )

        assert resp.status_code == 500


class TestProactivityFeedReadAll:
    """Tests for PATCH /proactivity/feed/read-all."""

    def test_read_all_success(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/proactivity/feed/read-all",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_read_all_error(self, app_client):
        db = _mock_db()
        db.table("proactivity_feed").execute.side_effect = Exception("DB error")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.patch(
                "/api/webapp/proactivity/feed/read-all",
                headers=_auth_header(),
            )

        assert resp.status_code == 500


class TestProactivityPreferences:
    """Tests for GET/PUT /proactivity/preferences."""

    def test_get_preferences_with_data(self, app_client):
        db = _mock_db()
        db.table("user_preferences").maybe_single.return_value = db.table("user_preferences")
        db.table("user_preferences").execute.return_value = _make_supabase_result(
            {"proactive_enabled": False, "notify_weather": True,
             "notify_traffic": False, "notify_reminders": True}
        )
        # For maybe_single, data is the dict directly, not a list
        result_mock = MagicMock()
        result_mock.data = {"proactive_enabled": False, "notify_weather": True,
                            "notify_traffic": False, "notify_reminders": True}
        db.table("user_preferences").execute.return_value = result_mock

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/proactivity/preferences",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "proactive_enabled" in data
        assert "notify_weather" in data

    def test_get_preferences_no_row_returns_defaults(self, app_client):
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.data = None
        db.table("user_preferences").maybe_single.return_value = db.table("user_preferences")
        db.table("user_preferences").execute.return_value = result_mock

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/proactivity/preferences",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["proactive_enabled"] is True
        assert data["notify_weather"] is True

    def test_get_preferences_error_returns_defaults(self, app_client):
        db = _mock_db()
        db.table("user_preferences").execute.side_effect = Exception("DB error")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/proactivity/preferences",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["proactive_enabled"] is True

    def test_put_preferences_success(self, app_client):
        db = _mock_db()
        db.table("user_preferences").execute.return_value = _make_supabase_result(
            [{"user_id": "user-1", "proactive_enabled": False,
              "notify_weather": True, "notify_traffic": True, "notify_reminders": True}]
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.put(
                "/api/webapp/proactivity/preferences",
                json={"proactive_enabled": False},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["proactive_enabled"] is False

    def test_put_preferences_empty_body_returns_422(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.put(
                "/api/webapp/proactivity/preferences",
                json={},
                headers=_auth_header(),
            )

        assert resp.status_code == 422

    def test_put_preferences_error(self, app_client):
        db = _mock_db()
        db.table("user_preferences").execute.side_effect = Exception("DB error")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.put(
                "/api/webapp/proactivity/preferences",
                json={"notify_weather": False},
                headers=_auth_header(),
            )

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Marketplace / Integrations
# ---------------------------------------------------------------------------


class TestMarketplaceIntegrations:
    """Tests for GET /market/integrations."""

    def test_list_integrations_success(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.return_value = _make_supabase_result(
            [{"provider": "google", "expires_at": "2026-12-31T00:00:00Z"}]
        )
        db.table("users").execute.return_value = _make_supabase_result(
            [{"plan": "me"}]
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "integrations" in data
        assert data["user_plan"] == "me"
        # google_calendar should be connected
        google_cal = next(
            (i for i in data["integrations"] if i["id"] == "google_calendar"),
            None,
        )
        assert google_cal is not None
        assert google_cal["is_connected"] is True
        assert google_cal["is_available"] is True

    def test_list_integrations_free_plan(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.return_value = _make_supabase_result([])
        db.table("users").execute.return_value = _make_supabase_result(
            [{"plan": "free"}]
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        # Only telegram available on free plan
        telegram = next(
            (i for i in data["integrations"] if i["id"] == "telegram"),
            None,
        )
        assert telegram is not None
        assert telegram["is_available"] is True
        assert telegram["upgrade_required"] is False

        # Spotify requires upgrade on free
        spotify = next(
            (i for i in data["integrations"] if i["id"] == "spotify"),
            None,
        )
        assert spotify is not None
        assert spotify["is_available"] is False
        assert spotify["upgrade_required"] is True

    def test_list_integrations_category_filter(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.return_value = _make_supabase_result([])
        db.table("users").execute.return_value = _make_supabase_result(
            [{"plan": "everywhere"}]
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations?category=entertainment",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["integrations"]) == 1
        assert data["integrations"][0]["id"] == "spotify"

    def test_list_integrations_user_not_found(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.return_value = _make_supabase_result([])
        db.table("users").execute.return_value = _make_supabase_result([])

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        assert resp.json()["user_plan"] == "free"

    def test_list_integrations_error(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.side_effect = Exception("DB error")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations",
                headers=_auth_header(),
            )

        assert resp.status_code == 500


class TestIntegrationStatus:
    """Tests for GET /market/integrations/{id}/status."""

    def test_status_connected(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.return_value = _make_supabase_result(
            [{"provider": "spotify", "expires_at": "2026-12-31", "created_at": "2026-01-01"}]
        )

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations/spotify/status",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_connected"] is True
        assert data["connected_at"] == "2026-01-01"

    def test_status_not_connected(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.return_value = _make_supabase_result([])

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations/spotify/status",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_connected"] is False
        assert data["connected_at"] is None

    def test_status_not_found(self, app_client):
        with patch("api.routes.webapp._get_db", return_value=_mock_db()):
            resp = app_client.get(
                "/api/webapp/market/integrations/nonexistent/status",
                headers=_auth_header(),
            )

        assert resp.status_code == 404

    def test_status_error(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.side_effect = Exception("DB error")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.get(
                "/api/webapp/market/integrations/spotify/status",
                headers=_auth_header(),
            )

        assert resp.status_code == 500


class TestIntegrationDisconnect:
    """Tests for DELETE /market/integrations/{id}/disconnect."""

    def test_disconnect_success(self, app_client):
        db = _mock_db()

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.delete(
                "/api/webapp/market/integrations/spotify/disconnect",
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_connected"] is False

    def test_disconnect_not_found(self, app_client):
        with patch("api.routes.webapp._get_db", return_value=_mock_db()):
            resp = app_client.delete(
                "/api/webapp/market/integrations/nonexistent/disconnect",
                headers=_auth_header(),
            )

        assert resp.status_code == 404

    def test_disconnect_error(self, app_client):
        db = _mock_db()
        db.table("user_oauth_tokens").execute.side_effect = Exception("DB error")

        with patch("api.routes.webapp._get_db", return_value=db):
            resp = app_client.delete(
                "/api/webapp/market/integrations/spotify/disconnect",
                headers=_auth_header(),
            )

        assert resp.status_code == 500
