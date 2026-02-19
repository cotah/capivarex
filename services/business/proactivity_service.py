"""
Proactivity Service - Refactored Architecture.

Monitors user data and generates proactive insights with anti-spam filters.

Features:
- Context gathering from multiple services
- AI-powered insight generation
- SmartThings device monitoring
- Rate limiting and deduplication
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.core import (
    BaseService,
    register_service,
    get_service,
)

logger = logging.getLogger(__name__)


@register_service("proactivity")
class ProactivityService(BaseService):
    """
    Service for monitoring data and generating proactive insights.

    Features:
    - Multi-service context gathering
    - GPT-4o powered analysis
    - SmartThings device monitoring
    - Anti-spam filters (frequency + deduplication)
    """

    def __init__(self, name: str = "proactivity", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self._openai_client: Optional[Any] = None
        self._redis_client: Optional[Any] = None

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
                self._redis_client = redis_service.get_client()
            else:
                self.logger.warning("Redis service not available for proactivity")
        except Exception as e:
            self.logger.warning(f"Could not get Redis client: {e}")

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

    async def gather_context(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gather all context needed for proactivity analysis.

        Args:
            user: User data dictionary

        Returns:
            Context dictionary with data from all services
        """
        user_id = str(user.get("id", "unknown"))
        self.logger.info(f"Gathering context for user {user_id}...")

        location = user.get("location_preference", "Dublin")

        # Gather data from available services
        tasks: Dict[str, Any] = {}

        # Calendar
        calendar_service = get_service("calendar")
        if calendar_service and calendar_service.is_initialized():
            tasks["calendar"] = asyncio.to_thread(
                calendar_service.get_next_meeting
            )
        else:
            tasks["calendar"] = self._immediate({"error": "Calendar unavailable"})

        # Weather
        weather_service = get_service("weather")
        if weather_service and weather_service.is_initialized():
            tasks["weather"] = asyncio.to_thread(
                weather_service.get_current_weather, location
            )
        else:
            tasks["weather"] = self._immediate({"error": "Weather unavailable"})

        # Car
        car_service = get_service("car")
        if car_service and car_service.is_initialized():
            tasks["car_status"] = self._get_car_status(user_id)
        else:
            tasks["car_status"] = self._immediate(
                {"connected": False, "error": "Car unavailable"}
            )

        # Research/News
        research_service = get_service("research")
        if research_service and research_service.is_initialized():
            tasks["news"] = research_service.search_news(
                "latest technology and finance news"
            )
        else:
            tasks["news"] = self._immediate({"error": "Research unavailable"})

        # Finance
        finance_service = get_service("finance")
        if finance_service and finance_service.is_initialized():
            tasks["finance_alerts"] = asyncio.to_thread(
                finance_service.get_watchlist_summary, ["AAPL", "TSLA", "GOOGL"]
            )
        else:
            tasks["finance_alerts"] = self._immediate(
                {"error": "Finance unavailable"}
            )

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks.values(), return_exceptions=True),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            self.logger.error(f"Context gathering for user {user_id} timed out after 30s.")
            return {key: {"error": "Timeout"} for key in tasks.keys()}

        context: Dict[str, Any] = {}
        for key, value in zip(tasks.keys(), results):
            if isinstance(value, Exception):
                context[key] = {"error": str(value)}
            else:
                context[key] = value

        context["user"] = user

        # Add traffic if there's an event with location
        context["traffic"] = {}
        try:
            traffic_service = get_service("traffic")
            if (
                traffic_service
                and traffic_service.is_initialized()
                and isinstance(context.get("calendar"), dict)
                and context["calendar"].get("location")
            ):
                event = context["calendar"]
                start_value = event.get("start")
                if isinstance(start_value, str):
                    event_time = datetime.fromisoformat(
                        start_value.replace("Z", "+00:00")
                    )
                    event_time = event_time.replace(tzinfo=None)
                    context["traffic"] = await asyncio.to_thread(
                        traffic_service.check_traffic_before_event,
                        event.get("location"),
                        location,
                        event_time,
                        15,
                    )
        except Exception as e:
            self.logger.warning(f"Failed to get traffic context: {e}")
            context["traffic"] = {"error": str(e)}

        self.logger.info(f"Context gathered: {list(context.keys())}")
        return context

    async def check_smartthings_status(
        self,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Check SmartThings devices for proactive notifications.

        Args:
            user_id: User identifier

        Returns:
            Notification data if action needed, None otherwise
        """
        try:
            smartthings_service = get_service("smartthings")
            database_service = get_service("database")

            if not smartthings_service or not database_service:
                return None

            from utils.encryption import decrypt_token

            db_client = database_service.get_client()
            result = (
                db_client.table("smartthings_tokens")
                .select("*")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )

            if not result or not result.data:
                return None

            encrypted_token = result.data.get("access_token")
            if not encrypted_token:
                return None
            access_token = decrypt_token(encrypted_token)

            # Use the smartthings service with the user's token
            if not smartthings_service.is_initialized():
                await smartthings_service.initialize()

            devices = await smartthings_service.get_devices(access_token)

            issues: List[Dict[str, Any]] = []
            for device in devices:
                device_id = device.get("deviceId")
                label = device.get("label", "Device")
                if not device_id:
                    continue

                status = await smartthings_service.get_device_status(
                    device_id, access_token
                )

                capabilities: set = set()
                components = device.get("components", [])
                if isinstance(components, list):
                    for comp in components:
                        for cap in comp.get("capabilities", []):
                            if isinstance(cap, dict):
                                cap_id = cap.get("id")
                                if cap_id:
                                    capabilities.add(cap_id)
                            elif isinstance(cap, str):
                                capabilities.add(cap)

                main_status = status.get("components", {}).get("main", {})

                if "switch" in capabilities:
                    switch_status = (
                        main_status.get("switch", {})
                        .get("switch", {})
                        .get("value")
                    )
                    if switch_status == "on":
                        issues.append(
                            {
                                "type": "light_on",
                                "device_id": device_id,
                                "label": label,
                                "action": "turn_off",
                            }
                        )

                if "lock" in capabilities:
                    lock_status = (
                        main_status.get("lock", {})
                        .get("lock", {})
                        .get("value")
                    )
                    if lock_status == "unlocked":
                        issues.append(
                            {
                                "type": "door_unlocked",
                                "device_id": device_id,
                                "label": label,
                                "action": "lock",
                            }
                        )

                if "temperatureMeasurement" in capabilities:
                    temp_value = (
                        main_status.get("temperatureMeasurement", {})
                        .get("temperature", {})
                        .get("value")
                    )
                    if isinstance(temp_value, (int, float)) and (
                        temp_value < 5 or temp_value > 30
                    ):
                        issues.append(
                            {
                                "type": "temperature_issue",
                                "device_id": device_id,
                                "label": label,
                                "temperature": temp_value,
                                "action": "review_temperature",
                            }
                        )

            if not issues:
                return None

            return {
                "type": "smartthings_alert",
                "title": "Casa precisa de atencao",
                "message": self._build_smartthings_message(issues),
                "issues": issues,
                "actions": [
                    {"label": "Resolver Tudo", "action": "fix_all"},
                    {"label": "Ignorar", "action": "dismiss"},
                ],
            }
        except Exception as e:
            self.logger.error(f"SmartThings proactivity check failed: {e}")
            return None

    def _build_smartthings_message(self, issues: List[Dict[str, Any]]) -> str:
        """Build human-readable message from issues."""
        messages: List[str] = []

        lights_on = [i for i in issues if i["type"] == "light_on"]
        doors_unlocked = [i for i in issues if i["type"] == "door_unlocked"]
        temperature_issues = [i for i in issues if i["type"] == "temperature_issue"]

        if lights_on:
            count = len(lights_on)
            labels = ", ".join([i["label"] for i in lights_on])
            messages.append(f"{count} luz(es) acesa(s): {labels}")

        if doors_unlocked:
            count = len(doors_unlocked)
            labels = ", ".join([i["label"] for i in doors_unlocked])
            messages.append(f"{count} porta(s) destravada(s): {labels}")

        if temperature_issues:
            count = len(temperature_issues)
            labels = ", ".join(
                [f"{i['label']} ({i.get('temperature')}deg)" for i in temperature_issues]
            )
            messages.append(f"{count} alerta(s) de temperatura: {labels}")

        return "\n".join(messages)

    async def analyze_context_for_insights(
        self, context: Dict[str, Any]
    ) -> str:
        """
        Use GPT-4o to analyze context and generate proactive insights.

        Args:
            context: Gathered context dictionary

        Returns:
            Insight string, or empty if nothing important
        """
        if not self._openai_client:
            return ""

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
        - Traffic to Event: {context.get("traffic")}
        - Car Status: {context.get("car_status")}
        - News: {context.get("news")}
        - Stock Alerts: {context.get("finance_alerts")}

        Analysis: Is there something urgent or useful for the user now?
        """

        try:
            response = await self._openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=180,
                temperature=0.2,
                timeout=20.0,
            )
            insight = (response.choices[0].message.content or "").strip()

            if "[SILENCIO]" in insight or not insight:
                return ""

            return insight

        except Exception as e:
            self.logger.error(f"Error analyzing context for proactivity: {e}")
            return ""

    async def is_notification_allowed(
        self, user_id: str, insight: str
    ) -> bool:
        """
        Check repetition and frequency filters.

        Args:
            user_id: User identifier
            insight: Insight text to check

        Returns:
            True if notification is allowed
        """
        if not self._redis_client:
            return True  # Fail open if Redis unavailable

        now = datetime.now().timestamp()

        # Frequency filter (rate limiting)
        user_key_freq = f"proactive_freq:{user_id}"
        notifications = self._redis_client.lrange(user_key_freq, 0, -1)

        valid_timestamps = []
        for t in notifications:
            try:
                ts = float(t)
                if now - ts < 3600:
                    valid_timestamps.append(ts)
            except (TypeError, ValueError):
                continue

        if len(valid_timestamps) >= 5:  # Max 5 notifications per hour
            self.logger.warning(
                f"Frequency filter blocked notification for {user_id}"
            )
            return False

        # Deduplication filter (cooldown)
        insight_hash = hashlib.md5(insight.encode()).hexdigest()
        user_key_rep = f"proactive_rep:{user_id}:{insight_hash}"
        if self._redis_client.exists(user_key_rep):
            self.logger.warning(
                f"Deduplication filter blocked notification for {user_id}"
            )
            return False

        return True

    async def record_notification_sent(
        self, user_id: str, insight: str
    ) -> None:
        """
        Record that a notification was sent to activate filters.

        Args:
            user_id: User identifier
            insight: Sent insight text
        """
        if not self._redis_client:
            return

        now = datetime.now().timestamp()

        # Record for frequency filter (1 hour expiry)
        user_key_freq = f"proactive_freq:{user_id}"
        self._redis_client.lpush(user_key_freq, now)
        self._redis_client.expire(user_key_freq, 3600)

        # Record for deduplication filter (30 min expiry)
        insight_hash = hashlib.md5(insight.encode()).hexdigest()
        user_key_rep = f"proactive_rep:{user_id}:{insight_hash}"
        self._redis_client.set(user_key_rep, 1, ex=1800)


# Backward compatibility
def get_proactivity_service() -> ProactivityService:
    """Get the proactivity service singleton."""
    service = get_service("proactivity")
    if isinstance(service, ProactivityService):
        return service
    return ProactivityService()
