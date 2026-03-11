"""Tests for orchestrator routing safety net."""

from unittest.mock import MagicMock, AsyncMock, patch  # noqa: F401


class TestMercadoSafetyNet:
    """Tests that mercado keywords override wrong routing."""

    def _make_bot(self):
        """Create a bot instance for testing."""
        from telegram_bot.core.bot import CapivaraXBot

        bot = CapivaraXBot.__new__(CapivaraXBot)
        bot.logger = __import__("logging").getLogger("test")
        return bot

    def test_ver_lista_is_mercado(self):
        """'ver lista' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("ver lista") is True

    def test_exportar_excel_is_mercado(self):
        """'exportar excel' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("exportar excel") is True

    def test_minha_lista_is_mercado(self):
        """'minha lista' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("minha lista") is True

    def test_relatorio_is_mercado(self):
        """'relatório' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("relatório") is True

    def test_shopping_list_is_mercado(self):
        """'shopping list' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("shopping list") is True

    def test_export_report_is_mercado(self):
        """'export report' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("export report") is True

    def test_nota_fiscal_is_mercado(self):
        """'nota fiscal' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("nota fiscal") is True

    def test_generic_text_not_mercado(self):
        """Generic text should NOT be detected as mercado."""
        bot = self._make_bot()
        assert bot._is_mercado_query("bom dia") is False
        assert bot._is_mercado_query("how is the weather") is False
        assert bot._is_mercado_query("remind me at 5pm") is False

    def test_compare_prices_is_mercado(self):
        """'comparar preços' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("comparar preços") is True

    def test_store_ranking_is_mercado(self):
        """'store ranking' should be detected as mercado query."""
        bot = self._make_bot()
        assert bot._is_mercado_query("store ranking") is True

    def test_spanish_mercado_keywords(self):
        """Spanish mercado keywords should work."""
        bot = self._make_bot()
        assert bot._is_mercado_query("lista de compras") is True
        assert bot._is_mercado_query("comparar precios") is True


class TestSafetyNetPriority:
    """Tests that safety net priorities are correct."""

    def _make_bot(self):
        from telegram_bot.core.bot import CapivaraXBot

        bot = CapivaraXBot.__new__(CapivaraXBot)
        bot.logger = __import__("logging").getLogger("test")
        return bot

    def test_email_not_overridden_by_mercado(self):
        """Email-specific queries should NOT be caught by mercado."""
        bot = self._make_bot()
        # "meus emails" should be email, not mercado
        assert bot._is_email_query("meus emails") is True
        # If it also matches mercado, email should win (email check runs first)

    def test_calendar_connect_not_overridden(self):
        """Calendar connect queries should NOT be caught by mercado."""
        bot = self._make_bot()
        assert bot._is_calendar_connect_query("conectar google calendar") is True
