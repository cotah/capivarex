"""
Proactivity Service - Refactored Architecture.

Monitors user data and generates proactive insights with anti-spam filters.

Features:
- Context gathering from multiple services
- AI-powered insight generation
- Smart home device monitoring
- Rate limiting and deduplication
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pybreaker
from pydantic import ValidationError

from services.core import (
    BaseService,
    register_service,
    get_service,
)
from services.ai.model_config import DEFAULT_MODEL
from schemas.context import UserContext
from .schemas import WeatherData, CalendarEvent, FinanceData
from .user_preferences_service import get_preferences

logger = logging.getLogger(__name__)


@register_service("proactivity")
class ProactivityService(BaseService):
    """
    Service for monitoring data and generating proactive insights.

    Features:
    - Multi-service context gathering
    - GPT-4o powered analysis
    - Smart home device monitoring
    - Anti-spam filters (frequency + deduplication)
    """

    def __init__(self, name: str = "proactivity", config: Dict[str, Any] = None):
        """Initialise the proactivity service with circuit breakers."""
        super().__init__(name, config)
        self._openai_client: Optional[Any] = None
        self._redis_client: Optional[Any] = None
        self._redis_service: Optional[Any] = None

        # Circuit breakers: open after N consecutive failures, reset after timeout
        self._service_breakers = {
            "calendar": pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60),
            "weather": pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60),
            "car": pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60),
            "research": pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60),
            "finance": pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60),
            "traffic": pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60),
            "openai": pybreaker.CircuitBreaker(fail_max=2, reset_timeout=120),
        }

    async def _initialize(self) -> None:
        """Initialize dependencies."""
        try:
            openai_service = get_service("openai")
            if openai_service and openai_service.is_initialized():
                self._openai_client = openai_service.get_client()
            else:
                self.logger.warning("OpenAI service not available for proactivity")
        except Exception as e:
            self.logger.warning(f"Could not get OpenAI client: {e}")

        try:
            redis_service = get_service("redis")
            if redis_service and redis_service.is_initialized():
                self._redis_service = redis_service
                self._redis_client = redis_service
            else:
                self.logger.warning("Redis service not available for proactivity")
        except Exception as e:
            self.logger.warning(f"Could not get Redis service: {e}")

        self.logger.info("ProactivityService initialized")

    async def _health_check(self) -> bool:
        """Check if proactivity service is healthy."""
        return self._openai_client is not None

    @staticmethod
    async def _immediate(value: Any) -> Any:
        """Return value immediately as async."""
        return value

    async def _get_car_status(self, user_id: str) -> Dict[str, Any]:
        """Get essential car status (battery + location)."""
        try:
            vehicle_db = get_service("vehicle_db")
            car_service = get_service("car")

            if not vehicle_db or not car_service:
                return {"connected": False, "message": "Car services unavailable"}

            if not vehicle_db.is_initialized():
                await vehicle_db.initialize()
            if not car_service.is_initialized():
                await car_service.initialize()

            vehicle = await vehicle_db.get_primary_vehicle(user_id)
            if not vehicle:
                return {"connected": False, "message": "No vehicle connected"}

            vehicle_id = vehicle.get("vehicle_id")
            access_token = vehicle.get("access_token")

            if not vehicle_id or not access_token:
                return {"connected": False, "message": "Incomplete vehicle data"}

            battery = await car_service.get_battery_level(vehicle_id, access_token)
            location = await car_service.get_location(vehicle_id, access_token)

            return {
                "connected": True,
                "vehicle_id": vehicle_id,
                "battery": battery,
                "location": location,
            }
        except Exception as e:
            self.logger.warning(f"Failed to get car status for {user_id}: {e}")
            return {"connected": False, "error": str(e)}

    async def gather_context(self, user_context: UserContext) -> Dict[str, Any]:
        """
        Gather all context needed for proactivity analysis.

        Args:
            user_context: Validated UserContext object

        Returns:
            Context dictionary with data from all services
        """
        user_id = user_context.user_id
        self.logger.info(f"Gathering context for user {user_id}...")

        # Fetch user preferences for personalised context
        try:
            prefs = await get_preferences(user_id)
        except Exception:
            prefs = {}

        location = (
            prefs.get("preferred_city")
            or user_context.extra_data.get("location_preference")
            or "Dublin"
        )

        # Build a dict of coroutines keyed by service name so they can all
        # run concurrently via asyncio.gather.  Each coroutine is wrapped by
        # its service-specific circuit breaker to prevent cascading failures.
        tasks: Dict[str, Any] = {}

        # Check device permissions
        active_device = user_context.devices[0] if user_context.devices else None
        device_permissions = active_device.permissions if active_device else []

        # Calendar (requires calendar:read permission if device is present)
        calendar_service = get_service("calendar")
        calendar_breaker = self._service_breakers["calendar"]
        if active_device and "calendar:read" not in device_permissions:
            self.logger.info(
                f"Calendar access denied for user {user_id}: missing calendar:read permission"
            )
            tasks["calendar"] = self._immediate({"error": "Permission denied"})
        elif (
            calendar_service
            and calendar_service.is_initialized()
            and not calendar_breaker.current_state == "open"
        ):

            @calendar_breaker
            async def protected_calendar_call():
                """Fetch the next meeting via the calendar service (circuit-protected)."""
                return await calendar_service.async_get_next_meeting(user_id=user_id)

            tasks["calendar"] = protected_calendar_call()
        else:
            error_msg = "Calendar unavailable"
            if calendar_breaker.current_state == "open":
                error_msg = "Calendar service is offline (Circuit Open)"
            tasks["calendar"] = self._immediate({"error": error_msg})

        # Weather
        weather_service = get_service("weather")
        weather_breaker = self._service_breakers["weather"]
        if (
            weather_service
            and weather_service.is_initialized()
            and not weather_breaker.current_state == "open"
        ):

            @weather_breaker
            async def protected_weather_call():
                """Fetch current weather for *location* (circuit-protected)."""
                return await asyncio.to_thread(
                    weather_service.get_current_weather, location
                )

            tasks["weather"] = protected_weather_call()
        else:
            error_msg = "Weather unavailable"
            if weather_breaker.current_state == "open":
                error_msg = "Weather service is offline (Circuit Open)"
            tasks["weather"] = self._immediate({"error": error_msg})

        # Car: PAUSED — TODO: Reativar no Q3 2026 (agente car desativado)
        # News/Research: PAUSED — TODO: Reativar no Q3 2026 (news fetch removido do loop)

        # Finance
        finance_service = get_service("finance")
        finance_breaker = self._service_breakers["finance"]
        if (
            finance_service
            and finance_service.is_initialized()
            and not finance_breaker.current_state == "open"
        ):

            @finance_breaker
            async def protected_finance_call():
                """Fetch watchlist stock summaries (circuit-protected)."""
                return await asyncio.to_thread(
                    finance_service.get_watchlist_summary, ["AAPL", "TSLA", "GOOGL"]
                )

            tasks["finance_alerts"] = protected_finance_call()
        else:
            error_msg = "Finance unavailable"
            if finance_breaker.current_state == "open":
                error_msg = "Finance service is offline (Circuit Open)"
            tasks["finance_alerts"] = self._immediate({"error": error_msg})

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks.values(), return_exceptions=True), timeout=30.0
            )
        except asyncio.TimeoutError:
            self.logger.error(
                f"Context gathering for user {user_id} timed out after 30s."
            )
            return {key: {"error": "Timeout"} for key in tasks.keys()}

        # Map context keys to their validation schemas
        # car_status and news removed — agents paused (Q3 2026)
        schema_map = {
            "calendar": CalendarEvent,
            "weather": WeatherData,
            "finance_alerts": FinanceData,
        }

        context: Dict[str, Any] = {}
        for key, value in zip(tasks.keys(), results):
            if isinstance(value, Exception):
                context[key] = {"error": str(value)}
                self.logger.warning(f"Service '{key}' failed with exception: {value}")
                continue

            schema = schema_map.get(key)
            if schema:
                try:
                    if isinstance(value, list):
                        validated_data = [schema.model_validate(item) for item in value]
                        context[key] = [item.model_dump() for item in validated_data]
                    else:
                        validated_data = schema.model_validate(value)
                        context[key] = validated_data.model_dump()
                    self.logger.info(f"Service '{key}' data validated successfully.")
                except ValidationError as e:
                    context[key] = {"error": "Invalid data structure"}
                    self.logger.error(f"Service '{key}' data validation failed: {e}")
            else:
                context[key] = value

        context["user"] = user_context.model_dump()
        context["preferences"] = prefs

        # Enrich with home/work coordinates when available
        home_lat = prefs.get("home_latitude")
        home_lon = prefs.get("home_longitude")
        if home_lat and home_lon:
            context["home_location"] = {"latitude": home_lat, "longitude": home_lon}

        work_lat = prefs.get("work_latitude")
        work_lon = prefs.get("work_longitude")
        if work_lat and work_lon:
            context["work_location"] = {"latitude": work_lat, "longitude": work_lon}

        # Traffic: PAUSED — TODO: Reativar no Q3 2026 (agente traffic desativado)

        self.logger.info(f"Context gathered: {list(context.keys())}")
        return context

    async def check_smart_home_status(
        self,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Check smart home devices for proactive notifications.
        Future: will use Tuya API to detect lights left on, etc.
        """
        return None

    async def analyze_context_for_insights(self, context: Dict[str, Any]) -> str:
        """
        Use GPT-4o to analyze context and generate proactive insights.

        Args:
            context: Gathered context dictionary

        Returns:
            Insight string, or empty if nothing important
        """
        openai_breaker = self._service_breakers["openai"]
        if not self._openai_client or openai_breaker.current_state == "open":
            if openai_breaker.current_state == "open":
                self.logger.warning(
                    "OpenAI circuit breaker is open. Skipping insight analysis."
                )
            return ""

        # Fetch long-term memories for richer context
        memory_context = ""
        user_data = context.get("user", {})
        user_id = user_data.get("user_id", "")
        if user_id:
            try:
                from bot.core.memory import MemoryManager

                db_service = get_service("database")
                if db_service and db_service.is_initialized():
                    memory_manager = MemoryManager(db_service)
                    memory_context = await memory_manager.get_context_for_ai(user_id)
            except Exception as e:
                self.logger.warning(f"Could not fetch memories for prompt: {e}")

        prompt = f"""
        You are the proactive brain of SuperBot God, a personal AI assistant.
        Analyze the user context and decide if there is something URGENT or USEFUL to notify.

        RULES:
        1. FOCUS ON UTILITY: Only generate a notification if truly valuable.
        2. BE CONCISE: Short and direct messages.
        3. [SILENCIO]: If nothing important, respond ONLY with `[SILENCIO]`.
        4. NO GREETINGS: Get straight to the point.

        CURRENT CONTEXT:
        - User: {context.get("user")}
        - Next Event: {context.get("calendar")}
        - Weather: {context.get("weather")}
        - Stock Alerts: {context.get("finance_alerts")}

        {memory_context}

        Analysis: Is there something urgent or useful for the user now?
        """

        @openai_breaker
        async def protected_openai_call():
            """Send the proactivity prompt to GPT-4o and return the response text (circuit-protected)."""
            response = await self._openai_client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=180,
                temperature=0.2,
                timeout=20.0,
            )
            return (response.choices[0].message.content or "").strip()

        try:
            insight = await protected_openai_call()

            if "[SILENCIO]" in insight or not insight:
                return ""

            return insight

        except pybreaker.CircuitBreakerError:
            self.logger.error("OpenAI call blocked by open circuit breaker.")
            return ""
        except Exception as e:
            self.logger.error(f"Error analyzing context for proactivity: {e}")
            return ""

    async def is_notification_allowed(self, user_id: str, insight: str) -> bool:
        """
        Check repetition and frequency filters.

        Uses async RedisService API (Upstash REST).

        Args:
            user_id: User identifier
            insight: Insight text to check

        Returns:
            True if notification is allowed
        """
        redis_svc = self._redis_client
        if not redis_svc:
            return True  # Fail open if Redis unavailable

        now = datetime.now().timestamp()

        try:
            # Frequency filter: timestamps stored as JSON list
            user_key_freq = f"proactive_freq:{user_id}"
            stored = await redis_svc.get(user_key_freq)
            timestamps: list = stored if isinstance(stored, list) else []
            valid_timestamps = [ts for ts in timestamps if now - ts < 3600]

            if len(valid_timestamps) >= 5:
                self.logger.warning(
                    f"Frequency filter blocked notification for {user_id}"
                )
                return False

            # Deduplication filter
            insight_hash = hashlib.md5(insight.encode()).hexdigest()
            user_key_rep = f"proactive_rep:{user_id}:{insight_hash}"
            existing = await redis_svc.get(user_key_rep)
            if existing is not None:
                self.logger.warning(
                    f"Deduplication filter blocked notification for {user_id}"
                )
                return False

        except Exception as e:
            self.logger.warning(f"Redis filter check failed (fail-open): {e}")
            return True  # Fail open on Redis error

        return True

    async def record_notification_sent(self, user_id: str, insight: str) -> None:
        """
        Record that a notification was sent to activate filters.

        Uses async RedisService API (Upstash REST).

        Args:
            user_id: User identifier
            insight: Sent insight text
        """
        redis_svc = self._redis_client
        if not redis_svc:
            return

        now = datetime.now().timestamp()

        try:
            # Frequency filter: read current list, append, save (keep last 10)
            user_key_freq = f"proactive_freq:{user_id}"
            stored = await redis_svc.get(user_key_freq)
            timestamps: list = stored if isinstance(stored, list) else []
            timestamps.append(now)
            timestamps = timestamps[-10:]
            await redis_svc.set(user_key_freq, timestamps, expire_seconds=3600)

            # Deduplication filter (30 min expiry)
            insight_hash = hashlib.md5(insight.encode()).hexdigest()
            user_key_rep = f"proactive_rep:{user_id}:{insight_hash}"
            await redis_svc.set(user_key_rep, 1, expire_seconds=1800)

        except Exception as e:
            self.logger.warning(f"Redis notification recording failed: {e}")


# Backward compatibility
def get_proactivity_service() -> ProactivityService:
    """Get the proactivity service singleton."""
    service = get_service("proactivity")
    if isinstance(service, ProactivityService):
        return service
    return ProactivityService()
