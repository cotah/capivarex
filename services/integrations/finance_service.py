"""
Finance Service - Refactored
Serviço para integração com Twelve Data API (cotações e dados financeiros)
"""
import os
import time
from typing import Dict, Any, List
import aiohttp
from dotenv import load_dotenv

from services.core import BaseService, register_service, retry_on_failure

load_dotenv()


@register_service("finance")
class FinanceService(BaseService):
    """Serviço para buscar cotações e dados financeiros via Twelve Data API"""

    def __init__(self, name: str = "finance", config: Dict[str, Any] = None):
        """Initialise the finance service."""
        super().__init__(name, config)
        self.api_key = None
        self.base_url = "https://api.twelvedata.com"

    async def _initialize(self):
        """Initialize finance service."""
        self.api_key = os.getenv("TWELVE_DATA_API_KEY")
        if not self.api_key:
            raise ValueError("TWELVE_DATA_API_KEY not found in environment variables")
        self.logger.info("Finance service initialized successfully")

    async def _health_check(self) -> bool:
        """Check if finance service is healthy."""
        return self.api_key is not None

    # ------------------------------------------------------------------
    # Private: shared API call pattern
    # ------------------------------------------------------------------

    async def _api_request(
        self,
        endpoint: str,
        params: Dict[str, Any],
        error_label: str,
    ) -> Dict[str, Any]:
        """Execute a Twelve Data API request with tracking and error handling.

        Args:
            endpoint: API endpoint path (e.g. ``/quote``, ``/price``).
            params: Query parameters (``apikey`` is injected automatically).
            error_label: Human-readable label for error messages.

        Returns:
            Parsed JSON response.

        Raises:
            RuntimeError: If the request fails or the API returns an error.
        """
        if not self.api_key:
            await self.initialize()

        params["apikey"] = self.api_key
        start_time = time.time()

        try:
            url = f"{self.base_url}{endpoint}"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

            # Check for API-level errors
            if "code" in data and data["code"] != 200:
                raise RuntimeError(f"API Error: {data.get('message', 'Unknown error')}")

            latency = time.time() - start_time
            self._track_call(latency, error=False)
            return data

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("Error %s: %s", error_label, e, exc_info=True)
            raise RuntimeError(f"Erro ao {error_label}: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Busca a cotação atual de uma ação."""
        data = await self._api_request(
            "/quote", {"symbol": symbol}, error_label="buscar cotação",
        )

        result = {
            "symbol": data.get("symbol"),
            "name": data.get("name"),
            "exchange": data.get("exchange"),
            "currency": data.get("currency"),
            "price": float(data.get("close", 0)),
            "open": float(data.get("open", 0)),
            "high": float(data.get("high", 0)),
            "low": float(data.get("low", 0)),
            "volume": int(data.get("volume", 0)),
            "previous_close": float(data.get("previous_close", 0)),
            "change": float(data.get("change", 0)),
            "percent_change": float(data.get("percent_change", 0)),
            "timestamp": data.get("datetime"),
        }

        self.logger.info("Quote fetched for %s", symbol)
        return result

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_time_series(
        self,
        symbol: str,
        interval: str = "1day",
        outputsize: int = 30,
    ) -> Dict[str, Any]:
        """Busca o histórico de preços de uma ação."""
        data = await self._api_request(
            "/time_series",
            {
                "symbol": symbol,
                "interval": interval,
                "outputsize": min(outputsize, 5000),
            },
            error_label="buscar histórico",
        )

        values = []
        if "values" in data:
            for item in data["values"]:
                values.append({
                    "datetime": item.get("datetime"),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": int(item.get("volume", 0)),
                })

        result = {
            "symbol": data.get("meta", {}).get("symbol"),
            "interval": data.get("meta", {}).get("interval"),
            "currency": data.get("meta", {}).get("currency"),
            "exchange": data.get("meta", {}).get("exchange"),
            "values": values,
        }

        self.logger.info("Time series fetched for %s", symbol)
        return result

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_price(self, symbol: str) -> Dict[str, Any]:
        """Busca apenas o preço atual de uma ação (endpoint mais leve)."""
        data = await self._api_request(
            "/price", {"symbol": symbol}, error_label="buscar preço",
        )

        result = {
            "symbol": symbol,
            "price": float(data.get("price", 0)),
        }

        self.logger.info("Price fetched for %s", symbol)
        return result

    async def get_watchlist_summary(self, symbols: List[str]) -> Dict[str, Any]:
        """Retorna resumo de uma watchlist com variação e preço atual."""
        items = []
        for symbol in symbols:
            try:
                quote = await self.get_quote(symbol)
                items.append({
                    "symbol": quote.get("symbol", symbol),
                    "price": quote.get("price"),
                    "change": quote.get("change"),
                    "percent_change": quote.get("percent_change"),
                })
            except Exception as e:
                items.append({"symbol": symbol, "error": str(e)})

        movers_up = [
            i for i in items
            if isinstance(i.get("percent_change"), (int, float))
            and i["percent_change"] > 0
        ]
        movers_down = [
            i for i in items
            if isinstance(i.get("percent_change"), (int, float))
            and i["percent_change"] < 0
        ]

        return {
            "watchlist": items,
            "movers_up": sorted(
                movers_up, key=lambda x: x["percent_change"], reverse=True,
            )[:3],
            "movers_down": sorted(movers_down, key=lambda x: x["percent_change"])[:3],
        }


# Backward compatibility - global instance
finance_service = None


def get_finance_service() -> FinanceService:
    """Get global finance service instance."""
    global finance_service
    if finance_service is None:
        from services.core import get_service
        finance_service = get_service("finance")
    return finance_service
