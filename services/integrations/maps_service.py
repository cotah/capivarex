# -*- coding: utf-8 -*-
"""
services/integrations/maps_service.py
=====================================
Google Maps comprehensive service — Directions, Places, Nearby, Geocoding.

Reuses GOOGLE_MAPS_API_KEY (same as traffic_service).

Capabilities:
  - Step-by-step directions (DRIVE, WALK, BICYCLE, TRANSIT)
  - Generic Places text search (pharmacy, gas station, hospital, etc.)
  - Nearby search by type or keyword
  - Place details
  - Reverse geocoding (coords → address)

APIs used:
  - Google Routes API v2 (directions with steps)
  - Google Places API (New) — Text Search, Nearby Search, Place Details
  - Google Geocoding API (reverse)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from services.core import (
    BaseService,
    ServiceUnavailableError,
    register_service,
    retry_on_failure,
)

load_dotenv()

# ── API endpoints ──────────────────────────────────────────────────────
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_BASE = "https://places.googleapis.com/v1"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# ── Travel mode mapping ────────────────────────────────────────────────
TRAVEL_MODES = {
    "drive": "DRIVE",
    "driving": "DRIVE",
    "carro": "DRIVE",
    "car": "DRIVE",
    "walk": "WALK",
    "walking": "WALK",
    "andar": "WALK",
    "a pé": "WALK",
    "pe": "WALK",
    "caminhando": "WALK",
    "bike": "BICYCLE",
    "bicycle": "BICYCLE",
    "bicicleta": "BICYCLE",
    "cycling": "BICYCLE",
    "transit": "TRANSIT",
    "transporte": "TRANSIT",
    "bus": "TRANSIT",
    "metro": "TRANSIT",
    "trem": "TRANSIT",
    "ônibus": "TRANSIT",
    "onibus": "TRANSIT",
    "público": "TRANSIT",
    "publico": "TRANSIT",
}

# ── Places field masks ─────────────────────────────────────────────────
PLACES_FIELDS = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.rating",
    "places.userRatingCount",
    "places.location",
    "places.currentOpeningHours",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.primaryType",
    "places.editorialSummary",
    "places.priceLevel",
])

PLACE_DETAIL_FIELDS = ",".join([
    "id",
    "displayName",
    "formattedAddress",
    "rating",
    "userRatingCount",
    "location",
    "currentOpeningHours",
    "nationalPhoneNumber",
    "websiteUri",
    "primaryType",
    "types",
    "editorialSummary",
    "priceLevel",
    "reviews",
    "regularOpeningHours",
    "googleMapsUri",
])

# ── Routes field mask for step-by-step directions ──────────────────────
ROUTES_FIELD_MASK = (
    "routes.duration,routes.distanceMeters,"
    "routes.polyline.encodedPolyline,"
    "routes.legs.duration,routes.legs.distanceMeters,"
    "routes.legs.startLocation,routes.legs.endLocation,"
    "routes.legs.steps.navigationInstruction,"
    "routes.legs.steps.distanceMeters,"
    "routes.legs.steps.staticDuration,"
    "routes.legs.steps.travelMode,"
    "routes.legs.steps.transitDetails,"
    "routes.travelAdvisory"
)


def _parse_duration(raw: str) -> int:
    """Parse Google duration string like '1234s' → 1234 (int seconds)."""
    if not raw:
        return 0
    return int(raw.rstrip("s"))


def _format_distance(meters: int) -> str:
    """Format meters to human-readable string."""
    if meters >= 1000:
        return f"{meters / 1000:.1f} km"
    return f"{meters} m"


def _format_duration_human(seconds: int) -> str:
    """Format seconds to 'Xh Ymin' or 'X min'."""
    if seconds < 60:
        return f"{seconds} seg"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining == 0:
        return f"{hours}h"
    return f"{hours}h {remaining}min"


def _travel_mode_emoji(mode: str) -> str:
    """Emoji for travel mode."""
    return {
        "DRIVE": "🚗",
        "WALK": "🚶",
        "BICYCLE": "🚲",
        "TRANSIT": "🚌",
    }.get(mode, "📍")


def _resolve_travel_mode(text: str) -> str:
    """Resolve user text to Google Routes travel mode."""
    lower = text.lower().strip()
    return TRAVEL_MODES.get(lower, "DRIVE")


@register_service("maps")
class MapsService(BaseService):
    """
    Google Maps comprehensive service.

    Provides directions, places search, nearby search, place details,
    and reverse geocoding via Google APIs.
    """

    def __init__(self) -> None:
        super().__init__(name="maps")
        self.api_key: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def _initialize(self) -> None:
        self.api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
        if not self.api_key:
            raise ServiceUnavailableError(
                "GOOGLE_MAPS_API_KEY not found in environment"
            )
        self.logger.info("MapsService initialized (key=%s…)", self.api_key[:8])

    async def _health_check(self) -> bool:
        return bool(self.api_key)

    async def _cleanup(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    # ── Geocoding ─────────────────────────────────────────────────────

    async def geocode(self, address: str) -> Optional[Dict[str, float]]:
        """Address → {latitude, longitude}."""
        try:
            client = await self._get_client()
            resp = await client.get(
                GEOCODE_URL,
                params={"address": address, "key": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return {"latitude": loc["lat"], "longitude": loc["lng"]}
            return None
        except Exception as exc:
            self.logger.error("Geocode failed for '%s': %s", address, exc)
            return None

    async def reverse_geocode(
        self, lat: float, lng: float
    ) -> Optional[str]:
        """Coordinates → formatted address string."""
        try:
            client = await self._get_client()
            resp = await client.get(
                GEOCODE_URL,
                params={"latlng": f"{lat},{lng}", "key": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                return data["results"][0].get("formatted_address")
            return None
        except Exception as exc:
            self.logger.error("Reverse geocode failed: %s", exc)
            return None

    # ── Directions (step-by-step) ─────────────────────────────────────

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_directions(
        self,
        origin: str,
        destination: str,
        mode: str = "drive",
        language: str = "pt-BR",
    ) -> Dict[str, Any]:
        """
        Get step-by-step directions between two places.

        Args:
            origin: Starting address or place name
            destination: Destination address or place name
            mode: Travel mode (drive/walk/bike/transit or PT equivalents)
            language: Response language code

        Returns:
            Dict with success, summary, steps[], and raw route data.
        """
        if not self.api_key:
            raise RuntimeError("MapsService not initialized")

        start = time.time()
        travel_mode = _resolve_travel_mode(mode)

        # Geocode both endpoints
        origin_coords = await self.geocode(origin)
        dest_coords = await self.geocode(destination)

        if not origin_coords or not dest_coords:
            failed = []
            if not origin_coords:
                failed.append(f"origem '{origin}'")
            if not dest_coords:
                failed.append(f"destino '{destination}'")
            return {
                "success": False,
                "error": f"Não encontrei o endereço: {', '.join(failed)}",
            }

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": ROUTES_FIELD_MASK,
        }

        payload: Dict[str, Any] = {
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
            "travelMode": travel_mode,
            "languageCode": language,
            "units": "METRIC",
        }

        # Traffic-aware only for driving
        if travel_mode == "DRIVE":
            payload["routingPreference"] = "TRAFFIC_AWARE"

        try:
            client = await self._get_client()
            resp = await client.post(ROUTES_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("routes"):
                return {
                    "success": False,
                    "error": "Nenhuma rota encontrada entre esses pontos.",
                }

            route = data["routes"][0]
            duration_s = _parse_duration(route.get("duration", "0s"))
            distance_m = route.get("distanceMeters", 0)

            # Parse steps
            steps = []
            legs = route.get("legs", [])
            for leg in legs:
                for step in leg.get("steps", []):
                    nav = step.get("navigationInstruction", {})
                    instruction = nav.get("instructions", "")
                    maneuver = nav.get("maneuver", "")
                    step_distance = step.get("distanceMeters", 0)
                    step_duration = _parse_duration(
                        step.get("staticDuration", "0s")
                    )
                    step_mode = step.get("travelMode", travel_mode)

                    step_data: Dict[str, Any] = {
                        "instruction": instruction,
                        "maneuver": maneuver,
                        "distance": _format_distance(step_distance),
                        "distance_meters": step_distance,
                        "duration": _format_duration_human(step_duration),
                        "duration_seconds": step_duration,
                        "travel_mode": step_mode,
                    }

                    # Transit details (line name, departure/arrival stops)
                    transit = step.get("transitDetails")
                    if transit:
                        line = transit.get("transitLine", {})
                        step_data["transit"] = {
                            "line_name": line.get("nameShort")
                            or line.get("name", ""),
                            "vehicle_type": line.get("vehicle", {}).get(
                                "type", ""
                            ),
                            "departure_stop": transit.get(
                                "stopDetails", {}
                            )
                            .get("departureStop", {})
                            .get("name", ""),
                            "arrival_stop": transit.get(
                                "stopDetails", {}
                            )
                            .get("arrivalStop", {})
                            .get("name", ""),
                            "num_stops": transit.get("stopCount", 0),
                        }

                    if instruction:  # skip empty steps
                        steps.append(step_data)

            now = datetime.now(ZoneInfo("UTC"))
            arrival = now + timedelta(seconds=duration_s)

            latency = time.time() - start
            self._track_call(latency)

            emoji = _travel_mode_emoji(travel_mode)
            mode_label = {
                "DRIVE": "Carro",
                "WALK": "A pé",
                "BICYCLE": "Bicicleta",
                "TRANSIT": "Transporte público",
            }.get(travel_mode, travel_mode)

            return {
                "success": True,
                "summary": {
                    "origin": origin,
                    "destination": destination,
                    "mode": travel_mode,
                    "mode_label": mode_label,
                    "mode_emoji": emoji,
                    "distance": _format_distance(distance_m),
                    "distance_meters": distance_m,
                    "duration": _format_duration_human(duration_s),
                    "duration_seconds": duration_s,
                    "estimated_arrival": arrival.strftime("%H:%M"),
                },
                "steps": steps,
                "steps_count": len(steps),
            }

        except httpx.HTTPStatusError as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("Directions API error: %s", exc)
            return {"success": False, "error": f"Erro na API de rotas: {exc}"}

    # ── Places Text Search ────────────────────────────────────────────

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def search_places(
        self,
        query: str,
        location: Optional[Dict[str, float]] = None,
        radius: int = 5000,
        max_results: int = 5,
        language: str = "pt-BR",
    ) -> Dict[str, Any]:
        """
        Search for places by text query (e.g. "farmácia perto de Dublin").

        Args:
            query: Search query text
            location: Optional center point {latitude, longitude}
            radius: Search radius in meters (default 5km)
            max_results: Max results to return
            language: Language code

        Returns:
            Dict with success and places list.
        """
        if not self.api_key:
            raise RuntimeError("MapsService not initialized")

        start = time.time()
        url = f"{PLACES_BASE}/places:searchText"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": PLACES_FIELDS,
        }

        body: Dict[str, Any] = {
            "textQuery": query,
            "languageCode": language,
            "maxResultCount": max_results,
        }

        if location:
            body["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": location["latitude"],
                        "longitude": location["longitude"],
                    },
                    "radius": float(radius),
                }
            }

        try:
            client = await self._get_client()
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

            places = []
            for p in data.get("places", []):
                places.append(self._format_place(p))

            self._track_call(time.time() - start)
            return {"success": True, "places": places, "count": len(places)}

        except httpx.HTTPStatusError as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("Places search error: %s", exc)
            return {"success": False, "error": str(exc), "places": []}

    # ── Nearby Search ─────────────────────────────────────────────────

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def nearby_search(
        self,
        latitude: float,
        longitude: float,
        keyword: str = "",
        included_types: Optional[List[str]] = None,
        radius: int = 2000,
        max_results: int = 5,
        language: str = "pt-BR",
    ) -> Dict[str, Any]:
        """
        Find places near a location.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            keyword: Optional keyword filter
            included_types: Google place types (e.g. ["pharmacy", "hospital"])
            radius: Search radius in meters
            max_results: Max results
            language: Language code

        Returns:
            Dict with success and places list.
        """
        if not self.api_key:
            raise RuntimeError("MapsService not initialized")

        start = time.time()
        url = f"{PLACES_BASE}/places:searchNearby"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": PLACES_FIELDS,
        }

        body: Dict[str, Any] = {
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                    "radius": float(radius),
                }
            },
            "maxResultCount": max_results,
            "languageCode": language,
        }

        if included_types:
            body["includedTypes"] = included_types
        # keyword goes in includedTypes or textQuery via searchText
        # For nearby, we use rankPreference
        if keyword:
            body["rankPreference"] = "RELEVANCE"

        try:
            client = await self._get_client()
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

            places = []
            for p in data.get("places", []):
                places.append(self._format_place(p))

            self._track_call(time.time() - start)
            return {"success": True, "places": places, "count": len(places)}

        except httpx.HTTPStatusError as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("Nearby search error: %s", exc)
            return {"success": False, "error": str(exc), "places": []}

    # ── Place Details ─────────────────────────────────────────────────

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def get_place_details(
        self,
        place_id: str,
        language: str = "pt-BR",
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific place.

        Args:
            place_id: Google Place ID
            language: Language code

        Returns:
            Dict with success and place details.
        """
        if not self.api_key:
            raise RuntimeError("MapsService not initialized")

        start = time.time()
        url = f"{PLACES_BASE}/{place_id}"

        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": PLACE_DETAIL_FIELDS,
        }

        try:
            client = await self._get_client()
            resp = await client.get(
                url, headers=headers, params={"languageCode": language}
            )
            resp.raise_for_status()
            data = resp.json()

            place = self._format_place_detail(data)
            self._track_call(time.time() - start)
            return {"success": True, "place": place}

        except httpx.HTTPStatusError as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("Place details error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── Formatting helpers ────────────────────────────────────────────

    @staticmethod
    def _format_place(p: Dict) -> Dict[str, Any]:
        """Format a place from the Places API (New) response."""
        display_name = p.get("displayName", {})
        location = p.get("location", {})
        summary = p.get("editorialSummary", {})
        hours = p.get("currentOpeningHours", {})

        is_open = None
        if hours:
            is_open = hours.get("openNow")

        return {
            "id": p.get("id", ""),
            "name": display_name.get("text", "Unknown"),
            "address": p.get("formattedAddress", ""),
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount", 0),
            "price_level": p.get("priceLevel"),
            "type": p.get("primaryType", ""),
            "phone": p.get("nationalPhoneNumber", ""),
            "website": p.get("websiteUri", ""),
            "summary": summary.get("text", ""),
            "is_open": is_open,
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
        }

    @staticmethod
    def _format_place_detail(p: Dict) -> Dict[str, Any]:
        """Format detailed place info."""
        display_name = p.get("displayName", {})
        location = p.get("location", {})
        summary = p.get("editorialSummary", {})
        hours = p.get("currentOpeningHours", {})
        regular_hours = p.get("regularOpeningHours", {})

        reviews = []
        for r in (p.get("reviews") or [])[:3]:
            text_obj = r.get("text", {})
            reviews.append({
                "rating": r.get("rating"),
                "text": text_obj.get("text", ""),
                "author": r.get("authorAttribution", {}).get(
                    "displayName", ""
                ),
                "time": r.get("relativePublishTimeDescription", ""),
            })

        return {
            "id": p.get("id", ""),
            "name": display_name.get("text", "Unknown"),
            "address": p.get("formattedAddress", ""),
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount", 0),
            "price_level": p.get("priceLevel"),
            "type": p.get("primaryType", ""),
            "types": p.get("types", []),
            "phone": p.get("nationalPhoneNumber", ""),
            "website": p.get("websiteUri", ""),
            "google_maps_url": p.get("googleMapsUri", ""),
            "summary": summary.get("text", ""),
            "is_open": hours.get("openNow") if hours else None,
            "weekday_hours": regular_hours.get(
                "weekdayDescriptions", []
            ),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "reviews": reviews,
        }
