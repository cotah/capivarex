"""Unit tests for TransitService — covers lifecycle, parsers, and API methods."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from services.integrations.transit_service import TransitService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(**overrides):
    """Create a TransitService with mocked internals."""
    with patch.object(TransitService, "__init__", lambda self: None):
        svc = TransitService()
    svc.name = "transit"
    svc.logger = MagicMock()
    svc._gmaps_key = overrides.get("gmaps_key", "fake-gmaps-key")
    svc._nta_key = overrides.get("nta_key", "fake-nta-key")
    svc._client = overrides.get("client", AsyncMock(spec=httpx.AsyncClient))
    svc._gtfs_available = overrides.get("gtfs_available", False)
    svc._call_count = 0
    svc._error_count = 0
    svc._total_latency = 0.0
    svc._track_call = MagicMock()
    svc._initialized = True
    svc.is_initialized = MagicMock(return_value=True)
    svc.initialize = AsyncMock()
    return svc


def _mock_response(status_code=200, json_data=None, content=b""):
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.content = content
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=resp,
        )
    return resp


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestTransitLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_with_keys(self):
        svc = TransitService()
        with patch(
            "services.integrations.transit_service.os.getenv",
            side_effect=lambda k, d=None: {
                "GOOGLE_MAPS_API_KEY": "gk",
                "NTA_API_KEY": "nk",
            }.get(k, d),
        ):
            with patch("services.integrations.transit_service.httpx.AsyncClient"):
                await svc._initialize()
        assert svc._gmaps_key == "gk"
        assert svc._nta_key == "nk"

    @pytest.mark.asyncio
    async def test_initialize_without_gmaps_key(self):
        svc = TransitService()
        with patch(
            "services.integrations.transit_service.os.getenv", return_value=None
        ):
            with pytest.raises(Exception):
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_initialize_without_nta_key(self):
        svc = TransitService()
        with patch(
            "services.integrations.transit_service.os.getenv",
            side_effect=lambda k, d=None: {
                "GOOGLE_MAPS_API_KEY": "gk",
            }.get(k, d),
        ):
            with patch("services.integrations.transit_service.httpx.AsyncClient"):
                await svc._initialize()
        assert svc._gmaps_key == "gk"
        assert svc._nta_key is None

    @pytest.mark.asyncio
    async def test_health_check(self):
        svc = _make_service()
        result = await svc._health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_no_key(self):
        svc = _make_service(gmaps_key=None)
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup(self):
        mock_client = AsyncMock()
        svc = _make_service(client=mock_client)
        await svc._cleanup()
        mock_client.aclose.assert_called_once()
        assert svc._client is None

    @pytest.mark.asyncio
    async def test_cleanup_no_client(self):
        svc = _make_service(client=None)
        await svc._cleanup()  # Should not raise


# ---------------------------------------------------------------------------
# _parse_transit_steps tests
# ---------------------------------------------------------------------------


class TestParseTransitSteps:
    def test_walking_step(self):
        route = {
            "legs": [
                {
                    "steps": [
                        {
                            "travelMode": "WALK",
                            "navigationInstruction": {"instructions": "Walk north"},
                            "staticDuration": "300s",
                        }
                    ]
                }
            ]
        }
        steps, lines, walking = TransitService._parse_transit_steps(route)
        assert len(steps) == 1
        assert steps[0]["mode"] == "WALK"
        assert steps[0]["duration_minutes"] == 5.0
        assert walking == 300
        assert lines == []

    def test_transit_step_with_line(self):
        route = {
            "legs": [
                {
                    "steps": [
                        {
                            "travelMode": "TRANSIT",
                            "navigationInstruction": {"instructions": "Take bus"},
                            "staticDuration": "600s",
                            "transitDetails": {
                                "stopDetails": {
                                    "departureStop": {"name": "Stop A"},
                                    "arrivalStop": {"name": "Stop B"},
                                },
                                "transitLine": {
                                    "nameShort": "39A",
                                    "name": "Dublin Bus 39A",
                                    "vehicle": {"type": "BUS", "name": {"text": "Bus"}},
                                    "color": "#0000FF",
                                    "agencies": [{"name": "Dublin Bus"}],
                                },
                                "localizedValues": {
                                    "departureTime": {"time": {"text": "08:30"}},
                                    "arrivalTime": {"time": {"text": "08:50"}},
                                },
                                "stopCount": 12,
                                "headsign": "City Centre",
                            },
                        }
                    ]
                }
            ]
        }
        steps, lines, walking = TransitService._parse_transit_steps(route)
        assert len(steps) == 1
        assert steps[0]["mode"] == "TRANSIT"
        assert steps[0]["transit"]["short_name"] == "39A"
        assert steps[0]["transit"]["departure_stop"] == "Stop A"
        assert steps[0]["transit"]["arrival_stop"] == "Stop B"
        assert steps[0]["transit"]["agency"] == "Dublin Bus"
        assert steps[0]["transit"]["num_stops"] == 12
        assert steps[0]["transit"]["headsign"] == "City Centre"
        assert len(lines) == 1
        assert lines[0]["short_name"] == "39A"
        assert walking == 0

    def test_mixed_steps(self):
        route = {
            "legs": [
                {
                    "steps": [
                        {
                            "travelMode": "WALK",
                            "navigationInstruction": {},
                            "staticDuration": "120s",
                        },
                        {
                            "travelMode": "TRANSIT",
                            "navigationInstruction": {},
                            "staticDuration": "900s",
                            "transitDetails": {
                                "stopDetails": {},
                                "transitLine": {
                                    "nameShort": "DART",
                                    "vehicle": {},
                                    "name": "DART",
                                },
                                "localizedValues": {},
                                "stopCount": 5,
                            },
                        },
                        {
                            "travelMode": "WALK",
                            "navigationInstruction": {},
                            "staticDuration": "180s",
                        },
                    ]
                }
            ]
        }
        steps, lines, walking = TransitService._parse_transit_steps(route)
        assert len(steps) == 3
        assert walking == 300  # 120 + 180
        assert len(lines) == 1
        assert lines[0]["short_name"] == "DART"

    def test_empty_route(self):
        steps, lines, walking = TransitService._parse_transit_steps({})
        assert steps == []
        assert lines == []
        assert walking == 0

    def test_transit_without_agencies(self):
        route = {
            "legs": [
                {
                    "steps": [
                        {
                            "travelMode": "TRANSIT",
                            "navigationInstruction": {},
                            "staticDuration": "0s",
                            "transitDetails": {
                                "stopDetails": {},
                                "transitLine": {
                                    "nameShort": "Luas",
                                    "vehicle": {},
                                    "name": "Luas",
                                },
                                "localizedValues": {},
                            },
                        }
                    ]
                }
            ]
        }
        steps, lines, _ = TransitService._parse_transit_steps(route)
        assert steps[0]["transit"]["agency"] == ""


# ---------------------------------------------------------------------------
# JSON parsers tests
# ---------------------------------------------------------------------------


class TestJsonParsers:
    def test_parse_trip_updates_json_with_delays(self):
        resp = _mock_response(
            json_data={
                "entity": [
                    {
                        "tripUpdate": {
                            "trip": {"tripId": "T1", "routeId": "39A"},
                            "stopTimeUpdate": [
                                {
                                    "departure": {"delay": 300},
                                    "stopSequence": 5,
                                    "stopId": "S1",
                                }
                            ],
                        }
                    }
                ]
            }
        )
        result = TransitService._parse_trip_updates_json(resp, None)
        assert len(result) == 1
        assert result[0]["trip_id"] == "T1"
        assert result[0]["delay_seconds"] == 300
        assert result[0]["delay_minutes"] == 5.0

    def test_parse_trip_updates_json_with_filter(self):
        resp = _mock_response(
            json_data={
                "entity": [
                    {
                        "tripUpdate": {
                            "trip": {"tripId": "T1", "routeId": "39A"},
                            "stopTimeUpdate": [
                                {
                                    "departure": {"delay": 300},
                                    "stopSequence": 1,
                                    "stopId": "S1",
                                }
                            ],
                        }
                    },
                    {
                        "tripUpdate": {
                            "trip": {"tripId": "T2", "routeId": "46A"},
                            "stopTimeUpdate": [
                                {
                                    "departure": {"delay": 600},
                                    "stopSequence": 2,
                                    "stopId": "S2",
                                }
                            ],
                        }
                    },
                ]
            }
        )
        result = TransitService._parse_trip_updates_json(resp, "39A")
        assert len(result) == 1
        assert result[0]["route_id"] == "39A"

    def test_parse_trip_updates_json_cancelled(self):
        resp = _mock_response(
            json_data={
                "entity": [
                    {
                        "tripUpdate": {
                            "trip": {"tripId": "T1", "routeId": "DART"},
                            "stopTimeUpdate": [
                                {
                                    "scheduleRelationship": "SKIPPED",
                                    "stopSequence": 3,
                                    "stopId": "S3",
                                }
                            ],
                        }
                    }
                ]
            }
        )
        result = TransitService._parse_trip_updates_json(resp, None)
        assert len(result) == 1
        assert result[0]["is_cancelled"] is True

    def test_parse_trip_updates_json_error(self):
        resp = MagicMock()
        resp.json.side_effect = Exception("bad json")
        result = TransitService._parse_trip_updates_json(resp, None)
        assert result == []

    def test_parse_alerts_json(self):
        resp = _mock_response(
            json_data={
                "entity": [
                    {
                        "alert": {
                            "headerText": {
                                "translation": [{"text": "Service disruption"}]
                            },
                            "descriptionText": {
                                "translation": [{"text": "Bus 39A delayed"}]
                            },
                            "cause": "ACCIDENT",
                            "effect": "SIGNIFICANT_DELAYS",
                        }
                    }
                ]
            }
        )
        result = TransitService._parse_alerts_json(resp)
        assert len(result) == 1
        assert result[0]["header_text"] == "Service disruption"
        assert result[0]["cause"] == "ACCIDENT"

    def test_parse_alerts_json_error(self):
        resp = MagicMock()
        resp.json.side_effect = Exception("bad json")
        result = TransitService._parse_alerts_json(resp)
        assert result == []

    @pytest.mark.asyncio
    async def test_parse_vehicle_positions_json(self):
        resp = _mock_response(
            json_data={
                "entity": [
                    {
                        "vehicle": {
                            "vehicle": {"id": "V1"},
                            "trip": {"tripId": "T1", "routeId": "39A"},
                            "position": {
                                "latitude": 53.3,
                                "longitude": -6.2,
                                "bearing": 90,
                                "speed": 10,
                            },
                            "timestamp": 1234567890,
                        }
                    }
                ]
            }
        )
        # Force JSON fallback by making protobuf import fail
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "gtfs_realtime_pb2" in str(name):
                raise ImportError("no gtfs")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = await TransitService._parse_vehicle_positions(resp)
        assert len(result) == 1
        assert result[0]["vehicle_id"] == "V1"
        assert result[0]["lat"] == 53.3
        assert result[0]["speed_kmh"] == 36.0

    @pytest.mark.asyncio
    async def test_parse_vehicle_positions_empty(self):
        resp = _mock_response(json_data={"entity": []})
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "gtfs_realtime_pb2" in str(name):
                raise ImportError("no gtfs")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = await TransitService._parse_vehicle_positions(resp)
        assert result == []


# ---------------------------------------------------------------------------
# _geocode tests
# ---------------------------------------------------------------------------


class TestGeocode:
    @pytest.mark.asyncio
    async def test_geocode_success(self):
        svc = _make_service()
        svc._client.get = AsyncMock(
            return_value=_mock_response(
                json_data={
                    "status": "OK",
                    "results": [{"geometry": {"location": {"lat": 53.3, "lng": -6.2}}}],
                }
            )
        )
        result = await svc._geocode("Dublin")
        assert result == {"lat": 53.3, "lng": -6.2}

    @pytest.mark.asyncio
    async def test_geocode_no_results(self):
        svc = _make_service()
        svc._client.get = AsyncMock(
            return_value=_mock_response(
                json_data={
                    "status": "ZERO_RESULTS",
                    "results": [],
                }
            )
        )
        result = await svc._geocode("nowhere")
        assert result is None

    @pytest.mark.asyncio
    async def test_geocode_exception(self):
        svc = _make_service()
        svc._client.get = AsyncMock(side_effect=Exception("network error"))
        result = await svc._geocode("Dublin")
        assert result is None


# ---------------------------------------------------------------------------
# _fetch_trip_updates tests
# ---------------------------------------------------------------------------


class TestFetchTripUpdates:
    @pytest.mark.asyncio
    async def test_fetch_json_mode(self):
        svc = _make_service(gtfs_available=False)
        svc._client.get = AsyncMock(
            return_value=_mock_response(
                json_data={
                    "entity": [
                        {
                            "tripUpdate": {
                                "trip": {"tripId": "T1", "routeId": "39A"},
                                "stopTimeUpdate": [
                                    {
                                        "departure": {"delay": 300},
                                        "stopSequence": 1,
                                        "stopId": "S1",
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        )
        result = await svc._fetch_trip_updates()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_error(self):
        svc = _make_service()
        svc._client.get = AsyncMock(side_effect=Exception("timeout"))
        result = await svc._fetch_trip_updates()
        assert result == []


# ---------------------------------------------------------------------------
# _fetch_service_alerts tests
# ---------------------------------------------------------------------------


class TestFetchServiceAlerts:
    @pytest.mark.asyncio
    async def test_fetch_alerts_no_nta_key(self):
        svc = _make_service(nta_key=None)
        result = await svc._fetch_service_alerts()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_alerts_json_mode(self):
        svc = _make_service(gtfs_available=False)
        svc._client.get = AsyncMock(
            return_value=_mock_response(
                json_data={
                    "entity": [
                        {
                            "alert": {
                                "headerText": {"translation": [{"text": "Delays"}]},
                                "descriptionText": {
                                    "translation": [{"text": "Bus 39A"}]
                                },
                            }
                        }
                    ]
                }
            )
        )
        result = await svc._fetch_service_alerts()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_alerts_error(self):
        svc = _make_service()
        svc._client.get = AsyncMock(side_effect=Exception("fail"))
        result = await svc._fetch_service_alerts()
        assert result == []


# ---------------------------------------------------------------------------
# get_vehicle_positions tests
# ---------------------------------------------------------------------------


class TestGetVehiclePositions:
    @pytest.mark.asyncio
    async def test_get_positions_success(self):
        svc = _make_service(gtfs_available=False)
        svc._client.get = AsyncMock(
            return_value=_mock_response(
                json_data={
                    "entity": [
                        {
                            "vehicle": {
                                "vehicle": {"id": "V1"},
                                "trip": {"tripId": "T1", "routeId": "R1"},
                                "position": {
                                    "latitude": 53.3,
                                    "longitude": -6.2,
                                    "bearing": 0,
                                    "speed": 5,
                                },
                                "timestamp": 1000,
                            }
                        }
                    ]
                }
            )
        )
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "gtfs_realtime_pb2" in str(name):
                raise ImportError("no gtfs")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = await svc.get_vehicle_positions()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_positions_error(self):
        svc = _make_service()
        svc._client.get = AsyncMock(side_effect=Exception("fail"))
        result = await svc.get_vehicle_positions()
        assert result == []
