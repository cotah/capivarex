# -*- coding: utf-8 -*-
"""
tests/test_maps_agent.py
========================
Tests for MapsAgent and MapsService.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agents.specialized.maps_agent import MapsAgent


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def agent():
    return MapsAgent()


@pytest.fixture
def mock_maps_service():
    svc = AsyncMock()
    svc.is_initialized.return_value = True
    svc.initialize = AsyncMock()
    return svc


@pytest.fixture
def base_context():
    return {"user_id": "123", "chat_id": "123", "lang": "pt"}


@pytest.fixture
def directions_result():
    return {
        "success": True,
        "summary": {
            "origin": "Connolly Station Dublin",
            "destination": "Heuston Station Dublin",
            "mode": "WALK",
            "mode_label": "A pé",
            "mode_emoji": "🚶",
            "distance": "3.2 km",
            "distance_meters": 3200,
            "duration": "38 min",
            "duration_seconds": 2280,
            "estimated_arrival": "15:30",
        },
        "steps": [
            {
                "instruction": "Vire à direita na Amiens St",
                "maneuver": "turn-right",
                "distance": "200 m",
                "distance_meters": 200,
                "duration": "3 min",
                "duration_seconds": 180,
                "travel_mode": "WALK",
            },
            {
                "instruction": "Continue na Gardiner St",
                "maneuver": "straight",
                "distance": "500 m",
                "distance_meters": 500,
                "duration": "6 min",
                "duration_seconds": 360,
                "travel_mode": "WALK",
            },
        ],
        "steps_count": 2,
    }


@pytest.fixture
def places_result():
    return {
        "success": True,
        "places": [
            {
                "id": "place_abc123",
                "name": "Boots Pharmacy",
                "address": "123 O'Connell St, Dublin",
                "rating": 4.2,
                "rating_count": 156,
                "is_open": True,
                "phone": "+353 1 123 4567",
                "type": "pharmacy",
            },
            {
                "id": "place_def456",
                "name": "Lloyds Pharmacy",
                "address": "45 Henry St, Dublin",
                "rating": 3.8,
                "rating_count": 89,
                "is_open": False,
                "phone": "",
                "type": "pharmacy",
            },
        ],
        "count": 2,
    }


# ── Registration ──────────────────────────────────────────────────────

class TestMapsAgentRegistration:
    def test_agent_registered(self, agent):
        assert agent.name == "maps"

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        assert "directions" in caps
        assert "places_search" in caps
        assert "nearby_search" in caps


# ── Intent Classification ─────────────────────────────────────────────

class TestMapsIntentClassification:
    def test_regex_directions_pt(self, agent):
        result = agent._regex_classify("como chegar de Dublin a Cork")
        assert result["action"] == "directions"

    def test_regex_directions_en(self, agent):
        result = agent._regex_classify("directions from home to airport")
        assert result["action"] == "directions"

    def test_regex_nearby(self, agent):
        result = agent._regex_classify("o que tem perto de Swords")
        assert result["action"] == "nearby"
        assert "Swords" in result["location_context"]

    def test_regex_search_place(self, agent):
        result = agent._regex_classify("buscar farmácia em Dublin")
        assert result["action"] == "search_place"

    def test_regex_fallback(self, agent):
        result = agent._regex_classify("random unrelated text about maps")
        assert result["action"] == "search_place"


# ── Directions Handler ────────────────────────────────────────────────

class TestMapsDirections:
    @pytest.mark.asyncio
    async def test_directions_success(
        self, agent, mock_maps_service, base_context, directions_result
    ):
        mock_maps_service.get_directions = AsyncMock(return_value=directions_result)

        with patch("agents.specialized.maps_agent.get_service") as mock_get:
            mock_get.return_value = mock_maps_service

            intent = {
                "action": "directions",
                "origin": "Connolly Station Dublin",
                "destination": "Heuston Station Dublin",
                "mode": "walk",
            }

            result = await agent._handle_directions(
                mock_maps_service, intent, base_context, "pt"
            )

        assert result.status.value == "success"
        assert "Connolly" in result.response
        assert "Heuston" in result.response
        assert "3.2 km" in result.response
        assert "38 min" in result.response

    @pytest.mark.asyncio
    async def test_directions_no_destination(self, agent, mock_maps_service, base_context):
        intent = {
            "action": "directions",
            "origin": "Dublin",
            "destination": "",
            "mode": "drive",
        }

        result = await agent._handle_directions(
            mock_maps_service, intent, base_context, "pt"
        )
        assert result.status.value == "error"

    @pytest.mark.asyncio
    async def test_directions_no_origin_no_user_location(
        self, agent, mock_maps_service, base_context
    ):
        intent = {
            "action": "directions",
            "origin": "",
            "destination": "Cork",
            "mode": "drive",
        }

        result = await agent._handle_directions(
            mock_maps_service, intent, base_context, "pt"
        )
        # Now returns SUCCESS with request_location prompt instead of error
        assert result.status.value == "success"
        assert result.data.get("request_location") is True

    @pytest.mark.asyncio
    async def test_directions_uses_user_location(
        self, agent, mock_maps_service, directions_result
    ):
        mock_maps_service.get_directions = AsyncMock(return_value=directions_result)
        context = {"user_id": "123", "chat_id": "123", "user_location": "Dublin"}

        intent = {
            "action": "directions",
            "origin": "",
            "destination": "Cork",
            "mode": "drive",
        }

        result = await agent._handle_directions(
            mock_maps_service, intent, context, "en"
        )
        assert result.status.value == "success"
        mock_maps_service.get_directions.assert_called_once()

    @pytest.mark.asyncio
    async def test_directions_api_failure(self, agent, mock_maps_service, base_context):
        mock_maps_service.get_directions = AsyncMock(
            return_value={"success": False, "error": "Geocode failed"}
        )

        intent = {
            "action": "directions",
            "origin": "XYZXYZ",
            "destination": "ABCABC",
            "mode": "drive",
        }

        result = await agent._handle_directions(
            mock_maps_service, intent, base_context, "pt"
        )
        assert result.status.value == "error"


# ── Places Search Handler ─────────────────────────────────────────────

class TestMapsSearch:
    @pytest.mark.asyncio
    async def test_search_success(
        self, agent, mock_maps_service, base_context, places_result
    ):
        mock_maps_service.search_places = AsyncMock(return_value=places_result)
        mock_maps_service.geocode = AsyncMock(return_value=None)

        intent = {
            "action": "search_place",
            "query": "farmácia em Dublin",
            "location_context": "",
        }

        result = await agent._handle_search(
            mock_maps_service, intent, base_context, "pt"
        )
        assert result.status.value == "success"
        assert "Boots Pharmacy" in result.response
        assert "Lloyds Pharmacy" in result.response

    @pytest.mark.asyncio
    async def test_search_no_results(self, agent, mock_maps_service, base_context):
        mock_maps_service.search_places = AsyncMock(
            return_value={"success": True, "places": [], "count": 0}
        )
        mock_maps_service.geocode = AsyncMock(return_value=None)

        intent = {
            "action": "search_place",
            "query": "unicorn shop",
            "location_context": "",
        }

        result = await agent._handle_search(
            mock_maps_service, intent, base_context, "pt"
        )
        assert result.status.value == "success"
        assert "unicorn shop" in result.response.lower()

    @pytest.mark.asyncio
    async def test_search_with_location_bias(
        self, agent, mock_maps_service, base_context, places_result
    ):
        mock_maps_service.geocode = AsyncMock(
            return_value={"latitude": 53.35, "longitude": -6.26}
        )
        mock_maps_service.search_places = AsyncMock(return_value=places_result)

        intent = {
            "action": "search_place",
            "query": "pharmacy",
            "location_context": "Swords Dublin",
        }

        result = await agent._handle_search(
            mock_maps_service, intent, base_context, "en"
        )
        assert result.status.value == "success"
        mock_maps_service.geocode.assert_called_with("Swords Dublin")

    @pytest.mark.asyncio
    async def test_search_empty_query(self, agent, mock_maps_service, base_context):
        intent = {"action": "search_place", "query": "", "location_context": ""}

        result = await agent._handle_search(
            mock_maps_service, intent, base_context, "pt"
        )
        assert result.status.value == "error"


# ── Nearby Handler ────────────────────────────────────────────────────

class TestMapsNearby:
    @pytest.mark.asyncio
    async def test_nearby_with_coords_and_type(
        self, agent, mock_maps_service, base_context, places_result
    ):
        mock_maps_service.geocode = AsyncMock(
            return_value={"latitude": 53.35, "longitude": -6.26}
        )
        mock_maps_service.nearby_search = AsyncMock(return_value=places_result)

        intent = {
            "action": "nearby",
            "query": "farmácia perto de Dublin",
            "place_type": "pharmacy",
            "location_context": "Dublin",
        }

        result = await agent._handle_nearby(
            mock_maps_service, intent, base_context, "pt"
        )
        assert result.status.value == "success"
        mock_maps_service.nearby_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_nearby_fallback_to_text_search(
        self, agent, mock_maps_service, base_context, places_result
    ):
        mock_maps_service.geocode = AsyncMock(return_value=None)
        mock_maps_service.search_places = AsyncMock(return_value=places_result)

        intent = {
            "action": "nearby",
            "query": "hospital",
            "place_type": "",
            "location_context": "",
        }
        context = {**base_context, "user_location": ""}

        result = await agent._handle_nearby(
            mock_maps_service, intent, context, "pt"
        )
        assert result.status.value == "success"
        mock_maps_service.search_places.assert_called_once()


# ── Execute (full flow) ───────────────────────────────────────────────

class TestMapsExecute:
    @pytest.mark.asyncio
    async def test_service_unavailable(self, agent, base_context):
        with patch("agents.specialized.maps_agent.get_service", return_value=None):
            result = await agent.execute("como chegar a Cork", base_context)
        assert result.status.value == "error"

    @pytest.mark.asyncio
    async def test_execute_routes_to_directions(
        self, agent, mock_maps_service, base_context, directions_result
    ):
        mock_maps_service.get_directions = AsyncMock(return_value=directions_result)

        with (
            patch("agents.specialized.maps_agent.get_service") as mock_get,
            patch.object(
                agent,
                "_classify_intent",
                return_value={
                    "action": "directions",
                    "origin": "Connolly",
                    "destination": "Heuston",
                    "mode": "walk",
                    "query": "",
                    "place_type": "",
                    "location_context": "",
                    "language": "pt",
                },
            ),
        ):
            mock_get.return_value = mock_maps_service
            result = await agent.execute(
                "como chegar de Connolly a Heuston a pé", base_context
            )

        assert result.status.value == "success"

    @pytest.mark.asyncio
    async def test_execute_exception_handling(self, agent, mock_maps_service, base_context):
        mock_maps_service.is_initialized.return_value = True

        with patch("agents.specialized.maps_agent.get_service") as mock_get:
            mock_get.return_value = mock_maps_service
            with patch.object(
                agent, "_classify_intent", side_effect=Exception("boom")
            ):
                result = await agent.execute("teste", base_context)

        assert result.status.value == "error"


# ── Response Formatting ───────────────────────────────────────────────

class TestMapsFormatting:
    def test_format_places_response(self, agent, places_result):
        text = agent._format_places_response(
            places_result["places"], "farmácia", "pt"
        )
        assert "Boots Pharmacy" in text
        assert "Aberto agora" in text
        assert "Fechado" in text

    def test_format_place_detail_response(self, agent):
        place = {
            "name": "Boots Pharmacy",
            "summary": "A popular pharmacy chain.",
            "address": "123 O'Connell St",
            "phone": "+353 1 123 4567",
            "rating": 4.2,
            "rating_count": 156,
            "is_open": True,
            "weekday_hours": ["Monday: 9:00 – 18:00"],
            "reviews": [
                {
                    "rating": 5,
                    "text": "Great service!",
                    "author": "John",
                    "time": "2 months ago",
                }
            ],
            "website": "https://www.boots.ie",
            "google_maps_url": "https://maps.google.com/...",
        }
        text = agent._format_place_detail_response(place, "pt")
        assert "Boots Pharmacy" in text
        assert "Aberto agora" in text
        assert "Great service!" in text
        assert "Horário de funcionamento" in text
