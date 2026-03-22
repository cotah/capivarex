# tests/unit/test_module_access.py
"""Unit tests for the capivara module access system."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from capivarex_modules.config import (
    CAPIVARA_MODULES,
    AGENT_TO_MODULE,
    get_module_for_agent,
    is_core_agent,
)
from capivarex_modules.access_service import ModuleAccessService, ModuleAccessResult


class TestModuleConfig:
    def test_all_active_agents_have_module(self):
        """Every agent in ALLOWED_AGENTS must belong to a module."""
        allowed_agents = {
            "chat", "calendar", "email_summary", "email_management", "meeting", "notes", "reminder",
            "research", "search", "voice", "translate", "tracking", "finance",
            "weather", "timer", "maps"
        }
        for agent in allowed_agents:
            module = get_module_for_agent(agent)
            assert module in CAPIVARA_MODULES, f"Agent '{agent}' has no module"

    def test_ara_is_always_included(self):
        assert CAPIVARA_MODULES["ara"]["always_included"] is True

    def test_other_modules_not_always_included(self):
        for name, config in CAPIVARA_MODULES.items():
            if name != "ara":
                assert config["always_included"] is False, f"{name} should not be always_included"

    def test_core_agents_bypass_check(self):
        assert is_core_agent("chat") is True
        assert is_core_agent("orchestrator") is True
        assert is_core_agent("finance") is False

    def test_agent_to_module_reverse_lookup(self):
        assert AGENT_TO_MODULE["calendar"] == "ara"
        assert AGENT_TO_MODULE["finance"] == "ivi"
        assert AGENT_TO_MODULE["smarthome"] == "oka"
        assert AGENT_TO_MODULE["travel"] == "yara"
        assert AGENT_TO_MODULE["twilio"] == "ayvu"
        assert AGENT_TO_MODULE["email_summary"] == "ara"
        assert AGENT_TO_MODULE["email_management"] == "mbae"
        assert AGENT_TO_MODULE["image"] == "pora"

    def test_all_8_modules_exist(self):
        expected = {"ara", "ivi", "oka", "yara", "ayvu", "mbae", "pora"}
        assert set(CAPIVARA_MODULES.keys()) == expected

    def test_each_module_has_required_fields(self):
        required = {"name", "full_name", "description", "color", "emoji", "status", "always_included", "agents"}
        for name, config in CAPIVARA_MODULES.items():
            for field in required:
                assert field in config, f"Module '{name}' missing field '{field}'"

    def test_unknown_agent_defaults_to_ara(self):
        assert get_module_for_agent("nonexistent_agent") == "ara"


class TestModuleAccessService:
    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.get_client.return_value = MagicMock()
        return db

    @pytest.fixture
    def access_service(self, mock_db):
        return ModuleAccessService(db_service=mock_db, redis_service=None)

    @pytest.mark.asyncio
    async def test_ara_agents_always_allowed(self, access_service):
        result = await access_service.check_agent_access("user-123", "calendar")
        assert result.allowed is True
        assert result.reason == "always_included"

    @pytest.mark.asyncio
    async def test_core_agents_always_allowed(self, access_service):
        result = await access_service.check_agent_access("user-123", "chat")
        assert result.allowed is True
        assert result.reason == "core_agent"

    @pytest.mark.asyncio
    async def test_orchestrator_always_allowed(self, access_service):
        result = await access_service.check_agent_access("user-123", "orchestrator")
        assert result.allowed is True
        assert result.reason == "core_agent"

    @pytest.mark.asyncio
    async def test_locked_module_returns_upgrade_message(self, access_service):
        # Mock DB returning no access
        client = access_service._db.get_client.return_value
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        result = await access_service.check_agent_access("user-123", "finance")
        assert result.allowed is False
        assert result.module_name == "ivi"
        assert result.upgrade_message is not None
        assert "IVI" in result.upgrade_message

    @pytest.mark.asyncio
    async def test_disabled_module_returns_disabled_reason(self, access_service):
        result = await access_service.check_agent_access("user-123", "image")
        assert result.allowed is False
        assert result.reason == "module_disabled"

    @pytest.mark.asyncio
    async def test_subscribed_module_allowed(self, access_service):
        # Mock DB returning active subscription
        client = access_service._db.get_client.return_value
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"status": "active"}
        ]

        result = await access_service.check_agent_access("user-123", "finance")
        assert result.allowed is True
        assert result.reason == "subscription_active"

    @pytest.mark.asyncio
    async def test_cancelled_module_not_allowed(self, access_service):
        # Mock DB returning cancelled subscription
        client = access_service._db.get_client.return_value
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"status": "cancelled"}
        ]

        result = await access_service.check_agent_access("user-123", "finance")
        assert result.allowed is False

    def test_module_access_result_to_dict(self):
        result = ModuleAccessResult(
            allowed=True,
            reason="always_included",
            module_name="ara",
            agent_name="calendar",
        )
        d = result.to_dict()
        assert d["allowed"] is True
        assert d["reason"] == "always_included"
        assert d["module_name"] == "ara"
        assert d["agent_name"] == "calendar"
        assert d["upgrade_message"] is None

    @pytest.mark.asyncio
    async def test_all_ara_agents_pass(self, access_service):
        """Every agent in ARA module should be allowed without subscription."""
        ara_agents = CAPIVARA_MODULES["ara"]["agents"]
        for agent in ara_agents:
            result = await access_service.check_agent_access("user-123", agent)
            assert result.allowed is True, f"ARA agent '{agent}' should be allowed"


class TestModuleAccessServiceWithRedis:
    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        return redis

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.get_client.return_value = MagicMock()
        return db

    @pytest.fixture
    def access_service(self, mock_db, mock_redis):
        return ModuleAccessService(db_service=mock_db, redis_service=mock_redis)

    @pytest.mark.asyncio
    async def test_redis_cache_hit(self, access_service, mock_redis):
        """When Redis has cached '1', skip DB query."""
        mock_redis.get = AsyncMock(return_value="1")

        result = await access_service.check_agent_access("user-123", "finance")
        assert result.allowed is True
        assert result.reason == "subscription_active"

    @pytest.mark.asyncio
    async def test_redis_cache_miss_queries_db(self, access_service, mock_redis, mock_db):
        """When Redis returns None, query DB and cache result."""
        mock_redis.get = AsyncMock(return_value=None)
        client = mock_db.get_client.return_value
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        result = await access_service.check_agent_access("user-123", "finance")
        assert result.allowed is False
        # Should have cached the result
        mock_redis.set.assert_called_once()
