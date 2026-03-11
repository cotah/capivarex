"""
Finance Service - Refactored
Serviço para integração com Twelve Data API (cotações e dados financeiros)

FIX [2025-02]: Adicionado retry automático para tickers B3 (bolsa brasileira).
  ANTES: PETR4.SA falha → erro imediato "não foi possível consultar"
  DEPOIS: PETR4.SA falha → tenta PETR4:BVMF (formato nativo Twelve Data) → sucesso

  Razão: A Twelve Data aceita dois formatos para ações brasileiras:
    - PETR4.SA  → yfinance (Yahoo Finance) format — às vezes aceito, às vezes não
    - PETR4:BVMF → Twelve Data native format — mais confiável
  O retry resolve o problema sem mudar o mapeamento no finance_agent.py
"""

import os
import time
from typing import Dict, Any, List, Optional

import aiohttp
from dotenv import load_dotenv

from services.core import BaseService, register_service, retry_on_failure

load_dotenv()

# Mapeamento de sufixos de bolsa para formato Twelve Data
# Ex: PETR4.SA → PETR4:BVMF
_EXCHANGE_SUFFIX_MAP: Dict[str, str] = {
    ".SA": "BVMF",  # B3 — Bolsa brasileira
    ".L": "LSE",  # London Stock Exchange
    ".T": "TSE",  # Tokyo Stock Exchange
    ".HK": "HKEX",  # Hong Kong
    ".AX": "ASX",  # Australia
    ".TO": "TSX",  # Toronto
    ".KS": "KRX",  # Korea
    ".SS": "SSE",  # Shanghai
    ".SZ": "SZSE",  # Shenzhen
    ".BO": "BSE",  # Bombay (India)
    ".NS": "NSE",  # National Stock Exchange (India)
    ".PA": "EURONEXT",  # Paris
    ".DE": "XETRA",  # Germany
    ".MI": "BIT",  # Milan
    ".MC": "BME",  # Madrid
}


def _convert_to_twelve_data_format(ticker: str) -> Optional[str]:
    """
    Converte ticker com sufixo Yahoo Finance para formato Twelve Data.

    Args:
        ticker: Ticker em qualquer formato (ex: "PETR4.SA", "VALE3.SA")

    Returns:
        Ticker no formato Twelve Data (ex: "PETR4:BVMF") ou None se não reconhecido
    """
    ticker_upper = ticker.upper()
    for suffix, exchange in _EXCHANGE_SUFFIX_MAP.items():
        if ticker_upper.endswith(suffix.upper()):
            base = ticker_upper[: -len(suffix)]
            return f"{base}:{exchange}"
    return None


def _is_foreign_ticker(ticker: str) -> bool:
    """Verifica se o ticker tem sufixo de bolsa estrangeira."""
    return any(ticker.upper().endswith(s.upper()) for s in _EXCHANGE_SUFFIX_MAP)


@register_service("finance")
class FinanceService(BaseService):
    """Serviço para buscar cotações e dados financeiros via Twelve Data API"""

    def __init__(self, name: str = "finance", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.api_key = None
        self.base_url = "https://api.twelvedata.com"

    async def _initialize(self):
        self.api_key = os.getenv("TWELVE_DATA_API_KEY")
        if not self.api_key:
            raise ValueError("TWELVE_DATA_API_KEY not found in environment variables")
        self.logger.info("Finance service initialized successfully")

    async def _health_check(self) -> bool:
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
        if not self.api_key:
            await self.initialize()

        params["apikey"] = self.api_key
        start_time = time.time()

        try:
            url = f"{self.base_url}{endpoint}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
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
        """
        Busca a cotação atual de uma ação.

        FIX: Para tickers de bolsas estrangeiras com sufixo Yahoo Finance (ex: PETR4.SA),
        tenta primeiro o ticker como está. Se falhar, converte para o formato
        nativo Twelve Data (ex: PETR4:BVMF) e tenta novamente.
        """
        # Tenta o ticker original primeiro
        try:
            data = await self._api_request(
                "/quote",
                {"symbol": symbol},
                error_label="buscar cotação",
            )
            return self._parse_quote(data, symbol)
        except RuntimeError as original_error:
            # FIX: Se falhou e é um ticker estrangeiro com sufixo .SA/.L/etc,
            # tenta o formato nativo Twelve Data
            if _is_foreign_ticker(symbol):
                alt_ticker = _convert_to_twelve_data_format(symbol)
                if alt_ticker and alt_ticker != symbol:
                    self.logger.info(
                        "Quote failed for %s, retrying with Twelve Data format: %s",
                        symbol,
                        alt_ticker,
                    )
                    try:
                        data = await self._api_request(
                            "/quote",
                            {"symbol": alt_ticker},
                            error_label=f"buscar cotação (formato alternativo {alt_ticker})",
                        )
                        return self._parse_quote(data, symbol)
                    except RuntimeError:
                        pass  # Ambos falharam → re-raise o erro original
            raise original_error

    def _parse_quote(
        self, data: Dict[str, Any], original_symbol: str
    ) -> Dict[str, Any]:
        """Parse e normaliza a resposta de cotação da Twelve Data API."""
        return {
            "symbol": data.get("symbol", original_symbol),
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
                values.append(
                    {
                        "datetime": item.get("datetime"),
                        "open": float(item.get("open", 0)),
                        "high": float(item.get("high", 0)),
                        "low": float(item.get("low", 0)),
                        "close": float(item.get("close", 0)),
                        "volume": int(item.get("volume", 0)),
                    }
                )

        return {
            "symbol": data.get("meta", {}).get("symbol"),
            "interval": data.get("meta", {}).get("interval"),
            "currency": data.get("meta", {}).get("currency"),
            "exchange": data.get("meta", {}).get("exchange"),
            "values": values,
        }

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_price(self, symbol: str) -> Dict[str, Any]:
        """Busca apenas o preço atual (endpoint mais leve)."""
        data = await self._api_request(
            "/price",
            {"symbol": symbol},
            error_label="buscar preço",
        )
        return {
            "symbol": symbol,
            "price": float(data.get("price", 0)),
        }

    async def get_watchlist_summary(self, symbols: List[str]) -> Dict[str, Any]:
        """Retorna resumo de uma watchlist com variação e preço atual."""
        items = []
        for symbol in symbols:
            try:
                quote = await self.get_quote(symbol)
                items.append(
                    {
                        "symbol": quote.get("symbol", symbol),
                        "price": quote.get("price"),
                        "change": quote.get("change"),
                        "percent_change": quote.get("percent_change"),
                    }
                )
            except Exception as e:
                items.append({"symbol": symbol, "error": str(e)})

        movers_up = [
            i
            for i in items
            if isinstance(i.get("percent_change"), (int, float))
            and i["percent_change"] > 0
        ]
        movers_down = [
            i
            for i in items
            if isinstance(i.get("percent_change"), (int, float))
            and i["percent_change"] < 0
        ]

        return {
            "watchlist": items,
            "movers_up": sorted(
                movers_up, key=lambda x: x["percent_change"], reverse=True
            )[:3],
            "movers_down": sorted(movers_down, key=lambda x: x["percent_change"])[:3],
        }


# Backward compatibility
finance_service = None


def get_finance_service() -> FinanceService:
    global finance_service
    if finance_service is None:
        from services.core import get_service

        finance_service = get_service("finance")
    return finance_service
