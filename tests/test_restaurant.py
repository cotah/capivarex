# -*- coding: utf-8 -*-
"""
tests/test_restaurant.py
=========================
Testes unitários para RestaurantService e RestaurantAgent.

Cobertura:
- _resolve_cuisine_type: mapeamento de texto → tipo Google Places
- _price_label: formatação de price level
- _parse_place / _parse_place_detail: normalização de dados brutos
- format_restaurant / format_list: formatação para Telegram
- Cache (hit/miss/TTL)
- RestaurantService.search_nearby: happy path, filtros, API error
- RestaurantService.search_by_text: happy path, sem resultados, API error
- RestaurantService.get_details: happy path, cache hit
- RestaurantAgent intent detection e extraction helpers
- RestaurantAgent.execute: search, detail, sem localização, sem resultados,
  service unavailable, API error, sem user_id
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Dados de fixture ────────────────────────────────────────────────────────

RAW_PLACE = {
    "id": "ChIJabc123",
    "displayName": {"text": "Tasca do João"},
    "formattedAddress": "Rua da Alegria 10, Lisboa, Portugal",
    "rating": 4.5,
    "userRatingCount": 320,
    "priceLevel": "PRICE_LEVEL_MODERATE",
    "currentOpeningHours": {
        "openNow": True,
        "weekdayDescriptions": ["Segunda: 12:00 – 23:00"],
    },
    "primaryType": "restaurant",
    "nationalPhoneNumber": "+351 21 000 0000",
    "websiteUri": "https://tascadojoao.pt",
    "editorialSummary": {"text": "Tasca típica portuguesa"},
    "location": {"latitude": 38.7169, "longitude": -9.1395},
}

RAW_PLACE_DETAIL = {
    **RAW_PLACE,
    "googleMapsUri": "https://maps.google.com/?cid=123",
    "regularOpeningHours": {
        "weekdayDescriptions": [
            "Segunda: 12:00 – 23:00",
            "Terça: 12:00 – 23:00",
            "Quarta: 12:00 – 23:00",
            "Quinta: 12:00 – 23:00",
            "Sexta: 12:00 – 00:00",
            "Sábado: 13:00 – 00:00",
            "Domingo: Fechado",
        ]
    },
    "reviews": [
        {
            "authorAttribution": {"displayName": "Maria S."},
            "rating": 5,
            "text": {"text": "Excelente bacalhau!"},
            "relativePublishTimeDescription": "há 2 semanas",
        }
    ],
    "dineIn": True,
    "takeout": True,
    "delivery": False,
    "reservable": True,
}

PARSED_PLACE = {
    "place_id": "ChIJabc123",
    "name": "Tasca do João",
    "rating": 4.5,
    "review_count": 320,
    "price": "€€",
    "address": "Rua da Alegria 10, Lisboa, Portugal",
    "phone": "+351 21 000 0000",
    "is_open": True,
    "maps_url": "https://www.google.com/maps/place/?q=place_id:ChIJabc123",
}


# ─── RestaurantService helpers ───────────────────────────────────────────────


class TestCuisineMap:
    def test_pizza(self):
        from services.integrations.restaurant_service import _resolve_cuisine_type

        assert _resolve_cuisine_type("quero pizza") == "pizza_restaurant"

    def test_sushi(self):
        from services.integrations.restaurant_service import _resolve_cuisine_type

        assert _resolve_cuisine_type("sushi perto de mim") == "sushi_restaurant"

    def test_japones(self):
        from services.integrations.restaurant_service import _resolve_cuisine_type

        assert _resolve_cuisine_type("restaurante japonês") == "japanese_restaurant"

    def test_burger(self):
        from services.integrations.restaurant_service import _resolve_cuisine_type

        assert (
            _resolve_cuisine_type("melhor burger da cidade") == "hamburger_restaurant"
        )

    def test_vegano(self):
        from services.integrations.restaurant_service import _resolve_cuisine_type

        assert _resolve_cuisine_type("comida vegana") == "vegan_restaurant"

    def test_unknown(self):
        from services.integrations.restaurant_service import _resolve_cuisine_type

        assert _resolve_cuisine_type("comida típica alentejana") is None


class TestPriceLabel:
    def test_moderate(self):
        from services.integrations.restaurant_service import _price_label

        assert _price_label("PRICE_LEVEL_MODERATE") == "€€"

    def test_expensive(self):
        from services.integrations.restaurant_service import _price_label

        assert _price_label("PRICE_LEVEL_EXPENSIVE") == "€€€"

    def test_none(self):
        from services.integrations.restaurant_service import _price_label

        assert _price_label(None) == "N/D"

    def test_unknown(self):
        from services.integrations.restaurant_service import _price_label

        assert _price_label("PRICE_LEVEL_WHATEVER") == "N/D"


class TestParsePlace:
    def test_basic_fields(self):
        from services.integrations.restaurant_service import RestaurantService

        p = RestaurantService._parse_place(RAW_PLACE)
        assert p["name"] == "Tasca do João"
        assert p["rating"] == 4.5
        assert p["review_count"] == 320
        assert p["price"] == "€€"
        assert p["is_open"] is True
        assert p["phone"] == "+351 21 000 0000"
        assert "ChIJabc123" in p["maps_url"]

    def test_missing_phone(self):
        from services.integrations.restaurant_service import RestaurantService

        raw = {**RAW_PLACE}
        raw.pop("nationalPhoneNumber", None)
        p = RestaurantService._parse_place(raw)
        assert p["phone"] == ""

    def test_no_opening_hours(self):
        from services.integrations.restaurant_service import RestaurantService

        raw = {**RAW_PLACE, "currentOpeningHours": {}}
        p = RestaurantService._parse_place(raw)
        assert p["is_open"] is None


class TestParsePlaceDetail:
    def test_services(self):
        from services.integrations.restaurant_service import RestaurantService

        d = RestaurantService._parse_place_detail(RAW_PLACE_DETAIL)
        assert "🍽️ Comer no local" in d["services"]
        assert "🥡 Take away" in d["services"]
        assert "📅 Aceita reservas" in d["services"]
        assert "🛵 Entrega" not in d["services"]

    def test_weekly_hours(self):
        from services.integrations.restaurant_service import RestaurantService

        d = RestaurantService._parse_place_detail(RAW_PLACE_DETAIL)
        assert len(d["weekly_hours"]) == 7

    def test_reviews(self):
        from services.integrations.restaurant_service import RestaurantService

        d = RestaurantService._parse_place_detail(RAW_PLACE_DETAIL)
        assert len(d["reviews"]) == 1
        assert d["reviews"][0]["author"] == "Maria S."
        assert d["reviews"][0]["rating"] == 5

    def test_maps_url_from_google(self):
        from services.integrations.restaurant_service import RestaurantService

        d = RestaurantService._parse_place_detail(RAW_PLACE_DETAIL)
        assert "maps.google.com" in d["maps_url"]


class TestFormatRestaurant:
    def test_format_basic(self):
        from services.integrations.restaurant_service import RestaurantService

        text = RestaurantService.format_restaurant(PARSED_PLACE, 0)
        assert "Tasca do João" in text
        assert "4.5" in text
        assert "🥇" in text
        assert "🟢" in text  # aberto

    def test_format_index_medals(self):
        from services.integrations.restaurant_service import RestaurantService

        assert "🥇" in RestaurantService.format_restaurant(PARSED_PLACE, 0)
        assert "🥈" in RestaurantService.format_restaurant(PARSED_PLACE, 1)
        assert "🥉" in RestaurantService.format_restaurant(PARSED_PLACE, 2)

    def test_format_closed(self):
        from services.integrations.restaurant_service import RestaurantService

        place = {**PARSED_PLACE, "is_open": False}
        text = RestaurantService.format_restaurant(place, 0)
        assert "🔴" in text

    def test_format_list_empty(self):
        from services.integrations.restaurant_service import RestaurantService

        assert "Nenhum" in RestaurantService.format_list([])

    def test_format_list_with_places(self):
        from services.integrations.restaurant_service import RestaurantService

        text = RestaurantService.format_list([PARSED_PLACE, PARSED_PLACE])
        assert "2" in text
        assert "Tasca do João" in text


class TestRestaurantServiceCache:
    def _svc(self):
        from services.integrations.restaurant_service import RestaurantService

        svc = RestaurantService.__new__(RestaurantService)
        svc.name = "restaurant"
        svc.logger = MagicMock()
        svc._api_key = "fake-key"
        svc._initialized = True
        svc._cache = {}
        return svc

    def test_cache_miss(self):
        svc = self._svc()
        assert svc._get_cache("missing_key") is None

    def test_cache_hit(self):
        svc = self._svc()
        svc._set_cache("key1", ["data"])
        assert svc._get_cache("key1") == ["data"]

    def test_cache_expired(self):
        svc = self._svc()
        svc._cache["key1"] = {"data": ["data"], "expires_at": time.time() - 1}
        assert svc._get_cache("key1") is None


# ─── RestaurantService API calls ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestRestaurantServiceSearch:
    def _svc(self):
        from services.integrations.restaurant_service import RestaurantService

        svc = RestaurantService.__new__(RestaurantService)
        svc.name = "restaurant"
        svc.logger = MagicMock()
        svc._api_key = "fake-key"
        svc._initialized = True
        svc._cache = {}
        return svc

    def _mock_response(self, places):
        resp = AsyncMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={"places": places})
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    def _mock_session(self, resp):
        session = AsyncMock()
        session.post = MagicMock(return_value=resp)
        session.get = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        return session

    async def test_search_nearby_returns_sorted_by_rating(self):
        svc = self._svc()
        low = {**RAW_PLACE, "rating": 3.0, "id": "low"}
        high = {**RAW_PLACE, "rating": 4.8, "id": "high"}
        resp = self._mock_response([low, high])
        session = self._mock_session(resp)

        with patch("aiohttp.ClientSession", return_value=session):
            with patch.object(svc, "_track_call"):
                results = await svc.search_nearby(38.71, -9.13)

        assert results[0]["rating"] == 4.8
        assert results[1]["rating"] == 3.0

    async def test_search_nearby_min_rating_filter(self):
        svc = self._svc()
        low = {**RAW_PLACE, "rating": 3.0, "id": "low"}
        high = {**RAW_PLACE, "rating": 4.8, "id": "high"}
        resp = self._mock_response([low, high])
        session = self._mock_session(resp)

        with patch("aiohttp.ClientSession", return_value=session):
            with patch.object(svc, "_track_call"):
                results = await svc.search_nearby(38.71, -9.13, min_rating=4.0)

        assert all(r["rating"] >= 4.0 for r in results)

    async def test_search_nearby_cache_hit(self):
        svc = self._svc()
        svc._cache["nearby:38.7169:-9.1395:None:None:1500:False"] = {
            "data": [PARSED_PLACE],
            "expires_at": time.time() + 600,
        }
        results = await svc.search_nearby(38.7169, -9.1395)
        assert results == [PARSED_PLACE]

    async def test_search_by_text_happy_path(self):
        svc = self._svc()
        resp = self._mock_response([RAW_PLACE])
        session = self._mock_session(resp)

        with patch("aiohttp.ClientSession", return_value=session):
            with patch.object(svc, "_track_call"):
                results = await svc.search_by_text("sushi Lisboa")

        assert len(results) == 1
        assert results[0]["name"] == "Tasca do João"

    async def test_search_by_text_empty(self):
        svc = self._svc()
        resp = self._mock_response([])
        session = self._mock_session(resp)

        with patch("aiohttp.ClientSession", return_value=session):
            with patch.object(svc, "_track_call"):
                results = await svc.search_by_text("restaurante marte")

        assert results == []

    async def test_search_api_error_raises_runtime(self):
        import aiohttp as _aiohttp

        svc = self._svc()
        err = _aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=403)
        session = AsyncMock()
        session.post = MagicMock(side_effect=err)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=session):
            with patch.object(svc, "_track_call"):
                with pytest.raises(RuntimeError, match="403"):
                    await svc.search_nearby(38.71, -9.13)


@pytest.mark.asyncio
class TestRestaurantServiceGetDetails:
    def _svc(self):
        from services.integrations.restaurant_service import RestaurantService

        svc = RestaurantService.__new__(RestaurantService)
        svc.name = "restaurant"
        svc.logger = MagicMock()
        svc._api_key = "fake-key"
        svc._initialized = True
        svc._cache = {}
        return svc

    async def test_get_details_happy_path(self):
        svc = self._svc()
        resp = AsyncMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value=RAW_PLACE_DETAIL)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session = AsyncMock()
        session.get = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=session):
            with patch.object(svc, "_track_call"):
                details = await svc.get_details("ChIJabc123")

        assert details["name"] == "Tasca do João"
        assert details["reservable"] is True
        assert len(details["weekly_hours"]) == 7

    async def test_get_details_uses_cache(self):
        svc = self._svc()
        svc._cache["detail:ChIJabc123"] = {
            "data": {"name": "Cached Restaurant"},
            "expires_at": time.time() + 600,
        }
        details = await svc.get_details("ChIJabc123")
        assert details["name"] == "Cached Restaurant"


# ─── RestaurantAgent helpers ─────────────────────────────────────────────────


class TestAgentHelpers:
    def test_detect_intent_search(self):
        from agents.specialized.restaurant_agent import _detect_intent

        assert _detect_intent("Restaurantes italianos perto", {}) == "search"
        assert _detect_intent("Sugere pizza em Lisboa", {}) == "search"
        assert _detect_intent("Onde jantar esta noite?", {}) == "search"

    def test_detect_intent_detail(self):
        from agents.specialized.restaurant_agent import _detect_intent

        assert _detect_intent("Mais detalhes sobre o 1", {}) == "detail"
        assert _detect_intent("Telefone do segundo", {}) == "detail"
        assert _detect_intent("Horário do primeiro", {}) == "detail"

    def test_detect_intent_context_override(self):
        from agents.specialized.restaurant_agent import _detect_intent

        assert _detect_intent("qualquer coisa", {"action": "detail"}) == "detail"

    def test_extract_open_now_true(self):
        from agents.specialized.restaurant_agent import _extract_open_now

        assert _extract_open_now("sushi aberto agora") is True
        assert _extract_open_now("pizza aberto hoje") is True

    def test_extract_open_now_false(self):
        from agents.specialized.restaurant_agent import _extract_open_now

        assert _extract_open_now("pizza em Lisboa") is False

    def test_extract_min_rating(self):
        from agents.specialized.restaurant_agent import _extract_min_rating

        assert _extract_min_rating("rating acima de 4") == 4.0
        assert _extract_min_rating("rating mínimo 4,5") == 4.5
        assert _extract_min_rating("sem filtro") == 0.0

    def test_extract_radius_km(self):
        from agents.specialized.restaurant_agent import _extract_radius

        assert _extract_radius("a 2km daqui") == 2000
        assert _extract_radius("a 500 metros") == 500
        assert _extract_radius("sem raio") == 1500  # default

    def test_extract_detail_index(self):
        from agents.specialized.restaurant_agent import _extract_detail_index

        assert _extract_detail_index("mostra o 1") == 0
        assert _extract_detail_index("detalhe do segundo") == 1
        assert _extract_detail_index("info do terceiro") == 2
        assert _extract_detail_index("primeiro") == 0
        assert _extract_detail_index("sem número") is None


# ─── RestaurantAgent.execute ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRestaurantAgentExecute:
    def _agent(self):
        from agents.specialized.restaurant_agent import RestaurantAgent

        a = RestaurantAgent.__new__(RestaurantAgent)
        a.name = "restaurant"
        a.logger = MagicMock()
        return a

    def _svc(self):
        from services.integrations.restaurant_service import RestaurantService

        svc = MagicMock(spec=RestaurantService)
        svc.is_initialized.return_value = True
        svc.format_restaurant = RestaurantService.format_restaurant
        svc.format_list = RestaurantService.format_list
        return svc

    def _ctx(self, **kwargs):
        return {"user_id": "user1", "chat_id": "user1", **kwargs}

    async def test_search_with_coordinates(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_nearby = AsyncMock(return_value=[PARSED_PLACE])

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute(
                "Restaurantes italianos perto",
                self._ctx(lat=38.71, lng=-9.13),
            )

        assert r.status.value == "success"
        assert r.data["count"] == 1
        svc.search_nearby.assert_called_once()

    async def test_search_without_coordinates_uses_text(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_by_text = AsyncMock(return_value=[PARSED_PLACE])

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute(
                "Sushi em Lisboa",
                self._ctx(city="Lisboa"),
            )

        assert r.status.value == "success"
        svc.search_by_text.assert_called_once()

    async def test_search_open_now_filter(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_nearby = AsyncMock(return_value=[PARSED_PLACE])

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute(
                "Pizza aberto agora",
                self._ctx(lat=38.71, lng=-9.13),
            )

        assert r.status.value == "success"
        call_kwargs = svc.search_nearby.call_args[1]
        assert call_kwargs.get("open_now") is True

    async def test_search_no_results(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_by_text = AsyncMock(return_value=[])

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute("Comida marciana", self._ctx())

        assert r.status.value == "success"
        assert "não encontrei" in r.response.lower()

    async def test_detail_with_last_results(self):
        agent = self._agent()
        svc = self._svc()
        svc.get_details = AsyncMock(
            return_value={
                **PARSED_PLACE,
                "weekly_hours": [],
                "services": [],
                "reviews": [],
            }
        )

        ctx = self._ctx(last_results=[PARSED_PLACE, PARSED_PLACE])
        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute("Mais detalhes sobre o primeiro", ctx)

        assert r.status.value == "success"
        svc.get_details.assert_called_once_with("ChIJabc123")

    async def test_detail_without_last_results(self):
        agent = self._agent()
        svc = self._svc()

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute("Mais detalhes sobre o 1", self._ctx())

        assert r.status.value == "error"
        assert "pesquisa" in r.response.lower()

    async def test_detail_index_out_of_range(self):
        agent = self._agent()
        svc = self._svc()

        ctx = self._ctx(last_results=[PARSED_PLACE])
        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute("Detalhes do quinto", ctx)

        assert r.status.value == "error"

    async def test_no_user_id(self):
        agent = self._agent()
        svc = self._svc()

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute("Restaurantes", {"user_id": "", "chat_id": ""})

        assert r.status.value == "error"

    async def test_service_unavailable(self):
        agent = self._agent()
        with patch(
            "agents.specialized.restaurant_agent.get_service", return_value=None
        ):
            r = await agent.execute("Pizza", self._ctx())
        assert r.status.value == "error"
        assert (
            "unavailable" in r.response.lower()
            or "não disponível" in r.response.lower()
        )

    async def test_api_error_handled(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_nearby = AsyncMock(
            side_effect=RuntimeError("Google Places API erro 403")
        )

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            r = await agent.execute("Pizza", self._ctx(lat=38.71, lng=-9.13))

        assert r.status.value == "error"
        assert "403" in r.response or "erro" in r.response.lower()

    async def test_results_stored_in_context(self):
        """Resultados ficam guardados no context para uso em detalhe."""
        agent = self._agent()
        svc = self._svc()
        svc.search_nearby = AsyncMock(return_value=[PARSED_PLACE])

        ctx = self._ctx(lat=38.71, lng=-9.13)
        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            await agent.execute("Restaurantes italianos", ctx)

        assert "last_results" in ctx
        assert len(ctx["last_results"]) == 1

    async def test_min_rating_filter_applied(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_nearby = AsyncMock(return_value=[PARSED_PLACE])

        with patch("agents.specialized.restaurant_agent.get_service", return_value=svc):
            await agent.execute(
                "Restaurantes rating acima de 4",
                self._ctx(lat=38.71, lng=-9.13),
            )

        call_kwargs = svc.search_nearby.call_args[1]
        assert call_kwargs.get("min_rating") == 4.0

    async def test_get_capabilities(self):
        from agents.specialized.restaurant_agent import RestaurantAgent

        a = RestaurantAgent.__new__(RestaurantAgent)
        caps = a.get_capabilities()
        assert "search_restaurants_nearby" in caps
        assert "filter_open_now" in caps
        assert "get_restaurant_details" in caps
        assert "get_reviews" in caps
