"""Unit tests for TenancyManager."""

import pytest
from unittest.mock import Mock, MagicMock

from bot.core.tenancy import TenancyManager, TenantContext


def _mock_db(query_result=None, upsert_fail=False):
    """Build a mock database service with a chainable .client.table(...)."""
    db = Mock()
    client = MagicMock()

    # identity_map select chain
    response = Mock()
    response.data = query_result

    select = client.table.return_value.select.return_value
    select.eq.return_value.eq.return_value.execute.return_value = response

    # upsert chain
    if upsert_fail:
        client.table.return_value.upsert.side_effect = RuntimeError("upsert fail")
    else:
        client.table.return_value.upsert.return_value.execute.return_value = Mock()

    db.client = client
    return db


# -------------------------------------------------------------------
# resolve_context
# -------------------------------------------------------------------


class TestResolveContext:
    @pytest.mark.asyncio
    async def test_resolve_telegram_success(self):
        db = _mock_db(query_result=[{"user_id": "u1"}])
        tm = TenancyManager(db)
        ctx = await tm.resolve_context("telegram", "12345")
        assert ctx is not None
        assert ctx.tenant_id == "u1"
        assert ctx.user_id == "u1"
        assert ctx.channel == "telegram"
        assert ctx.chat_id == "12345"
        assert ctx.session_id is None

    @pytest.mark.asyncio
    async def test_resolve_webapp_success(self):
        db = _mock_db(query_result=[{"user_id": "u2"}])
        tm = TenancyManager(db)
        ctx = await tm.resolve_context("webapp", "session-abc")
        assert ctx is not None
        assert ctx.channel == "webapp"
        assert ctx.session_id == "session-abc"
        assert ctx.chat_id is None

    @pytest.mark.asyncio
    async def test_resolve_no_mapping(self):
        db = _mock_db(query_result=[])
        tm = TenancyManager(db)
        ctx = await tm.resolve_context("telegram", "99999")
        assert ctx is None

    @pytest.mark.asyncio
    async def test_resolve_none_data(self):
        db = _mock_db(query_result=None)
        tm = TenancyManager(db)
        ctx = await tm.resolve_context("telegram", "99999")
        assert ctx is None

    @pytest.mark.asyncio
    async def test_resolve_db_exception(self):
        db = Mock()
        db.client = Mock()
        db.client.table.side_effect = RuntimeError("db down")
        tm = TenancyManager(db)
        ctx = await tm.resolve_context("telegram", "123")
        assert ctx is None


# -------------------------------------------------------------------
# Convenience helpers
# -------------------------------------------------------------------


class TestConvenienceHelpers:
    @pytest.mark.asyncio
    async def test_get_context_for_telegram(self):
        db = _mock_db(query_result=[{"user_id": "u1"}])
        tm = TenancyManager(db)
        ctx = await tm.get_context_for_telegram("111")
        assert ctx is not None
        assert ctx.channel == "telegram"

    @pytest.mark.asyncio
    async def test_get_context_for_webapp_session(self):
        db = _mock_db(query_result=[{"user_id": "u1"}])
        tm = TenancyManager(db)
        ctx = await tm.get_context_for_webapp(session_id="sess-1")
        assert ctx is not None

    @pytest.mark.asyncio
    async def test_get_context_for_webapp_email_fallback(self):
        """When session lookup fails, falls back to email."""
        call_count = 0

        async def _resolve(channel, identifier):
            nonlocal call_count
            call_count += 1
            if identifier == "user@example.com":
                return TenantContext(
                    tenant_id="u1",
                    user_id="u1",
                    channel="webapp",
                    session_id="user@example.com",
                )
            return None

        db = _mock_db()
        tm = TenancyManager(db)
        tm.resolve_context = _resolve

        ctx = await tm.get_context_for_webapp(
            session_id="bad-session", email="user@example.com"
        )
        assert ctx is not None
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_get_context_for_webapp_none(self):
        db = _mock_db()
        tm = TenancyManager(db)
        ctx = await tm.get_context_for_webapp()
        assert ctx is None


# -------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------


class TestRegistration:
    @pytest.mark.asyncio
    async def test_register_telegram_user(self):
        db = _mock_db()
        tm = TenancyManager(db)
        result = await tm.register_telegram_user("123", "u1")
        assert result is True

    @pytest.mark.asyncio
    async def test_register_telegram_user_failure(self):
        db = _mock_db(upsert_fail=True)
        tm = TenancyManager(db)
        result = await tm.register_telegram_user("123", "u1")
        assert result is False

    @pytest.mark.asyncio
    async def test_register_webapp_user_session_and_email(self):
        db = _mock_db()
        tm = TenancyManager(db)
        result = await tm.register_webapp_user("u1", session_id="s1", email="a@b.c")
        assert result is True

    @pytest.mark.asyncio
    async def test_register_webapp_user_no_identifiers(self):
        db = _mock_db()
        tm = TenancyManager(db)
        result = await tm.register_webapp_user("u1")
        assert result is False


# -------------------------------------------------------------------
# TenantContext dataclass
# -------------------------------------------------------------------


class TestTenantContext:
    def test_defaults(self):
        tc = TenantContext(tenant_id="t1", user_id="u1", channel="cli")
        assert tc.session_id is None
        assert tc.chat_id is None

    def test_full_fields(self):
        tc = TenantContext(
            tenant_id="t1",
            user_id="u1",
            channel="telegram",
            session_id="s1",
            chat_id="c1",
        )
        assert tc.session_id == "s1"
        assert tc.chat_id == "c1"
