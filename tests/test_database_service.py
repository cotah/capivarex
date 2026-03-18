"""
Unit tests for DatabaseService — Supabase client wrapper.
"""

from unittest.mock import Mock, patch, MagicMock

import pytest


def _make_service():
    """Create a DatabaseService with mocked Supabase client."""
    from services.infrastructure.database import DatabaseService

    svc = DatabaseService()
    svc.url = "https://fake.supabase.co"
    svc.key = "fake-key"
    svc._initialized = True

    # Build a chain-able Supabase mock
    svc.client = MagicMock()
    return svc


def _chain_result(data):
    """Return an execute() result with .data attribute."""
    result = Mock()
    result.data = data
    return result


# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_init_missing_url():
    """DatabaseService raises on missing SUPABASE_URL."""
    from services.infrastructure.database import DatabaseService
    from services.core import ServiceConfigurationError

    svc = DatabaseService()
    with patch.dict(
        "os.environ", {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": "key"}, clear=False
    ):
        with pytest.raises(ServiceConfigurationError, match="SUPABASE_URL"):
            await svc._initialize()


@pytest.mark.asyncio
async def test_db_get_all_users():
    """get_all_users_with_preferences filters by proactivity enabled."""
    svc = _make_service()

    users = [
        {
            "id": "1",
            "proactivity_preferences": {"enabled": True},
            "telegram_chat_id": "123",
        },
        {
            "id": "2",
            "proactivity_preferences": {"enabled": False},
            "telegram_chat_id": "456",
        },
        {"id": "3", "proactivity_preferences": {}, "telegram_chat_id": "789"},
    ]

    svc.client.table.return_value.select.return_value.neq.return_value.execute.return_value = _chain_result(
        users
    )

    result = await svc.get_all_users_with_preferences()
    assert len(result) == 1
    assert result[0]["id"] == "1"


@pytest.mark.asyncio
async def test_db_get_user_by_telegram_id():
    """get_user_by_telegram_id returns matching user."""
    svc = _make_service()

    user = {"id": "1", "telegram_chat_id": "123", "full_name": "Test"}
    svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
        [user]
    )

    result = await svc.get_user_by_telegram_id("123")
    assert result is not None
    assert result["full_name"] == "Test"


@pytest.mark.asyncio
async def test_db_health_check():
    """Health check returns True with valid client."""
    svc = _make_service()
    svc.client.table.return_value.select.return_value.limit.return_value.execute.return_value = _chain_result(
        [{"id": "1"}]
    )

    result = await svc._health_check()
    assert result is True
