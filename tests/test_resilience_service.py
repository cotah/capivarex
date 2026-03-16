"""Tests for resilience service — Supabase outage protection."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.infrastructure.resilience_service import (
    resilient_query,
    cache_set,
    cache_get,
    cache_delete,
    get_user_resilient,
    get_proactivity_users_resilient,
    is_supabase_healthy,
    get_resilience_status,
    _mark_supabase_down,
    _mark_supabase_up,
)


class TestResilienceStatus:
    """Tests for health tracking."""

    def test_initial_state_healthy(self):
        _mark_supabase_up()
        assert is_supabase_healthy() is True

    def test_mark_down_after_3_failures(self):
        _mark_supabase_up()  # Reset
        _mark_supabase_down()
        _mark_supabase_down()
        assert is_supabase_healthy() is True  # Still healthy (only 2)
        _mark_supabase_down()
        assert is_supabase_healthy() is False  # Now down (3)
        _mark_supabase_up()  # Cleanup

    def test_mark_up_resets(self):
        _mark_supabase_down()
        _mark_supabase_down()
        _mark_supabase_down()
        _mark_supabase_up()
        assert is_supabase_healthy() is True
        status = get_resilience_status()
        assert status["mode"] == "normal"
        assert status["consecutive_failures"] == 0


class TestCacheOperations:
    """Tests for Redis cache get/set/delete."""

    @pytest.mark.asyncio
    async def test_cache_set_no_redis(self):
        with patch("services.infrastructure.resilience_service.get_service", return_value=None):
            result = await cache_set("test_key", {"data": "value"})
        assert result is False

    @pytest.mark.asyncio
    async def test_cache_get_no_redis(self):
        with patch("services.infrastructure.resilience_service.get_service", return_value=None):
            result = await cache_get("test_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_set_and_get(self):
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value={"data": "cached_value"})

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            ok = await cache_set("test_key", {"data": "cached_value"})
            assert ok is True

            result = await cache_get("test_key")
            assert result == {"data": "cached_value"}

    @pytest.mark.asyncio
    async def test_cache_delete_no_redis(self):
        with patch("services.infrastructure.resilience_service.get_service", return_value=None):
            result = await cache_delete("test_key")
        assert result is False


class TestResilientQuery:
    """Tests for the main resilient_query wrapper."""

    @pytest.mark.asyncio
    async def test_supabase_success_caches(self):
        """When Supabase works, data is cached and returned."""
        _mark_supabase_up()

        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock()

        async def supabase_fn():
            return {"id": "user-1", "name": "Marcos"}

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            result = await resilient_query("user:1", supabase_fn)

        assert result == {"id": "user-1", "name": "Marcos"}
        assert is_supabase_healthy() is True

    @pytest.mark.asyncio
    async def test_supabase_fails_serves_cache(self):
        """When Supabase fails, serves from Redis cache."""
        _mark_supabase_up()

        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.get = AsyncMock(return_value={"id": "user-1", "name": "Marcos (cached)"})

        async def supabase_fn():
            raise ConnectionError("Supabase down")

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            result = await resilient_query("user:1", supabase_fn)

        assert result is not None
        assert "cached" in result["name"]

    @pytest.mark.asyncio
    async def test_both_fail_returns_none(self):
        """When both Supabase and Redis fail, returns None."""
        _mark_supabase_up()

        with patch("services.infrastructure.resilience_service.get_service", return_value=None):
            async def supabase_fn():
                raise ConnectionError("Supabase down")

            result = await resilient_query("user:1", supabase_fn)

        assert result is None

    @pytest.mark.asyncio
    async def test_supabase_none_not_cached_by_default(self):
        """None results are not cached by default."""
        _mark_supabase_up()

        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock()

        async def supabase_fn():
            return None

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            result = await resilient_query("user:missing", supabase_fn)

        assert result is None
        mock_redis.set.assert_not_called()


class TestResilientOperations:
    """Tests for pre-built resilient operations."""

    @pytest.mark.asyncio
    async def test_get_user_no_db(self):
        with patch("services.infrastructure.resilience_service.get_service", return_value=None):
            result = await get_user_resilient("user-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_proactivity_users_no_db(self):
        with patch("services.infrastructure.resilience_service.get_service", return_value=None):
            result = await get_proactivity_users_resilient()
        assert result == []


class TestResilientQueryEdgeCases:
    """Extra coverage for resilient_query."""

    @pytest.mark.asyncio
    async def test_cache_empty_result_when_flag_set(self):
        """cache_empty=True caches None results."""
        _mark_supabase_up()
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock()

        async def supabase_fn():
            return None

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            result = await resilient_query("key", supabase_fn, cache_empty=True)
        assert result is None
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_resilient_with_db(self):
        """get_user_resilient uses resilient_query."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_id = AsyncMock(return_value={"id": "u1", "name": "Marcos"})

        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock()

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "redis":
                return mock_redis
            return None

        _mark_supabase_up()
        with patch("services.infrastructure.resilience_service.get_service", fake_svc):
            result = await get_user_resilient("u1")
        # Result comes from db.get_user_by_id (which itself uses resilient_query)
        assert result is not None

    @pytest.mark.asyncio
    async def test_resilience_status_degraded(self):
        """Status shows degraded when Supabase is down."""
        _mark_supabase_up()
        _mark_supabase_down()
        _mark_supabase_down()
        _mark_supabase_down()
        status = get_resilience_status()
        assert status["mode"] == "degraded"
        assert status["consecutive_failures"] >= 3
        _mark_supabase_up()  # Cleanup


class TestSafeTask:
    """Tests for utils/safe_task.py."""

    @pytest.mark.asyncio
    async def test_safe_task_success(self):
        from utils.safe_task import safe_create_task

        result = []
        async def _work():
            result.append("done")

        task = safe_create_task(_work(), name="test_success")
        await task
        assert result == ["done"]

    @pytest.mark.asyncio
    async def test_safe_task_logs_exception(self):
        from utils.safe_task import safe_create_task
        import asyncio

        async def _fail():
            raise ValueError("test error")

        task = safe_create_task(_fail(), name="test_fail")
        # Wait for the task to complete (it will fail)
        await asyncio.sleep(0.1)
        assert task.done()

    @pytest.mark.asyncio
    async def test_safe_task_cancelled(self):
        from utils.safe_task import safe_create_task
        import asyncio

        async def _slow():
            await asyncio.sleep(10)

        task = safe_create_task(_slow(), name="test_cancel")
        task.cancel()
        await asyncio.sleep(0.05)
        assert task.cancelled() or task.done()


class TestCacheProactiveCaching:
    """Tests for proactive caching functions."""

    @pytest.mark.asyncio
    async def test_cache_user_on_login(self):
        from services.infrastructure.resilience_service import cache_user_on_login
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock()

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            await cache_user_on_login("u1", {"id": "u1", "name": "Marcos"})
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_auth_token(self):
        from services.infrastructure.resilience_service import cache_auth_token
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock()

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            await cache_auth_token("u1", {"token": "abc"})
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_auth_cached(self):
        from services.infrastructure.resilience_service import get_auth_cached
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.get = AsyncMock(return_value={"token": "abc"})

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            result = await get_auth_cached("u1")
        assert result == {"token": "abc"}

    @pytest.mark.asyncio
    async def test_cache_delete_success(self):
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.delete = AsyncMock()

        with patch("services.infrastructure.resilience_service.get_service", return_value=mock_redis):
            result = await cache_delete("test_key")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_proactivity_users_with_db(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_all_users_with_proactivity_enabled = AsyncMock(return_value=[{"user_id": "u1"}])

        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.set = AsyncMock()

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "redis":
                return mock_redis
            return None

        _mark_supabase_up()
        with patch("services.infrastructure.resilience_service.get_service", fake_svc):
            result = await get_proactivity_users_resilient()
        assert len(result) == 1
