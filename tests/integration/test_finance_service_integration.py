"""Integration tests for FinanceService with mocked HTTP responses."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.integrations.finance_service import FinanceService


def _make_service():
    svc = FinanceService()
    svc.api_key = "fake-api-key"
    svc._initialized = True
    return svc


def _mock_aiohttp_session(json_data):
    """Create a mock aiohttp session returning json_data."""
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


def _quote_response():
    return {
        "symbol": "AAPL",
        "name": "Apple Inc",
        "exchange": "NASDAQ",
        "currency": "USD",
        "close": "150.25",
        "open": "148.00",
        "high": "151.00",
        "low": "147.50",
        "volume": "50000000",
        "previous_close": "147.75",
        "change": "2.50",
        "percent_change": "1.69",
        "datetime": "2026-02-19",
    }


class TestGetQuote:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        mock_session = _mock_aiohttp_session(_quote_response())

        with patch(
            "services.integrations.finance_service.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await svc.get_quote("AAPL")

        assert result["symbol"] == "AAPL"
        assert result["price"] == 150.25
        assert result["change"] == 2.50
        assert result["percent_change"] == 1.69

    @pytest.mark.asyncio
    async def test_api_error(self):
        svc = _make_service()
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("429 Rate Limit"))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.integrations.finance_service.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            with pytest.raises(RuntimeError, match="Erro ao buscar cotação"):
                await svc.get_quote("INVALID")

    @pytest.mark.asyncio
    async def test_api_level_error(self):
        svc = _make_service()
        error_data = {"code": 400, "message": "Invalid symbol"}
        mock_session = _mock_aiohttp_session(error_data)

        with patch(
            "services.integrations.finance_service.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            with pytest.raises(RuntimeError):
                await svc.get_quote("INVALID")


class TestGetPrice:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        mock_session = _mock_aiohttp_session({"price": "150.25"})

        with patch(
            "services.integrations.finance_service.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await svc.get_price("AAPL")

        assert result["symbol"] == "AAPL"
        assert result["price"] == 150.25


class TestGetTimeSeries:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        data = {
            "meta": {
                "symbol": "AAPL",
                "interval": "1day",
                "currency": "USD",
                "exchange": "NASDAQ",
            },
            "values": [
                {
                    "datetime": "2026-02-19",
                    "open": "148",
                    "high": "151",
                    "low": "147",
                    "close": "150",
                    "volume": "5000000",
                },
                {
                    "datetime": "2026-02-18",
                    "open": "146",
                    "high": "149",
                    "low": "145",
                    "close": "148",
                    "volume": "4000000",
                },
            ],
        }
        mock_session = _mock_aiohttp_session(data)

        with patch(
            "services.integrations.finance_service.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await svc.get_time_series("AAPL", interval="1day", outputsize=2)

        assert result["symbol"] == "AAPL"
        assert len(result["values"]) == 2
        assert result["values"][0]["close"] == 150.0


class TestGetWatchlistSummary:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        svc.get_quote = AsyncMock(
            side_effect=[
                {
                    "symbol": "AAPL",
                    "price": 150.0,
                    "change": 2.5,
                    "percent_change": 1.69,
                },
                {
                    "symbol": "GOOGL",
                    "price": 140.0,
                    "change": -1.0,
                    "percent_change": -0.71,
                },
            ]
        )

        result = await svc.get_watchlist_summary(["AAPL", "GOOGL"])

        assert len(result["watchlist"]) == 2
        assert len(result["movers_up"]) == 1
        assert len(result["movers_down"]) == 1
        assert result["movers_up"][0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        svc = _make_service()
        svc.get_quote = AsyncMock(
            side_effect=[
                {
                    "symbol": "AAPL",
                    "price": 150.0,
                    "change": 2.5,
                    "percent_change": 1.69,
                },
                RuntimeError("API error"),
            ]
        )

        result = await svc.get_watchlist_summary(["AAPL", "FAIL"])

        assert len(result["watchlist"]) == 2
        assert "error" in result["watchlist"][1]


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy(self):
        svc = _make_service()
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_unhealthy(self):
        svc = _make_service()
        svc.api_key = None
        assert await svc._health_check() is False
