# -*- coding: utf-8 -*-
"""
Crypto Service
==============
Preços e informações de criptomoedas via CoinGecko API pública (sem autenticação).
A API pública do CoinGecko tem rate limit de ~30 req/min — suficiente para uso pessoal.

Features:
  - Preço atual em USD, BRL, EUR
  - Variação 24h (%)
  - Market cap e volume
  - Top N moedas por market cap
  - Cache em memória (TTL 60s — preços mudam rápido mas não milissegundo)
"""

import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
)

load_dotenv()
logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CACHE_TTL_SECONDS = 60  # preços são atualizados a cada 60s

# Mapa de aliases comuns → CoinGecko coin ID
COIN_ALIASES: Dict[str, str] = {
    # Bitcoin
    "bitcoin": "bitcoin", "btc": "bitcoin",
    # Ethereum
    "ethereum": "ethereum", "eth": "ethereum", "ether": "ethereum",
    # BNB
    "bnb": "binancecoin", "binance coin": "binancecoin", "binance": "binancecoin",
    # Solana
    "solana": "solana", "sol": "solana",
    # XRP
    "xrp": "ripple", "ripple": "ripple",
    # USDT
    "usdt": "tether", "tether": "tether",
    # USDC
    "usdc": "usd-coin",
    # Cardano
    "cardano": "cardano", "ada": "cardano",
    # Dogecoin
    "dogecoin": "dogecoin", "doge": "dogecoin",
    # Polkadot
    "polkadot": "polkadot", "dot": "polkadot",
    # Avalanche
    "avalanche": "avalanche-2", "avax": "avalanche-2",
    # Polygon
    "polygon": "matic-network", "matic": "matic-network",
    # Chainlink
    "chainlink": "chainlink", "link": "chainlink",
    # Litecoin
    "litecoin": "litecoin", "ltc": "litecoin",
    # Shiba Inu
    "shiba": "shiba-inu", "shib": "shiba-inu", "shiba inu": "shiba-inu",
    # Pepe
    "pepe": "pepe",
    # Toncoin
    "ton": "the-open-network", "toncoin": "the-open-network",
    # Sui
    "sui": "sui",
    # Aptos
    "aptos": "aptos", "apt": "aptos",
}

# Moedas de cotação suportadas
SUPPORTED_VS_CURRENCIES = {"usd", "brl", "eur", "gbp", "jpy", "aud", "cad"}
DEFAULT_VS_CURRENCIES = ["usd", "brl", "eur"]


@register_service("crypto")
class CryptoService(BaseService):
    """
    Cryptocurrency data service via CoinGecko public API.

    No API key required for public endpoints (rate limit: ~30 req/min).
    """

    def __init__(self):
        super().__init__(name="crypto")
        self._http: Optional[httpx.AsyncClient] = None
        self._cache: Dict[str, Dict] = {}  # key → {data, expires_at}

    async def _initialize(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=COINGECKO_BASE,
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "Capivarex-Bot/1.0",
            },
        )
        self.logger.info("CryptoService initialized (CoinGecko public API)")

    async def _health_check(self) -> bool:
        try:
            response = await self._http.get("/ping")
            return response.status_code == 200
        except Exception as e:
            self.logger.error("CoinGecko health check failed: %s", e)
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=2, backoff_factor=1.0)
    async def get_price(
        self,
        coin: str,
        vs_currencies: Optional[List[str]] = None,
        include_24h_change: bool = True,
        include_market_cap: bool = False,
    ) -> Dict[str, Any]:
        """
        Get current price for a cryptocurrency.

        Args:
            coin: Coin name or ticker (btc, ethereum, "shiba inu", ...)
            vs_currencies: List of target currencies (default: usd, brl, eur)
            include_24h_change: Include 24h price change %
            include_market_cap: Include market cap

        Returns:
            Dict with: coin_id, coin_name, prices, change_24h, market_cap

        Raises:
            ValueError: If coin not found
            RuntimeError: If API request fails
        """
        if not self.is_initialized():
            await self.initialize()

        coin_id = self._resolve_coin_id(coin)
        if not coin_id:
            raise ValueError(f"Criptomoeda '{coin}' não encontrada. Tente o ticker (BTC, ETH, SOL...)")

        vs = ",".join(vs_currencies or DEFAULT_VS_CURRENCIES)
        cache_key = f"price:{coin_id}:{vs}"

        cached = self._get_cache(cache_key)
        if cached:
            return cached

        params: Dict[str, Any] = {
            "ids": coin_id,
            "vs_currencies": vs,
            "include_24hr_change": str(include_24h_change).lower(),
            "include_market_cap": str(include_market_cap).lower(),
        }

        start = time.time()
        try:
            response = await self._http.get("/simple/price", params=params)
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RuntimeError("Rate limit da API CoinGecko atingido. Tente novamente em 1 minuto.")
            raise RuntimeError(f"Erro na API CoinGecko: {e.response.status_code}")
        except httpx.RequestError as e:
            raise RuntimeError(f"Falha na conexão com CoinGecko: {str(e)}")

        latency = time.time() - start

        if coin_id not in raw:
            raise ValueError(f"Dados não encontrados para '{coin_id}' na CoinGecko.")

        coin_data = raw[coin_id]
        result: Dict[str, Any] = {
            "coin_id": coin_id,
            "coin_name": coin_id.replace("-", " ").title(),
            "prices": {},
            "change_24h": {},
            "market_cap": {},
            "latency_s": round(latency, 3),
        }

        for currency in (vs_currencies or DEFAULT_VS_CURRENCIES):
            c = currency.lower()
            result["prices"][c] = coin_data.get(c)
            if include_24h_change:
                result["change_24h"][c] = coin_data.get(f"{c}_24h_change")
            if include_market_cap:
                result["market_cap"][c] = coin_data.get(f"{c}_market_cap")

        self._set_cache(cache_key, result)
        self._track_call(latency, error=False)
        return result

    async def get_top_coins(
        self,
        n: int = 10,
        vs_currency: str = "usd",
    ) -> List[Dict[str, Any]]:
        """
        Get top N cryptocurrencies by market cap.

        Args:
            n: Number of coins (max 50)
            vs_currency: Currency for prices (usd, brl, eur)

        Returns:
            List of dicts with: rank, id, name, symbol, price, change_24h, market_cap
        """
        if not self.is_initialized():
            await self.initialize()

        n = min(n, 50)
        cache_key = f"top:{n}:{vs_currency}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        params = {
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": n,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "24h",
        }

        start = time.time()
        try:
            response = await self._http.get("/coins/markets", params=params)
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Erro na API CoinGecko: {e.response.status_code}")
        except httpx.RequestError as e:
            raise RuntimeError(f"Falha na conexão: {str(e)}")

        latency = time.time() - start

        results = [
            {
                "rank": i + 1,
                "id": c["id"],
                "name": c["name"],
                "symbol": c["symbol"].upper(),
                "price": c.get("current_price"),
                "change_24h": c.get("price_change_percentage_24h"),
                "market_cap": c.get("market_cap"),
                "currency": vs_currency,
            }
            for i, c in enumerate(raw)
        ]

        self._set_cache(cache_key, results)
        self._track_call(latency, error=False)
        return results

    def resolve_coin_id(self, coin: str) -> Optional[str]:
        """Public wrapper for coin ID resolution."""
        return self._resolve_coin_id(coin)

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    def _resolve_coin_id(self, coin: str) -> Optional[str]:
        """Resolve coin name/ticker to CoinGecko coin ID."""
        coin_lower = coin.strip().lower()
        return COIN_ALIASES.get(coin_lower)

    def _get_cache(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and time.time() < entry["expires_at"]:
            return entry["data"]
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        self._cache[key] = {
            "data": data,
            "expires_at": time.time() + CACHE_TTL_SECONDS,
        }
