"""
User Preferences Service.

Provides:
- Fetch user preferences (creates defaults if missing)
- Upsert user preferences
- Save/get GPS location

Available columns:
  preferred_city, preferred_country_code, temperature_unit,
  home_temperature_threshold, light_auto_on, arrival_light_delay_hours,
  preferred_language, timezone, wake_up_time, sleep_time,
  proactive_enabled, notify_weather, notify_traffic, notify_reminders,
  home_latitude, home_longitude, work_latitude, work_longitude,
  home_address, work_address,
  last_latitude, last_longitude, last_location_at
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from services.infrastructure.database import get_supabase_client

logger = logging.getLogger(__name__)


async def get_preferences(user_id: str) -> dict:
    """Busca preferências do utilizador. Cria registo padrão se não existir."""
    try:
        sb = get_supabase_client()
    except Exception:
        return {}
    if not sb:
        return {}
    try:
        res = (
            sb.table("user_preferences")
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if res.data:
            return res.data
        # criar com defaults
        defaults: Dict[str, Any] = {"user_id": user_id}
        res = sb.table("user_preferences").insert(defaults).execute()
        return res.data[0] if res.data else {}
    except Exception:
        return {}


async def set_preferences(user_id: str, **kwargs: Any) -> dict:
    """Upsert das preferências do utilizador."""
    try:
        sb = get_supabase_client()
        data: Dict[str, Any] = {"user_id": user_id, **kwargs}
        res = sb.table("user_preferences").upsert(data, on_conflict="user_id").execute()
        return res.data[0] if res.data else {}
    except Exception:
        return {}


async def save_location(
    user_id: str,
    latitude: float,
    longitude: float,
    location_type: str = "last",
) -> dict:
    """
    Guarda localização GPS do utilizador.

    Args:
        user_id: ID do utilizador
        latitude: Latitude GPS
        longitude: Longitude GPS
        location_type: "last" (localização actual),
                       "home" (casa),
                       "work" (trabalho)

    Returns:
        Preferências actualizadas
    """
    now = datetime.now(timezone.utc).isoformat()

    if location_type == "home":
        return await set_preferences(
            user_id,
            home_latitude=latitude,
            home_longitude=longitude,
            last_latitude=latitude,
            last_longitude=longitude,
            last_location_at=now,
        )
    elif location_type == "work":
        return await set_preferences(
            user_id,
            work_latitude=latitude,
            work_longitude=longitude,
            last_latitude=latitude,
            last_longitude=longitude,
            last_location_at=now,
        )
    else:
        return await set_preferences(
            user_id,
            last_latitude=latitude,
            last_longitude=longitude,
            last_location_at=now,
        )


async def get_location(
    user_id: str,
    prefer: str = "last",
) -> Optional[Tuple[float, float]]:
    """
    Retorna (latitude, longitude) do utilizador.

    Args:
        user_id: ID do utilizador
        prefer: "last" (mais recente), "home", "work"

    Returns:
        Tuple (lat, lng) ou None se não disponível
    """
    prefs = await get_preferences(user_id)
    if not prefs:
        return None

    if prefer == "home":
        lat = prefs.get("home_latitude")
        lng = prefs.get("home_longitude")
    elif prefer == "work":
        lat = prefs.get("work_latitude")
        lng = prefs.get("work_longitude")
    else:
        lat = prefs.get("last_latitude")
        lng = prefs.get("last_longitude")

    if lat is not None and lng is not None:
        return (float(lat), float(lng))
    return None


async def has_location(user_id: str) -> bool:
    """Verifica se o utilizador tem localização guardada."""
    loc = await get_location(user_id)
    return loc is not None
