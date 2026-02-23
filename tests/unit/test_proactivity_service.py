"""Unit tests for ProactivityService."""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, Mock, patch

from services.business.proactivity_service import ProactivityService


def _make_redis_mock():
    """Build an async Redis mock that mimics RedisService get/set API."""
    store = {}

    async def _get(key):
        return store.get(key)

    async def _set(key, value, expire_seconds=None):
        store[key] = value
        return True

    mock = Mock()
    mock.get = _get
    mock.set = _set
    mock._store = store
    return mock


def _make_service():
    """Build a ProactivityService with mocked clients."""
    svc = ProactivityService()
    svc._initialized = True
    svc._openai_client = Mock()
    svc._redis_client = _make_redis_mock()
    return svc


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_with_services(self):
        mock_openai = Mock()
        mock_openai.is_initialized.return_value = True
        mock_openai.get_client.return_value = Mock()

        mock_redis = Mock()
        mock_redis.is_initialized.return_value = True

        def _get(name):
            if name == "openai":
                return mock_openai
            if name == "redis":
                return mock_redis
            return None

        with patch("services.business.proactivity_service.get_service", side_effect=_get):
            svc = ProactivityService()
            await svc._initialize()
        assert svc._openai_client is not None
        assert svc._redis_client is not None

    @pytest.mark.asyncio
    async def test_initialize_without_services(self):
        with patch("services.business.proactivity_service.get_service", return_value=None):
            svc = ProactivityService()
            await svc._initialize()
        assert svc._openai_client is None
        assert svc._redis_client is None

    @pytest.mark.asyncio
    async def test_initialize_exception_handling(self):
        with patch("services.business.proactivity_service.get_service", side_effect=RuntimeError("boom")):
            svc = ProactivityService()
            await svc._initialize()
        assert svc._openai_client is None
        assert svc._redis_client is None


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_with_openai(self):
        svc = _make_service()
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_unhealthy_without_openai(self):
        svc = _make_service()
        svc._openai_client = None
        assert await svc._health_check() is False


class TestImmediate:
    @pytest.mark.asyncio
    async def test_immediate_returns_value(self):
        result = await ProactivityService._immediate("hello")
        assert result == "hello"


class TestGatherContext:
    @pytest.mark.asyncio
    async def test_gather_context_all_services_unavailable(self):
        """When all services are None, gather returns empty/default context."""
        from schemas.context import UserContext

        svc = _make_service()
        ctx = UserContext(
            user_id="u1", telegram_chat_id=123, full_name="Test",
            permissions=["calendar", "weather", "car", "finance", "traffic"],
        )

        with patch("services.business.proactivity_service.get_service", return_value=None):
            result = await svc.gather_context(ctx)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_gather_context_timeout_handled(self):
        """Context gathering should handle asyncio.TimeoutError gracefully."""
        from schemas.context import UserContext

        svc = _make_service()
        ctx = UserContext(
            user_id="u1", telegram_chat_id=123, full_name="Test",
        )

        with patch("services.business.proactivity_service.get_service", return_value=None):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
                result = await svc.gather_context(ctx)
        assert isinstance(result, dict)


class TestIsNotificationAllowed:
    @pytest.mark.asyncio
    async def test_allowed_no_redis(self):
        svc = _make_service()
        svc._redis_client = None
        result = await svc.is_notification_allowed("u1", "test insight")
        assert result is True

    @pytest.mark.asyncio
    async def test_rate_limited(self):
        """When 5+ recent timestamps exist, notification is blocked."""
        svc = _make_service()
        now = time.time()
        # Pre-populate frequency key with 5 recent timestamps
        valid_timestamps = [now - 60 * i for i in range(5)]
        svc._redis_client._store["proactive_freq:u1"] = valid_timestamps
        result = await svc.is_notification_allowed("u1", "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_not_rate_limited(self):
        """When fewer than 5 recent timestamps, notification is allowed."""
        svc = _make_service()
        now = time.time()
        svc._redis_client._store["proactive_freq:u1"] = [now - 60]
        result = await svc.is_notification_allowed("u1", "test")
        assert result is True

    @pytest.mark.asyncio
    async def test_duplicate_blocked(self):
        """When duplicate hash key exists, notification is blocked."""
        import hashlib
        svc = _make_service()
        insight = "same insight"
        insight_hash = hashlib.md5(insight.encode()).hexdigest()
        svc._redis_client._store[f"proactive_rep:u1:{insight_hash}"] = 1
        result = await svc.is_notification_allowed("u1", insight)
        assert result is False


class TestRecordNotificationSent:
    @pytest.mark.asyncio
    async def test_record_with_redis(self):
        import hashlib
        svc = _make_service()
        await svc.record_notification_sent("u1", "test insight")
        # Verify frequency key was set
        assert "proactive_freq:u1" in svc._redis_client._store
        timestamps = svc._redis_client._store["proactive_freq:u1"]
        assert isinstance(timestamps, list)
        assert len(timestamps) == 1
        # Verify dedup key was set
        insight_hash = hashlib.md5("test insight".encode()).hexdigest()
        assert f"proactive_rep:u1:{insight_hash}" in svc._redis_client._store

    @pytest.mark.asyncio
    async def test_record_no_redis(self):
        svc = _make_service()
        svc._redis_client = None
        # Should not raise even without Redis
        await svc.record_notification_sent("u1", "test")


class TestAnalyzeContext:
    @pytest.mark.asyncio
    async def test_no_openai_client(self):
        svc = _make_service()
        svc._openai_client = None
        result = await svc.analyze_context_for_insights({})
        assert result == ""

    @pytest.mark.asyncio
    async def test_analyze_success(self):
        svc = _make_service()
        mock_resp = Mock()
        mock_resp.choices = [Mock()]
        mock_resp.choices[0].message = Mock(content="Good morning! Here's your briefing.")
        svc._openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await svc.analyze_context_for_insights({"weather": {"temp": 20}})
        assert "briefing" in result.lower()

    @pytest.mark.asyncio
    async def test_analyze_silencio(self):
        svc = _make_service()
        mock_resp = Mock()
        mock_resp.choices = [Mock()]
        mock_resp.choices[0].message = Mock(content="[SILENCIO]")
        svc._openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await svc.analyze_context_for_insights({})
        assert result == ""

    @pytest.mark.asyncio
    async def test_analyze_exception(self):
        svc = _make_service()
        svc._openai_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

        result = await svc.analyze_context_for_insights({})
        assert result == ""


class TestGetCarStatus:
    @pytest.mark.asyncio
    async def test_no_services(self):
        svc = _make_service()
        with patch("services.business.proactivity_service.get_service", return_value=None):
            result = await svc._get_car_status("u1")
        assert result["connected"] is False

    @pytest.mark.asyncio
    async def test_no_vehicle(self):
        svc = _make_service()
        mock_vdb = AsyncMock()
        mock_vdb.get_primary_vehicle = AsyncMock(return_value=None)
        mock_car = Mock()

        def _get(name):
            if name == "vehicle_db":
                return mock_vdb
            if name == "car":
                return mock_car
            return None

        with patch("services.business.proactivity_service.get_service", side_effect=_get):
            result = await svc._get_car_status("u1")
        assert result["connected"] is False


class TestBuildSmartthingsMessage:
    def test_light_issues(self):
        svc = _make_service()
        issues = [{"type": "light_on", "label": "Living Room"}]
        msg = svc._build_smartthings_message(issues)
        assert "Living Room" in msg
        assert "luz" in msg.lower()

    def test_door_issues(self):
        svc = _make_service()
        issues = [{"type": "door_unlocked", "label": "Front Door"}]
        msg = svc._build_smartthings_message(issues)
        assert "Front Door" in msg
        assert "porta" in msg.lower()

    def test_temperature_issues(self):
        svc = _make_service()
        issues = [{"type": "temperature_issue", "label": "Bedroom", "temperature": 35}]
        msg = svc._build_smartthings_message(issues)
        assert "Bedroom" in msg
        assert "temperatura" in msg.lower()

    def test_mixed_issues(self):
        svc = _make_service()
        issues = [
            {"type": "light_on", "label": "Kitchen"},
            {"type": "door_unlocked", "label": "Garage"},
            {"type": "temperature_issue", "label": "Office", "temperature": 30},
        ]
        msg = svc._build_smartthings_message(issues)
        assert "Kitchen" in msg
        assert "Garage" in msg
        assert "Office" in msg

    def test_empty_issues(self):
        svc = _make_service()
        msg = svc._build_smartthings_message([])
        assert msg == ""


class TestGatherContextPreferences:
    @pytest.mark.asyncio
    async def test_prefs_exception_falls_back_to_empty(self):
        """When get_preferences raises, prefs defaults to {} and location to Dublin."""
        from schemas.context import UserContext

        svc = _make_service()
        ctx = UserContext(user_id="u1", telegram_chat_id=123, full_name="Test")

        with (
            patch("services.business.proactivity_service.get_service", return_value=None),
            patch(
                "services.business.proactivity_service.get_preferences",
                new=AsyncMock(side_effect=Exception("boom")),
            ),
        ):
            result = await svc.gather_context(ctx)
        assert result.get("preferences") == {}

    @pytest.mark.asyncio
    async def test_prefs_preferred_city_used(self):
        """When prefs has preferred_city, it is used and home_location is injected."""
        from schemas.context import UserContext

        svc = _make_service()
        ctx = UserContext(user_id="u1", telegram_chat_id=123, full_name="Test")
        prefs = {
            "preferred_city": "Lisboa",
            "home_latitude": 38.7,
            "home_longitude": -9.1,
        }

        with (
            patch("services.business.proactivity_service.get_service", return_value=None),
            patch(
                "services.business.proactivity_service.get_preferences",
                new=AsyncMock(return_value=prefs),
            ),
        ):
            result = await svc.gather_context(ctx)
        assert result["preferences"]["preferred_city"] == "Lisboa"
        assert "home_location" in result
        assert result["home_location"]["latitude"] == 38.7

    @pytest.mark.asyncio
    async def test_prefs_work_coordinates_injected(self):
        """When prefs has work coordinates, context gets work_location."""
        from schemas.context import UserContext

        svc = _make_service()
        ctx = UserContext(user_id="u1", telegram_chat_id=123, full_name="Test")
        prefs = {"work_latitude": 38.72, "work_longitude": -9.15}

        with (
            patch("services.business.proactivity_service.get_service", return_value=None),
            patch(
                "services.business.proactivity_service.get_preferences",
                new=AsyncMock(return_value=prefs),
            ),
        ):
            result = await svc.gather_context(ctx)
        assert "work_location" in result
        assert result["work_location"]["latitude"] == 38.72


class TestGetProactivityService:
    def test_singleton_getter(self):
        with patch("services.business.proactivity_service.get_service", return_value=None):
            from services.business.proactivity_service import get_proactivity_service
            svc = get_proactivity_service()
            assert isinstance(svc, ProactivityService)
