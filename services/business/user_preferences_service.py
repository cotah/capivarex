"""
User Preferences Service.

Provides:
- Fetch user preferences (creates defaults if missing)
- Upsert user preferences

Available columns:
    preferred_city, preferred_country_code, temperature_unit,
    home_temperature_threshold, light_auto_on, arrival_light_delay_hours,
    preferred_language, timezone, wake_up_time, sleep_time,
    proactive_enabled, notify_weather, notify_traffic, notify_reminders,
    home_latitude, home_longitude, work_latitude, work_longitude
"""

import logging
from typing import Any, Dict

from services.infrastructure.database import get_supabase_client

logger = logging.getLogger(__name__)


async def get_preferences(user_id: str) -> dict:
    """Busca preferências do utilizador. Cria registo padrão se não existir."""
    sb = get_supabase_client()
    if not sb:
        logger.warning("Database client unavailable for get_preferences")
        return {}

    try:
        res = (
            sb.table("user_preferences")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not res.data:
            # criar com defaults
            defaults: Dict[str, Any] = {"user_id": user_id}
            res = sb.table("user_preferences").insert(defaults).execute()
        return res.data or {}
    except Exception as e:
        logger.error("Failed to get preferences for %s: %s", user_id, e)
        return {}


async def set_preferences(user_id: str, **kwargs: Any) -> dict:
    """Upsert das preferências do utilizador."""
    sb = get_supabase_client()
    if not sb:
        logger.warning("Database client unavailable for set_preferences")
        return {}

    try:
        data: Dict[str, Any] = {"user_id": user_id, **kwargs}
        res = (
            sb.table("user_preferences")
            .upsert(data, on_conflict="user_id")
            .execute()
        )
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.error("Failed to set preferences for %s: %s", user_id, e)
        return {}
