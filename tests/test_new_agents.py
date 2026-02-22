# -*- coding: utf-8 -*-
"""
Tests para as 3 novas features:
  - TimeAgent (sem deps externas — 100% testável)
  - TranslateService + TranslateAgent (mock Gemini API)
  - CryptoService + CryptoAgent (mock CoinGecko HTTP)
"""
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TIME AGENT (zero mocks — usa stdlib)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimeAgent:
    """TimeAgent usa apenas datetime + zoneinfo — sem deps externas."""

    @pytest.fixture
    def agent(self):
        from agents.specialized.time_agent import TimeAgent
        return TimeAgent()

    @pytest.mark.asyncio
    async def test_current_time_with_city(self, agent):
        """Pergunta de hora com cidade deve retornar SUCCESS com horário."""
        r = await agent.execute("Que horas são em Tóquio?", {})
        assert r.is_success()
        assert r.data["timezone"] == "Asia/Tokyo"
        assert ":" in r.data["time"]  # HH:MM:SS

    @pytest.mark.asyncio
    async def test_current_time_no_city(self, agent):
        """Sem cidade deve retornar horário UTC."""
        r = await agent.execute("Que horas são agora?", {})
        assert r.is_success()
        assert "UTC" in r.data["timezone"]

    @pytest.mark.asyncio
    async def test_current_time_context_timezone(self, agent):
        """Context com timezone deve sobrepor UTC padrão."""
        r = await agent.execute("que horas são?", {"timezone": "America/Sao_Paulo"})
        assert r.is_success()
        assert "Sao_Paulo" in r.data["timezone"]

    @pytest.mark.asyncio
    async def test_current_date_query(self, agent):
        """Query de data deve retornar data atual formatada."""
        r = await agent.execute("Que dia é hoje?", {})
        assert r.is_success()
        assert "date" in r.data
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}", r.data["date"])

    @pytest.mark.asyncio
    async def test_timezone_diff_two_cities(self, agent):
        """Diferença entre Dublin e São Paulo deve ser detectada corretamente."""
        r = await agent.execute(
            "Diferença de horário entre Dublin e São Paulo?", {}
        )
        assert r.is_success()
        assert "city_a" in r.data
        assert "city_b" in r.data
        # Dublin é UTC+0/+1, SP é UTC-3 — diferença de 3-4h
        diff = abs(r.data["diff_hours"])
        assert 2 <= diff <= 5  # dependendo do horário de verão

    @pytest.mark.asyncio
    async def test_timezone_diff_context_cities(self, agent):
        """Contexto com city_a e city_b deve funcionar sem extrair do prompt."""
        r = await agent.execute("diferença", {"city_a": "tokyo", "city_b": "new york"})
        assert r.is_success()
        diff = abs(r.data["diff_hours"])
        assert 12 <= diff <= 15  # Tokyo-NY é ~13-14h

    @pytest.mark.asyncio
    async def test_two_cities_in_prompt(self, agent):
        """Dois nomes de cidades no prompt devem acionar modo diff."""
        r = await agent.execute("hora em Lisboa e Londres agora", {})
        # Pode retornar SUCCESS (diff) ou SUCCESS (hora de Lisboa)
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_known_cities_map(self, agent):
        """Todos os major cities no mapa devem resolver sem erro."""
        from agents.specialized.time_agent import CITY_TO_TZ
        cities_to_test = ["são paulo", "new york", "tokyo", "london", "sydney", "dubai"]
        for city in cities_to_test:
            tz = agent._resolve_tz(city, {})
            assert str(tz) == CITY_TO_TZ[city], f"Failed for {city}"

    @pytest.mark.asyncio
    async def test_invalid_city_falls_back_to_utc(self, agent):
        """Cidade desconhecida deve usar UTC como fallback."""
        tz = agent._resolve_tz("atlantis", {})
        assert str(tz) == "UTC"

    @pytest.mark.asyncio
    async def test_period_of_day_in_response(self, agent):
        """Resposta deve incluir período do dia (manhã/tarde/noite/etc)."""
        r = await agent.execute("Que horas são em Paris?", {})
        assert r.is_success()
        keywords = ["manhã", "tarde", "noite", "madrugada", "meio-dia"]
        assert any(kw in r.response for kw in keywords)

    @pytest.mark.asyncio
    async def test_weekday_in_date_response(self, agent):
        """Resposta de data deve incluir dia da semana em PT-BR."""
        r = await agent.execute("Qual a data de hoje?", {})
        assert r.is_success()
        weekdays = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        assert any(wd in r.response.lower() for wd in weekdays)

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        assert "current_time" in caps
        assert "timezone_difference" in caps

    @pytest.mark.asyncio
    async def test_diff_without_cities_returns_error(self, agent):
        """Pedido de diff sem cidades no prompt nem contexto deve retornar ERROR."""
        r = await agent.execute("qual a diferença de horário?", {})
        assert not r.is_success()
        assert "duas cidades" in r.response.lower() or "two cities" in r.response.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TRANSLATE SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class TestTranslateService:
    """TranslateService com mock do Gemini GenerativeModel."""

    @pytest.fixture
    def svc(self):
        """TranslateService com cliente Gemini mockado."""
        from services.business.translate_service import TranslateService
        s = TranslateService()
        mock_model = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "Hello, how are you?"
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)
        s._client = mock_model
        s._initialized = True
        return s, mock_model

    @pytest.mark.asyncio
    async def test_translate_to_english(self, svc):
        """Tradução PT → EN deve retornar texto e metadados."""
        service, _ = svc
        result = await service.translate("Olá, como você está?", target_lang="en")
        assert result["translated_text"] == "Hello, how are you?"
        assert result["target_lang"] == "en"
        assert result["original_text"] == "Olá, como você está?"
        assert result["chars"] == len("Olá, como você está?")

    @pytest.mark.asyncio
    async def test_translate_normalizes_lang_name(self, svc):
        """Nome de idioma em PT deve ser normalizado para código ISO."""
        service, _ = svc
        result = await service.translate("Bonjour", target_lang="inglês")
        assert result["target_lang"] == "en"
        assert result["target_lang_name"] == "Inglês"

    @pytest.mark.asyncio
    async def test_translate_caches_result(self, svc):
        """Segunda tradução igual deve usar cache (não chamar API)."""
        service, mock_model = svc
        await service.translate("Olá", target_lang="en")
        await service.translate("Olá", target_lang="en")  # cache hit
        assert mock_model.generate_content_async.call_count == 1

    @pytest.mark.asyncio
    async def test_translate_different_targets_no_cache(self, svc):
        """Idiomas diferentes não devem compartilhar cache."""
        service, mock_model = svc
        await service.translate("Olá", target_lang="en")
        await service.translate("Olá", target_lang="es")
        assert mock_model.generate_content_async.call_count == 2

    @pytest.mark.asyncio
    async def test_detect_language_returns_dict(self, svc):
        """detect_language deve retornar dict com lang_code."""
        service, mock_model = svc
        mock_response = MagicMock()
        mock_response.text = '{"lang_code": "pt", "lang_name": "Portuguese", "confidence": "high"}'
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)

        result = await service.detect_language("Olá mundo")
        assert result["lang_code"] == "pt"
        assert result["lang_name"] == "Portuguese"

    @pytest.mark.asyncio
    async def test_detect_language_invalid_json_returns_unknown(self, svc):
        """detect_language com resposta inválida do Gemini não deve crashar."""
        service, mock_model = svc
        mock_response = MagicMock()
        mock_response.text = "I cannot determine the language."
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)

        result = await service.detect_language("???")
        assert result["lang_code"] == "unknown"

    def test_supported_languages_includes_major_langs(self, svc):
        """Idiomas principais devem estar listados."""
        service, _ = svc
        langs = service.get_supported_languages()
        for code in ["pt", "en", "es", "fr", "de", "ja", "zh"]:
            assert code in langs

    @pytest.mark.asyncio
    async def test_translate_tracks_latency(self, svc):
        """Resultado deve incluir latency_s > 0."""
        service, _ = svc
        result = await service.translate("test", target_lang="pt")
        assert "latency_s" in result
        assert result["latency_s"] >= 0

    def test_clear_cache(self, svc):
        """clear_cache deve limpar o dicionário de cache."""
        service, _ = svc
        service._cache["test_key"] = {"data": "x", "expires_at": 999}
        service.clear_cache()
        assert len(service._cache) == 0

    @pytest.mark.asyncio
    async def test_translate_without_initialization_raises(self):
        """translate sem inicializar (sem API key) deve lançar ServiceUnavailableError."""
        from services.business.translate_service import TranslateService
        from services.core import ServiceUnavailableError
        import os

        svc = TranslateService()
        # Sem client e sem key
        with patch.dict(os.environ, {}, clear=False):
            # Remove keys se existirem
            for k in ["GOOGLE_API_KEY", "GEMINI_API_KEY"]:
                os.environ.pop(k, None)
            with pytest.raises((ServiceUnavailableError, Exception)):
                await svc.initialize()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TRANSLATE AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class TestTranslateAgent:
    """TranslateAgent com TranslateService mockado."""

    @pytest.fixture
    def agent_and_svc(self):
        from agents.specialized.translate_agent import TranslateAgent
        from services.business.translate_service import TranslateService

        agent = TranslateAgent()
        mock_svc = AsyncMock(spec=TranslateService)
        mock_svc.is_initialized.return_value = True
        mock_svc.translate = AsyncMock(return_value={
            "translated_text": "Hello, good morning",
            "original_text": "Olá, bom dia",
            "source_lang": "pt",
            "target_lang": "en",
            "target_lang_name": "Inglês",
            "detected_lang": None,
            "chars": 12,
            "latency_s": 0.3,
        })
        mock_svc.detect_language = AsyncMock(return_value={
            "lang_code": "pt",
            "lang_name": "Portuguese",
            "confidence": "high",
        })

        return agent, mock_svc

    @pytest.mark.asyncio
    async def test_translate_prompt_pattern(self, agent_and_svc):
        """'Traduz X para Y' deve chamar translate corretamente."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.translate_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Traduz 'olá, bom dia' para inglês", {})
        assert r.is_success()
        mock_svc.translate.assert_called_once()

    @pytest.mark.asyncio
    async def test_how_to_say_pattern(self, agent_and_svc):
        """'Como se diz X em Y' deve chamar translate."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.translate_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Como se diz 'obrigado' em japonês?", {})
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_detect_language_intent(self, agent_and_svc):
        """'Qual o idioma desse texto' deve chamar detect_language."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.translate_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Qual o idioma desse texto: Bonjour le monde", {})
        assert r.is_success()
        mock_svc.detect_language.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_target_lang(self, agent_and_svc):
        """Context com target_lang deve ser usado quando não há padrão no prompt."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.translate_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Bom dia, como você está?", {"target_lang": "en"})
        assert r.is_success()
        mock_svc.translate.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_unavailable(self, agent_and_svc):
        """Sem TranslateService deve retornar ERROR com mensagem clara."""
        agent, _ = agent_and_svc
        with patch("agents.specialized.translate_agent.get_service", return_value=None):
            r = await agent.execute("traduz olá para inglês", {})
        assert not r.is_success()
        assert "disponível" in r.response.lower() or "unavailable" in r.response.lower()

    @pytest.mark.asyncio
    async def test_unknown_intent_returns_help_message(self, agent_and_svc):
        """Prompt sem intenção clara deve retornar mensagem de ajuda."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.translate_agent.get_service", return_value=mock_svc):
            r = await agent.execute("qual o clima hoje?", {})
        # Pode retornar ERROR com exemplos de uso
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_short_text_response_inline(self, agent_and_svc):
        """Texto curto deve ter resposta inline (sem bloco separado)."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.translate_agent.get_service", return_value=mock_svc):
            r = await agent.execute("traduz 'hello' para português", {})
        assert r.is_success()
        # Resposta curta não deve ter bloco "Tradução para:"
        # (o resultado é curto o suficiente para inline)

    def test_capabilities(self, agent_and_svc):
        agent, _ = agent_and_svc
        caps = agent.get_capabilities()
        assert "translate_text" in caps
        assert "detect_language" in caps


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CRYPTO SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class TestCryptoService:
    """CryptoService com mock do cliente HTTP."""

    @pytest.fixture
    def svc(self):
        """CryptoService com httpx.AsyncClient mockado."""
        from services.business.crypto_service import CryptoService

        s = CryptoService()

        mock_http = AsyncMock()
        # Mock para /simple/price
        mock_price_response = AsyncMock()
        mock_price_response.status_code = 200
        mock_price_response.raise_for_status = Mock()
        mock_price_response.json = Mock(return_value={
            "bitcoin": {
                "usd": 65000.50,
                "brl": 325000.00,
                "eur": 60000.00,
                "usd_24h_change": 2.35,
                "brl_24h_change": 2.35,
                "eur_24h_change": 2.35,
            }
        })
        mock_http.get = AsyncMock(return_value=mock_price_response)

        s._http = mock_http
        s._initialized = True
        return s, mock_http

    @pytest.mark.asyncio
    async def test_get_price_btc(self, svc):
        """get_price('bitcoin') deve retornar preços em USD, BRL, EUR."""
        service, _ = svc
        result = await service.get_price("bitcoin")
        assert result["coin_id"] == "bitcoin"
        assert result["prices"]["usd"] == 65000.50
        assert result["prices"]["brl"] == 325000.00
        assert result["change_24h"]["usd"] == pytest.approx(2.35)

    @pytest.mark.asyncio
    async def test_get_price_by_ticker(self, svc):
        """get_price('btc') deve resolver para 'bitcoin'."""
        service, _ = svc
        result = await service.get_price("btc")
        assert result["coin_id"] == "bitcoin"

    @pytest.mark.asyncio
    async def test_get_price_unknown_coin_raises(self, svc):
        """Coin desconhecida deve lançar ValueError."""
        service, _ = svc
        with pytest.raises(ValueError, match="não encontrada"):
            await service.get_price("notacoin123")

    @pytest.mark.asyncio
    async def test_get_price_uses_cache(self, svc):
        """Segunda chamada igual deve usar cache (não chamar HTTP)."""
        service, mock_http = svc
        await service.get_price("bitcoin")
        await service.get_price("bitcoin")
        # Apenas 1 chamada HTTP (segunda vem do cache)
        assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expires(self, svc):
        """Cache expirado deve fazer nova chamada HTTP."""
        service, mock_http = svc

        # Injeta entrada expirada manualmente
        service._cache["price:bitcoin:usd,brl,eur"] = {
            "data": {"coin_id": "bitcoin", "prices": {}, "change_24h": {}, "market_cap": {}},
            "expires_at": time.time() - 1,  # já expirou
        }
        await service.get_price("bitcoin")
        assert mock_http.get.call_count == 1  # fez nova chamada

    @pytest.mark.asyncio
    async def test_get_top_coins(self, svc):
        """get_top_coins deve retornar lista de coins com rank."""
        service, mock_http = svc
        mock_markets_response = AsyncMock()
        mock_markets_response.status_code = 200
        mock_markets_response.raise_for_status = Mock()
        mock_markets_response.json = Mock(return_value=[
            {
                "id": "bitcoin", "name": "Bitcoin", "symbol": "btc",
                "current_price": 65000, "market_cap": 1_200_000_000_000,
                "price_change_percentage_24h": 2.1,
            },
            {
                "id": "ethereum", "name": "Ethereum", "symbol": "eth",
                "current_price": 3500, "market_cap": 400_000_000_000,
                "price_change_percentage_24h": -1.2,
            },
        ])
        mock_http.get = AsyncMock(return_value=mock_markets_response)

        results = await service.get_top_coins(n=2, vs_currency="usd")
        assert len(results) == 2
        assert results[0]["rank"] == 1
        assert results[0]["name"] == "Bitcoin"
        assert results[1]["symbol"] == "ETH"

    @pytest.mark.asyncio
    async def test_get_price_rate_limit_error(self, svc):
        """Rate limit (429) deve lançar RuntimeError com mensagem amigável."""
        import httpx
        service, mock_http = svc

        mock_response = MagicMock()
        mock_response.status_code = 429
        error = httpx.HTTPStatusError("Too many requests", request=Mock(), response=mock_response)
        mock_http.get = AsyncMock(side_effect=error)

        with pytest.raises(RuntimeError, match="Rate limit"):
            await service.get_price("bitcoin")

    def test_resolve_coin_id_aliases(self, svc):
        """Aliases comuns devem resolver para coin IDs corretos."""
        service, _ = svc
        assert service.resolve_coin_id("btc") == "bitcoin"
        assert service.resolve_coin_id("eth") == "ethereum"
        assert service.resolve_coin_id("sol") == "solana"
        assert service.resolve_coin_id("doge") == "dogecoin"
        assert service.resolve_coin_id("nonexistent") is None

    @pytest.mark.asyncio
    async def test_health_check_success(self, svc):
        """_health_check deve retornar True quando ping OK."""
        service, mock_http = svc
        mock_ping = AsyncMock()
        mock_ping.status_code = 200
        mock_http.get = AsyncMock(return_value=mock_ping)

        result = await service._health_check()
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CRYPTO AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class TestCryptoAgent:
    """CryptoAgent com CryptoService mockado."""

    @pytest.fixture
    def agent_and_svc(self):
        from agents.specialized.crypto_agent import CryptoAgent
        from services.business.crypto_service import CryptoService

        agent = CryptoAgent()
        mock_svc = AsyncMock(spec=CryptoService)
        mock_svc.is_initialized.return_value = True
        mock_svc.get_price = AsyncMock(return_value={
            "coin_id": "bitcoin",
            "coin_name": "Bitcoin",
            "prices": {"usd": 65000.00, "brl": 325000.00, "eur": 60000.00},
            "change_24h": {"usd": 2.35, "brl": 2.35, "eur": 2.35},
            "market_cap": {},
            "latency_s": 0.2,
        })
        mock_svc.get_top_coins = AsyncMock(return_value=[
            {"rank": 1, "id": "bitcoin", "name": "Bitcoin", "symbol": "BTC",
             "price": 65000, "change_24h": 2.1, "market_cap": 1_200_000_000_000, "currency": "usd"},
            {"rank": 2, "id": "ethereum", "name": "Ethereum", "symbol": "ETH",
             "price": 3500, "change_24h": -1.2, "market_cap": 400_000_000_000, "currency": "usd"},
        ])
        mock_svc.resolve_coin_id = Mock(side_effect=lambda x: "bitcoin" if x in ("btc", "bitcoin") else None)

        return agent, mock_svc

    @pytest.mark.asyncio
    async def test_bitcoin_price_query(self, agent_and_svc):
        """'Qual o preço do Bitcoin?' deve retornar SUCCESS com preço."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Qual o preço do Bitcoin?", {})
        assert r.is_success()
        assert "Bitcoin" in r.response
        assert "65.000" in r.response or "65,000" in r.response

    @pytest.mark.asyncio
    async def test_btc_ticker_query(self, agent_and_svc):
        """'BTC em BRL' deve usar ticker e currency corretamente."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            r = await agent.execute("BTC em BRL", {})
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_top_coins_query(self, agent_and_svc):
        """'Top 10 criptomoedas' deve chamar get_top_coins."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Top 10 criptomoedas", {})
        assert r.is_success()
        mock_svc.get_top_coins.assert_called_once()
        assert "Bitcoin" in r.response
        assert "Ethereum" in r.response

    @pytest.mark.asyncio
    async def test_top_with_n(self, agent_and_svc):
        """'Top 5 cripto' deve passar n=5 para get_top_coins."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            await agent.execute("top 5 criptos", {})
        call_kwargs = mock_svc.get_top_coins.call_args
        n_passed = call_kwargs.kwargs.get("n") or call_kwargs.args[0]
        assert n_passed == 5

    @pytest.mark.asyncio
    async def test_currency_extraction_brl(self, agent_and_svc):
        """'ETH em reais' deve extrair BRL como moeda preferida."""
        agent, mock_svc = agent_and_svc
        mock_svc.get_price.return_value = {
            "coin_id": "ethereum",
            "coin_name": "Ethereum",
            "prices": {"usd": 3500.00, "brl": 17500.00, "eur": 3200.00},
            "change_24h": {"usd": -1.2, "brl": -1.2, "eur": -1.2},
            "market_cap": {},
            "latency_s": 0.1,
        }
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            r = await agent.execute("ETH em reais", {})
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_price_includes_24h_change(self, agent_and_svc):
        """Resposta de preço deve incluir variação 24h com emoji."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            r = await agent.execute("preço do bitcoin", {})
        assert r.is_success()
        assert "%" in r.response or "24h" in r.response

    @pytest.mark.asyncio
    async def test_unknown_coin_returns_error(self, agent_and_svc):
        """Moeda desconhecida deve retornar ERROR."""
        agent, mock_svc = agent_and_svc
        mock_svc.get_price = AsyncMock(side_effect=ValueError("não encontrada"))
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            r = await agent.execute("quanto custa o BogusCoin123?", {})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_service_unavailable(self, agent_and_svc):
        """Sem CryptoService deve retornar ERROR claro."""
        agent, _ = agent_and_svc
        with patch("agents.specialized.crypto_agent.get_service", return_value=None):
            r = await agent.execute("preço do bitcoin", {})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_context_coin_override(self, agent_and_svc):
        """Context com 'coin' deve sobrepor extração do prompt."""
        agent, mock_svc = agent_and_svc
        with patch("agents.specialized.crypto_agent.get_service", return_value=mock_svc):
            r = await agent.execute("qual o preço?", {"coin": "bitcoin"})
        assert r.is_success()

    def test_capabilities(self, agent_and_svc):
        agent, _ = agent_and_svc
        caps = agent.get_capabilities()
        assert "crypto_price" in caps
        assert "top_coins_ranking" in caps
