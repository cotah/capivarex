"""
Duffel API Service — Flights & Stays integration.

Provides search, offer retrieval and booking for flights,
plus search, rates, quotes and booking for accommodation.

API Reference: https://duffel.com/docs/api/overview/welcome
"""

import os
import logging
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from services.core import BaseService, register_service, ServiceUnavailableError

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.duffel.com"

# Direct booking URLs for major airlines
# Users are redirected to the airline's own booking page
AIRLINE_BOOKING_URLS: dict[str, str] = {
    # European
    "Ryanair": "https://www.ryanair.com/gb/en/trip/flights/select",
    "Aer Lingus": "https://www.aerlingus.com/booking/select-flights",
    "British Airways": "https://www.britishairways.com/travel/book/public/en_gb",
    "easyJet": "https://www.easyjet.com/en",
    "Vueling": "https://www.vueling.com/en",
    "TAP Portugal": "https://www.flytap.com/en-gb/booking",
    "TAP Air Portugal": "https://www.flytap.com/en-gb/booking",
    "Iberia": "https://www.iberia.com/gb/en/booking/",
    "Lufthansa": "https://www.lufthansa.com/gb/en/booking",
    "Air France": "https://www.airfrance.co.uk/booking",
    "KLM": "https://www.klm.co.uk/booking",
    "Swiss International Air Lines": "https://www.swiss.com/gb/en/booking",
    "Wizz Air": "https://wizzair.com/en-gb/booking",
    "Norwegian": "https://www.norwegian.com/en/booking/",
    "SAS": "https://www.flysas.com/en/booking/",
    # Americas
    "LATAM Airlines": "https://www.latamairlines.com/br/en/booking",
    "GOL": "https://www.voegol.com.br/en/booking",
    "Azul": "https://www.voeazul.com.br/en/booking",
    "American Airlines": "https://www.aa.com/booking/find-flights",
    "United Airlines": "https://www.united.com/en/us/book-flight",
    "Delta Air Lines": "https://www.delta.com/flight-search/book-a-flight",
    "JetBlue": "https://www.jetblue.com/booking/flights",
    # Middle East / Asia
    "Emirates": "https://www.emirates.com/english/book/",
    "Qatar Airways": "https://www.qatarairways.com/en/booking.html",
    "Turkish Airlines": "https://www.turkishairlines.com/en-int/flights/booking/",
    "Etihad Airways": "https://www.etihad.com/en-gb/fly-etihad/book-a-flight",
}

# Fallback: Google Flights search
_GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"


@register_service("duffel")
class DuffelService(BaseService):
    """Duffel REST API service for flights and stays."""

    def __init__(
        self,
        name: str = "duffel",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, config)
        self.token: Optional[str] = None
        self.headers: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def _initialize(self) -> None:
        self.token = os.getenv("DUFFEL_API_TOKEN")
        if not self.token:
            raise ServiceUnavailableError(
                "DUFFEL_API_TOKEN must be set in environment variables"
            )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        # Quick health check
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=10.0) as client:
                resp = await client.get(f"{_BASE_URL}/air/airports?limit=1")
                if resp.status_code == 200:
                    self.logger.info("Duffel service initialized successfully")
                else:
                    self.logger.warning(
                        "Duffel health check returned %s — service may still work",
                        resp.status_code,
                    )
        except Exception as exc:
            self.logger.warning("Duffel health check failed: %s", exc)

    async def _health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=5.0) as client:
                resp = await client.get(f"{_BASE_URL}/air/airports?limit=1")
                return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Low-level HTTP helpers                                               #
    # ------------------------------------------------------------------ #

    async def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        async with httpx.AsyncClient(headers=self.headers, timeout=30.0) as client:
            resp = await client.get(f"{_BASE_URL}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, payload: Dict) -> Dict:
        async with httpx.AsyncClient(headers=self.headers, timeout=60.0) as client:
            resp = await client.post(f"{_BASE_URL}{path}", json=payload)
            resp.raise_for_status()
            return resp.json()

    # ================================================================== #
    #  FLIGHTS                                                             #
    # ================================================================== #

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        passengers: Optional[List[Dict[str, Any]]] = None,
        cabin_class: str = "economy",
        max_results: int = 5,
    ) -> Dict[str, Any]:
        """Search for flight offers.

        Args:
            origin: IATA code (airport or city), e.g. "DUB", "NYC"
            destination: IATA code
            departure_date: ISO date, e.g. "2026-04-15"
            return_date: Optional return date (round trip)
            passengers: List of passenger dicts. Default: 1 adult
            cabin_class: economy | premium_economy | business | first
            max_results: Max offers to return

        Returns:
            Dict with offers list and metadata
        """
        if passengers is None:
            passengers = [{"type": "adult"}]

        slices = [
            {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "departure_date": departure_date,
            }
        ]

        if return_date:
            slices.append(
                {
                    "origin": destination.upper(),
                    "destination": origin.upper(),
                    "departure_date": return_date,
                }
            )

        payload = {
            "data": {
                "slices": slices,
                "passengers": passengers,
                "cabin_class": cabin_class,
            }
        }

        self.logger.info(
            "Searching flights: %s → %s on %s (%s)",
            origin,
            destination,
            departure_date,
            cabin_class,
        )

        result = await self._post("/air/offer_requests", payload)
        data = result.get("data", {})
        offers = data.get("offers", [])

        # Sort by price and limit
        offers.sort(key=lambda o: float(o.get("total_amount", "999999")))
        offers = offers[:max_results]

        return {
            "offer_request_id": data.get("id"),
            "offers": offers,
            "total_found": len(data.get("offers", [])),
            "passengers": data.get("passengers", []),
        }

    async def get_offer(self, offer_id: str) -> Dict[str, Any]:
        """Get the latest version of a specific offer (prices may change)."""
        result = await self._get(f"/air/offers/{offer_id}")
        return result.get("data", {})

    async def create_flight_order(
        self,
        offer_id: str,
        passengers: List[Dict[str, Any]],
        payment_currency: str,
        payment_amount: str,
    ) -> Dict[str, Any]:
        """Book a flight by creating an order.

        Args:
            offer_id: The selected offer ID
            passengers: List of passenger details (name, dob, etc)
            payment_currency: ISO 4217 currency code
            payment_amount: Total amount string

        Returns:
            Order dict with booking_reference
        """
        payload = {
            "data": {
                "selected_offers": [offer_id],
                "payments": [
                    {
                        "type": "balance",
                        "currency": payment_currency,
                        "amount": payment_amount,
                    }
                ],
                "passengers": passengers,
            }
        }

        self.logger.info("Creating flight order for offer %s", offer_id)
        result = await self._post("/air/orders", payload)
        return result.get("data", {})

    # ================================================================== #
    #  STAYS (Accommodation)                                               #
    # ================================================================== #

    async def search_stays(
        self,
        latitude: float,
        longitude: float,
        check_in: str,
        check_out: str,
        guests: Optional[List[Dict[str, Any]]] = None,
        rooms: int = 1,
        radius: int = 10,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search for accommodation near a location.

        Args:
            latitude: Location latitude
            longitude: Location longitude
            check_in: ISO date, e.g. "2026-04-15"
            check_out: ISO date, e.g. "2026-04-18"
            guests: List of guest dicts. Default: 1 adult
            rooms: Number of rooms
            radius: Search radius in km (1-100)
            max_results: Max results to return

        Returns:
            List of search result dicts
        """
        if guests is None:
            guests = [{"type": "adult"}]

        payload = {
            "data": {
                "location": {
                    "geographic_coordinates": {
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                    "radius": radius,
                },
                "check_in_date": check_in,
                "check_out_date": check_out,
                "guests": guests,
                "rooms": rooms,
            }
        }

        self.logger.info(
            "Searching stays near %.4f,%.4f: %s to %s",
            latitude,
            longitude,
            check_in,
            check_out,
        )

        result = await self._post("/stays/search", payload)
        data = result.get("data", {})
        results = data.get("results", [])

        # Sort by cheapest rate
        results.sort(
            key=lambda r: float(r.get("cheapest_rate_total_amount") or "999999")
        )

        return results[:max_results]

    async def get_stay_rates(self, search_result_id: str) -> Dict[str, Any]:
        """Fetch all rooms and rates for a search result."""
        result = await self._post(
            f"/stays/search_results/{search_result_id}/actions/fetch_all_rates",
            {},
        )
        return result.get("data", {})

    async def create_stay_quote(self, rate_id: str) -> Dict[str, Any]:
        """Create a quote (confirm price) for a stay rate."""
        payload = {"data": {"rate_id": rate_id}}
        result = await self._post("/stays/quotes", payload)
        return result.get("data", {})

    async def create_stay_booking(
        self,
        quote_id: str,
        guests: List[Dict[str, str]],
        email: str,
        phone: str,
        special_requests: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Book accommodation.

        Args:
            quote_id: Quote ID from create_stay_quote
            guests: List of guest dicts with given_name, family_name
            email: Guest email
            phone: Guest phone in E.164 format
            special_requests: Optional requests for the hotel

        Returns:
            Booking dict with confirmation reference
        """
        payload = {
            "data": {
                "quote_id": quote_id,
                "guests": guests,
                "email": email,
                "phone_number": phone,
            }
        }

        if special_requests:
            payload["data"]["accommodation_special_requests"] = special_requests

        self.logger.info("Creating stay booking for quote %s", quote_id)
        result = await self._post("/stays/bookings", payload)
        return result.get("data", {})

    # ================================================================== #
    #  HELPERS                                                             #
    # ================================================================== #

    async def search_airports(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for airports/cities by name."""
        result = await self._get(
            "/air/airports",
            params={"name": query, "limit": limit},
        )
        return result.get("data", [])

    @staticmethod
    def format_flight_offer(offer: dict) -> str:
        """Format a flight offer into a readable string with booking link."""
        lines = []
        total = offer.get("total_amount", "?")
        currency = offer.get("total_currency", "")
        owner = offer.get("owner", {})
        owner_name = owner.get("name", "Unknown Airline")

        lines.append(f"✈️ **{owner_name}** — {currency} {total}")

        origin_code = ""
        dest_code = ""
        dep_date = ""

        for i, sl in enumerate(offer.get("slices", []), 1):
            origin = sl.get("origin", {}).get("iata_code", "?")
            dest = sl.get("destination", {}).get("iata_code", "?")
            segments = sl.get("segments", [])
            if i == 1:
                origin_code = origin
                dest_code = dest
            if segments:
                dep_time = segments[0].get("departing_at", "")[:16].replace("T", " ")
                arr_time = segments[-1].get("arriving_at", "")[:16].replace("T", " ")
                if i == 1 and dep_time:
                    dep_date = dep_time[:10]
                stops = len(segments) - 1
                stop_text = "Direct" if stops == 0 else f"{stops} stop(s)"
                lines.append(
                    f"  {'→' if i == 1 else '←'} {origin} → {dest} | "
                    f"{dep_time} → {arr_time} | {stop_text}"
                )

        # Duration
        for sl in offer.get("slices", []):
            duration = sl.get("duration")
            if duration:
                lines.append(f"  ⏱ Duration: {duration}")

        # Booking link
        booking_url = AIRLINE_BOOKING_URLS.get(owner_name)
        if not booking_url:
            # Fallback to Google Flights with pre-filled search
            booking_url = (
                f"{_GOOGLE_FLIGHTS_URL}?q=flights+from+{origin_code}+to+{dest_code}"
                f"+on+{dep_date}"
                if dep_date
                else _GOOGLE_FLIGHTS_URL
            )
        lines.append(f"  🔗 [Book on {owner_name}]({booking_url})")

        return "\n".join(lines)

    @staticmethod
    def format_stay_result(result: Dict) -> str:
        """Format a stay search result into a readable string."""
        accommodation = result.get("accommodation", {})
        name = accommodation.get("name", "Unknown Hotel")
        rating = accommodation.get("rating", "")
        review = accommodation.get("review_score", "")
        price = result.get("cheapest_rate_total_amount", "?")
        currency = result.get("cheapest_rate_total_currency", "")

        stars = "⭐" * int(rating) if rating else ""
        review_text = f" | Score: {review}/10" if review else ""

        return f"🏨 **{name}** {stars}{review_text}\n   From {currency} {price}"
