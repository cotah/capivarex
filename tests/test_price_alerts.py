"""Tests for proactive price drop alerts."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestVerificarDescidasPreco:
    """Tests for verificar_descidas_preco method."""

    def _make_service(self):
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.logger = __import__("logging").getLogger("test")
        return svc

    def _mock_db(self, data):
        """Build a mock DB that returns data for the chained Supabase call."""
        mock_db = MagicMock()
        (
            mock_db.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .order.return_value
            .execute.return_value
        ) = MagicMock(data=data)
        return mock_db

    @pytest.mark.asyncio
    async def test_no_data_returns_no_alerts(self):
        """No alerts when user has no purchase data."""
        svc = self._make_service()
        mock_db = self._mock_db([])

        with patch("services.get_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.is_initialized.return_value = True
            mock_svc.client = mock_db
            mock_get.return_value = mock_svc
            result = await svc.verificar_descidas_preco("123", lang="en")

        assert result["has_alerts"] is False

    @pytest.mark.asyncio
    async def test_too_few_items_returns_no_alerts(self):
        """No alerts when user has fewer than 5 purchase records."""
        svc = self._make_service()
        today = date.today().isoformat()
        mock_data = [
            {"produto": "Leite", "preco_unitario": 1.00, "mercado": "Lidl", "data_compra": today},
            {"produto": "Pao", "preco_unitario": 0.80, "mercado": "Lidl", "data_compra": today},
        ]
        mock_db = self._mock_db(mock_data)

        with patch("services.get_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.is_initialized.return_value = True
            mock_svc.client = mock_db
            mock_get.return_value = mock_svc
            result = await svc.verificar_descidas_preco("123", lang="en")

        assert result["has_alerts"] is False

    @pytest.mark.asyncio
    async def test_detects_price_drop(self):
        """Detects significant price drop (>15% and >0.30)."""
        svc = self._make_service()
        today = date.today().isoformat()
        old = (date.today() - timedelta(days=30)).isoformat()

        mock_data = [
            # Latest: 1.00
            {"produto": "Leite", "preco_unitario": 1.00, "mercado": "Lidl", "data_compra": today},
            # Older: avg 1.475 (33% drop, 0.475 saving)
            {"produto": "Leite", "preco_unitario": 1.50, "mercado": "Lidl", "data_compra": old},
            {"produto": "Leite", "preco_unitario": 1.45, "mercado": "Aldi", "data_compra": old},
            # Filler items to pass the len >= 5 check
            {"produto": "Pao", "preco_unitario": 0.80, "mercado": "Lidl", "data_compra": old},
            {"produto": "Ovos", "preco_unitario": 2.50, "mercado": "Lidl", "data_compra": old},
            {"produto": "Manteiga", "preco_unitario": 1.20, "mercado": "Lidl", "data_compra": old},
        ]

        mock_db = self._mock_db(mock_data)

        with patch("services.get_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.is_initialized.return_value = True
            mock_svc.client = mock_db
            mock_get.return_value = mock_svc
            result = await svc.verificar_descidas_preco("123", lang="en")

        assert result["has_alerts"] is True
        assert len(result["alerts"]) == 1
        assert result["alerts"][0]["produto"] == "Leite"
        assert result["alerts"][0]["economia"] > 0.30

    @pytest.mark.asyncio
    async def test_ignores_small_drops(self):
        """Ignores drops < 15% or < 0.30."""
        svc = self._make_service()
        today = date.today().isoformat()
        old = (date.today() - timedelta(days=30)).isoformat()

        mock_data = [
            # Latest: 1.40, Old avg: 1.50 (7% drop, 0.10 saving - too small)
            {"produto": "Pao", "preco_unitario": 1.40, "mercado": "Lidl", "data_compra": today},
            {"produto": "Pao", "preco_unitario": 1.50, "mercado": "Lidl", "data_compra": old},
            # Filler items to pass the len >= 5 check
            {"produto": "A1", "preco_unitario": 1.00, "mercado": "X", "data_compra": old},
            {"produto": "A2", "preco_unitario": 1.00, "mercado": "X", "data_compra": old},
            {"produto": "A3", "preco_unitario": 1.00, "mercado": "X", "data_compra": old},
        ]

        mock_db = self._mock_db(mock_data)

        with patch("services.get_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.is_initialized.return_value = True
            mock_svc.client = mock_db
            mock_get.return_value = mock_svc
            result = await svc.verificar_descidas_preco("123", lang="en")

        assert result["has_alerts"] is False

    @pytest.mark.asyncio
    async def test_max_5_alerts(self):
        """Returns max 5 alerts even if more exist."""
        svc = self._make_service()
        today = date.today().isoformat()
        old = (date.today() - timedelta(days=30)).isoformat()

        # 7 products, all with big drops (50% drop each)
        mock_data = []
        for i in range(7):
            prod = f"Produto{i}"
            mock_data.append(
                {"produto": prod, "preco_unitario": 1.00, "mercado": "Lidl", "data_compra": today}
            )
            mock_data.append(
                {"produto": prod, "preco_unitario": 2.00, "mercado": "Lidl", "data_compra": old}
            )

        mock_db = self._mock_db(mock_data)

        with patch("services.get_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.is_initialized.return_value = True
            mock_svc.client = mock_db
            mock_get.return_value = mock_svc
            result = await svc.verificar_descidas_preco("123", lang="en")

        assert result["has_alerts"] is True
        assert len(result["alerts"]) <= 5

    @pytest.mark.asyncio
    async def test_message_is_i18n(self):
        """Message uses i18n strings."""
        svc = self._make_service()
        today = date.today().isoformat()
        old = (date.today() - timedelta(days=30)).isoformat()

        mock_data = [
            {"produto": "Leite", "preco_unitario": 1.00, "mercado": "Lidl", "data_compra": today},
            {"produto": "Leite", "preco_unitario": 1.50, "mercado": "Lidl", "data_compra": old},
            {"produto": "Leite", "preco_unitario": 1.50, "mercado": "Aldi", "data_compra": old},
            # Filler items
            {"produto": "A1", "preco_unitario": 1.00, "mercado": "X", "data_compra": old},
            {"produto": "A2", "preco_unitario": 1.00, "mercado": "X", "data_compra": old},
        ]

        mock_db = self._mock_db(mock_data)

        with patch("services.get_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.is_initialized.return_value = True
            mock_svc.client = mock_db
            mock_get.return_value = mock_svc
            result_en = await svc.verificar_descidas_preco("123", lang="en")
            result_pt = await svc.verificar_descidas_preco("123", lang="pt")

        assert "Good news" in result_en["mensagem"]
        assert "Boas" in result_pt["mensagem"]


class TestWeeklyTrigger:
    """Tests for weekly trigger logic."""

    def test_monday_detection(self):
        """Monday = weekday 0."""
        from datetime import datetime

        # 2026-03-02 is a Monday
        dt = datetime(2026, 3, 2, 10, 0, 0)
        assert dt.weekday() == 0

    def test_week_key_format(self):
        """Week key format is year-Wxx."""
        from datetime import datetime

        dt = datetime(2026, 3, 2, 10, 0, 0)
        week_key = f"{dt.year}-W{dt.isocalendar()[1]}"
        assert week_key == "2026-W10"

    def test_flag_prevents_duplicate(self):
        """Flag set prevents re-running same week."""
        sent: set = set()
        key = "2026-W10"
        assert key not in sent
        sent.add(key)
        assert key in sent

    def test_i18n_keys_exist(self):
        """All required i18n keys return non-empty strings."""
        from services.i18n import t

        keys = [
            "mercado_price_drops_header",
            "mercado_price_drop_item",
            "mercado_price_drops_savings",
        ]
        for key in keys:
            for lang in ("en", "pt", "es"):
                result = t(
                    key,
                    lang=lang,
                    product="Leite",
                    price="1.00",
                    store="Lidl",
                    old_price="1.50",
                    change="-33",
                    total="0.50",
                )
                assert result and len(result) > 3, f"Missing: {key} / {lang}"
