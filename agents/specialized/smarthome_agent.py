"""
SmartHome Agent — Controls smart home devices via Tuya Cloud API.

Handles:
- Listing all devices
- Querying device status
- Turning devices on/off
- Setting brightness for lights
- Locking/unlocking smart locks
- Setting thermostat temperature
- General smart home questions
"""

import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang
from services.ai.model_config import INTENT_MODEL


logger = logging.getLogger(__name__)

# Valid intents for smart home commands
VALID_INTENTS = {
    "list_devices",
    "device_status",
    "turn_on",
    "turn_off",
    "set_brightness",
    "lock",
    "unlock",
    "thermostat",
    "general",
}


@register_agent("smarthome")
class SmartHomeAgent(BaseAgent):
    """Smart home agent for controlling devices via Tuya."""

    def __init__(self):
        super().__init__(
            name="smarthome", description="Controls smart home devices via Tuya"
        )

    # ------------------------------------------------------------------
    # Tuya OAuth helper
    # ------------------------------------------------------------------

    def _get_tuya_oauth(self) -> Optional[Any]:
        """Get the Tuya OAuth service."""
        try:
            from services.auth.tuya_oauth_service import get_tuya_oauth
            oauth = get_tuya_oauth()
            if oauth.client_id and oauth.client_secret:
                return oauth
            self.logger.warning("Tuya OAuth: client_id or client_secret missing")
            return None
        except Exception as e:
            self.logger.warning("Tuya OAuth service unavailable: %s", e)
            return None

    # ------------------------------------------------------------------
    # Intent classification (GPT-4o-mini)
    # ------------------------------------------------------------------

    async def _analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """
        Analyze user intent and extract device name using OpenAI.

        Device names are extracted EXACTLY as the user typed them,
        never translated — ensures matching against Tuya API labels.
        """
        openai_svc = get_service("openai")
        if not openai_svc:
            return {"intent": "general"}

        await openai_svc.initialize()
        client = openai_svc.get_client()
        if not client:
            return {"intent": "general"}

        system_prompt = (
            "You are an intent classifier for smart home commands.\n\n"
            "Analyze the user's message and return a JSON object with:\n"
            '- "intent": one of: list_devices, device_status, turn_on, turn_off, '
            "set_brightness, lock, unlock, thermostat, general\n"
            '- "device_name": the device name mentioned by the user, '
            "extracted EXACTLY as they typed it (NEVER translate it).\n"
            '- "brightness": brightness level 0-100 if mentioned, or null\n'
            '- "temperature": temperature value if mentioned, or null\n\n'
            "Examples:\n"
            '"turn the bedroom light off" → {"intent":"turn_off","device_name":"bedroom light","brightness":null,"temperature":null}\n'
            '"acenda as luzes da sala" → {"intent":"turn_on","device_name":"sala","brightness":null,"temperature":null}\n'
            '"quais dispositivos tenho?" → {"intent":"list_devices","device_name":null,"brightness":null,"temperature":null}\n'
            '"status da TV" → {"intent":"device_status","device_name":"TV","brightness":null,"temperature":null}\n'
            '"set brightness to 50%" → {"intent":"set_brightness","device_name":null,"brightness":50,"temperature":null}\n'
            '"lock the front door" → {"intent":"lock","device_name":"front door","brightness":null,"temperature":null}\n'
            '"set the AC to 22 degrees" → {"intent":"thermostat","device_name":"AC","brightness":null,"temperature":22}\n\n'
            "CRITICAL: Extract device_name in the ORIGINAL language the user used. "
            "Do NOT translate device names under any circumstances.\n\n"
            "Return ONLY the JSON object, no other text."
        )

        try:
            response = await client.chat.completions.create(
                model=INTENT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_completion_tokens=100,
            )

            import json

            raw = (response.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)

            intent = parsed.get("intent", "general")
            if intent not in VALID_INTENTS:
                intent = "general"

            return {
                "intent": intent,
                "device_name": parsed.get("device_name"),
                "brightness": parsed.get("brightness"),
                "temperature": parsed.get("temperature"),
            }

        except Exception as e:
            self.logger.warning(f"SmartHome intent analysis failed: {e}")
            return {"intent": "general"}

    # ------------------------------------------------------------------
    # Main execute
    # ------------------------------------------------------------------

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Process smart home queries and commands via Tuya."""
        lang = get_user_lang(context)
        user_id = context.get("user_id", "")

        tuya = self._get_tuya_oauth()
        if tuya and user_id:
            try:
                is_connected = await tuya.is_connected(user_id)
                if is_connected:
                    return await self._execute_tuya(tuya, user_id, prompt, context, lang)
            except Exception as e:
                self.logger.error("Tuya check failed: %s", e)

        # Not connected
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=t("smarthome_not_connected_tuya", lang=lang),
            data={"needs_connection": True},
        )

    # ------------------------------------------------------------------
    # Tuya command execution
    # ------------------------------------------------------------------

    async def _execute_tuya(
        self, tuya: Any, user_id: str, prompt: str,
        context: Dict[str, Any], lang: str,
    ) -> AgentResponse:
        """Execute smart home commands via Tuya API."""
        analysis = await self._analyze_intent(prompt)
        intent = analysis["intent"]
        device_name = analysis.get("device_name")

        try:
            if intent == "list_devices":
                return await self._tuya_list_devices(tuya, user_id, lang)
            elif intent == "device_status":
                return await self._tuya_device_status(tuya, user_id, device_name, lang)
            elif intent in ("turn_on", "lock"):
                return await self._tuya_switch(tuya, user_id, device_name, True, lang)
            elif intent in ("turn_off", "unlock"):
                return await self._tuya_switch(tuya, user_id, device_name, False, lang)
            elif intent == "set_brightness":
                brightness = analysis.get("brightness", 50)
                return await self._tuya_brightness(tuya, user_id, device_name, brightness, lang)
            elif intent == "thermostat":
                temperature = analysis.get("temperature", 22)
                return await self._tuya_thermostat(tuya, user_id, device_name, temperature, lang)
            else:
                return await self._tuya_list_devices(tuya, user_id, lang)
        except Exception as e:
            self.logger.error(f"Tuya command failed: {e}", exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("smarthome_command_error", lang=lang, error=str(e)),
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Tuya device helpers
    # ------------------------------------------------------------------

    async def _tuya_find_device(
        self, tuya: Any, user_id: str, device_name: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Find a Tuya device by name (fuzzy match)."""
        devices = await tuya.get_user_devices(user_id)
        if not devices or not device_name:
            return None
        name_lower = device_name.lower()
        for d in devices:
            label = (d.get("name") or d.get("custom_name") or "").lower()
            if name_lower in label or label in name_lower:
                return d
        for d in devices:
            label = (d.get("name") or d.get("custom_name") or "").lower()
            if any(word in label for word in name_lower.split()):
                return d
        return None

    async def _tuya_list_devices(
        self, tuya: Any, user_id: str, lang: str,
    ) -> AgentResponse:
        """List all Tuya devices."""
        devices = await tuya.get_user_devices(user_id)
        if not devices:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_no_devices", lang=lang),
                data={"devices": []},
            )
        lines = [t("smarthome_devices_header", lang=lang)]
        for i, d in enumerate(devices, 1):
            name = d.get("name") or d.get("custom_name") or "Unknown"
            category = d.get("category", "")
            online = "🟢" if d.get("online") else "🔴"
            lines.append(f"{i}. {online} **{name}** — {category}")
        lines.append(t("smarthome_devices_total", lang=lang, count=len(devices)))
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"devices": devices, "count": len(devices)},
        )

    async def _tuya_device_status(
        self, tuya: Any, user_id: str, device_name: Optional[str], lang: str,
    ) -> AgentResponse:
        """Get status of a Tuya device."""
        device = await self._tuya_find_device(tuya, user_id, device_name)
        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_device_not_found", lang=lang, name=device_name or "unknown"),
            )
        device_id = device.get("id")
        name = device.get("name") or device.get("custom_name") or "Device"
        status_list = await tuya.get_device_status(user_id, device_id)
        online = "🟢 Online" if device.get("online") else "🔴 Offline"
        lines = [f"**{name}** — {online}"]
        for s in (status_list or []):
            code = s.get("code", "")
            value = s.get("value", "")
            lines.append(f"  • {code}: {value}")
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"device": device, "status": status_list},
        )

    async def _tuya_switch(
        self, tuya: Any, user_id: str, device_name: Optional[str],
        turn_on: bool, lang: str,
    ) -> AgentResponse:
        """Turn a Tuya device on or off."""
        device = await self._tuya_find_device(tuya, user_id, device_name)
        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_device_not_found", lang=lang, name=device_name or "unknown"),
            )
        device_id = device.get("id")
        name = device.get("name") or device.get("custom_name") or "Device"

        # Get device status to discover actual switch codes
        status_list = await tuya.get_device_status(user_id, device_id)
        device_codes = [s.get("code", "") for s in (status_list or [])]

        # Build list of switch codes to try, prioritizing codes the device actually has
        known_switch_codes = ["switch_led", "switch_1", "switch", "switch_led_1", "Power", "power"]
        codes_to_try = [c for c in known_switch_codes if c in device_codes]
        # Also try any boolean codes from status that look like switches
        for s in (status_list or []):
            code = s.get("code", "")
            value = s.get("value")
            if isinstance(value, bool) and code not in codes_to_try:
                codes_to_try.append(code)
        # Fallback to known codes if none found
        if not codes_to_try:
            codes_to_try = known_switch_codes

        for code in codes_to_try:
            result = await tuya.send_command(user_id, device_id, [{"code": code, "value": turn_on}])
            if result.get("success"):
                if turn_on:
                    action = t("smarthome_turned_on", lang=lang, label=name)
                else:
                    action = t("smarthome_turned_off", lang=lang, label=name)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=action,
                    data={"device_id": device_id, "action": "on" if turn_on else "off"},
                )
            # Device offline — stop immediately
            if result.get("error") == "device_offline":
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=f"📴 {name} is offline. Check if it's powered on and connected to WiFi.",
                )
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=t("smarthome_command_error", lang=lang, error=f"No switch code found for {name}. Available codes: {', '.join(device_codes)}"),
        )

    async def _tuya_brightness(
        self, tuya: Any, user_id: str, device_name: Optional[str],
        brightness: int, lang: str,
    ) -> AgentResponse:
        """Set brightness of a Tuya light."""
        device = await self._tuya_find_device(tuya, user_id, device_name)
        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_device_not_found", lang=lang, name=device_name or "unknown"),
            )
        device_id = device.get("id")
        name = device.get("name") or device.get("custom_name") or "Light"
        tuya_brightness = max(10, min(1000, int(brightness * 10)))
        for code in ["bright_value_v2", "bright_value"]:
            result = await tuya.send_command(user_id, device_id, [{"code": code, "value": tuya_brightness}])
            if result.get("success"):
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=t("smarthome_brightness_set", lang=lang, name=name, brightness=brightness),
                )
            if result.get("error") == "device_offline":
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=f"📴 {name} is offline.",
                )
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=t("smarthome_command_error", lang=lang, error="Brightness not supported"),
        )

    async def _tuya_thermostat(
        self, tuya: Any, user_id: str, device_name: Optional[str],
        temperature: int, lang: str,
    ) -> AgentResponse:
        """Set thermostat temperature."""
        device = await self._tuya_find_device(tuya, user_id, device_name)
        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_device_not_found", lang=lang, name=device_name or "unknown"),
            )
        device_id = device.get("id")
        name = device.get("name") or device.get("custom_name") or "Thermostat"
        result = await tuya.send_command(user_id, device_id, [{"code": "temp_set", "value": temperature}])
        if result.get("success"):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_thermostat_set", lang=lang, name=name, temp=temperature),
            )
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=t("smarthome_command_error", lang=lang, error="Thermostat command failed"),
        )

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def get_capabilities(self) -> List[str]:
        """Get smart home agent capabilities."""
        return [
            "device_control",
            "device_status",
            "light_control",
            "lock_control",
            "thermostat_control",
            "device_listing",
        ]
