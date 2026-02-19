"""Unit tests for ServiceRegistry."""

import pytest
from services.core.base_service import BaseService, ServiceStatus
from services.core.service_registry import ServiceRegistry


class _DummyService(BaseService):
    def __init__(self, name="dummy", config=None):
        super().__init__(name, config)

    async def _initialize(self):
        pass

    async def _health_check(self):
        return True


class _NotAService:
    pass


@pytest.fixture
def fresh_registry():
    """Return a fresh ServiceRegistry (bypass singleton)."""
    reg = object.__new__(ServiceRegistry)
    reg._services = {}
    reg._service_classes = {}
    reg._initialized = True
    return reg


class TestServiceRegistryRegister:
    def test_register_lazy(self, fresh_registry):
        fresh_registry.register("dummy", _DummyService, lazy=True)
        assert "dummy" in fresh_registry.list_services()
        assert "dummy" not in fresh_registry._services

    def test_register_eager(self, fresh_registry):
        fresh_registry.register("dummy", _DummyService, lazy=False)
        assert "dummy" in fresh_registry._services

    def test_register_non_service_raises(self, fresh_registry):
        with pytest.raises(TypeError):
            fresh_registry.register("bad", _NotAService)


class TestServiceRegistryGet:
    def test_get_lazy_loads(self, fresh_registry):
        fresh_registry.register("dummy", _DummyService, lazy=True)
        svc = fresh_registry.get("dummy")
        assert isinstance(svc, _DummyService)
        assert fresh_registry.get("dummy") is svc

    def test_get_missing_returns_none(self, fresh_registry):
        assert fresh_registry.get("nope") is None


class TestServiceRegistryOther:
    def test_list_services(self, fresh_registry):
        fresh_registry.register("a", _DummyService)
        fresh_registry.register("b", _DummyService)
        assert sorted(fresh_registry.list_services()) == ["a", "b"]

    def test_clear(self, fresh_registry):
        fresh_registry.register("a", _DummyService, lazy=False)
        fresh_registry.clear()
        assert fresh_registry.list_services() == []

    def test_get_all_metrics(self, fresh_registry):
        fresh_registry.register("dummy", _DummyService, lazy=False)
        metrics = fresh_registry.get_all_metrics()
        assert "dummy" in metrics

    @pytest.mark.asyncio
    async def test_health_check_all(self, fresh_registry):
        fresh_registry.register("dummy", _DummyService, lazy=False)
        results = await fresh_registry.health_check_all()
        assert results["dummy"] == ServiceStatus.HEALTHY
