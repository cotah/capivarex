"""
Traffic Service - Refactored with BaseService architecture.

Google Maps Routes API integration for traffic-aware routing.

Provides:
- Address geocoding via Google Geocoding API (async via httpx)
- Route computation with real-time traffic via Google Routes API v2
- Human-readable traffic summaries
- Pre-event departure recommendations with urgency levels
- Metrics tracking and health checks
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()


@register_service("traffic")
class TrafficService(BaseService):
    """
    Traffic and routing service powered by Google Maps APIs.

    Features:
    - Geocoding (address -> lat/lng) — async
    - Traffic-aware route computation (Google Routes API v2) — async
    - Human-readable traffic summaries
    - Pre-event departure advisor with urgency levels
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "traffic",
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialise the traffic service."""
        super().__init__(name, config)
        self.api_key: Optional[str] = None
        self.routes_url: str = (
            "https://routes.googleapis.com/directions/v2:computeRoutes"
        )
        self.geocode_url: str = (
            "https://maps.googleapis.com/maps/api/geocode/json"
        )
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # HTTP client management
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Get or create the async HTTP client.

        Returns:
            httpx.AsyncClient instance.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    # ------------------------------------------------------------------
    # BaseService lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Load Google Maps API key from config or environment."""
        self.api_key = self._get_config(
            "api_key",
            os.environ.get("GOOGLE_MAPS_API_KEY"),
        )

        if not self.api_key:
            raise ServiceUnavailableError(
                "GOOGLE_MAPS_API_KEY not found in environment variables"
            )

        self.logger.info("Traffic service initialized successfully")

    async def _health_check(self) -> bool:
        """Service is healthy when the API key is configured."""
        return self.api_key is not None

    async def _cleanup(self) -> None:
        """Close the async HTTP client on service shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Geocoding (async)
    # ------------------------------------------------------------------

    async def _geocode_address(self, address: str) -> Optional[Dict[str, float]]:
        """
        Convert a street address to latitude/longitude via Google Geocoding API.

        Args:
            address: Human-readable address string.

        Returns:
            Dict with ``latitude`` and ``longitude``, or None on failure.
        """
        try:
            params = {
                "address": address,
                "key": self.api_key,
            }
            client = await self._get_client()
            response = await client.get(
                self.geocode_url, params=params,
            )
            response.raise_for_status()

            data = response.json()
            if data.get("status") == "OK" and data.get("results"):
                location = data["results"][0]["geometry"]["location"]
                return {
                    "latitude": location["lat"],
                    "longitude": location["lng"],
                }
            return None

        except Exception as exc:
            self.logger.error("Geocoding failed for '%s': %s", address, exc)
            return None

    # ------------------------------------------------------------------
    # Route computation (Google Routes API v2) — async
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_route_with_traffic(
        self,
        origin: str,
        destination: str,
        departure_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Compute a route with real-time traffic between origin and destination.

        Uses the Google Routes API v2 (``computeRoutes``) with
        ``TRAFFIC_AWARE`` routing preference.

        Args:
            origin: Street address or place name.
            destination: Street address or place name.
            departure_time: When the trip starts (default: now).

        Returns:
            Dict with ``success``, ``route`` details, and ``traffic`` info.

        Raises:
            RuntimeError: On geocoding or API failure.
        """
        if not self.api_key:
            raise RuntimeError("Traffic service not initialized")

        start_time = time.time()

        try:
            if departure_time is None:
                departure_time = datetime.now()

            # Geocode both endpoints (async)
            origin_coords = await self._geocode_address(origin)
            dest_coords = await self._geocode_address(destination)

            if not origin_coords or not dest_coords:
                raise RuntimeError(
                    "Could not geocode the provided addresses"
                )

            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": (
                    "routes.duration,routes.distanceMeters,"
                    "routes.polyline.encodedPolyline,"
                    "routes.legs,routes.travelAdvisory"
                ),
            }

            payload = {
                "origin": {
                    "location": {
                        "latLng": {
                            "latitude": origin_coords["latitude"],
                            "longitude": origin_coords["longitude"],
                        }
                    }
                },
                "destination": {
                    "location": {
                        "latLng": {
                            "latitude": dest_coords["latitude"],
                            "longitude": dest_coords["longitude"],
                        }
                    }
                },
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "computeAlternativeRoutes": False,
                "languageCode": "pt-BR",
                "units": "METRIC",
            }

            client = await self._get_client()
            response = await client.post(
                self.routes_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

            data = response.json()

            if not data.get("routes"):
                raise RuntimeError("No routes found")

            route = data["routes"][0]

            # Parse duration (comes as e.g. "1234s")
            duration_seconds = int(
                route.get("duration", "0s").replace("s", "")
            )
            distance_meters = route.get("distanceMeters", 0)

            travel_advisory = route.get("travelAdvisory", {})

            latency = time.time() - start_time
            self._track_call(latency)

            return {
                "success": True,
                "route": {
                    "origin": origin,
                    "destination": destination,
                    "distance_km": round(distance_meters / 1000, 2),
                    "distance_meters": distance_meters,
                    "duration_minutes": round(duration_seconds / 60, 1),
                    "duration_seconds": duration_seconds,
                    "departure_time": departure_time.isoformat(),
                    "estimated_arrival": (
                        departure_time + timedelta(seconds=duration_seconds)
                    ).isoformat(),
                },
                "traffic": {
                    "has_traffic_data": bool(travel_advisory),
                    "speed_reading_intervals": travel_advisory.get(
                        "speedReadingIntervals", []
                    ),
                    "fuel_consumption_microliters": travel_advisory.get(
                        "fuelConsumptionMicroliters"
                    ),
                },
            }

        except httpx.HTTPStatusError as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("Route request failed: %s", exc)
            raise RuntimeError(f"Error fetching route: {exc}") from exc
        except (KeyError, ValueError) as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("Route response parsing failed: %s", exc)
            raise RuntimeError(
                f"Error processing API response: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Human-readable summary
    # ------------------------------------------------------------------

    async def get_traffic_summary(
        self,
        origin: str,
        destination: str,
        departure_time: Optional[datetime] = None,
    ) -> str:
        """
        Return a human-readable traffic summary for a route.

        Args:
            origin: Origin address.
            destination: Destination address.
            departure_time: When the trip starts (default: now).

        Returns:
            Formatted summary string.
        """
        try:
            result = await self.get_route_with_traffic(
                origin, destination, departure_time
            )

            if not result["success"]:
                return "Could not retrieve traffic information."

            route = result["route"]
            traffic = result["traffic"]

            summary = (
                f"Route: {route['origin']} -> {route['destination']}\n\n"
                f"Distance: {route['distance_km']} km\n"
                f"Estimated time: {route['duration_minutes']} minutes\n"
                f"Departure: "
                f"{datetime.fromisoformat(route['departure_time']).strftime('%H:%M')}\n"
                f"Estimated arrival: "
                f"{datetime.fromisoformat(route['estimated_arrival']).strftime('%H:%M')}\n"
            )

            if traffic["has_traffic_data"]:
                summary += "\nReal-time traffic data available."
            else:
                summary += "\nLimited traffic data for this route."

            return summary

        except Exception as exc:
            self.logger.error("Error generating traffic summary: %s", exc)
            return f"Error generating traffic summary: {exc}"

    # ------------------------------------------------------------------
    # Pre-event departure advisor
    # ------------------------------------------------------------------

    async def check_traffic_before_event(
        self,
        event_location: str,
        user_location: str,
        event_time: datetime,
        preparation_minutes: int = 15,
    ) -> Dict[str, Any]:
        """
        Check traffic conditions and recommend a departure time for an event.

        Computes the current route, derives a suggested departure time, and
        assigns an urgency level.

        Args:
            event_location: Where the event takes place.
            user_location: Current location of the user.
            event_time: Scheduled start time of the event.
            preparation_minutes: Buffer minutes at the venue (default 15).

        Returns:
            Dict with urgency, message, suggested departure, travel time,
            distance, and minutes until departure.
        """
        try:
            # Desired arrival = event time minus preparation buffer
            desired_arrival = event_time - timedelta(
                minutes=preparation_minutes
            )

            # Get traffic-aware route
            result = await self.get_route_with_traffic(
                user_location, event_location
            )

            if not result.get("success"):
                return {
                    "success": False,
                    "error": "Could not compute route",
                }

            route = result["route"]
            travel_time_minutes = route["duration_minutes"]

            # Derive suggested departure
            suggested_departure = desired_arrival - timedelta(
                minutes=travel_time_minutes
            )

            now = datetime.now()
            time_until_departure = suggested_departure - now
            minutes_until_departure = int(
                time_until_departure.total_seconds() / 60
            )

            # Determine urgency
            if minutes_until_departure < 0:
                urgency = "LATE"
                message = (
                    f"WARNING! You should have left "
                    f"{abs(minutes_until_departure)} minutes ago!"
                )
            elif minutes_until_departure < 10:
                urgency = "URGENT"
                message = (
                    f"LEAVE NOW! Only {minutes_until_departure} "
                    f"minutes until you need to depart!"
                )
            elif minutes_until_departure < 30:
                urgency = "SOON"
                message = (
                    f"Get ready! Leave in {minutes_until_departure} minutes."
                )
            else:
                urgency = "RELAXED"
                message = (
                    f"You have time. Leave in "
                    f"{minutes_until_departure} minutes."
                )

            return {
                "success": True,
                "urgency": urgency,
                "message": message,
                "suggested_departure": suggested_departure.isoformat(),
                "travel_time_minutes": travel_time_minutes,
                "distance_km": route["distance_km"],
                "event_time": event_time.isoformat(),
                "time_until_departure_minutes": minutes_until_departure,
            }

        except Exception as exc:
            self.logger.error("Error checking traffic before event: %s", exc)
            return {
                "success": False,
                "error": f"Error checking traffic: {exc}",
            }


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------

_traffic_service: Optional[TrafficService] = None


def get_traffic_service() -> TrafficService:
    """Get the global TrafficService instance from the registry."""
    global _traffic_service
    if _traffic_service is None:
        from services.core import get_service

        _traffic_service = get_service("traffic")
    return _traffic_service
