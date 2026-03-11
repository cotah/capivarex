"""
Unit tests for FinanceAgent — stock quotes and financial data.
"""

from unittest.mock import AsyncMock, patch

import pytest

from agents.core import AgentStatus


@pytest.fixture
def finance_agent():
    from agents.specialized.finance_agent import FinanceAgent

    return FinanceAgent()


@pytest.fixture
def mock_finance_svc():
    """Mock finance service returning a sample quote."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.get_quote = AsyncMock(
        return_value={
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "price": 195.50,
            "currency": "USD",
            "change": 2.30,
            "percent_change": 1.19,
            "high": 196.10,
            "low": 193.80,
        }
    )
    return svc


# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finance_symbol_extraction(finance_agent):
    """FinanceAgent correctly extracts $AAPL ticker from prompt."""
    symbol = finance_agent._extract_symbol("quanto está a $AAPL?")
    assert symbol == "AAPL"


@pytest.mark.asyncio
async def test_finance_company_name_to_symbol(finance_agent):
    """FinanceAgent maps company names to ticker symbols."""
    assert finance_agent._extract_symbol("quanto está a ação da Apple?") == "AAPL"
    assert finance_agent._extract_symbol("preço das ações da Microsoft") == "MSFT"
    assert finance_agent._extract_symbol("cotação da Tesla") == "TSLA"
    assert finance_agent._extract_symbol("como está a Google hoje?") == "GOOGL"
    assert finance_agent._extract_symbol("quanto vale a Amazon?") == "AMZN"


@pytest.mark.asyncio
async def test_finance_direct_ticker_still_works(finance_agent):
    """FinanceAgent still handles direct ticker symbols."""
    assert finance_agent._extract_symbol("cotação MSFT") == "MSFT"
    assert finance_agent._extract_symbol("PETR4.SA") == "PETR4.SA"


@pytest.mark.asyncio
async def test_finance_quote_response(finance_agent, mock_finance_svc):
    """FinanceAgent returns formatted quote for a valid symbol."""
    with patch(
        "agents.specialized.finance_agent.get_service", return_value=mock_finance_svc
    ):
        result = await finance_agent.execute("cotação da AAPL", {"symbol": "AAPL"})
    assert result.status == AgentStatus.SUCCESS
    assert "195.50" in result.response


@pytest.mark.asyncio
async def test_finance_missing_symbol(finance_agent):
    """FinanceAgent returns error when no symbol can be identified."""
    result = await finance_agent.execute("quanto está a bolsa hoje?", {})
    # "bolsa" is a stopword, should fail to extract
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_finance_service_unavailable(finance_agent):
    """FinanceAgent returns error when service is missing."""
    with patch("agents.specialized.finance_agent.get_service", return_value=None):
        result = await finance_agent.execute("AAPL", {"symbol": "AAPL"})
    assert result.status == AgentStatus.ERROR
    assert (
        "unavailable" in result.response.lower()
        or "disponivel" in result.response.lower()
    )
