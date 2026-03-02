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
        existing = {
            "user_id": "u1",
            "preferred_city": "Lisboa",
            "timezone": "Europe/Lisbon",
        }
        sb = _mock_table_chain(existing)

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_preferences

            result = await get_preferences("u1")
        assert result == existing
        assert result["preferred_city"] == "Lisboa"

    @pytest.mark.asyncio
    async def test_db_operation_exception_returns_empty(self):
        """get_preferences returns {} when DB query/insert raises."""
        sb = MagicMock()
        sb.table.side_effect = Exception("query failed")
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_preferences

            result = await get_preferences("user123")
        assert result == {}


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


class TestSaveLocation:
    @pytest.mark.asyncio
    async def test_save_home_location(self):
        """save_location with type='home' sets home_* and last_* fields."""
        row = {"user_id": "u1", "home_latitude": 38.7, "home_longitude": -9.1}
        sb = _mock_table_chain([row])

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import save_location

            result = await save_location("u1", 38.7, -9.1, location_type="home")
        assert result == row

    @pytest.mark.asyncio
    async def test_save_work_location(self):
        """save_location with type='work' sets work_* and last_* fields."""
        row = {"user_id": "u1", "work_latitude": 38.72, "work_longitude": -9.15}
        sb = _mock_table_chain([row])

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import save_location

            result = await save_location("u1", 38.72, -9.15, location_type="work")
        assert result == row

    @pytest.mark.asyncio
    async def test_save_last_location(self):
        """save_location with default type sets only last_* fields."""
        row = {"user_id": "u1", "last_latitude": 53.3, "last_longitude": -6.26}
        sb = _mock_table_chain([row])

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import save_location

            result = await save_location("u1", 53.3, -6.26)
        assert result == row


class TestGetLocation:
    @pytest.mark.asyncio
    async def test_get_home_location(self):
        """get_location with prefer='home' returns home coordinates."""
        prefs = {"home_latitude": 38.7, "home_longitude": -9.1}
        sb = _mock_table_chain(prefs)

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_location

            result = await get_location("u1", prefer="home")
        assert result == (38.7, -9.1)

    @pytest.mark.asyncio
    async def test_get_work_location(self):
        """get_location with prefer='work' returns work coordinates."""
        prefs = {"work_latitude": 38.72, "work_longitude": -9.15}
        sb = _mock_table_chain(prefs)

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_location

            result = await get_location("u1", prefer="work")
        assert result == (38.72, -9.15)

    @pytest.mark.asyncio
    async def test_get_last_location(self):
        """get_location with default prefer returns last coordinates."""
        prefs = {"last_latitude": 53.3, "last_longitude": -6.26}
        sb = _mock_table_chain(prefs)

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_location

            result = await get_location("u1")
        assert result == (53.3, -6.26)

    @pytest.mark.asyncio
    async def test_get_location_missing_coords_returns_none(self):
        """get_location returns None when coordinates are not set."""
        prefs = {"user_id": "u1"}
        sb = _mock_table_chain(prefs)

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import get_location

            result = await get_location("u1", prefer="home")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_location_no_prefs_returns_none(self):
        """get_location returns None when no preferences exist."""
        with patch(f"{MODULE}.get_supabase_client", side_effect=Exception("no db")):
            from services.business.user_preferences_service import get_location

            result = await get_location("u1")
        assert result is None


class TestHasLocation:
    @pytest.mark.asyncio
    async def test_has_location_true(self):
        """has_location returns True when coordinates exist."""
        prefs = {"last_latitude": 53.3, "last_longitude": -6.26}
        sb = _mock_table_chain(prefs)

        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.user_preferences_service import has_location

            result = await has_location("u1")
        assert result is True

    @pytest.mark.asyncio
    async def test_has_location_false(self):
        """has_location returns False when no location set."""
        with patch(f"{MODULE}.get_supabase_client", side_effect=Exception("no db")):
            from services.business.user_preferences_service import has_location

            result = await has_location("u1")
        assert result is False
