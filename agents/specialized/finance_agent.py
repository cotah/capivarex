"""
Finance Agent - Provides stock quotes and financial data.

Refactored to use new BaseAgent architecture.
"""

import logging
import re
from typing import Any, Dict, List

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang


logger = logging.getLogger(__name__)

# Regex patterns for ticker extraction
DOLLAR_TICKER_PATTERN = re.compile(r"\$([A-Za-z]{1,6}(?:\d{0,2})?(?:\.SA)?)")
GENERIC_TICKER_PATTERN = re.compile(r"\b([A-Za-z]{2,6}(?:\d{0,2})?(?:\.SA)?)\b")

# Company name → ticker symbol mapping (all keys lowercase)
COMPANY_TO_SYMBOL = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "tesla": "TSLA",
    "meta": "META",
    "facebook": "META",
    "nvidia": "NVDA",
    "netflix": "NFLX",
    "intel": "INTC",
    "amd": "AMD",
    "disney": "DIS",
    "coca-cola": "KO",
    "coca cola": "KO",
    "pepsi": "PEP",
    "pepsico": "PEP",
    "walmart": "WMT",
    "nike": "NKE",
    "uber": "UBER",
    "airbnb": "ABNB",
    "spotify": "SPOT",
    "paypal": "PYPL",
    "adobe": "ADBE",
    "salesforce": "CRM",
    "oracle": "ORCL",
    "ibm": "IBM",
    "samsung": "005930.KS",
    "petrobras": "PETR4.SA",
    "vale": "VALE3.SA",
    "itau": "ITUB4.SA",
    "itaú": "ITUB4.SA",
    "bradesco": "BBDC4.SA",
    "banco do brasil": "BBAS3.SA",
    "magazine luiza": "MGLU3.SA",
    "magalu": "MGLU3.SA",
    "nubank": "NU",
    "mercado libre": "MELI",
    "mercado livre": "MELI",
}

# Common PT-BR words that are also company names — these are ambiguous
# and need context to distinguish verb from company (e.g. "vale" verb vs "Vale" company)
_AMBIGUOUS_COMPANY_WORDS = {"vale"}

# Stopwords to filter out (includes company names so regex doesn't grab them)
STOPWORDS = {
    "QUAL",
    "COMO",
    "ESTA",
    "ESTAO",
    "COTACAO",
    "ACAO",
    "ACOES",
    "PRECO",
    "BOLSA",
    "HOJE",
    "DA",
    "DE",
    "DO",
    "A",
    "O",
    "E",
    "QUANTO",
    "VALE",
    "PARA",
    "DAS",
    "DOS",
    "NO",
    "NA",
    "UM",
    "UMA",
    "AS",
    "OS",
    "EM",
    "SE",
    "QUE",
    "POR",
    "COM",
    "MAIS",
    "SOBRE",
} | {name.upper() for name in COMPANY_TO_SYMBOL if len(name) <= 6 and " " not in name}


@register_agent("finance")
class FinanceAgent(BaseAgent):
    """
    Finance agent for stock quotes and financial data.

    Handles:
    - Stock quotes
    - Price information
    - Market data
    - Ticker lookup
    """

    def __init__(self):
        """Initialise the finance agent."""
        super().__init__(
            name="finance",
            description="Provides stock quotes and financial market data",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """
        Get financial quote for symbol, configure alerts, or manage watchlist.

        Handles:
        - "add Tesla to my watchlist" → adds to personal watchlist
        - "remove AAPL from my list" → removes from watchlist
        - "show my watchlist" → displays current watchlist
        - "set my stock alerts to 3%" → updates threshold
        - Regular stock queries
        """
        lang = get_user_lang(context)
        user_id = context.get("user_id", "")
        prompt_lower = prompt.lower()

        # ── Alert configuration (check BEFORE watchlist — "show my alerts" must hit alerts, not watchlist) ──
        if any(kw in prompt_lower for kw in ["alert", "alerta", "threshold", "limite"]):
            return await self._handle_alert_config(prompt_lower, user_id, lang)

        # ── Watchlist management ──
        watchlist_keywords = [
            "watchlist",
            "lista",
            "acompanhar",
            "seguir",
            "track",
            "add to my",
            "adiciona",
            "remove from",
            "remov",
            "show my watchlist",
            "my stocks",
            "my crypto",
            "meus ativos",
            "minha carteira",
        ]
        if any(kw in prompt_lower for kw in watchlist_keywords):
            return await self._handle_watchlist(prompt, prompt_lower, user_id, lang)

        symbol = (
            str(context.get("symbol") or self._extract_symbol(prompt)).strip().upper()
        )

        if not symbol:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("finance_no_ticker", lang=lang),
                error="No symbol provided",
            )

        try:
            # Get finance service from registry
            finance_svc = get_service("finance")
            if not finance_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("finance_service_unavailable", lang=lang),
                    error="Finance service not available",
                )

            await finance_svc.initialize()

            # Get quote (async call via refactored service)
            quote = await finance_svc.get_quote(symbol)

            # Format response
            response_text = (
                f"Cotacao de {quote.get('name') or symbol} ({quote.get('symbol') or symbol}): "
                f"${quote.get('price', 0):.2f} {quote.get('currency', 'N/A')}. "
                f"Variacao {quote.get('change', 0):.2f} ({quote.get('percent_change', 0):.2f}%). "
                f"Max {quote.get('high', 0):.2f}, Min {quote.get('low', 0):.2f}."
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=response_text,
                data={"symbol": symbol, "quote": quote},
            )

        except Exception as e:
            self.logger.error(
                f"Finance query failed for symbol '{symbol}': {e}", exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Nao foi possivel consultar cotacao para {symbol}.",
                error=str(e),
                metadata={"symbol": symbol},
            )

    async def _handle_watchlist(
        self, prompt: str, prompt_lower: str, user_id: str, lang: str
    ) -> AgentResponse:
        """Handle watchlist add/remove/show commands."""
        from services.business.weekly_recap_service import (
            get_user_watchlist,
            add_to_watchlist,
            remove_from_watchlist,
        )

        # Detect intent: add, remove, or show
        is_add = any(
            kw in prompt_lower
            for kw in ["add", "adiciona", "acompanhar", "seguir", "track"]
        )
        is_remove = any(
            kw in prompt_lower for kw in ["remove", "remov", "tira", "delete", "exclu"]
        )

        # Show watchlist only if NOT adding or removing
        if not is_add and not is_remove:
            watchlist = await get_user_watchlist(user_id)
            stocks = ", ".join(watchlist["stocks"]) if watchlist["stocks"] else "none"
            crypto = ", ".join(watchlist["crypto"]) if watchlist["crypto"] else "none"
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"📊 Your watchlist:\n\n📈 **Stocks:** {stocks}\n₿ **Crypto:** {crypto}\n\nYou can say 'add Tesla' or 'remove AAPL' to update it.",
                data={"watchlist": watchlist},
            )

        # Detect if crypto
        crypto_words = [
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "solana",
            "sol",
            "crypto",
            "cripto",
            "bnb",
            "cardano",
            "ada",
            "xrp",
            "doge",
            "dogecoin",
            "polkadot",
            "dot",
            "avalanche",
            "avax",
            "matic",
            "polygon",
            "litecoin",
            "ltc",
        ]
        is_crypto = any(w in prompt_lower for w in crypto_words)

        # Extract symbol — strip command words first to avoid extracting "add" as ticker
        clean_prompt = prompt
        for noise in [
            "add",
            "remove",
            "to my watchlist",
            "from my watchlist",
            "to my list",
            "from my list",
            "adiciona",
            "remove",
            "na minha",
            "da minha",
            "watchlist",
            "lista",
            "acompanhar",
            "seguir",
            "track",
        ]:
            clean_prompt = clean_prompt.replace(noise, " ").replace(noise.upper(), " ")
        clean_prompt = " ".join(clean_prompt.split())  # normalize whitespace

        symbol = self._extract_symbol(clean_prompt) if clean_prompt.strip() else ""
        if not symbol:
            for name in crypto_words:
                if name in prompt_lower:
                    symbol = name
                    is_crypto = True
                    break

        if not symbol:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Which stock or crypto would you like to add/remove? Just tell me the name or ticker.",
            )

        asset_type = "crypto" if is_crypto else "stock"

        if is_remove:
            result = await remove_from_watchlist(user_id, symbol, asset_type)
        else:
            result = await add_to_watchlist(user_id, symbol, asset_type)

        if result.get("ok"):
            action = "removed from" if is_remove else "added to"
            target = result.get("removed") or result.get("added", symbol)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"✅ **{target}** {action} your watchlist! I'll keep you updated on its performance.",
                data=result,
            )
        else:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"ℹ️ {result.get('error', 'Could not update watchlist')}",
            )

    async def _handle_alert_config(
        self, prompt_lower: str, user_id: str, lang: str
    ) -> AgentResponse:
        """Handle alert configuration commands."""
        import re
        from services.business.finance_alert_service import (
            get_alert_config,
            set_alert_config,
        )

        # Disable alerts
        if any(
            kw in prompt_lower
            for kw in ["disable", "desativar", "off", "desligar", "stop"]
        ):
            await set_alert_config(user_id, {"enabled": False})
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="🔕 Finance alerts disabled. Say 'enable alerts' to turn them back on.",
            )

        # Enable alerts
        if any(
            kw in prompt_lower for kw in ["enable", "ativar", "on", "ligar", "start"]
        ):
            await set_alert_config(user_id, {"enabled": True})
            config = await get_alert_config(user_id)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"🔔 Finance alerts enabled! I'll notify you when stocks or crypto move more than {config['threshold_pct']}% in a day.",
            )

        # Set threshold: "set alerts to 3%", "alert threshold 5%", "alerta 3%"
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", prompt_lower)
        if pct_match:
            threshold = float(pct_match.group(1))
            if threshold < 0.5:
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response="⚠️ Minimum threshold is 0.5%. A lower value would generate too many alerts.",
                )
            if threshold > 50:
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response="⚠️ Maximum threshold is 50%. That high, you'd almost never get alerts.",
                )
            await set_alert_config(
                user_id, {"threshold_pct": threshold, "enabled": True}
            )
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"✅ Alert threshold set to {threshold}%. I'll notify you when any stock or crypto moves more than {threshold}% in a day.",
            )

        # Just asking about alerts — show current config
        config = await get_alert_config(user_id)
        status = "enabled 🔔" if config.get("enabled") else "disabled 🔕"
        threshold = config.get("threshold_pct", 5.0)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f'📊 Your finance alerts are **{status}** with a **{threshold}%** threshold.\n\nYou can say:\n• "Set alerts to 3%" — change threshold\n• "Disable alerts" — turn off\n• "Enable alerts" — turn on',
        )

    def _extract_symbol(self, prompt: str) -> str:
        """
        Extract stock symbol from prompt.

        First checks the company-name mapping (e.g. 'Apple' → 'AAPL'),
        then falls back to regex for direct ticker references (e.g. '$AAPL').

        Args:
            prompt: User's prompt

        Returns:
            Stock symbol or empty string
        """
        text = prompt or ""
        text_lower = text.lower()

        # 1. Check company name mapping (longest match first to handle
        #    multi-word names like "banco do brasil" before "banco")
        # For short company names that are also common PT-BR words (in STOPWORDS),
        # require explicit company context to avoid false positives.
        # E.g. 'vale' as verb in "quanto vale a bolsa?" should NOT match Vale S.A.
        for company in sorted(COMPANY_TO_SYMBOL, key=len, reverse=True):
            if len(company) >= 7 or " " in company:
                if company in text_lower:
                    return COMPANY_TO_SYMBOL[company]
            elif company in _AMBIGUOUS_COMPANY_WORDS:
                # Ambiguous short name: require company context indicators
                company_ctx = re.compile(
                    r"(?:ações?\s+d[aeo]\s+|cotação\s+d[aeo]\s+|empresa\s+)"
                    + re.escape(company)
                    + r"|"
                    + re.escape(company)
                    + r"\s*(?:s\.?a\.?|sa\b)",
                    re.IGNORECASE,
                )
                if company_ctx.search(text):
                    return COMPANY_TO_SYMBOL[company]
            else:
                pattern = re.compile(
                    r"\b" + re.escape(company) + r"\b",
                    re.IGNORECASE,
                )
                if pattern.search(text):
                    return COMPANY_TO_SYMBOL[company]

        # 2. Try dollar-prefixed ticker ($AAPL)
        dollar_match = DOLLAR_TICKER_PATTERN.search(text)
        if dollar_match:
            return dollar_match.group(1).upper()

        # 3. Try generic ticker patterns (e.g. "AAPL" or "PETR4.SA")
        candidates = GENERIC_TICKER_PATTERN.findall(text)
        for candidate in candidates:
            symbol = candidate.upper()

            # Filter stopwords
            if symbol in STOPWORDS:
                continue

            # Valid if contains digits or is short enough
            if any(ch.isdigit() for ch in symbol) or len(symbol) <= 5:
                return symbol

        return ""

    def get_capabilities(self) -> List[str]:
        """Get finance agent capabilities."""
        return ["stock_quotes", "price_information", "market_data", "ticker_lookup"]
