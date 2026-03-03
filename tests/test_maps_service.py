# -*- coding: utf-8 -*-
"""
tests/test_maps_service.py
==========================
Tests for MapsService — directions, places, geocoding.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.integrations.maps_service import (
    MapsService,
    _format_distance,
    _format_duration_human,
    _resolve_travel_mode,
    _parse_duration,
)


# ── Unit: Helper functions ────────────────────────────────────────────

class TestMapsHelpers:
    def test_parse_duration(self):
        assert _parse_duration("1234s") == 1234
        assert _parse_duration("0s") == 0
        assert _parse_duration("") == 0

    def test_format_distance_meters(self):
        assert _format_distance(500) == "500 m"
        assert _format_distance(999) == "999 m"

    def test_format_distance_km(self):
        assert _format_distance(1000) == "1.0 km"
        assert _format_distance(2500) == "2.5 km"
        assert _format_distance(15300) == "15.3 km"

    def test_format_duration_seconds(self):
        assert _format_duration_human(30) == "30 seg"

    def test_format_duration_minutes(self):
        assert _format_duration_human(300) == "5 min"
        assert _format_duration_human(2700) == "45 min"

    def test_format_duration_hours(self):
        assert _format_duration_human(3600) == "1h"
        assert _format_duration_human(5400) == "1h 30min"
        assert _format_duration_human(7200) == "2h"

    def test_resolve_travel_mode_pt(self):
        assert _resolve_travel_mode("carro") == "DRIVE"
        assert _resolve_travel_mode("a pé") == "WALK"
        assert _resolve_travel_mode("bicicleta") == "BICYCLE"
        assert _resolve_travel_mode("transporte") == "TRANSIT"
        assert _resolve_travel_mode("ônibus") == "TRANSIT"

    def test_resolve_travel_mode_en(self):
        assert _resolve_travel_mode("drive") == "DRIVE"
        assert _resolve_travel_mode("walk") == "WALK"
        assert _resolve_travel_mode("bike") == "BICYCLE"
        assert _resolve_travel_mode("transit") == "TRANSIT"

    def test_resolve_travel_mode_default(self):
        assert _resolve_travel_mode("unknown") == "DRIVE"
        assert _resolve_travel_mode("") == "DRIVE"


# ── Service Lifecycle ─────────────────────────────────────────────────

class TestMapsServiceLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_with_key(self):
        svc = MapsService()
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test_key_123"}):
            await svc._initialize()
        assert svc.api_key == "test_key_123"

    @pytest.mark.asyncio
    async def test_initialize_without_key(self):
        svc = MapsService()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(Exception):  # ServiceUnavailableError
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_health_check(self):
        svc = MapsService()
        svc.api_key = "test_key"
        assert await svc._health_check() is True

        svc.api_key = ""
        assert await svc._health_check() is False


# ── Geocoding ─────────────────────────────────────────────────────────

class TestMapsGeocoding:
    @pytest.mark.asyncio
    async def test_geocode_success(self):
        svc = MapsService()
        svc.api_key = "test_key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "OK",
            "results": [
                {"geometry": {"location": {"lat": 53.35, "lng": -6.26}}}
            ],
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.geocode("Dublin, Ireland")
        assert result is not None
        assert result["latitude"] == 53.35
        assert result["longitude"] == -6.26

    @pytest.mark.asyncio
    async def test_geocode_not_found(self):
        svc = MapsService()
        svc.api_key = "test_key"

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ZERO_RESULTS", "results": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.geocode("XYZNONEXISTENT")
        assert result is None

    @pytest.mark.asyncio
    async def test_reverse_geocode_success(self):
        svc = MapsService()
        svc.api_key = "test_key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "OK",
            "results": [{"formatted_address": "O'Connell St, Dublin"}],
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.reverse_geocode(53.35, -6.26)
        assert result == "O'Connell St, Dublin"


# ── Directions ────────────────────────────────────────────────────────

class TestMapsDirections:
    @pytest.mark.asyncio
    async def test_get_directions_success(self):
        svc = MapsService()
        svc.api_key = "test_key"
        svc._track_call = MagicMock()

        # Mock geocode
        svc.geocode = AsyncMock(
            side_effect=[
                {"latitude": 53.35, "longitude": -6.26},  # origin
                {"latitude": 51.89, "longitude": -8.47},  # destination
            ]
        )

        # Mock Routes API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "routes": [
                {
                    "duration": "9000s",
                    "distanceMeters": 260000,
                    "travelAdvisory": {},
                    "legs": [
                        {
                            "duration": "9000s",
                            "distanceMeters": 260000,
                            "steps": [
                                {
                                    "navigationInstruction": {
                                        "instructions": "Take M7 south",
                                        "maneuver": "merge",
                                    },
                                    "distanceMeters": 50000,
                                    "staticDuration": "1800s",
                                    "travelMode": "DRIVE",
                                },
                                {
                                    "navigationInstruction": {
                                        "instructions": "Continue on M8",
                                        "maneuver": "straight",
                                    },
                                    "distanceMeters": 100000,
                                    "staticDuration": "3600s",
                                    "travelMode": "DRIVE",
                                },
                            ],
                        }
                    ],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.get_directions("Dublin", "Cork", mode="drive")

        assert result["success"] is True
        assert result["summary"]["distance"] == "260.0 km"
        assert result["summary"]["duration"] == "2h 30min"
        assert result["steps_count"] == 2
        assert result["steps"][0]["instruction"] == "Take M7 south"

    @pytest.mark.asyncio
    async def test_get_directions_geocode_fails(self):
        svc = MapsService()
        svc.api_key = "test_key"
        svc.geocode = AsyncMock(return_value=None)

        result = await svc.get_directions("XYZXYZ", "ABCABC")
        assert result["success"] is False
        assert "endereço" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_directions_no_routes(self):
        svc = MapsService()
        svc.api_key = "test_key"
        svc._track_call = MagicMock()

        svc.geocode = AsyncMock(
            return_value={"latitude": 53.35, "longitude": -6.26}
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"routes": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.get_directions("A", "B")
        assert result["success"] is False


# ── Places Search ─────────────────────────────────────────────────────

class TestMapsPlacesSearch:
    @pytest.mark.asyncio
    async def test_search_places_success(self):
        svc = MapsService()
        svc.api_key = "test_key"
        svc._track_call = MagicMock()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "places": [
                {
                    "id": "abc123",
                    "displayName": {"text": "Boots Pharmacy"},
                    "formattedAddress": "123 O'Connell St",
                    "rating": 4.2,
                    "userRatingCount": 156,
                    "location": {"latitude": 53.35, "longitude": -6.26},
                    "currentOpeningHours": {"openNow": True},
                    "primaryType": "pharmacy",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.search_places("pharmacy Dublin")
        assert result["success"] is True
        assert result["count"] == 1
        assert result["places"][0]["name"] == "Boots Pharmacy"
        assert result["places"][0]["is_open"] is True

    @pytest.mark.asyncio
    async def test_search_places_empty(self):
        svc = MapsService()
        svc.api_key = "test_key"
        svc._track_call = MagicMock()

        mock_response = MagicMock()
        mock_response.json.return_value = {"places": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.search_places("nonexistent place xyz")
        assert result["success"] is True
        assert result["count"] == 0


# ── Place Formatting ──────────────────────────────────────────────────

class TestMapsPlaceFormatting:
    def test_format_place(self):
        raw = {
            "id": "abc",
            "displayName": {"text": "Test Place"},
            "formattedAddress": "123 Test St",
            "rating": 4.5,
            "userRatingCount": 100,
            "location": {"latitude": 53.0, "longitude": -6.0},
            "currentOpeningHours": {"openNow": True},
            "primaryType": "restaurant",
            "nationalPhoneNumber": "+353 1 234 5678",
            "websiteUri": "https://test.com",
            "editorialSummary": {"text": "A great place"},
            "priceLevel": "PRICE_LEVEL_MODERATE",
        }

        result = MapsService._format_place(raw)
        assert result["name"] == "Test Place"
        assert result["rating"] == 4.5
        assert result["is_open"] is True
        assert result["phone"] == "+353 1 234 5678"

    def test_format_place_minimal(self):
        raw = {"id": "xyz", "displayName": {}, "location": {}}
        result = MapsService._format_place(raw)
        assert result["name"] == "Unknown"
        assert result["is_open"] is None
