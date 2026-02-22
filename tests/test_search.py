# -*- coding: utf-8 -*-
"""
tests/test_search.py
======================
Testes para SearchService e SearchAgent (Serper API).

Cobre:
  - Service: search() — resultados orgânicos, answer box, knowledge graph
  - Service: search_places() — lugares com endereço, telefone, rating
  - Service: search_news() — notícias recentes
  - Service: search_shopping() — produtos com preço
  - Service: erros — 401 (key inválida), 429 (quota), HTTP erro
  - Service: parsers — _parse_organic, _parse_places, _parse_news, _parse_shopping
  - Agent: detecção de intent (places, shopping, news, general)
  - Agent: detecção de país
  - Agent: formato de resposta (places, shopping, news, general)
  - Agent: answer box no topo da resposta
  - Agent: fallback shopping → general quando sem produtos
  - Agent: erro amigável API key ausente
  - Agent: erro amigável quota esgotada
  - Agent: service unavailable
  - Agent: query vazia → mensagem de ajuda
  - Agent: context override (search_type, country, num_results)
  - Agent: capabilities
"""

from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORIES
# ═══════════════════════════════════════════════════════════════════════════════

def _serper_organic_response(n=3) -> Dict:
    return {
        "organic": [
            {
                "position": i + 1,
                "title": f"Result {i + 1}",
                "link": f"https://example{i}.com",
                "snippet": f"Snippet {i + 1}",
                "date": "Feb 21, 2026",
            }
            for i in range(n)
        ],
        "answerBox": {
            "title": "Bitcoin Price",
            "answer": "$95,000",
            "link": "https://coinmarketcap.com",
        },
        "knowledgeGraph": {
            "title": "Bitcoin",
            "type": "Cryptocurrency",
            "description": "A decentralized digital currency.",
            "website": "https://bitcoin.org",
        },
    }


def _serper_places_response(n=3) -> Dict:
    return {
        "places": [
            {
                "title": f"Place {i + 1}",
                "address": f"{i + 1} Main Street, Dublin",
                "phoneNumber": f"+353 1 000 000{i}",
                "rating": 4.5,
                "ratingCount": 120 + i * 10,
                "type": "Restaurant",
                "website": f"https://place{i}.ie",
                "openState": "Open now",
                "latitude": 53.33 + i * 0.01,
                "longitude": -6.26 + i * 0.01,
                "thumbnailUrl": f"https://img{i}.jpg",
                "openingHours": ["Mon-Fri: 9am-9pm", "Sat-Sun: 10am-8pm"],
            }
            for i in range(n)
        ]
    }


def _serper_news_response(n=3) -> Dict:
    return {
        "news": [
            {
                "title": f"News {i + 1}",
                "link": f"https://news{i}.com/article",
                "snippet": f"News snippet {i + 1}",
                "source": f"Source {i + 1}",
                "date": "Feb 21, 2026",
                "imageUrl": f"https://img{i}.jpg",
            }
            for i in range(n)
        ]
    }


def _serper_shopping_response(n=3) -> Dict:
    return {
        "shopping": [
            {
                "title": f"Product {i + 1}",
                "price": f"€{(i + 1) * 10}.99",
                "source": f"Shop {i + 1}",
                "link": f"https://shop{i}.com/product",
                "rating": 4.0 + i * 0.1,
                "ratingCount": 50 + i * 5,
                "delivery": "Free delivery",
                "imageUrl": f"https://img{i}.jpg",
            }
            for i in range(n)
        ]
    }


def _mock_http_response(data: Dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def search_service():
    from services.business.search_service import SearchService
    svc = SearchService()
    svc._api_key = "test_serper_key"
    svc._client = AsyncMock()
    svc._initialized = True
    return svc


@pytest.fixture
def search_agent():
    from agents.specialized.search_agent import SearchAgent
    return SearchAgent()


@pytest.fixture
def mock_svc():
    from services.business.search_service import SearchService
    svc = AsyncMock(spec=SearchService)
    svc.is_initialized.return_value = True

    svc.search = AsyncMock(return_value={
        "results": [
            {"position": 1, "title": "Result 1", "link": "https://r1.com",
             "snippet": "Snippet 1", "date": ""},
            {"position": 2, "title": "Result 2", "link": "https://r2.com",
             "snippet": "Snippet 2", "date": ""},
        ],
        "total_results": 2,
        "answer_box": {"title": "Answer", "answer": "42", "link": "https://ans.com"},
        "knowledge_graph": {},
    })

    svc.search_places = AsyncMock(return_value={
        "places": [
            {"title": "Cantina Italiana", "address": "1 Grafton St, Dublin",
             "phone": "+353 1 000 0001", "rating": 4.8, "reviews": 320,
             "type": "Restaurant", "website": "https://cantina.ie",
             "open_now": "Open now", "coordinates": {"lat": 53.33, "lng": -6.26},
             "hours": ["Mon-Sun: 12pm-10pm"], "thumbnail": ""},
        ],
        "total_places": 1,
    })

    svc.search_news = AsyncMock(return_value={
        "news": [
            {"title": "Bitcoin atinge $100k", "link": "https://news.com",
             "snippet": "Bitcoin...", "source": "Reuters", "date": "Feb 21, 2026",
             "image": ""},
        ],
        "total_news": 1,
    })

    svc.search_shopping = AsyncMock(return_value={
        "products": [
            {"title": "Livro Python", "price": "€29.99", "source": "Amazon",
             "link": "https://amz.com/p1", "rating": 4.7, "reviews": 230,
             "delivery": "Free delivery", "image": ""},
        ],
        "total_products": 1,
    })

    return svc


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SearchService — search()
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchServiceSearch:

    @pytest.mark.asyncio
    async def test_search_returns_results(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_organic_response(3))
        )
        result = await search_service.search("Python tutorial")
        assert len(result["results"]) == 3
        assert result["results"][0]["title"] == "Result 1"
        assert result["results"][0]["link"] == "https://example0.com"

    @pytest.mark.asyncio
    async def test_search_returns_answer_box(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_organic_response())
        )
        result = await search_service.search("Bitcoin price")
        assert result["answer_box"]["answer"] == "$95,000"

    @pytest.mark.asyncio
    async def test_search_returns_knowledge_graph(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_organic_response())
        )
        result = await search_service.search("Bitcoin")
        assert result["knowledge_graph"]["title"] == "Bitcoin"

    @pytest.mark.asyncio
    async def test_search_401_raises(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response({}, status_code=401)
        )
        with pytest.raises(RuntimeError, match="inválida"):
            await search_service.search("test")

    @pytest.mark.asyncio
    async def test_search_429_raises(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response({}, status_code=429)
        )
        with pytest.raises(RuntimeError, match="[Qq]uota"):
            await search_service.search("test")

    @pytest.mark.asyncio
    async def test_search_passes_country_param(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_organic_response())
        )
        await search_service.search("restaurantes", country="br")
        call_json = search_service._client.post.call_args.kwargs.get("json", {})
        assert call_json.get("gl") == "br"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SearchService — search_places()
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchServicePlaces:

    @pytest.mark.asyncio
    async def test_places_returns_structured_data(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_places_response(2))
        )
        result = await search_service.search_places("italian restaurant Dublin")
        assert len(result["places"]) == 2
        assert result["places"][0]["title"] == "Place 1"
        assert result["places"][0]["address"] == "1 Main Street, Dublin"
        assert result["places"][0]["phone"] == "+353 1 000 0000"
        assert result["places"][0]["rating"] == 4.5

    @pytest.mark.asyncio
    async def test_places_has_coordinates(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_places_response(1))
        )
        result = await search_service.search_places("pharmacy Dublin")
        coords = result["places"][0]["coordinates"]
        assert "lat" in coords
        assert "lng" in coords

    @pytest.mark.asyncio
    async def test_places_empty_returns_empty_list(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response({"places": []})
        )
        result = await search_service.search_places("xyz place")
        assert result["places"] == []
        assert result["total_places"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SearchService — search_news() e search_shopping()
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchServiceNewsAndShopping:

    @pytest.mark.asyncio
    async def test_news_returns_structured_data(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_news_response(3))
        )
        result = await search_service.search_news("Bitcoin")
        assert len(result["news"]) == 3
        assert result["news"][0]["title"] == "News 1"
        assert result["news"][0]["source"] == "Source 1"

    @pytest.mark.asyncio
    async def test_shopping_returns_products(self, search_service):
        search_service._client.post = AsyncMock(
            return_value=_mock_http_response(_serper_shopping_response(2))
        )
        result = await search_service.search_shopping("Python book")
        assert len(result["products"]) == 2
        assert result["products"][0]["price"] == "€10.99"
        assert result["products"][0]["source"] == "Shop 1"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SearchAgent — detecção de intent e país
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchAgentDetection:

    def test_detect_places(self):
        from agents.specialized.search_agent import _detect_search_type
        assert _detect_search_type("restaurante italiano perto de mim") == "places"
        assert _detect_search_type("farmácia aberta agora em Dublin") == "places"
        assert _detect_search_type("livraria perto do centro") == "places"

    def test_detect_shopping(self):
        from agents.specialized.search_agent import _detect_search_type
        assert _detect_search_type("quanto custa iPhone 15") == "shopping"
        assert _detect_search_type("comprar livro de Python") == "shopping"
        assert _detect_search_type("presente para mulher barato") == "shopping"

    def test_detect_news(self):
        from agents.specialized.search_agent import _detect_search_type
        assert _detect_search_type("notícias sobre Bitcoin hoje") == "news"
        assert _detect_search_type("últimas notícias de tecnologia") == "news"

    def test_detect_general(self):
        from agents.specialized.search_agent import _detect_search_type
        assert _detect_search_type("site oficial da Duffel API") == "general"
        assert _detect_search_type("documentação do FastAPI") == "general"

    def test_extract_country_ireland_default(self):
        from agents.specialized.search_agent import _extract_country
        assert _extract_country("restaurante em Dublin", {}) == "ie"

    def test_extract_country_brazil(self):
        from agents.specialized.search_agent import _extract_country
        assert _extract_country("livraria em São Paulo", {}) == "br"

    def test_extract_country_context_override(self):
        from agents.specialized.search_agent import _extract_country
        assert _extract_country("qualquer coisa", {"country": "us"}) == "us"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SearchAgent — intents e respostas
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchAgentIntents:

    @pytest.mark.asyncio
    async def test_places_intent(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute(
                "restaurante italiano perto de mim", {}
            )
        assert r.is_success()
        mock_svc.search_places.assert_called_once()
        assert "Cantina Italiana" in r.response

    @pytest.mark.asyncio
    async def test_places_response_has_address(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("farmácia aberta Dublin", {})
        assert "Grafton St" in r.response or "Dublin" in r.response

    @pytest.mark.asyncio
    async def test_places_response_has_rating(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("restaurante perto", {})
        assert "4.8" in r.response or "⭐" in r.response

    @pytest.mark.asyncio
    async def test_news_intent(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("notícias sobre Bitcoin hoje", {})
        assert r.is_success()
        mock_svc.search_news.assert_called_once()
        assert "Bitcoin atinge" in r.response

    @pytest.mark.asyncio
    async def test_shopping_intent(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("comprar livro de Python", {})
        assert r.is_success()
        mock_svc.search_shopping.assert_called_once()
        assert "€29.99" in r.response

    @pytest.mark.asyncio
    async def test_general_intent(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("documentação FastAPI", {})
        assert r.is_success()
        mock_svc.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_general_shows_answer_box(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute(
                "Bitcoin price", {"search_type": "general"}
            )
        assert "42" in r.response or "Answer" in r.response

    @pytest.mark.asyncio
    async def test_context_search_type_override(self, search_agent, mock_svc):
        """Context pode forçar um tipo específico de busca."""
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            await search_agent.execute(
                "Python",
                {"search_type": "shopping"}
            )
        mock_svc.search_shopping.assert_called_once()

    @pytest.mark.asyncio
    async def test_shopping_fallback_to_general(self, search_agent, mock_svc):
        """Se shopping não retorna produtos, faz fallback para busca geral."""
        mock_svc.search_shopping.return_value = {"products": [], "total_products": 0}
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("comprar algo muito específico xpto", {})
        assert r.is_success()
        mock_svc.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_places_empty_returns_error(self, search_agent, mock_svc):
        mock_svc.search_places.return_value = {"places": [], "total_places": 0}
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("restaurante perto", {})
        assert not r.is_success()
        assert "não encontrei" in r.response.lower()

    @pytest.mark.asyncio
    async def test_empty_query_returns_help(self, search_agent, mock_svc):
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("", {})
        assert not r.is_success()
        assert "buscar" in r.response.lower() or "busca" in r.response.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SearchAgent — erros
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchAgentErrors:

    @pytest.mark.asyncio
    async def test_service_unavailable(self, search_agent):
        with patch("agents.specialized.search_agent.get_service", return_value=None):
            r = await search_agent.execute("restaurante Dublin", {})
        assert not r.is_success()
        assert "SERPER_API_KEY" in r.response

    @pytest.mark.asyncio
    async def test_api_key_error_friendly(self, search_agent, mock_svc):
        mock_svc.search_places.side_effect = RuntimeError(
            "SERPER_API_KEY inválida."
        )
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("restaurante perto", {})
        assert not r.is_success()
        assert "SERPER_API_KEY" in r.response

    @pytest.mark.asyncio
    async def test_quota_error_friendly(self, search_agent, mock_svc):
        mock_svc.search_places.side_effect = RuntimeError(
            "Quota Serper esgotada."
        )
        with patch("agents.specialized.search_agent.get_service", return_value=mock_svc):
            r = await search_agent.execute("restaurante perto", {})
        assert not r.is_success()
        assert "quota" in r.response.lower() or "limite" in r.response.lower()

    def test_capabilities(self, search_agent):
        caps = search_agent.get_capabilities()
        assert "web_search" in caps
        assert "places_search" in caps
        assert "shopping_search" in caps
        assert "business_finder" in caps
