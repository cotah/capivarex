"""
Unit tests for FinanceAgent — stock quotes and financial data.
"""

from unittest.mock import AsyncMock, MagicMock, patch

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


# ---------------------------------------------------------------------------
# Alert Configuration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finance_alert_set_threshold(finance_agent):
    """Finance agent handles 'set alerts to 3%'."""
    with (
        patch(
            "services.business.finance_alert_service.set_alert_config",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "services.business.finance_alert_service.get_alert_config",
            new_callable=AsyncMock,
            return_value={"enabled": True, "threshold_pct": 3.0},
        ),
    ):
        result = await finance_agent.execute(
            "set my stock alerts to 3%",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "3" in result.response


@pytest.mark.asyncio
async def test_finance_alert_disable(finance_agent):
    """Finance agent handles 'disable alerts'."""
    with patch(
        "services.business.finance_alert_service.set_alert_config",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await finance_agent.execute(
            "disable my alerts",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "disabled" in result.response.lower()


@pytest.mark.asyncio
async def test_finance_alert_enable(finance_agent):
    """Finance agent handles 'enable alerts'."""
    with (
        patch(
            "services.business.finance_alert_service.set_alert_config",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "services.business.finance_alert_service.get_alert_config",
            new_callable=AsyncMock,
            return_value={"enabled": True, "threshold_pct": 5.0},
        ),
    ):
        result = await finance_agent.execute(
            "enable my alerts",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "enabled" in result.response.lower()


@pytest.mark.asyncio
async def test_finance_alert_status(finance_agent):
    """Finance agent shows current alert config."""
    with patch(
        "services.business.finance_alert_service.get_alert_config",
        new_callable=AsyncMock,
        return_value={"enabled": True, "threshold_pct": 5.0},
    ):
        result = await finance_agent.execute(
            "show my alerts",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "5" in result.response


@pytest.mark.asyncio
async def test_finance_alert_threshold_too_low(finance_agent):
    """Finance agent rejects threshold below 0.5%."""
    result = await finance_agent.execute(
        "set alerts to 0.1%",
        {"user_id": "test-user-123"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert "0.5" in result.response


@pytest.mark.asyncio
async def test_finance_alert_threshold_too_high(finance_agent):
    """Finance agent rejects threshold above 50%."""
    result = await finance_agent.execute(
        "set alert threshold 60%",
        {"user_id": "test-user-123"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert "50" in result.response


# ---------------------------------------------------------------------------
# Watchlist Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_show_watchlist(finance_agent):
    """Finance agent shows user's watchlist."""
    with patch("services.business.weekly_recap_service.get_service", return_value=None):
        result = await finance_agent.execute(
            "show my watchlist",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "AAPL" in result.response  # Default stocks
    assert "bitcoin" in result.response  # Default crypto


@pytest.mark.asyncio
async def test_add_stock_to_watchlist(finance_agent):
    """Finance agent adds stock to watchlist."""
    mock_db = MagicMock()
    mock_db.is_initialized.return_value = True
    mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    with patch(
        "services.business.weekly_recap_service.get_service", return_value=mock_db
    ):
        result = await finance_agent.execute(
            "add NVDA to my watchlist",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "NVDA" in result.response


@pytest.mark.asyncio
async def test_add_crypto_to_watchlist(finance_agent):
    """Finance agent adds crypto to watchlist."""
    mock_db = MagicMock()
    mock_db.is_initialized.return_value = True
    mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    with patch(
        "services.business.weekly_recap_service.get_service", return_value=mock_db
    ):
        result = await finance_agent.execute(
            "add bitcoin to my watchlist",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "already" in result.response.lower()  # bitcoin is in defaults


@pytest.mark.asyncio
async def test_remove_from_watchlist(finance_agent):
    """Finance agent removes stock from watchlist."""
    mock_db = MagicMock()
    mock_db.is_initialized.return_value = True
    mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    with patch(
        "services.business.weekly_recap_service.get_service", return_value=mock_db
    ):
        result = await finance_agent.execute(
            "remove AAPL from my watchlist",
            {"user_id": "test-user-123"},
        )
    assert result.status == AgentStatus.SUCCESS
    assert "AAPL" in result.response
