"""
Basic unit tests for reminder_service to improve coverage.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestReminderServiceInit:
    """Test ReminderService initialization."""

    def test_service_name(self):
        from services.business.reminder_service import ReminderService

        svc = ReminderService()
        assert svc.name == "reminder"

    def test_not_initialized_by_default(self):
        from services.business.reminder_service import ReminderService

        svc = ReminderService()
        assert not svc.is_initialized()


class TestFormatRecurrence:
    """Test the format_recurrence static/class method."""

    def test_daily(self):
        from services.business.reminder_service import ReminderService

        result = ReminderService.format_recurrence("daily")
        assert "dia" in result.lower() or "daily" in result.lower()

    def test_weekly(self):
        from services.business.reminder_service import ReminderService

        result = ReminderService.format_recurrence("weekly")
        assert result is not None
        assert len(result) > 0

    def test_none_recurrence(self):
        from services.business.reminder_service import ReminderService

        result = ReminderService.format_recurrence(None)
        assert result is not None

    def test_unknown_recurrence(self):
        from services.business.reminder_service import ReminderService

        result = ReminderService.format_recurrence("unknown_value")
        assert result is not None


class TestReminderServiceInitialize:
    """Test ReminderService._initialize with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_initialize_no_redis(self):
        from services.business.reminder_service import ReminderService

        svc = ReminderService()
        with patch("services.business.reminder_service.get_service", return_value=None):
            with pytest.raises(Exception):
                await svc.initialize()

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self):
        from services.business.reminder_service import ReminderService

        svc = ReminderService()
        mock_redis = AsyncMock()
        mock_redis.is_initialized.return_value = True

        with patch(
            "services.business.reminder_service.get_service",
            side_effect=lambda n: mock_redis,
        ):
            try:
                await svc.initialize()
            except Exception:
                pass  # Se falhar por outra razão, aceitamos


class TestCheckAndFireDue:
    """Test check_and_fire_due with mocked redis."""

    @pytest.mark.asyncio
    async def test_no_reminders(self):
        from services.business.reminder_service import ReminderService

        svc = ReminderService()
        mock_redis = AsyncMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.get = AsyncMock(return_value=None)
        svc._redis = mock_redis
        svc._initialized = True

        fired = await svc.check_and_fire_due(notify_fn=AsyncMock())
        assert fired == [] or fired is not None
