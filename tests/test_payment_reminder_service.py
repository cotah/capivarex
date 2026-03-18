"""Tests for payment reminder service — A4: bill detection + due date alerts."""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from services.business.payment_reminder_service import (
    detect_payment_mention,
    extract_payment_info,
    _fallback_extract,
    save_payment,
    remove_payment,
    list_payments,
    check_payments_due,
    generate_payment_alert,
    handle_payment_mention,
)


class TestPaymentDetection:
    """Tests for keyword detection."""

    def test_detect_pt_conta(self):
        assert detect_payment_mention("a conta da luz vence dia 20") is True

    def test_detect_pt_fatura(self):
        assert detect_payment_mention("fatura do telefone") is True

    def test_detect_en_bill(self):
        assert detect_payment_mention("electric bill due next week") is True

    def test_detect_en_invoice(self):
        assert detect_payment_mention("invoice #123 payment") is True

    def test_detect_es_factura(self):
        assert detect_payment_mention("factura del agua") is True

    def test_no_detect(self):
        assert detect_payment_mention("que horas são?") is False

    def test_no_detect_similar(self):
        assert detect_payment_mention("vou sair de casa") is False


class TestFallbackExtraction:
    """Tests for keyword-based extraction."""

    def test_extract_with_day(self):
        result = _fallback_extract("conta da luz vence dia 20")
        assert result is not None
        assert result["due_day"] == 20

    def test_extract_with_amount(self):
        result = _fallback_extract("fatura de €50 vence dia 15")
        assert result is not None
        assert "50" in result["amount"]

    def test_extract_no_payment(self):
        result = _fallback_extract("bom dia, como estás?")
        assert result is None

    def test_extract_dollar(self):
        result = _fallback_extract("bill of $120 due day 5")
        assert result is not None
        assert "120" in result["amount"]


class TestGPTExtraction:
    """Tests for GPT-based extraction."""

    @pytest.mark.asyncio
    async def test_gpt_extract(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            '{"name": "Electricity bill", "amount": "€50", '
            '"due_day": 20, "due_date": "", "recurring": true, "frequency": "monthly"}'
        )

        with patch(
            "services.business.payment_reminder_service.get_service",
            return_value=mock_openai,
        ):
            result = await extract_payment_info("conta da luz 50 euros vence dia 20")
        assert result is not None
        assert result["name"] == "Electricity bill"
        assert result["due_day"] == 20

    @pytest.mark.asyncio
    async def test_gpt_not_payment(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = '{"is_payment": false}'

        with patch(
            "services.business.payment_reminder_service.get_service",
            return_value=mock_openai,
        ):
            result = await extract_payment_info("bom dia")
        assert result is None

    @pytest.mark.asyncio
    async def test_gpt_failure_fallback(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.side_effect = Exception("API error")

        with patch(
            "services.business.payment_reminder_service.get_service",
            return_value=mock_openai,
        ):
            result = await extract_payment_info("conta vence dia 15")
        assert result is not None
        assert result["due_day"] == 15

    @pytest.mark.asyncio
    async def test_no_openai_fallback(self):
        with patch(
            "services.business.payment_reminder_service.get_service", return_value=None
        ):
            result = await extract_payment_info("bill due day 10")
        assert result is not None
        assert result["due_day"] == 10


class TestStorage:
    """Tests for payment storage."""

    @pytest.mark.asyncio
    async def test_save_no_db(self):
        with patch(
            "services.business.payment_reminder_service.get_service", return_value=None
        ):
            result = await save_payment("u1", {"name": "Electricity", "due_day": 20})
        assert result is False

    @pytest.mark.asyncio
    async def test_list_no_db(self):
        with patch(
            "services.business.payment_reminder_service.get_service", return_value=None
        ):
            result = await list_payments("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_remove_no_db(self):
        with patch(
            "services.business.payment_reminder_service.get_service", return_value=None
        ):
            result = await remove_payment("u1", "Electricity")
        assert result is False


class TestCheckDue:
    """Tests for due date checking."""

    @pytest.mark.asyncio
    async def test_no_payments(self):
        with patch(
            "services.business.payment_reminder_service.get_service", return_value=None
        ):
            result = await check_payments_due("u1", "Marcos")
        assert result == []

    @pytest.mark.asyncio
    async def test_payment_due_today(self):
        today = datetime.now(timezone.utc).day

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "value": json.dumps(
                        [
                            {
                                "name": "Electricity",
                                "amount": "€50",
                                "due_day": today,
                                "recurring": True,
                            }
                        ]
                    )
                }
            ]
        )

        with patch(
            "services.business.payment_reminder_service.get_service",
            return_value=mock_db,
        ):
            result = await check_payments_due("u1", "Marcos")

        assert len(result) >= 1
        due_today = [a for a in result if a["urgency"] == "today"]
        assert len(due_today) == 1

    @pytest.mark.asyncio
    async def test_payment_due_specific_date(self):
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "value": json.dumps(
                        [
                            {
                                "name": "Insurance",
                                "amount": "€100",
                                "due_day": 0,
                                "due_date": future,
                            }
                        ]
                    )
                }
            ]
        )

        with patch(
            "services.business.payment_reminder_service.get_service",
            return_value=mock_db,
        ):
            result = await check_payments_due("u1")

        assert len(result) == 1
        assert result[0]["urgency"] in ("soon", "tomorrow")


class TestAlertGeneration:
    """Tests for humanized alerts."""

    @pytest.mark.asyncio
    async def test_no_alerts(self):
        result = await generate_payment_alert("Marcos", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_alert(self):
        alerts = [
            {
                "name": "Electricity",
                "amount": "€50",
                "urgency": "today",
                "days_until": 0,
            },
            {"name": "Internet", "amount": "€30", "urgency": "soon", "days_until": 3},
        ]

        with patch(
            "services.business.payment_reminder_service.get_service", return_value=None
        ):
            result = await generate_payment_alert("Marcos", alerts)

        assert result is not None
        assert "Marcos" in result
        assert "Electricity" in result
        assert "TODAY" in result

    @pytest.mark.asyncio
    async def test_overdue_alert(self):
        alerts = [
            {"name": "Rent", "amount": "€800", "urgency": "overdue", "days_until": -2}
        ]

        with patch(
            "services.business.payment_reminder_service.get_service", return_value=None
        ):
            result = await generate_payment_alert("Ana", alerts)
        assert "overdue" in result.lower()
        assert "🔴" in result


class TestHandlePaymentMention:
    """Tests for the main entry point."""

    @pytest.mark.asyncio
    async def test_no_payment_returns_none(self):
        result = await handle_payment_mention("u1", "bom dia", "Marcos")
        assert result is None

    @pytest.mark.asyncio
    async def test_payment_saved(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        def fake_svc(name):
            return mock_db if name == "database" else None

        with patch("services.business.payment_reminder_service.get_service", fake_svc):
            result = await handle_payment_mention(
                "u1", "conta da luz vence dia 20", "Marcos"
            )

        assert result is not None
        assert "💰" in result
        assert "Marcos" in result

    @pytest.mark.asyncio
    async def test_gpt_alert(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "💰 Hey Marcos! Quick reminder — your electricity bill (€50) "
            "is due today. Don't forget to pay!"
        )

        alerts = [
            {
                "name": "Electricity",
                "amount": "€50",
                "urgency": "today",
                "days_until": 0,
            }
        ]

        with patch(
            "services.business.payment_reminder_service.get_service",
            return_value=mock_openai,
        ):
            result = await generate_payment_alert("Marcos", alerts)
        assert "Marcos" in result
        assert "Electricity" in result.lower() or "electricity" in result.lower()
