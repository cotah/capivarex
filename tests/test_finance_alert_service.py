"""Tests for services.business.finance_alert_service."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.finance_alert_service import (
    get_alert_config,
    set_alert_config,
    check_price_alerts,
    _default_config,
    _get_crypto_prices,
    _get_stock_prices,
    DEFAULT_THRESHOLD_PCT,
)


class TestDefaultConfig:
    def test_returns_dict(self):
        config = _default_config()
        assert config["enabled"] is True
        assert config["threshold_pct"] == DEFAULT_THRESHOLD_PCT

    def test_default_threshold(self):
        assert DEFAULT_THRESHOLD_PCT == 5.0


class TestGetAlertConfig:
    @pytest.mark.asyncio
    async def test_returns_default_when_no_db(self):
        with patch(
            "services.business.finance_alert_service.get_service", return_value=None
        ):
            config = await get_alert_config("user-123")
        assert config["enabled"] is True
        assert config["threshold_pct"] == 5.0

    @pytest.mark.asyncio
    async def test_returns_stored_config(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_result = MagicMock()
        mock_result.data = [
            {"data": json.dumps({"threshold_pct": 3.0, "enabled": True})}
        ]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            config = await get_alert_config("user-123")

        assert config["threshold_pct"] == 3.0

    @pytest.mark.asyncio
    async def test_returns_default_on_error(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.get_client.return_value = MagicMock()
        mock_db.get_client.return_value.table.side_effect = Exception("DB error")

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            config = await get_alert_config("user-123")

        assert config["threshold_pct"] == 5.0

    @pytest.mark.asyncio
    async def test_no_client(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.get_client.return_value = None

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            config = await get_alert_config("user-123")

        assert config == _default_config()

    @pytest.mark.asyncio
    async def test_string_data(self):
        """Config stored as string JSON."""
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_result = MagicMock()
        mock_result.data = [{"data": '{"threshold_pct": 7.5}'}]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            config = await get_alert_config("user-123")

        assert config["threshold_pct"] == 7.5


class TestSetAlertConfig:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_db(self):
        with patch(
            "services.business.finance_alert_service.get_service", return_value=None
        ):
            result = await set_alert_config("user-123", {"threshold_pct": 3.0})
        assert result is False

    @pytest.mark.asyncio
    async def test_upserts_config(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        # get_alert_config returns default
        mock_result_empty = MagicMock()
        mock_result_empty.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result_empty
        mock_client.table.return_value.upsert.return_value.execute.return_value = (
            MagicMock()
        )

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            result = await set_alert_config("user-123", {"threshold_pct": 3.0})

        assert result is True

    @pytest.mark.asyncio
    async def test_no_client(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.get_client.return_value = None

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            result = await set_alert_config("user-123", {"threshold_pct": 3.0})

        assert result is False

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client
        mock_client.table.side_effect = Exception("DB crash")

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            result = await set_alert_config("user-123", {"threshold_pct": 3.0})

        assert result is False


class TestGetCryptoPrices:
    @pytest.mark.asyncio
    async def test_returns_prices(self):
        mock_crypto = MagicMock()
        mock_crypto.initialize = AsyncMock()
        mock_crypto.is_initialized.return_value = True
        mock_crypto.get_top_coins = AsyncMock(
            return_value=[
                {"symbol": "BTC", "name": "Bitcoin", "price": 70000, "change_24h": 2.5},
            ]
        )

        with patch(
            "services.business.finance_alert_service.get_service",
            return_value=mock_crypto,
        ):
            prices = await _get_crypto_prices()

        assert len(prices) == 1
        assert prices[0]["symbol"] == "BTC"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        with patch(
            "services.business.finance_alert_service.get_service", return_value=None
        ):
            prices = await _get_crypto_prices()
        assert prices == []


class TestGetStockPrices:
    @pytest.mark.asyncio
    async def test_returns_prices(self):
        mock_finance = MagicMock()
        mock_finance.initialize = AsyncMock()
        mock_finance.get_quote = AsyncMock(
            return_value={
                "symbol": "AAPL",
                "name": "Apple",
                "price": 250,
                "percent_change": -2.1,
            }
        )

        with patch(
            "services.business.finance_alert_service.get_service",
            return_value=mock_finance,
        ):
            prices = await _get_stock_prices()

        assert len(prices) >= 1
        assert prices[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        with patch(
            "services.business.finance_alert_service.get_service", return_value=None
        ):
            prices = await _get_stock_prices()
        assert prices == []


class TestCheckPriceAlerts:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_db(self):
        with patch(
            "services.business.finance_alert_service.get_service", return_value=None
        ):
            count = await check_price_alerts()
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_users(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            count = await check_price_alerts()

        assert count == 0

    @pytest.mark.asyncio
    async def test_sends_alert_on_threshold(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        # Users with proactivity enabled
        mock_users = MagicMock()
        mock_users.data = [{"user_id": "user-1"}]

        # Alert config
        mock_config = MagicMock()
        mock_config.data = [
            {"data": json.dumps({"enabled": True, "threshold_pct": 3.0})}
        ]

        # No existing alerts today
        mock_no_existing = MagicMock()
        mock_no_existing.data = []

        def table_side(name):
            t = MagicMock()
            if name == "proactivity_preferences":
                t.select.return_value.eq.return_value.execute.return_value = mock_users
            elif name == "user_context":
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_config
            elif name == "proactivity_feed":
                t.select.return_value.eq.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = mock_no_existing
                t.insert.return_value.execute.return_value = MagicMock()
            return t

        mock_client.table = table_side

        with (
            patch(
                "services.business.finance_alert_service.get_service",
                return_value=mock_db,
            ),
            patch(
                "services.business.finance_alert_service._get_crypto_prices",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "symbol": "BTC",
                        "name": "Bitcoin",
                        "price": 70000,
                        "change_24h": 8.5,
                    },
                ],
            ),
            patch(
                "services.business.finance_alert_service._get_stock_prices",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            count = await check_price_alerts()

        assert count >= 1


class TestCheckPriceAlertsAdditional:
    @pytest.mark.asyncio
    async def test_skips_disabled_user(self):
        """User with alerts disabled should be skipped."""
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_users = MagicMock()
        mock_users.data = [{"user_id": "user-disabled"}]

        mock_config = MagicMock()
        mock_config.data = [
            {"data": json.dumps({"enabled": False, "threshold_pct": 5.0})}
        ]

        def table_side(name):
            t = MagicMock()
            if name == "proactivity_preferences":
                t.select.return_value.eq.return_value.execute.return_value = mock_users
            elif name == "user_context":
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_config
            return t

        mock_client.table = table_side

        with (
            patch(
                "services.business.finance_alert_service.get_service",
                return_value=mock_db,
            ),
            patch(
                "services.business.finance_alert_service._get_crypto_prices",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "symbol": "BTC",
                        "name": "Bitcoin",
                        "price": 70000,
                        "change_24h": 8.5,
                    },
                ],
            ),
            patch(
                "services.business.finance_alert_service._get_stock_prices",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            count = await check_price_alerts()
        assert count == 0

    @pytest.mark.asyncio
    async def test_stock_alert_sent(self):
        """Stock with big move triggers alert."""
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_users = MagicMock()
        mock_users.data = [{"user_id": "user-1"}]

        mock_config = MagicMock()
        mock_config.data = [
            {"data": json.dumps({"enabled": True, "threshold_pct": 3.0})}
        ]

        mock_no_existing = MagicMock()
        mock_no_existing.data = []

        def table_side(name):
            t = MagicMock()
            if name == "proactivity_preferences":
                t.select.return_value.eq.return_value.execute.return_value = mock_users
            elif name == "user_context":
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_config
            elif name == "proactivity_feed":
                t.select.return_value.eq.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = mock_no_existing
                t.insert.return_value.execute.return_value = MagicMock()
            return t

        mock_client.table = table_side

        with (
            patch(
                "services.business.finance_alert_service.get_service",
                return_value=mock_db,
            ),
            patch(
                "services.business.finance_alert_service._get_crypto_prices",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.finance_alert_service._get_stock_prices",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "symbol": "TSLA",
                        "name": "Tesla",
                        "price": 391,
                        "percent_change": -6.2,
                    },
                ],
            ),
        ):
            count = await check_price_alerts()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_no_client_returns_zero(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.get_client.return_value = None

        with patch(
            "services.business.finance_alert_service.get_service", return_value=mock_db
        ):
            count = await check_price_alerts()
        assert count == 0
