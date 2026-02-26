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
        Get financial quote for symbol.

        Args:
            prompt: User's finance query
            context: Context with optional symbol

        Returns:
            AgentResponse with quote data
        """
        lang = get_user_lang(context)
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
