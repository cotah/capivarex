"""Unit tests for RequestProcessor."""

import time
import pytest
from unittest.mock import AsyncMock, Mock, patch

from utils.request_processor import RequestProcessor, RATE_LIMIT_SECONDS
import utils.request_processor as rp_module


@pytest.fixture(autouse=True)
def _clear_rate_limit_state():
    """Clear the module-level rate limit dict between tests."""
    rp_module._user_last_message_time.clear()
    yield
    rp_module._user_last_message_time.clear()


def _mock_db_service(user_data=None):
    """Return a mock database service."""
    db = Mock()
    db.is_initialized = Mock(return_value=True)
    db.get_user_by_telegram_id = AsyncMock(return_value=user_data)
    return db


def _mock_tenancy_resolve(tenant_context=None):
    """Patch TenancyManager.resolve_context to return a fixed value."""
    return patch(
        "utils.request_processor.TenancyManager.resolve_context",
        new_callable=AsyncMock,
        return_value=tenant_context,
    )


# -------------------------------------------------------------------
# Rate limiting
# -------------------------------------------------------------------


class TestRateLimiting:
    def test_first_message_not_limited(self):
        proc = RequestProcessor(user_identifier=100)
        assert proc._is_rate_limited() is False

    def test_rapid_second_message_limited(self):
        proc = RequestProcessor(user_identifier=200)
        proc._is_rate_limited()  # records timestamp
        assert proc._is_rate_limited() is True  # within 2s

    def test_message_after_delay_not_limited(self):
        proc = RequestProcessor(user_identifier=300)
        proc._is_rate_limited()
        # Manually set timestamp to the past
        rp_module._user_last_message_time[300] = time.time() - RATE_LIMIT_SECONDS - 1
        assert proc._is_rate_limited() is False


# -------------------------------------------------------------------
# Context binding
# -------------------------------------------------------------------


class TestBindContextVars:
    def test_bind_with_no_context(self):
        proc = RequestProcessor(user_identifier=1)
        proc.request_id = "req-123"
        # Should not raise even without user/tenant context
        with patch(
            "utils.request_processor.structlog.contextvars.bind_contextvars"
        ) as mock_bind:
            proc._bind_context_vars()
            mock_bind.assert_called_once_with(request_id="req-123")

    def test_bind_with_full_context(self):
        proc = RequestProcessor(user_identifier=1)
        proc.request_id = "req-456"

        from schemas.context import UserContext

        proc.user_context = UserContext(
            user_id="uid", telegram_chat_id=1, full_name="Test"
        )
        from bot.core.tenancy import TenantContext

        proc.tenant_context = TenantContext(
            tenant_id="tid", user_id="uid", channel="telegram"
        )

        with patch(
            "utils.request_processor.structlog.contextvars.bind_contextvars"
        ) as mock_bind:
            proc._bind_context_vars()
            call_kwargs = mock_bind.call_args[1]
            assert call_kwargs["request_id"] == "req-456"
            assert call_kwargs["user_id"] == "uid"
            assert call_kwargs["tenant_id"] == "tid"


# -------------------------------------------------------------------
# _fetch_user_context
# -------------------------------------------------------------------


class TestFetchUserContext:
    @pytest.mark.asyncio
    async def test_fetch_success(self):
        user_data = {
            "user_id": "u1",
            "telegram_chat_id": 12345,
            "full_name": "Henri",
        }
        mock_db = _mock_db_service(user_data)
        with patch("utils.request_processor.get_service", return_value=mock_db):
            proc = RequestProcessor(user_identifier=12345)
            ctx = await proc._fetch_user_context()

        assert ctx is not None
        assert ctx.user_id == "u1"
        assert ctx.full_name == "Henri"

    @pytest.mark.asyncio
    async def test_fetch_no_db_service(self):
        with patch("utils.request_processor.get_service", return_value=None):
            proc = RequestProcessor(user_identifier=1)
            ctx = await proc._fetch_user_context()
        assert ctx is None

    @pytest.mark.asyncio
    async def test_fetch_db_not_initialized(self):
        mock_db = Mock()
        mock_db.is_initialized = Mock(return_value=False)
        with patch("utils.request_processor.get_service", return_value=mock_db):
            proc = RequestProcessor(user_identifier=1)
            ctx = await proc._fetch_user_context()
        assert ctx is None

    @pytest.mark.asyncio
    async def test_fetch_user_not_found(self):
        mock_db = _mock_db_service(user_data=None)
        with patch("utils.request_processor.get_service", return_value=mock_db):
            proc = RequestProcessor(user_identifier=999)
            ctx = await proc._fetch_user_context()
        assert ctx is None

    @pytest.mark.asyncio
    async def test_fetch_invalid_user_data(self):
        # Missing required fields should cause validation error
        mock_db = _mock_db_service(user_data={"bad": "data"})
        with patch("utils.request_processor.get_service", return_value=mock_db):
            proc = RequestProcessor(user_identifier=1)
            ctx = await proc._fetch_user_context()
        assert ctx is None


# -------------------------------------------------------------------
# _resolve_tenant
# -------------------------------------------------------------------


class TestResolveTenant:
    @pytest.mark.asyncio
    async def test_resolve_success(self):
        from bot.core.tenancy import TenantContext

        tc = TenantContext(tenant_id="t1", user_id="u1", channel="telegram")
        mock_db = Mock()
        mock_db.is_initialized = Mock(return_value=True)

        with patch("utils.request_processor.get_service", return_value=mock_db):
            with _mock_tenancy_resolve(tc):
                proc = RequestProcessor(user_identifier=123, source="telegram")
                result = await proc._resolve_tenant()

        assert result is not None
        assert result.tenant_id == "t1"

    @pytest.mark.asyncio
    async def test_resolve_no_db(self):
        with patch("utils.request_processor.get_service", return_value=None):
            proc = RequestProcessor(user_identifier=1)
            result = await proc._resolve_tenant()
        assert result is None


# -------------------------------------------------------------------
# Full pipeline: process()
# -------------------------------------------------------------------


class TestProcess:
    @pytest.mark.asyncio
    async def test_process_full_pipeline(self):
        user_data = {
            "user_id": "u1",
            "telegram_chat_id": 100,
            "full_name": "Test",
        }
        from bot.core.tenancy import TenantContext

        tc = TenantContext(tenant_id="t1", user_id="u1", channel="telegram")

        mock_db = _mock_db_service(user_data)

        with patch("utils.request_processor.get_service", return_value=mock_db):
            with _mock_tenancy_resolve(tc):
                with patch("utils.request_processor.structlog.contextvars"):
                    proc = RequestProcessor(user_identifier=100)
                    result = await proc.process()

        assert result is True
        assert proc.request_id is not None
        assert proc.user_context is not None
        assert proc.tenant_context is not None

    @pytest.mark.asyncio
    async def test_process_rate_limited(self):
        with patch("utils.request_processor.structlog.contextvars"):
            proc1 = RequestProcessor(user_identifier=500)
            with patch("utils.request_processor.get_service", return_value=None):
                await proc1.process()  # first call OK

            proc2 = RequestProcessor(user_identifier=500)
            result = await proc2.process()
            assert result is False


# -------------------------------------------------------------------
# FastAPI dependency
# -------------------------------------------------------------------


class TestGetRequestProcessor:
    @pytest.mark.asyncio
    async def test_dependency_success(self):
        from utils.request_processor import get_request_processor

        with patch("utils.request_processor.get_service", return_value=None):
            with patch("utils.request_processor.structlog.contextvars"):
                processor = await get_request_processor(current_user={"id": "uid"})
        assert processor is not None
        assert processor.request_id is not None

    @pytest.mark.asyncio
    async def test_dependency_rate_limited(self):
        from utils.request_processor import get_request_processor
        from fastapi import HTTPException

        user = {"id": "rate_test_user"}
        user_id_hash = hash(user["id"])

        # Pre-fill the rate limiter
        rp_module._user_last_message_time[user_id_hash] = time.time()

        with patch("utils.request_processor.get_service", return_value=None):
            with patch("utils.request_processor.structlog.contextvars"):
                with pytest.raises(HTTPException) as exc_info:
                    await get_request_processor(current_user=user)
                assert exc_info.value.status_code == 429
