"""
Restaurant DB Service.

Persistence layer for restaurant searches, favorites and reservations.

Tables:
    restaurant_searches     — search history / analytics
    restaurant_favorites    — user's saved restaurants
    restaurant_reservations — reservation requests
"""

import logging
from typing import Any, Dict, List, Optional

from services.infrastructure.database import get_supabase_client

logger = logging.getLogger(__name__)


async def save_search(
    user_id: str,
    cuisine: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: int = 5,
    open_now: bool = False,
    min_rating: Optional[float] = None,
    results_count: int = 0,
) -> None:
    """Log a restaurant search for analytics."""
    sb = get_supabase_client()
    if not sb:
        return
    try:
        sb.table("restaurant_searches").insert(
            {
                "user_id": user_id,
                "cuisine": cuisine,
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "open_now": open_now,
                "min_rating": min_rating,
                "results_count": results_count,
            }
        ).execute()
    except Exception as e:
        logger.error("Failed to save restaurant search: %s", e)


async def add_favorite(
    user_id: str,
    place_id: str,
    name: str,
    address: Optional[str] = None,
    rating: Optional[float] = None,
    cuisine: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Dict[str, Any]:
    """Add a restaurant to the user's favorites."""
    sb = get_supabase_client()
    if not sb:
        return {}
    try:
        res = (
            sb.table("restaurant_favorites")
            .insert(
                {
                    "user_id": user_id,
                    "place_id": place_id,
                    "name": name,
                    "address": address,
                    "rating": rating,
                    "cuisine": cuisine,
                    "latitude": latitude,
                    "longitude": longitude,
                }
            )
            .execute()
        )
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.error("Failed to add favorite: %s", e)
        return {}


async def get_favorites(user_id: str) -> List[Dict[str, Any]]:
    """Return all favorites for a user, newest first."""
    sb = get_supabase_client()
    if not sb:
        return []
    try:
        res = (
            sb.table("restaurant_favorites")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("Failed to get favorites: %s", e)
        return []


async def create_reservation(
    user_id: str,
    place_id: str,
    restaurant_name: str,
    restaurant_phone: Optional[str] = None,
    party_size: Optional[int] = None,
    reservation_dt: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pending reservation request."""
    sb = get_supabase_client()
    if not sb:
        return {}
    try:
        res = (
            sb.table("restaurant_reservations")
            .insert(
                {
                    "user_id": user_id,
                    "place_id": place_id,
                    "restaurant_name": restaurant_name,
                    "restaurant_phone": restaurant_phone,
                    "party_size": party_size,
                    "reservation_dt": reservation_dt,
                    "notes": notes,
                    "status": "pending",
                }
            )
            .execute()
        )
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.error("Failed to create reservation: %s", e)
        return {}


async def get_reservations(user_id: str) -> List[Dict[str, Any]]:
    """Return all reservations for a user, newest first."""
    sb = get_supabase_client()
    if not sb:
        return []
    try:
        res = (
            sb.table("restaurant_reservations")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("Failed to get reservations: %s", e)
        return []
