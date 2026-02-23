"""Unit tests for user_preferences_service."""

import pytest
from unittest.mock import MagicMock, Mock, patch

MODULE = "services.business.user_preferences_service"


def _chain(data):
    """Build a mock result with .data attribute."""
    result = Mock()
    result.data = data
    return result


def _mock_table_chain(return_data):
    """Build a chainable mock: table().select().eq().maybe_single().execute()."""
    chain = MagicMock()
    chain.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.single.return_value = chain
    chain.insert.return_value = chain
    chain.upsert.return_value = chain
    chain.execute.return_value = _chain(return_data)
    return chain


class TestGetPreferences:
    @pytest.mark.asyncio
    async def test_db_unavailable_returns_empty(self):
        """get_preferences returns {} when get_supabase_client raises."""
        with patch(f"{MODULE}.get_supabase_client", side_effect=Exception("no db")):
            from services.business.user_preferences_service import get_preferences

            result = await get_preferences("user123")
        assert result == {}

    @pytest.mark.asyncio
    async def test_db_returns_none_client(self):
        """get_preferences returns {} when client is None."""
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.user_preferences_service import get_preferences

            result = await get_preferences("user123")
        assert result == {}

    @pytest.mark.asyncio
    async def test_creates_default_when_not_exists(self):
        """get_preferences creates a default row when user has no preferences."""
        sb = _mock_table_chain(None)
        # First call (maybe_single) returns no data, second call (insert) returns defaults
        inserted = {"user_id": "user123"}
        sb.execute.side_effect = [_chain(None), _chain([inserted])]

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_preferences

            result = await get_preferences("user123")
        assert result == inserted

    @pytest.mark.asyncio
    async def test_returns_existing_preferences(self):
        """get_preferences returns existing data when row exists."""
        existing = {"user_id": "u1", "preferred_city": "Lisboa", "timezone": "Europe/Lisbon"}
        sb = _mock_table_chain(existing)

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_preferences

            result = await get_preferences("u1")
        assert result == existing
        assert result["preferred_city"] == "Lisboa"


class TestSetPreferences:
    @pytest.mark.asyncio
    async def test_upserts_correctly(self):
        """set_preferences calls upsert and returns the row."""
        row = {"user_id": "u1", "preferred_city": "Porto"}
        sb = _mock_table_chain([row])

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import set_preferences

            result = await set_preferences("u1", preferred_city="Porto")
        assert result == row

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_empty(self):
        """set_preferences returns {} when DB raises."""
        with patch(f"{MODULE}.get_supabase_client", side_effect=Exception("boom")):
            from services.business.user_preferences_service import set_preferences

            result = await set_preferences("u1", preferred_city="Porto")
        assert result == {}

    @pytest.mark.asyncio
    async def test_partial_update(self):
        """set_preferences accepts partial kwargs."""
        row = {"user_id": "u1", "temperature_unit": "fahrenheit"}
        sb = _mock_table_chain([row])

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import set_preferences

            result = await set_preferences("u1", temperature_unit="fahrenheit")
        assert result["temperature_unit"] == "fahrenheit"
