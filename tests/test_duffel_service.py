"""Tests for DuffelService (services/integrations/duffel_service.py)."""

import pytest
from unittest.mock import AsyncMock, Mock, patch


# ------------------------------------------------------------------- #
# Helpers                                                               #
# ------------------------------------------------------------------- #


def _make_duffel():
    """Create a DuffelService ready for testing."""
    from services.integrations.duffel_service import DuffelService

    svc = DuffelService()
    svc.token = "duffel_test_123"
    svc.headers = {
        "Authorization": "Bearer duffel_test_123",
        "Duffel-Version": "v2",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    svc._initialized = True
    return svc


# ------------------------------------------------------------------- #
# Init / Health                                                         #
# ------------------------------------------------------------------- #


class TestDuffelInit:
    @pytest.mark.asyncio
    async def test_missing_token(self):
        from services.integrations.duffel_service import DuffelService
        from services.core import ServiceUnavailableError

        svc = DuffelService()
        with patch.dict("os.environ", {"DUFFEL_API_TOKEN": ""}, clear=False):
            with pytest.raises(ServiceUnavailableError, match="DUFFEL_API_TOKEN"):
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_success(self):
        from services.integrations.duffel_service import DuffelService

        svc = DuffelService()
        mock_resp = Mock(status_code=200)

        with patch.dict(
            "os.environ", {"DUFFEL_API_TOKEN": "duffel_test_x"}, clear=False
        ):
            with patch("httpx.AsyncClient") as mc:
                c = AsyncMock()
                c.get = AsyncMock(return_value=mock_resp)
                c.__aenter__ = AsyncMock(return_value=c)
                c.__aexit__ = AsyncMock(return_value=False)
                mc.return_value = c
                await svc._initialize()
                assert svc.token == "duffel_test_x"

    @pytest.mark.asyncio
    async def test_health_check_warns_on_non200(self):
        from services.integrations.duffel_service import DuffelService

        svc = DuffelService()
        mock_resp = Mock(status_code=401)

        with patch.dict(
            "os.environ", {"DUFFEL_API_TOKEN": "duffel_test_x"}, clear=False
        ):
            with patch("httpx.AsyncClient") as mc:
                c = AsyncMock()
                c.get = AsyncMock(return_value=mock_resp)
                c.__aenter__ = AsyncMock(return_value=c)
                c.__aexit__ = AsyncMock(return_value=False)
                mc.return_value = c
                await svc._initialize()
                assert svc.token is not None

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        from services.integrations.duffel_service import DuffelService

        svc = DuffelService()
        with patch.dict(
            "os.environ", {"DUFFEL_API_TOKEN": "duffel_test_x"}, clear=False
        ):
            with patch("httpx.AsyncClient") as mc:
                c = AsyncMock()
                c.get = AsyncMock(side_effect=Exception("timeout"))
                c.__aenter__ = AsyncMock(return_value=c)
                c.__aexit__ = AsyncMock(return_value=False)
                mc.return_value = c
                await svc._initialize()
                assert svc.token is not None


class TestDuffelHealthCheck:
    @pytest.mark.asyncio
    async def test_ok(self):
        svc = _make_duffel()
        with patch("httpx.AsyncClient") as mc:
            c = AsyncMock()
            c.get = AsyncMock(return_value=Mock(status_code=200))
            c.__aenter__ = AsyncMock(return_value=c)
            c.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = c
            assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_fail(self):
        svc = _make_duffel()
        with patch("httpx.AsyncClient") as mc:
            c = AsyncMock()
            c.get = AsyncMock(side_effect=Exception("down"))
            c.__aenter__ = AsyncMock(return_value=c)
            c.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = c
            assert await svc._health_check() is False


# ------------------------------------------------------------------- #
# HTTP helpers                                                          #
# ------------------------------------------------------------------- #


class TestDuffelHTTP:
    @pytest.mark.asyncio
    async def test_get(self):
        svc = _make_duffel()
        with patch("httpx.AsyncClient") as mc:
            c = AsyncMock()
            resp = Mock()
            resp.status_code = 200
            resp.raise_for_status = Mock()
            resp.json.return_value = {"data": []}
            c.get = AsyncMock(return_value=resp)
            c.__aenter__ = AsyncMock(return_value=c)
            c.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = c
            result = await svc._get("/air/airports", params={"limit": 1})
            assert result == {"data": []}

    @pytest.mark.asyncio
    async def test_post(self):
        svc = _make_duffel()
        with patch("httpx.AsyncClient") as mc:
            c = AsyncMock()
            resp = Mock()
            resp.status_code = 200
            resp.raise_for_status = Mock()
            resp.json.return_value = {"data": {"id": "123"}}
            c.post = AsyncMock(return_value=resp)
            c.__aenter__ = AsyncMock(return_value=c)
            c.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = c
            result = await svc._post("/air/offer_requests", {"data": {}})
            assert result["data"]["id"] == "123"


# ------------------------------------------------------------------- #
# Flights                                                               #
# ------------------------------------------------------------------- #


class TestSearchFlights:
    @pytest.mark.asyncio
    async def test_one_way(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={
                "data": {
                    "id": "orq_1",
                    "offers": [
                        {
                            "id": "off_1",
                            "total_amount": "150.00",
                            "total_currency": "EUR",
                            "owner": {"name": "Ryanair"},
                            "slices": [],
                        },
                    ],
                    "passengers": [{"id": "pas_1", "type": "adult"}],
                }
            }
        )
        result = await svc.search_flights("DUB", "LHR", "2026-04-15")
        assert result["offer_request_id"] == "orq_1"
        assert len(result["offers"]) == 1

    @pytest.mark.asyncio
    async def test_round_trip(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={
                "data": {
                    "id": "orq_2",
                    "offers": [
                        {
                            "id": "off_2",
                            "total_amount": "300.00",
                            "total_currency": "EUR",
                            "owner": {"name": "TAP"},
                            "slices": [],
                        }
                    ],
                    "passengers": [],
                }
            }
        )
        await svc.search_flights("LIS", "CDG", "2026-05-01", return_date="2026-05-15")
        payload = svc._post.call_args[0][1]
        assert len(payload["data"]["slices"]) == 2

    @pytest.mark.asyncio
    async def test_limits_results(self):
        svc = _make_duffel()
        offers = [
            {
                "id": f"off_{i}",
                "total_amount": str(100 + i),
                "total_currency": "EUR",
                "owner": {"name": f"A{i}"},
                "slices": [],
            }
            for i in range(10)
        ]
        svc._post = AsyncMock(
            return_value={"data": {"id": "orq_3", "offers": offers, "passengers": []}}
        )
        result = await svc.search_flights("DUB", "JFK", "2026-06-01", max_results=3)
        assert len(result["offers"]) == 3
        assert result["total_found"] == 10

    @pytest.mark.asyncio
    async def test_custom_passengers_and_cabin(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={"data": {"id": "orq_4", "offers": [], "passengers": []}}
        )
        await svc.search_flights(
            "dub",
            "lhr",
            "2026-04-15",
            passengers=[{"type": "adult"}, {"type": "adult"}],
            cabin_class="business",
        )
        payload = svc._post.call_args[0][1]
        assert payload["data"]["cabin_class"] == "business"
        assert len(payload["data"]["passengers"]) == 2
        assert payload["data"]["slices"][0]["origin"] == "DUB"


class TestGetOffer:
    @pytest.mark.asyncio
    async def test_get_offer(self):
        svc = _make_duffel()
        svc._get = AsyncMock(
            return_value={"data": {"id": "off_1", "total_amount": "155.00"}}
        )
        result = await svc.get_offer("off_1")
        assert result["total_amount"] == "155.00"


class TestCreateFlightOrder:
    @pytest.mark.asyncio
    async def test_create_order(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={"data": {"id": "ord_1", "booking_reference": "ABC123"}}
        )
        result = await svc.create_flight_order(
            "off_1",
            [
                {
                    "id": "pas_1",
                    "given_name": "Henrique",
                    "family_name": "P",
                    "born_on": "1995-01-01",
                    "gender": "m",
                    "title": "mr",
                    "email": "h@t.com",
                    "phone_number": "+353123456",
                }
            ],
            "EUR",
            "150.00",
        )
        assert result["booking_reference"] == "ABC123"


# ------------------------------------------------------------------- #
# Stays                                                                 #
# ------------------------------------------------------------------- #


class TestSearchStays:
    @pytest.mark.asyncio
    async def test_search(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={
                "data": {
                    "results": [
                        {
                            "id": "sr_1",
                            "cheapest_rate_total_amount": "120.00",
                            "cheapest_rate_total_currency": "EUR",
                            "accommodation": {
                                "name": "Hotel A",
                                "rating": 4,
                                "review_score": 8.5,
                            },
                        },
                        {
                            "id": "sr_2",
                            "cheapest_rate_total_amount": "90.00",
                            "cheapest_rate_total_currency": "EUR",
                            "accommodation": {"name": "Hotel B", "rating": 3},
                        },
                    ]
                }
            }
        )
        results = await svc.search_stays(53.35, -6.26, "2026-04-15", "2026-04-18")
        assert len(results) == 2
        assert results[0]["cheapest_rate_total_amount"] == "90.00"

    @pytest.mark.asyncio
    async def test_empty(self):
        svc = _make_duffel()
        svc._post = AsyncMock(return_value={"data": {"results": []}})
        results = await svc.search_stays(0.0, 0.0, "2026-04-15", "2026-04-18")
        assert results == []

    @pytest.mark.asyncio
    async def test_custom_params(self):
        svc = _make_duffel()
        svc._post = AsyncMock(return_value={"data": {"results": []}})
        await svc.search_stays(
            51.5,
            -0.12,
            "2026-05-01",
            "2026-05-03",
            guests=[{"type": "adult"}, {"type": "adult"}],
            rooms=2,
            radius=20,
            max_results=10,
        )
        payload = svc._post.call_args[0][1]
        assert payload["data"]["rooms"] == 2
        assert payload["data"]["location"]["radius"] == 20


class TestStayRatesQuoteBooking:
    @pytest.mark.asyncio
    async def test_get_rates(self):
        svc = _make_duffel()
        svc._post = AsyncMock(return_value={"data": {"rooms": [{"id": "rm_1"}]}})
        result = await svc.get_stay_rates("sr_1")
        assert "rooms" in result

    @pytest.mark.asyncio
    async def test_create_quote(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={"data": {"id": "quo_1", "total_amount": "120.00"}}
        )
        result = await svc.create_stay_quote("rate_1")
        assert result["id"] == "quo_1"

    @pytest.mark.asyncio
    async def test_create_booking(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={
                "data": {
                    "id": "bok_1",
                    "status": "confirmed",
                    "booking_reference": "HTL456",
                }
            }
        )
        result = await svc.create_stay_booking(
            "quo_1",
            [{"given_name": "Henrique", "family_name": "P"}],
            "h@t.com",
            "+353123456",
        )
        assert result["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_create_booking_with_requests(self):
        svc = _make_duffel()
        svc._post = AsyncMock(
            return_value={"data": {"id": "bok_2", "status": "confirmed"}}
        )
        await svc.create_stay_booking(
            "quo_2",
            [{"given_name": "A", "family_name": "B"}],
            "a@b.com",
            "+1234",
            special_requests="Early check-in please",
        )
        payload = svc._post.call_args[0][1]
        assert (
            payload["data"]["accommodation_special_requests"] == "Early check-in please"
        )


# ------------------------------------------------------------------- #
# Helpers                                                               #
# ------------------------------------------------------------------- #


class TestSearchAirports:
    @pytest.mark.asyncio
    async def test_search_airports(self):
        svc = _make_duffel()
        svc._get = AsyncMock(
            return_value={"data": [{"iata_code": "DUB", "name": "Dublin Airport"}]}
        )
        result = await svc.search_airports("Dublin")
        assert len(result) == 1
        assert result[0]["iata_code"] == "DUB"


class TestFormatFlightOffer:
    def test_basic_format(self):
        from services.integrations.duffel_service import DuffelService

        offer = {
            "total_amount": "150.00",
            "total_currency": "EUR",
            "owner": {"name": "Ryanair"},
            "slices": [
                {
                    "origin": {"iata_code": "DUB"},
                    "destination": {"iata_code": "LHR"},
                    "duration": "PT1H30M",
                    "segments": [
                        {
                            "departing_at": "2026-04-15T08:00:00",
                            "arriving_at": "2026-04-15T09:30:00",
                        }
                    ],
                }
            ],
        }
        text = DuffelService.format_flight_offer(offer)
        assert "Ryanair" in text
        assert "EUR 150.00" in text
        assert "DUB" in text
        assert "LHR" in text
        assert "Direct" in text

    def test_with_stops(self):
        from services.integrations.duffel_service import DuffelService

        offer = {
            "total_amount": "400.00",
            "total_currency": "USD",
            "owner": {"name": "Delta"},
            "slices": [
                {
                    "origin": {"iata_code": "JFK"},
                    "destination": {"iata_code": "ATL"},
                    "segments": [
                        {
                            "departing_at": "2026-04-15T10:00:00",
                            "arriving_at": "2026-04-15T12:00:00",
                        },
                        {
                            "departing_at": "2026-04-15T13:00:00",
                            "arriving_at": "2026-04-15T15:00:00",
                        },
                    ],
                }
            ],
        }
        text = DuffelService.format_flight_offer(offer)
        assert "1 stop" in text

    def test_empty_slices(self):
        from services.integrations.duffel_service import DuffelService

        offer = {
            "total_amount": "99.00",
            "total_currency": "GBP",
            "owner": {"name": "EasyJet"},
            "slices": [],
        }
        text = DuffelService.format_flight_offer(offer)
        assert "EasyJet" in text


class TestBuildBookingUrl:
    def test_basic_url(self):
        from services.integrations.duffel_service import DuffelService

        url = DuffelService.build_booking_url(
            city="Dublin",
            checkin="2026-04-15",
            checkout="2026-04-18",
        )
        assert url.startswith("https://www.booking.com/searchresults.html?")
        assert "ss=Dublin" in url
        assert "checkin=2026-04-15" in url
        assert "checkout=2026-04-18" in url
        assert "group_adults=2" in url
        assert "no_rooms=1" in url
        assert "group_children=0" in url

    def test_custom_params(self):
        from services.integrations.duffel_service import DuffelService

        url = DuffelService.build_booking_url(
            city="São Paulo",
            checkin="2026-05-01",
            checkout="2026-05-05",
            adults=3,
            rooms=2,
            children=1,
        )
        assert "group_adults=3" in url
        assert "no_rooms=2" in url
        assert "group_children=1" in url
        # City with special chars should be URL-encoded
        assert "S%C3%A3o+Paulo" in url or "S%C3%A3o%20Paulo" in url

    def test_city_with_spaces(self):
        from services.integrations.duffel_service import DuffelService

        url = DuffelService.build_booking_url(
            city="New York",
            checkin="2026-06-01",
            checkout="2026-06-05",
        )
        assert "ss=New+York" in url or "ss=New%20York" in url


class TestFormatStayResult:
    def test_basic(self):
        from services.integrations.duffel_service import DuffelService

        result = {
            "cheapest_rate_total_amount": "120.00",
            "cheapest_rate_total_currency": "EUR",
            "accommodation": {"name": "Grand Hotel", "rating": 4, "review_score": 8.8},
        }
        text = DuffelService.format_stay_result(result)
        assert "Grand Hotel" in text
        assert "⭐⭐⭐⭐" in text
        assert "8.8" in text

    def test_no_rating(self):
        from services.integrations.duffel_service import DuffelService

        result = {
            "cheapest_rate_total_amount": "50.00",
            "cheapest_rate_total_currency": "USD",
            "accommodation": {"name": "Budget Inn"},
        }
        text = DuffelService.format_stay_result(result)
        assert "Budget Inn" in text
        assert "⭐" not in text
