"""Tests for subscription expiring service — A9: detect renewals + alert before charge."""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from services.business.subscription_service import (
    detect_subscription_mention,
    extract_subscription_info,
    _fallback_extract,
    save_subscription,
    remove_subscription,
    list_subscriptions,
    check_expiring_subscriptions,
    generate_subscription_alert,
    handle_subscription_mention,
)


class TestDetection:
    """Tests for subscription keyword detection."""

    def test_detect_en(self):
        assert (
            detect_subscription_mention("Your Netflix subscription renews on March 25")
            is True
        )

    def test_detect_pt(self):
        assert detect_subscription_mention("A sua assinatura será renovada") is True

    def test_detect_auto_renew(self):
        assert (
            detect_subscription_mention("auto-renew is enabled for your plan") is True
        )

    def test_detect_trial(self):
        assert detect_subscription_mention("Your free trial ends in 3 days") is True

    def test_no_detect(self):
        assert detect_subscription_mention("que horas são?") is False


class TestFallbackExtract:
    """Tests for keyword-based extraction."""

    def test_extract_netflix(self):
        result = _fallback_extract("Netflix subscription renews on the 25th for €15.99")
        assert result is not None
        assert "Netflix" in result["name"]
        assert "15.99" in result["amount"]
        assert result["renewal_day"] == 25

    def test_extract_spotify(self):
        result = _fallback_extract("Spotify renewal day 10")
        assert result is not None
        assert "Spotify" in result["name"]

    def test_extract_unknown_service(self):
        result = _fallback_extract("My subscription to XYZ Corp renews")
        assert result is not None

    def test_no_subscription(self):
        result = _fallback_extract("just a normal message")
        assert result is None


class TestGPTExtract:
    """Tests for GPT extraction."""

    @pytest.mark.asyncio
    async def test_gpt_success(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            '{"name": "Netflix", "amount": "€15.99", "renewal_day": 25, '
            '"renewal_date": "", "frequency": "monthly", "auto_renew": true}'
        )

        with patch(
            "services.business.subscription_service.get_service",
            return_value=mock_openai,
        ):
            result = await extract_subscription_info("Netflix renews day 25 for €15.99")
        assert result["name"] == "Netflix"

    @pytest.mark.asyncio
    async def test_gpt_not_subscription(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = '{"is_subscription": false}'

        with patch(
            "services.business.subscription_service.get_service",
            return_value=mock_openai,
        ):
            result = await extract_subscription_info("hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_gpt_failure_fallback(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.side_effect = Exception("API error")

        with patch(
            "services.business.subscription_service.get_service",
            return_value=mock_openai,
        ):
            result = await extract_subscription_info("Netflix subscription day 10")
        assert result is not None
        assert "Netflix" in result["name"]

    @pytest.mark.asyncio
    async def test_no_openai(self):
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await extract_subscription_info("Spotify renewal day 5")
        assert result is not None


class TestStorage:
    """Tests for subscription storage."""

    @pytest.mark.asyncio
    async def test_save_no_db(self):
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await save_subscription("u1", {"name": "Netflix"})
        assert result is False

    @pytest.mark.asyncio
    async def test_list_no_db(self):
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await list_subscriptions("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_remove_no_db(self):
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await remove_subscription("u1", "Netflix")
        assert result is False


class TestCheckExpiring:
    """Tests for expiration checking."""

    @pytest.mark.asyncio
    async def test_no_subscriptions(self):
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await check_expiring_subscriptions("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_subscription_due_today(self):
        today = datetime.now(timezone.utc).day
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "value": json.dumps(
                        [{"name": "Netflix", "amount": "€15.99", "renewal_day": today}]
                    )
                }
            ]
        )

        with patch(
            "services.business.subscription_service.get_service", return_value=mock_db
        ):
            result = await check_expiring_subscriptions("u1")
        due_today = [a for a in result if a["urgency"] == "today"]
        assert len(due_today) == 1

    @pytest.mark.asyncio
    async def test_subscription_specific_date(self):
        future = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "value": json.dumps(
                        [
                            {
                                "name": "Adobe",
                                "amount": "$20",
                                "renewal_day": 0,
                                "renewal_date": future,
                            }
                        ]
                    )
                }
            ]
        )

        with patch(
            "services.business.subscription_service.get_service", return_value=mock_db
        ):
            result = await check_expiring_subscriptions("u1")
        assert len(result) == 1
        assert result[0]["urgency"] == "soon"


class TestAlertGeneration:
    """Tests for humanized alerts."""

    @pytest.mark.asyncio
    async def test_no_alerts(self):
        result = await generate_subscription_alert("Marcos", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_today(self):
        alerts = [
            {"name": "Netflix", "amount": "€15.99", "urgency": "today", "days_until": 0}
        ]
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await generate_subscription_alert("Marcos", alerts)
        assert "Netflix" in result
        assert "TODAY" in result
        assert "💳" in result

    @pytest.mark.asyncio
    async def test_fallback_soon(self):
        alerts = [
            {"name": "Spotify", "amount": "€9.99", "urgency": "soon", "days_until": 4}
        ]
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await generate_subscription_alert("Ana", alerts)
        assert "Spotify" in result
        assert "4 days" in result

    @pytest.mark.asyncio
    async def test_gpt_alert(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "💳 Hey Marcos! Just a heads up — your Netflix (€15.99) "
            "renews in 3 days. Want to keep it or cancel?"
        )
        alerts = [
            {"name": "Netflix", "amount": "€15.99", "urgency": "soon", "days_until": 3}
        ]

        with patch(
            "services.business.subscription_service.get_service",
            return_value=mock_openai,
        ):
            result = await generate_subscription_alert("Marcos", alerts)
        assert "Netflix" in result


class TestHandleMention:
    """Tests for the chat flow entry point."""

    @pytest.mark.asyncio
    async def test_not_subscription(self):
        result = await handle_subscription_mention("u1", "hello", "Marcos")
        assert result is None

    @pytest.mark.asyncio
    async def test_subscription_saved(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        def fake_svc(name):
            return mock_db if name == "database" else None

        with patch("services.business.subscription_service.get_service", fake_svc):
            result = await handle_subscription_mention(
                "u1", "Netflix subscription renews day 25", "Marcos"
            )
        assert result is not None
        assert "💳" in result
        assert "Netflix" in result

    @pytest.mark.asyncio
    async def test_fallback_tomorrow(self):
        alerts = [
            {
                "name": "Disney+",
                "amount": "€8.99",
                "urgency": "tomorrow",
                "days_until": 1,
            }
        ]
        with patch(
            "services.business.subscription_service.get_service", return_value=None
        ):
            result = await generate_subscription_alert("Test", alerts)
        assert "tomorrow" in result
