# -*- coding: utf-8 -*-
"""
services/business/saved_locations_service.py
============================================
Saved Locations — persistent named locations (home, work, gym, etc.).

Uses the existing ``user_context`` table with context_type = "saved_locations".

Data format in Supabase:
    {
        "home": {"address": "Swords, Dublin", "latitude": 53.45, "longitude": -6.22},
        "work": {"address": "City Centre, Dublin", "latitude": 53.35, "longitude": -6.26},
        "gym": {"address": "FlyeFit Swords, Dublin"}
    }

Usage:
    from services.business.saved_locations_service import SavedLocationsService

    svc = SavedLocationsService()
    await svc.save_location(user_id, "home", "Swords, Dublin")
    loc = await svc.get_location(user_id, "home")
    # -> {"address": "Swords, Dublin", "latitude": 53.45, "longitude": -6.22}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from services import get_service

logger = logging.getLogger(__name__)

# ── Alias mapping (multilingual) ──────────────────────────────────────
# Maps user text to canonical location key.

LOCATION_ALIASES: Dict[str, str] = {
    # Home
    "casa": "home",
    "minha casa": "home",
    "home": "home",
    "lar": "home",
    "meu apartamento": "home",
    "meu ap": "home",
    "residencia": "home",
    "mi casa": "home",
    "hogar": "home",
    # Work
    "trabalho": "work",
    "meu trabalho": "work",
    "work": "work",
    "office": "work",
    "escritorio": "work",
    "empresa": "work",
    "firma": "work",
    "mi trabajo": "work",
    "oficina": "work",
    "the office": "work",
    # Gym
    "academia": "gym",
    "gym": "gym",
    "the gym": "gym",
    "gimnasio": "gym",
    "musculacao": "gym",
    # School / University
    "escola": "school",
    "school": "school",
    "faculdade": "school",
    "universidade": "school",
    "uni": "school",
    "college": "school",
    "escuela": "school",
    "universidad": "school",
    # Parents
    "casa dos meus pais": "parents",
    "casa da minha mae": "parents",
    "casa do meu pai": "parents",
    "parents": "parents",
    "my parents": "parents",
    "mis padres": "parents",
    "casa de mis padres": "parents",
}

# Reverse: canonical key -> display label per language
LOCATION_LABELS: Dict[str, Dict[str, str]] = {
    "home": {"pt": "Casa", "en": "Home", "es": "Casa"},
    "work": {"pt": "Trabalho", "en": "Work", "es": "Trabajo"},
    "gym": {"pt": "Academia", "en": "Gym", "es": "Gimnasio"},
    "school": {"pt": "Escola/Faculdade", "en": "School", "es": "Escuela"},
    "parents": {
        "pt": "Casa dos pais",
        "en": "Parents' house",
        "es": "Casa de padres",
    },
}


def resolve_alias(text: str) -> Optional[str]:
    """
    Resolve user text to canonical location key.

    Args:
        text: User text like "casa", "trabalho", "gym"

    Returns:
        Canonical key like "home", "work", "gym" or None if not an alias.
    """
    lower = text.lower().strip()
    return LOCATION_ALIASES.get(lower)


def get_label(key: str, lang: str = "en") -> str:
    """Get human-readable label for a location key."""
    labels = LOCATION_LABELS.get(key, {})
    return labels.get(lang, labels.get("en", key.title()))


class SavedLocationsService:
    """
    Manage user's saved locations (home, work, gym, etc.).

    Uses the existing user_context table with context_type="saved_locations".
    Optionally geocodes addresses via MapsService.
    """

    CONTEXT_TYPE = "saved_locations"

    async def _get_db(self):
        """Get initialized database service."""
        db = get_service("database")
        if db and not db.is_initialized():
            await db.initialize()
        return db

    async def get_all_locations(self, user_id: str) -> Dict[str, Any]:
        """
        Get all saved locations for a user.

        Returns:
            Dict like {"home": {"address": "...", ...}, ...}
        """
        db = await self._get_db()
        if not db:
            return {}

        try:
            data = await db.get_user_context(user_id, self.CONTEXT_TYPE)
            if data and isinstance(data, dict):
                return data
            return {}
        except Exception as exc:
            logger.error("Error loading saved locations: %s", exc)
            return {}

    async def get_location(self, user_id: str, key: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific saved location.

        Args:
            user_id: User UUID
            key: Canonical location key ("home", "work", etc.)

        Returns:
            Dict with address/latitude/longitude, or None.
        """
        locations = await self.get_all_locations(user_id)
        return locations.get(key)

    async def save_location(
        self,
        user_id: str,
        key: str,
        address: str,
        geocode: bool = True,
    ) -> Dict[str, Any]:
        """
        Save a named location for the user.

        Args:
            user_id: User UUID
            key: Canonical location key ("home", "work", etc.)
            address: Human-readable address
            geocode: Whether to geocode the address for lat/lng

        Returns:
            The saved location data.
        """
        location_data: Dict[str, Any] = {"address": address}

        # Try to geocode for lat/lng
        if geocode:
            maps_svc = get_service("maps")
            if maps_svc:
                try:
                    if not maps_svc.is_initialized():
                        await maps_svc.initialize()
                    coords = await maps_svc.geocode(address)
                    if coords:
                        location_data["latitude"] = coords["latitude"]
                        location_data["longitude"] = coords["longitude"]
                except Exception as exc:
                    logger.debug("Geocode failed for saved location: %s", exc)

        # Load existing, merge, save
        db = await self._get_db()
        if not db:
            logger.error("Database not available for saving location")
            return location_data

        try:
            existing = await self.get_all_locations(user_id)
            existing[key] = location_data
            await db.save_user_context(user_id, self.CONTEXT_TYPE, existing)
            logger.info(
                "Saved location '%s' for user %s: %s",
                key,
                user_id[:8],
                address,
            )
            return location_data
        except Exception as exc:
            logger.error("Error saving location '%s': %s", key, exc)
            return location_data

    async def delete_location(self, user_id: str, key: str) -> bool:
        """Delete a saved location."""
        db = await self._get_db()
        if not db:
            return False

        try:
            existing = await self.get_all_locations(user_id)
            if key in existing:
                del existing[key]
                await db.save_user_context(user_id, self.CONTEXT_TYPE, existing)
                return True
            return False
        except Exception as exc:
            logger.error("Error deleting location '%s': %s", key, exc)
            return False

    async def resolve_address(self, user_id: str, text: str) -> Optional[str]:
        """
        Try to resolve user text to a saved address.

        If the text matches a known alias (e.g. "casa", "work"),
        returns the saved address. Otherwise returns None.

        Args:
            user_id: User UUID
            text: User input (e.g. "casa", "trabalho", "gym")

        Returns:
            Saved address string, or None if not found.
        """
        key = resolve_alias(text)
        if not key:
            return None

        location = await self.get_location(user_id, key)
        if location:
            return location.get("address")
        return None


# ── Singleton ─────────────────────────────────────────────────────────
_instance: Optional[SavedLocationsService] = None


def get_saved_locations_service() -> SavedLocationsService:
    """Get the singleton SavedLocationsService instance."""
    global _instance
    if _instance is None:
        _instance = SavedLocationsService()
    return _instance
