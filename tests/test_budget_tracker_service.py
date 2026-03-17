"""Tests for Budget Tracker service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.budget_tracker_service import (
    detect_spending,
    save_spending,
    get_monthly_summary,
    format_monthly_summary,
    set_budget_limit,
    _extract_amount,
    _detect_category,
)


class TestDetectSpending:
    def test_euro_pt(self):
        result = detect_spending("Gastei 50 euros no almoço")
        assert result is not None
        assert result["amount"] == 50.0
        assert result["currency"] == "EUR"
        assert result["category"] == "food"

    def test_euro_symbol(self):
        result = detect_spending("Paguei €35 no restaurante")
        assert result["amount"] == 35.0
        assert result["category"] == "food"

    def test_dollar(self):
        result = detect_spending("I spent $20 on gas")
        assert result["amount"] == 20.0
        assert result["currency"] == "USD"

    def test_brl(self):
        result = detect_spending("Gastei R$150 no supermercado")
        assert result["amount"] == 150.0
        assert result["currency"] == "BRL"

    def test_decimal_comma(self):
        result = detect_spending("Custou €12,50 o café")
        assert result["amount"] == 12.5

    def test_transport(self):
        result = detect_spending("Paguei 15 euros de uber")
        assert result["category"] == "transport"

    def test_entertainment(self):
        result = detect_spending("Gastei €30 no cinema")
        assert result["category"] == "entertainment"

    def test_bills(self):
        result = detect_spending("Paguei a conta de luz: €80")
        assert result["category"] == "bills"

    def test_shopping(self):
        result = detect_spending("Comprei roupa na zara por €45")
        assert result["category"] == "shopping"

    def test_no_spending(self):
        assert detect_spending("Qual a previsão do tempo?") is None

    def test_no_amount(self):
        assert detect_spending("Gastei dinheiro ontem") is None

    def test_health(self):
        result = detect_spending("Paguei €60 na farmácia")
        assert result["category"] == "health"

    def test_bought_en(self):
        result = detect_spending("I bought a book for €15")
        assert result is not None
        assert result["amount"] == 15.0


class TestExtractAmount:
    def test_euro_symbol_before(self):
        amount, cur = _extract_amount("€50")
        assert amount == 50.0
        assert cur == "EUR"

    def test_euro_symbol_after(self):
        amount, cur = _extract_amount("50€")
        assert amount == 50.0

    def test_euro_word(self):
        amount, cur = _extract_amount("50 euros")
        assert amount == 50.0
        assert cur == "EUR"

    def test_brl(self):
        amount, cur = _extract_amount("R$100")
        assert amount == 100.0
        assert cur == "BRL"

    def test_decimal(self):
        amount, cur = _extract_amount("€12.50")
        assert amount == 12.5

    def test_no_amount(self):
        amount, cur = _extract_amount("nada aqui")
        assert amount is None


class TestDetectCategory:
    def test_food(self):
        assert _detect_category("restaurante almoço") == "food"

    def test_transport(self):
        assert _detect_category("uber taxi") == "transport"

    def test_unknown(self):
        assert _detect_category("algo qualquer") == "other"


class TestSaveSpending:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.budget_tracker_service.get_service", return_value=None):
            result = await save_spending("u1", {"amount": 50, "category": "food"})
        assert result is False

    @pytest.mark.asyncio
    async def test_save_success(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"value": "[]"}])
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.business.budget_tracker_service.get_service", return_value=mock_db):
            result = await save_spending("u1", {"amount": 50, "currency": "EUR", "category": "food"})
        assert result is True

    @pytest.mark.asyncio
    async def test_save_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.budget_tracker_service.get_service", return_value=mock_db):
            result = await save_spending("u1", {"amount": 50})
        assert result is False


class TestMonthlySummary:
    @pytest.mark.asyncio
    async def test_empty_month(self):
        with (
            patch("services.business.budget_tracker_service._load_month_entries", new_callable=AsyncMock, return_value=[]),
            patch("services.business.budget_tracker_service._get_budget_limits", new_callable=AsyncMock, return_value={}),
        ):
            result = await get_monthly_summary("u1")
        assert result["total"] == 0
        assert result["entry_count"] == 0

    @pytest.mark.asyncio
    async def test_with_entries(self):
        entries = [
            {"amount": 50, "category": "food", "currency": "EUR"},
            {"amount": 30, "category": "food", "currency": "EUR"},
            {"amount": 20, "category": "transport", "currency": "EUR"},
        ]
        with (
            patch("services.business.budget_tracker_service._load_month_entries", new_callable=AsyncMock, return_value=entries),
            patch("services.business.budget_tracker_service._get_budget_limits", new_callable=AsyncMock, return_value={"total": 500}),
        ):
            result = await get_monthly_summary("u1")
        assert result["total"] == 100.0
        assert result["by_category"]["food"] == 80.0
        assert result["entry_count"] == 3


class TestFormatSummary:
    def test_with_data(self):
        summary = {
            "month": "2026-03",
            "total": 450.0,
            "by_category": {"food": 200, "transport": 100, "entertainment": 150},
            "entry_count": 15,
            "limits": {"total": 500, "food": 300},
            "currency": "EUR",
        }
        msg = format_monthly_summary(summary, "João")
        assert "Resumo Financeiro" in msg
        assert "€450.00" in msg
        assert "Food" in msg
        assert "90%" in msg  # 450/500

    def test_no_limits(self):
        summary = {
            "month": "2026-03",
            "total": 100.0,
            "by_category": {"food": 100},
            "entry_count": 5,
            "limits": {},
            "currency": "EUR",
        }
        msg = format_monthly_summary(summary)
        assert "€100.00" in msg
        assert "Atenção" not in msg

    def test_brl_currency(self):
        summary = {
            "month": "2026-03",
            "total": 500.0,
            "by_category": {"food": 500},
            "entry_count": 10,
            "limits": {},
            "currency": "BRL",
        }
        msg = format_monthly_summary(summary, "Ana")
        assert "R$" in msg


class TestBudgetLimits:
    @pytest.mark.asyncio
    async def test_set_no_db(self):
        with patch("services.business.budget_tracker_service.get_service", return_value=None):
            result = await set_budget_limit("u1", "food", 300)
        assert result is False

    @pytest.mark.asyncio
    async def test_set_success(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"value": "{}"}])
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.business.budget_tracker_service.get_service", return_value=mock_db):
            result = await set_budget_limit("u1", "total", 1000)
        assert result is True
