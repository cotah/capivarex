"""Tests for weekly recap service and watchlist management."""

import pytest
from unittest.mock import MagicMock, patch

from services.business.weekly_recap_service import (
    get_user_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    generate_weekly_recap,
    _build_raw_data,
    _fallback_recap,
    _save_watchlist,
    DEFAULT_STOCKS,
    DEFAULT_CRYPTO,
)


class TestWatchlist:
    """Tests for watchlist management."""

    @pytest.mark.asyncio
    async def test_get_watchlist_defaults(self):
        """Returns defaults when no DB or no saved watchlist."""
        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await get_user_watchlist("user-123")
        assert result["stocks"] == DEFAULT_STOCKS
        assert result["crypto"] == DEFAULT_CRYPTO

    @pytest.mark.asyncio
    async def test_get_watchlist_from_db(self):
        """Returns user's saved watchlist from DB."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {"context_data": '{"stocks": ["NVDA", "AMD"], "crypto": ["bitcoin"]}'}
            ]
        )

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=mock_db
        ):
            result = await get_user_watchlist("user-123")
        assert result["stocks"] == ["NVDA", "AMD"]
        assert result["crypto"] == ["bitcoin"]

    @pytest.mark.asyncio
    async def test_add_stock_to_watchlist(self):
        """Add a new stock to watchlist."""
        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await add_to_watchlist("user-123", "NVDA", "stock")
        assert result["ok"] is True
        assert "NVDA" in result["watchlist"]["stocks"]

    @pytest.mark.asyncio
    async def test_add_duplicate_stock(self):
        """Adding duplicate stock returns error."""
        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await add_to_watchlist("user-123", "AAPL", "stock")
        assert result["ok"] is False
        assert "already" in result["error"]

    @pytest.mark.asyncio
    async def test_add_crypto_to_watchlist(self):
        """Add crypto to watchlist."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=mock_db
        ):
            result = await add_to_watchlist("user-123", "cardano", "crypto")
        assert result["ok"] is True
        assert "cardano" in result["watchlist"]["crypto"]

    @pytest.mark.asyncio
    async def test_remove_stock(self):
        """Remove stock from watchlist."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=mock_db
        ):
            result = await remove_from_watchlist("user-123", "AAPL", "stock")
        assert result["ok"] is True
        assert "AAPL" not in result["watchlist"]["stocks"]

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self):
        """Removing non-existent stock returns error."""
        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await remove_from_watchlist("user-123", "ZZZZ", "stock")
        assert result["ok"] is False
        assert "not in" in result["error"]


class TestWeeklyRecap:
    """Tests for weekly recap generation."""

    def test_build_raw_data(self):
        """Raw data builder produces structured text."""
        raw = _build_raw_data(
            user_name="Marcos",
            user_stocks={
                "watchlist": [{"symbol": "AAPL", "price": 180, "change_pct": 3.2}]
            },
            market_movers=[{"symbol": "NVDA", "change_pct": 12.5}],
            user_crypto=[
                {
                    "name": "Bitcoin",
                    "current_price": 65000,
                    "price_change_percentage_24h": 5.1,
                }
            ],
            crypto_top=[{"name": "Solana", "price_change_percentage_24h": 15.3}],
        )
        assert "Marcos" in raw
        assert "AAPL" in raw
        assert "NVDA" in raw
        assert "Bitcoin" in raw
        assert "Solana" in raw

    def test_fallback_recap(self):
        """Fallback recap still produces warm text."""
        raw = "User name: Marcos\n\nUSER'S STOCKS:\n  AAPL: $180 (+3.20%)\n  TSLA: $220 (-1.80%)"
        result = _fallback_recap(raw, "Marcos")
        assert "Marcos" in result
        assert "🟢" in result
        assert "🔴" in result
        assert "watchlist" in result.lower()

    @pytest.mark.asyncio
    async def test_recap_dedup(self):
        """Recap not sent twice in same week."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "already-sent"}]
        )

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=mock_db
        ):
            result = await generate_weekly_recap(user_id="user-123", user_name="Test")
        assert result is None

    @pytest.mark.asyncio
    async def test_store_recap_no_db(self):
        from services.business.weekly_recap_service import _store_recap

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            await _store_recap("u1", "title", "msg")  # Should not crash

    @pytest.mark.asyncio
    async def test_get_stock_data_no_service(self):
        from services.business.weekly_recap_service import _get_stock_data

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await _get_stock_data(["AAPL"])
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_market_movers_no_service(self):
        from services.business.weekly_recap_service import _get_market_movers

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await _get_market_movers()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_crypto_data_no_service(self):
        from services.business.weekly_recap_service import _get_crypto_data

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await _get_crypto_data(["bitcoin"])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_top_crypto_no_service(self):
        from services.business.weekly_recap_service import _get_top_crypto

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await _get_top_crypto()
        assert result == []

    @pytest.mark.asyncio
    async def test_recap_sent_this_week_no_db(self):
        from services.business.weekly_recap_service import _recap_sent_this_week

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await _recap_sent_this_week("u1")
        assert result is False


class TestWeeklyRecapGeneration:
    """Tests for the full recap generation flow."""

    @pytest.mark.asyncio
    async def test_generate_recap_full(self):
        """Full recap generation with all services mocked."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        # Not sent this week
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        # Insert works
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        mock_finance = MagicMock()
        mock_finance.is_initialized.return_value = True
        mock_finance.get_watchlist_summary.return_value = {
            "watchlist": [
                {"symbol": "AAPL", "price": 180, "change_pct": 3.2},
                {"symbol": "TSLA", "price": 220, "change_pct": -1.8},
            ]
        }

        mock_crypto = MagicMock()
        mock_crypto.is_initialized.return_value = True
        mock_crypto.get_top_coins.return_value = [
            {
                "id": "bitcoin",
                "name": "Bitcoin",
                "symbol": "btc",
                "current_price": 65000,
                "price_change_percentage_24h": 5.1,
            },
            {
                "id": "ethereum",
                "name": "Ethereum",
                "symbol": "eth",
                "current_price": 3200,
                "price_change_percentage_24h": -1.2,
            },
            {
                "id": "solana",
                "name": "Solana",
                "symbol": "sol",
                "current_price": 140,
                "price_change_percentage_24h": 8.3,
            },
        ]

        def fake_svc(name):
            return {
                "database": mock_db,
                "finance": mock_finance,
                "crypto": mock_crypto,
                "openai": None,
                "notification": None,
            }.get(name)

        with patch("services.business.weekly_recap_service.get_service", fake_svc):
            result = await generate_weekly_recap(
                user_id="test-user-123",
                user_name="Marcos Silva",
            )

        assert result is not None
        assert "Marcos" in result["message"]
        # Should use fallback since openai=None
        assert "AAPL" in result["message"] or "Apple" in result["message"]

    @pytest.mark.asyncio
    async def test_generate_recap_all_services_down(self):
        """Recap still works when all services are down."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        def fake_svc(name):
            return mock_db if name == "database" else None

        with patch("services.business.weekly_recap_service.get_service", fake_svc):
            result = await generate_weekly_recap(user_id="u1", user_name="Ana")

        assert result is not None
        assert "Ana" in result["message"]

    @pytest.mark.asyncio
    async def test_humanize_recap_no_openai(self):
        """Humanize falls back gracefully when OpenAI unavailable."""
        from services.business.weekly_recap_service import _humanize_recap

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=None
        ):
            result = await _humanize_recap(
                "User name: Test\n\nUSER'S STOCKS:\n  AAPL: $180 (+3.20%)", "Test"
            )
        assert "Test" in result
        assert "🟢" in result

    @pytest.mark.asyncio
    async def test_save_watchlist_with_db(self):
        """Save watchlist to database."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch(
            "services.business.weekly_recap_service.get_service", return_value=mock_db
        ):
            await _save_watchlist("u1", {"stocks": ["AAPL"], "crypto": ["bitcoin"]})

        mock_db.get_client.return_value.table.assert_called_with("user_context")

    @pytest.mark.asyncio
    async def test_get_market_movers_with_data(self):
        """Market movers returns sorted top movers."""
        from services.business.weekly_recap_service import _get_market_movers

        mock_finance = MagicMock()
        mock_finance.is_initialized.return_value = True
        mock_finance.get_watchlist_summary.return_value = {
            "watchlist": [
                {"symbol": "NVDA", "change_pct": 12.5},
                {"symbol": "AAPL", "change_pct": 1.2},
                {"symbol": "META", "change_pct": -8.3},
            ]
        }

        with patch(
            "services.business.weekly_recap_service.get_service",
            return_value=mock_finance,
        ):
            result = await _get_market_movers()

        assert len(result) > 0
        # Sorted by absolute change
        assert abs(result[0].get("change_pct", 0)) >= abs(
            result[-1].get("change_pct", 0)
        )

    @pytest.mark.asyncio
    async def test_get_crypto_data_filters(self):
        """Crypto data filters to user's coins only."""
        from services.business.weekly_recap_service import _get_crypto_data

        mock_crypto = MagicMock()
        mock_crypto.is_initialized.return_value = True
        mock_crypto.get_top_coins.return_value = [
            {"id": "bitcoin", "name": "Bitcoin"},
            {"id": "ethereum", "name": "Ethereum"},
            {"id": "dogecoin", "name": "Dogecoin"},
        ]

        with patch(
            "services.business.weekly_recap_service.get_service",
            return_value=mock_crypto,
        ):
            result = await _get_crypto_data(["bitcoin", "ethereum"])

        assert len(result) == 2
        assert all(c["id"] in ["bitcoin", "ethereum"] for c in result)
