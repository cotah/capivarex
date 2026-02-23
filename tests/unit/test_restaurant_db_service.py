"""Unit tests for restaurant_db_service."""

import pytest
from unittest.mock import MagicMock, Mock, patch

MODULE = "services.business.restaurant_db_service"


def _chain(data):
    """Build a mock result with .data attribute."""
    result = Mock()
    result.data = data
    return result


def _mock_table_chain(return_data):
    """Build a chainable mock for supabase operations."""
    chain = MagicMock()
    chain.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.insert.return_value = chain
    chain.execute.return_value = _chain(return_data)
    return chain


class TestSaveSearch:
    @pytest.mark.asyncio
    async def test_saves_successfully(self):
        """save_search inserts without raising."""
        sb = _mock_table_chain(None)
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.restaurant_db_service import save_search

            await save_search(user_id="u1", cuisine="sushi", results_count=3)
        sb.table.assert_called_with("restaurant_searches")

    @pytest.mark.asyncio
    async def test_db_unavailable_does_not_raise(self):
        """save_search silently returns when DB is unavailable."""
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.restaurant_db_service import save_search

            await save_search(user_id="u1")  # should not raise

    @pytest.mark.asyncio
    async def test_db_exception_does_not_raise(self):
        """save_search catches exceptions from the DB."""
        sb = MagicMock()
        sb.table.side_effect = Exception("db error")
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.restaurant_db_service import save_search

            await save_search(user_id="u1")  # should not raise


class TestAddFavorite:
    @pytest.mark.asyncio
    async def test_adds_and_returns_row(self):
        """add_favorite inserts and returns the row."""
        row = {"user_id": "u1", "place_id": "p1", "name": "Sushi Zen"}
        sb = _mock_table_chain([row])
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.restaurant_db_service import add_favorite

            result = await add_favorite(user_id="u1", place_id="p1", name="Sushi Zen")
        assert result == row

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_empty(self):
        """add_favorite returns {} when DB is unavailable."""
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.restaurant_db_service import add_favorite

            result = await add_favorite(user_id="u1", place_id="p1", name="X")
        assert result == {}


class TestGetFavorites:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        """get_favorites returns a list of favorites."""
        favs = [{"name": "A"}, {"name": "B"}]
        sb = _mock_table_chain(favs)
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.restaurant_db_service import get_favorites

            result = await get_favorites("u1")
        assert result == favs

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_empty_list(self):
        """get_favorites returns [] when DB is unavailable."""
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.restaurant_db_service import get_favorites

            result = await get_favorites("u1")
        assert result == []


class TestCreateReservation:
    @pytest.mark.asyncio
    async def test_creates_and_returns_row(self):
        """create_reservation inserts and returns the row."""
        row = {"user_id": "u1", "place_id": "p1", "status": "pending"}
        sb = _mock_table_chain([row])
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.restaurant_db_service import create_reservation

            result = await create_reservation(
                user_id="u1", place_id="p1", restaurant_name="Pasta Place"
            )
        assert result == row
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_empty(self):
        """create_reservation returns {} when DB is unavailable."""
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.restaurant_db_service import create_reservation

            result = await create_reservation(
                user_id="u1", place_id="p1", restaurant_name="X"
            )
        assert result == {}


class TestGetReservations:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        """get_reservations returns a list."""
        rows = [{"restaurant_name": "A", "status": "pending"}]
        sb = _mock_table_chain(rows)
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.restaurant_db_service import get_reservations

            result = await get_reservations("u1")
        assert result == rows

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_empty_list(self):
        """get_reservations returns [] when DB is unavailable."""
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.restaurant_db_service import get_reservations

            result = await get_reservations("u1")
        assert result == []
