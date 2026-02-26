"""Tests for TravelAgent (agents/specialized/travel_agent.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch


# ------------------------------------------------------------------- #
# Helpers                                                               #
# ------------------------------------------------------------------- #


def _make_travel_agent():
    """Create a TravelAgent instance."""
    from agents.specialized.travel_agent import TravelAgent

    return TravelAgent()


def _mock_duffel(initialized=True):
    """Create a mock Duffel service."""
    svc = MagicMock()
    svc.is_initialized.return_value = initialized
    svc.initialize = AsyncMock()
    return svc


# ------------------------------------------------------------------- #
# No service available                                                  #
# ------------------------------------------------------------------- #


class TestTravelAgentNoService:
    @pytest.mark.asyncio
    async def test_no_duffel_service(self):
        agent = _make_travel_agent()
        with patch("agents.specialized.travel_agent.get_service", return_value=None):
            result = await agent.execute("find flights", {})
            assert (
                result.status.value == "error"
                or "unavailable" in result.response.lower()
                or "not available" in str(result.error or "").lower()
            )

    @pytest.mark.asyncio
    async def test_duffel_not_initialized(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel(initialized=False)
        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent,
                "_parse_intent",
                new_callable=AsyncMock,
                return_value={"type": "unknown"},
            ):
                await agent.execute("hello", {})
                mock_svc.initialize.assert_awaited_once()


# ------------------------------------------------------------------- #
# Unknown / help intent                                                 #
# ------------------------------------------------------------------- #


class TestTravelAgentHelp:
    @pytest.mark.asyncio
    async def test_unknown_intent_shows_help_en(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent,
                "_parse_intent",
                new_callable=AsyncMock,
                return_value={"type": "unknown"},
            ):
                result = await agent.execute("what can you do?", {})
                assert (
                    "Travel Agent" in result.response
                    or "travel" in result.response.lower()
                )

    @pytest.mark.asyncio
    async def test_unknown_intent_shows_help_pt(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent,
                "_parse_intent",
                new_callable=AsyncMock,
                return_value={"type": "unknown"},
            ):
                with patch(
                    "agents.specialized.travel_agent.get_user_lang", return_value="pt"
                ):
                    result = await agent.execute("o que faz?", {})
                    assert (
                        "Viagens" in result.response
                        or "voos" in result.response.lower()
                    )

    @pytest.mark.asyncio
    async def test_none_intent_shows_help(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=None
            ):
                result = await agent.execute("???", {})
                assert (
                    "Travel Agent" in result.response
                    or "travel" in result.response.lower()
                )


# ------------------------------------------------------------------- #
# Flight search                                                         #
# ------------------------------------------------------------------- #


class TestTravelAgentFlightSearch:
    @pytest.mark.asyncio
    async def test_flight_search_success(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_flights = AsyncMock(
            return_value={
                "offer_request_id": "orq_1",
                "total_found": 2,
                "offers": [
                    {
                        "id": "off_1",
                        "total_amount": "150.00",
                        "total_currency": "EUR",
                        "owner": {"name": "Ryanair"},
                        "slices": [],
                    },
                    {
                        "id": "off_2",
                        "total_amount": "200.00",
                        "total_currency": "EUR",
                        "owner": {"name": "Aer Lingus"},
                        "slices": [],
                    },
                ],
                "passengers": [],
            }
        )
        mock_svc.format_flight_offer = lambda o: (
            f"✈️ {o['owner']['name']} — EUR {o['total_amount']}"
        )

        intent = {
            "type": "flight",
            "origin": "DUB",
            "destination": "LHR",
            "departure_date": "2026-04-15",
            "return_date": None,
            "cabin_class": "economy",
            "passengers": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("fly Dublin to London April 15", {})
                assert result.status.value == "success"
                assert "Ryanair" in result.response
                assert result.data["offers"][0]["id"] == "off_1"

    @pytest.mark.asyncio
    async def test_flight_search_no_results(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_flights = AsyncMock(
            return_value={
                "offer_request_id": "orq_2",
                "total_found": 0,
                "offers": [],
                "passengers": [],
            }
        )

        intent = {
            "type": "flight",
            "origin": "DUB",
            "destination": "XXX",
            "departure_date": "2026-04-15",
            "return_date": None,
            "cabin_class": "economy",
            "passengers": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("fly to nowhere", {})
                assert (
                    "No flights" in result.response or "Nenhum voo" in result.response
                )

    @pytest.mark.asyncio
    async def test_flight_search_missing_fields(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()

        intent = {
            "type": "flight",
            "origin": "",
            "destination": "",
            "departure_date": "",
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("fly somewhere", {})
                assert (
                    "need more" in result.response.lower()
                    or "preciso" in result.response.lower()
                )

    @pytest.mark.asyncio
    async def test_flight_search_pt(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_flights = AsyncMock(
            return_value={
                "offer_request_id": "orq_3",
                "total_found": 1,
                "offers": [
                    {
                        "id": "off_3",
                        "total_amount": "250.00",
                        "total_currency": "EUR",
                        "owner": {"name": "TAP"},
                        "slices": [],
                    }
                ],
                "passengers": [],
            }
        )
        mock_svc.format_flight_offer = lambda o: f"✈️ {o['owner']['name']}"

        intent = {
            "type": "flight",
            "origin": "LIS",
            "destination": "CDG",
            "departure_date": "2026-05-01",
            "return_date": None,
            "cabin_class": "economy",
            "passengers": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                with patch(
                    "agents.specialized.travel_agent.get_user_lang", return_value="pt"
                ):
                    result = await agent.execute("voos de Lisboa para Paris", {})
                    assert (
                        "voos encontrados" in result.response.lower()
                        or "TAP" in result.response
                    )

    @pytest.mark.asyncio
    async def test_flight_multiple_passengers(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_flights = AsyncMock(
            return_value={
                "offer_request_id": "orq_4",
                "total_found": 0,
                "offers": [],
                "passengers": [],
            }
        )

        intent = {
            "type": "flight",
            "origin": "DUB",
            "destination": "JFK",
            "departure_date": "2026-06-01",
            "return_date": None,
            "cabin_class": "economy",
            "passengers": 3,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                await agent.execute("3 passengers Dublin to NYC", {})
                call_args = mock_svc.search_flights.call_args
                assert len(call_args.kwargs.get("passengers", [])) == 3


# ------------------------------------------------------------------- #
# Stay search                                                           #
# ------------------------------------------------------------------- #


class TestTravelAgentStaySearch:
    @pytest.mark.asyncio
    async def test_stay_search_success(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_stays = AsyncMock(
            return_value=[
                {
                    "id": "sr_1",
                    "cheapest_rate_total_amount": "120.00",
                    "cheapest_rate_total_currency": "EUR",
                    "accommodation": {
                        "name": "Grand Hotel",
                        "rating": 4,
                        "review_score": 8.5,
                    },
                },
            ]
        )
        mock_svc.format_stay_result = lambda r: f"🏨 {r['accommodation']['name']}"

        intent = {
            "type": "stay",
            "location": "Dublin",
            "latitude": 53.35,
            "longitude": -6.26,
            "check_in": "2026-04-15",
            "check_out": "2026-04-18",
            "rooms": 1,
            "guests": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("hotel in Dublin April 15-18", {})
                assert "Grand Hotel" in result.response
                assert result.data["results"][0]["name"] == "Grand Hotel"

    @pytest.mark.asyncio
    async def test_stay_search_no_results(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_stays = AsyncMock(return_value=[])

        intent = {
            "type": "stay",
            "location": "Middle of Nowhere",
            "latitude": 0.0,
            "longitude": 0.0,
            "check_in": "2026-04-15",
            "check_out": "2026-04-18",
            "rooms": 1,
            "guests": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("hotel in nowhere", {})
                assert (
                    "No accommodation" in result.response or "Nenhum" in result.response
                )

    @pytest.mark.asyncio
    async def test_stay_missing_dates(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()

        intent = {
            "type": "stay",
            "location": "Dublin",
            "latitude": 53.35,
            "longitude": -6.26,
            "check_in": "",
            "check_out": "",
            "rooms": 1,
            "guests": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("hotel in Dublin", {})
                assert (
                    "check-in" in result.response.lower()
                    or "check_in" in result.response.lower()
                    or "datas" in result.response.lower()
                )

    @pytest.mark.asyncio
    async def test_stay_no_coords_uses_context_gps(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_stays = AsyncMock(return_value=[])

        intent = {
            "type": "stay",
            "location": "here",
            "latitude": None,
            "longitude": None,
            "check_in": "2026-04-15",
            "check_out": "2026-04-18",
            "rooms": 1,
            "guests": 1,
        }
        context = {"latitude": 53.35, "longitude": -6.26}

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                await agent.execute("hotel near me", context)
                mock_svc.search_stays.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stay_no_coords_no_gps(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()

        intent = {
            "type": "stay",
            "location": "",
            "latitude": None,
            "longitude": None,
            "check_in": "2026-04-15",
            "check_out": "2026-04-18",
            "rooms": 1,
            "guests": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("hotel somewhere", {})
                assert (
                    "location" in result.response.lower()
                    or "localização" in result.response.lower()
                )


# ------------------------------------------------------------------- #
# Error handling                                                        #
# ------------------------------------------------------------------- #


class TestTravelAgentErrors:
    @pytest.mark.asyncio
    async def test_flight_search_exception(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_flights = AsyncMock(side_effect=Exception("API down"))

        intent = {
            "type": "flight",
            "origin": "DUB",
            "destination": "LHR",
            "departure_date": "2026-04-15",
            "return_date": None,
            "cabin_class": "economy",
            "passengers": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("fly Dublin London", {})
                assert result.status.value == "error"

    @pytest.mark.asyncio
    async def test_stay_search_exception(self):
        agent = _make_travel_agent()
        mock_svc = _mock_duffel()
        mock_svc.search_stays = AsyncMock(side_effect=Exception("timeout"))

        intent = {
            "type": "stay",
            "location": "Dublin",
            "latitude": 53.35,
            "longitude": -6.26,
            "check_in": "2026-04-15",
            "check_out": "2026-04-18",
            "rooms": 1,
            "guests": 1,
        }

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_svc
        ):
            with patch.object(
                agent, "_parse_intent", new_callable=AsyncMock, return_value=intent
            ):
                result = await agent.execute("hotel Dublin", {})
                assert result.status.value == "error"


# ------------------------------------------------------------------- #
# Intent parsing                                                        #
# ------------------------------------------------------------------- #


class TestIntentParsing:
    @pytest.mark.asyncio
    async def test_gpt_parse_success(self):
        agent = _make_travel_agent()
        mock_openai = MagicMock()
        mock_openai.initialize = AsyncMock()
        mock_client = AsyncMock()
        mock_completion = Mock()
        mock_completion.choices = [
            Mock(
                message=Mock(
                    content='{"type":"flight","origin":"DUB","destination":"LHR","departure_date":"2026-04-15","return_date":null,"cabin_class":"economy","passengers":1}'
                )
            )
        ]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_openai.get_client.return_value = mock_client

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_openai
        ):
            result = await agent._parse_intent("fly Dublin to London April 15", {})
            assert result["type"] == "flight"
            assert result["origin"] == "DUB"

    @pytest.mark.asyncio
    async def test_gpt_parse_with_markdown_fences(self):
        agent = _make_travel_agent()
        mock_openai = MagicMock()
        mock_openai.initialize = AsyncMock()
        mock_client = AsyncMock()
        mock_completion = Mock()
        mock_completion.choices = [
            Mock(
                message=Mock(
                    content='```json\n{"type":"stay","location":"Paris","latitude":48.85,"longitude":2.35,"check_in":"2026-04-15","check_out":"2026-04-18","rooms":1,"guests":1}\n```'
                )
            )
        ]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_openai.get_client.return_value = mock_client

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_openai
        ):
            result = await agent._parse_intent("hotel in Paris", {})
            assert result["type"] == "stay"
            assert result["latitude"] == 48.85

    @pytest.mark.asyncio
    async def test_gpt_parse_failure_fallback(self):
        agent = _make_travel_agent()
        mock_openai = MagicMock()
        mock_openai.initialize = AsyncMock()
        mock_openai.get_client.side_effect = Exception("no client")

        with patch(
            "agents.specialized.travel_agent.get_service", return_value=mock_openai
        ):
            result = await agent._parse_intent("find flights to London", {})
            assert result["type"] == "flight"

    @pytest.mark.asyncio
    async def test_no_openai_fallback(self):
        agent = _make_travel_agent()
        with patch("agents.specialized.travel_agent.get_service", return_value=None):
            result = await agent._parse_intent("hotel in Paris", {})
            assert result["type"] == "stay"


class TestFallbackParse:
    def test_flight_keywords(self):
        agent = _make_travel_agent()
        assert agent._fallback_parse("find me a flight")["type"] == "flight"
        assert agent._fallback_parse("I want to fly")["type"] == "flight"
        assert agent._fallback_parse("voo para Lisboa")["type"] == "flight"
        assert agent._fallback_parse("quero voar")["type"] == "flight"

    def test_stay_keywords(self):
        agent = _make_travel_agent()
        assert agent._fallback_parse("hotel in Dublin")["type"] == "stay"
        assert agent._fallback_parse("find accommodation")["type"] == "stay"
        assert agent._fallback_parse("estadia em Paris")["type"] == "stay"
        assert agent._fallback_parse("hospedagem")["type"] == "stay"

    def test_unknown(self):
        agent = _make_travel_agent()
        assert agent._fallback_parse("hello world")["type"] == "unknown"
        assert agent._fallback_parse("what time is it")["type"] == "unknown"


# ------------------------------------------------------------------- #
# Capabilities                                                          #
# ------------------------------------------------------------------- #


class TestCapabilities:
    def test_get_capabilities(self):
        agent = _make_travel_agent()
        caps = agent.get_capabilities()
        assert "flight_search" in caps
        assert "hotel_search" in caps
        assert "travel_booking" in caps
