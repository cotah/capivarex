"""Unit tests for BaseService, retry_on_failure, and related helpers."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from services.core.base_service import (
    BaseService,
    ServiceStatus,
    ServiceConfigurationError,
    _is_retryable,
    retry_on_failure,
)


# -- Concrete service for testing --

class _StubService(BaseService):
    """Minimal concrete service for testing BaseService behaviour."""

    def __init__(self, healthy=True, init_fail=False):
        super().__init__(name="stub_svc")
        self._healthy = healthy
        self._init_fail = init_fail

    async def _initialize(self):
        if self._init_fail:
            raise RuntimeError("init boom")

    async def _health_check(self):
        return self._healthy


# -- ServiceStatus --

class TestServiceStatus:
    def test_values(self):
        assert ServiceStatus.HEALTHY.value == "healthy"
        assert ServiceStatus.DEGRADED.value == "degraded"
        assert ServiceStatus.UNHEALTHY.value == "unhealthy"
        assert ServiceStatus.UNKNOWN.value == "unknown"


# -- BaseService lifecycle --

class TestBaseServiceLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_success(self):
        svc = _StubService()
        await svc.initialize()
        assert svc.is_initialized()
        assert svc.is_healthy()
        assert svc._status == ServiceStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_initialize_failure(self):
        svc = _StubService(init_fail=True)
        with pytest.raises(ServiceConfigurationError):
            await svc.initialize()
        assert not svc.is_initialized()
        assert svc._status == ServiceStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_double_initialize_skipped(self):
        svc = _StubService()
        await svc.initialize()
        # Second call should be no-op (logged as warning)
        await svc.initialize()
        assert svc.is_initialized()

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        svc = _StubService(healthy=True)
        status = await svc.health_check()
        assert status == ServiceStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_degraded(self):
        svc = _StubService(healthy=False)
        status = await svc.health_check()
        assert status == ServiceStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        svc = _StubService()
        svc._health_check = AsyncMock(side_effect=RuntimeError("check fail"))
        status = await svc.health_check()
        assert status == ServiceStatus.UNHEALTHY


# -- BaseService utilities --

class TestBaseServiceUtilities:
    def test_get_metrics_default(self):
        svc = _StubService()
        m = svc.get_metrics()
        assert m["name"] == "stub_svc"
        assert m["status"] == "unknown"
        assert m["initialized"] is False
        assert m["call_count"] == 0

    def test_track_call(self):
        svc = _StubService()
        svc._track_call(0.5, error=False)
        svc._track_call(1.0, error=True)
        m = svc.get_metrics()
        assert m["call_count"] == 2
        assert m["error_count"] == 1
        assert m["error_rate"] == 0.5

    def test_get_config_default(self):
        svc = _StubService()
        assert svc._get_config("missing") is None
        assert svc._get_config("missing", default=42) == 42

    def test_get_config_required_raises(self):
        svc = _StubService()
        with pytest.raises(ServiceConfigurationError, match="missing"):
            svc._get_config("missing", required=True)

    def test_get_config_present(self):
        svc = BaseService.__new__(_StubService)
        svc.config = {"key": "val"}
        assert svc._get_config("key") == "val"


# -- _is_retryable --

class TestIsRetryable:
    def test_timeout_error_retryable(self):
        assert _is_retryable(asyncio.TimeoutError()) is True

    def test_generic_exception_not_retryable(self):
        assert _is_retryable(ValueError("bad")) is False

    def test_runtime_error_not_retryable(self):
        assert _is_retryable(RuntimeError("nope")) is False


# -- retry_on_failure --

class TestRetryOnFailure:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        @retry_on_failure(max_retries=3)
        async def good():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await good()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self):
        call_count = 0

        @retry_on_failure(max_retries=3)
        async def bad():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await bad()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retryable_error_retries(self):
        call_count = 0

        @retry_on_failure(max_retries=2, backoff_factor=0.01)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise asyncio.TimeoutError()
            return "recovered"

        with patch("services.core.base_service.asyncio.sleep", new_callable=AsyncMock):
            result = await flaky()
        assert result == "recovered"
        assert call_count == 3
