# -*- coding: utf-8 -*-
"""
Crypto Agent
============
Responde perguntas sobre preços e informações de criptomoedas.

Exemplos:
  - "Qual o preço do Bitcoin?"
  - "Como está o ETH hoje?"
  - "BTC em BRL"
  - "Top 10 criptomoedas"
  - "Quais as maiores cripto por market cap?"
  - "Quanto está o Solana em dólares?"
"""

import logging
import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang

logger = logging.getLogger(__name__)

# Regex para detectar pedido de top N
_RE_TOP = re.compile(
    r"(?:top|melhores|maiores)\s*(\d+)?\s*"
    r"(?:cripto(?:moedas?)?|coins?|criptos?)?",
    re.IGNORECASE,
)

# Regex para detectar moeda de cotação no prompt
_RE_CURRENCY = re.compile(
    r"\b(usd|dólar|dolar|brl|real|reais|eur|euro|gbp|libra)\b",
    re.IGNORECASE,
)

# Mapa de sinônimos de moeda → código
_CURRENCY_MAP = {
    "dólar": "usd",
    "dolar": "usd",
    "usd": "usd",
    "real": "brl",
    "reais": "brl",
    "brl": "brl",
    "euro": "eur",
    "eur": "eur",
    "libra": "gbp",
    "gbp": "gbp",
}

# Símbolos de moeda para formatação
_CURRENCY_SYMBOLS = {
    "usd": "US$",
    "brl": "R$",
    "eur": "€",
    "gbp": "£",
    "jpy": "¥",
}


@register_agent("crypto")
class CryptoAgent(BaseAgent):
    """
    Crypto agent for cryptocurrency price and market queries.

    Handles:
    - Current price in USD, BRL, EUR
    - 24h change percentage
    - Top coins by market cap
    - Multi-coin comparison
    """

    def __init__(self):
        super().__init__(
            name="crypto",
            description="Preços e informações de criptomoedas em tempo real",
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Handle crypto query."""
        lang = get_user_lang(context)
        try:
            crypto_svc = get_service("crypto")
            if not crypto_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("crypto_service_unavailable", lang=lang),
                    error="CryptoService unavailable",
                )

            if not crypto_svc.is_initialized():
                await crypto_svc.initialize()

            prompt_lower = (prompt or "").lower()

            # Intent: top N coins
            top_match = _RE_TOP.search(prompt_lower)
            if top_match or any(
                w in prompt_lower
                for w in ["top cripto", "maiores cripto", "top coins", "ranking"]
            ):
                n = int(top_match.group(1)) if top_match and top_match.group(1) else 10
                currency = self._extract_currency(prompt_lower, context) or "usd"
                return await self._handle_top(
                    crypto_svc, n=min(n, 20), currency=currency
                )

            # Intent: specific coin price
            coin = self._extract_coin(prompt_lower, context, crypto_svc)
            if coin:
                currency = self._extract_currency(prompt_lower, context)
                return await self._handle_price(crypto_svc, coin, currency)

            # Fallback: não identificou moeda
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Não identifiquei qual criptomoeda você quer consultar. Tente:\n"
                    "• *Qual o preço do Bitcoin?*\n"
                    "• *Como está o ETH em BRL?*\n"
                    "• *Top 10 criptomoedas*"
                ),
                error="Could not identify coin",
            )

        except ValueError as e:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=str(e),
                error=str(e),
            )
        except Exception as e:
            self.logger.error("CryptoAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao consultar criptomoedas: {str(e)}",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_price(
        self,
        svc: Any,
        coin: str,
        preferred_currency: Optional[str],
    ) -> AgentResponse:
        """Fetch and format price for a single coin."""
        result = await svc.get_price(
            coin=coin,
            vs_currencies=["usd", "brl", "eur"],
            include_24h_change=True,
            include_market_cap=False,
        )

        coin_name = result["coin_name"]
        prices = result["prices"]
        changes = result["change_24h"]

        # Build primary price line (preferred currency first)
        currencies_order = [preferred_currency] if preferred_currency else []
        for c in ["usd", "brl", "eur"]:
            if c not in currencies_order:
                currencies_order.append(c)

        lines = [f"**{coin_name}**"]
        for c in currencies_order:
            price = prices.get(c)
            change = changes.get(c)
            if price is None:
                continue

            symbol = _CURRENCY_SYMBOLS.get(c, c.upper())
            price_fmt = (
                f"{symbol} {price:,.2f}" if price < 10_000 else f"{symbol} {price:,.0f}"
            )

            if change is not None:
                arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                change_str = f"{arrow} {change:+.2f}% (24h)"
                lines.append(f"  • {c.upper()}: {price_fmt} {change_str}")
            else:
                lines.append(f"  • {c.upper()}: {price_fmt}")

        response = "\n".join(lines)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=result,
        )

    async def _handle_top(
        self,
        svc: Any,
        n: int,
        currency: str,
    ) -> AgentResponse:
        """Fetch and format top N coins by market cap."""
        coins = await svc.get_top_coins(n=n, vs_currency=currency)
        symbol = _CURRENCY_SYMBOLS.get(currency, currency.upper())
        currency_upper = currency.upper()

        lines = [f"**Top {n} Criptomoedas por Market Cap ({currency_upper}):**\n"]
        for c in coins:
            price = c.get("price")
            change = c.get("change_24h")
            price_fmt = (
                f"{symbol} {price:,.2f}"
                if price and price < 10_000
                else f"{symbol} {price:,.0f}"
                if price
                else "N/A"
            )
            change_str = ""
            if change is not None:
                arrow = "▲" if change > 0 else "▼" if change < 0 else "–"
                change_str = f" ({arrow}{abs(change):.1f}%)"

            lines.append(
                f"{c['rank']:>2}. **{c['name']}** ({c['symbol']}) "
                f"— {price_fmt}{change_str}"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"coins": coins, "currency": currency},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_coin(
        self,
        prompt: str,
        context: Dict[str, Any],
        svc: Any,
    ) -> Optional[str]:
        """Extract coin identifier from prompt or context."""
        # Context override
        if context.get("coin"):
            return str(context["coin"])

        # Try known aliases sorted by length (longest first)
        from services.business.crypto_service import COIN_ALIASES

        for alias in sorted(COIN_ALIASES.keys(), key=len, reverse=True):
            # Word-boundary check for short tickers (btc, eth, sol, ...)
            if len(alias) <= 4:
                pattern = rf"\b{re.escape(alias)}\b"
                if re.search(pattern, prompt, re.IGNORECASE):
                    return alias
            elif alias in prompt:
                return alias

        return None

    def _extract_currency(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """Extract preferred quote currency from prompt or context."""
        # Context override
        if context.get("currency"):
            c = str(context["currency"]).lower()
            return _CURRENCY_MAP.get(c, c)

        match = _RE_CURRENCY.search(prompt)
        if match:
            return _CURRENCY_MAP.get(match.group(1).lower())

        return None

    def get_capabilities(self) -> List[str]:
        return [
            "crypto_price",
            "price_in_brl_usd_eur",
            "24h_change",
            "top_coins_ranking",
            "market_cap",
        ]
