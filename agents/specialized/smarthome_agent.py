"""
SmartHome Agent - Controls smart home devices via SmartThings API.

Refactored to use new BaseAgent architecture.
"""

import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang
from services.integrations.smartthings_oauth import get_smartthings_token_manager


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
    """
    Smart home agent for controlling devices via SmartThings.

    Handles:
    - Listing all devices
    - Querying device status
    - Turning devices on/off
    - Setting brightness for lights
    - Locking/unlocking smart locks
    - Setting thermostat temperature
    - General smart home questions
    """

    def __init__(self):
        """Initialise the smart home agent."""
        super().__init__(
            name="smarthome", description="Controls smart home devices via SmartThings"
        )

    async def _get_smartthings_service(self) -> Optional[Any]:
        """Get the SmartThings service, initializing if needed."""
        try:
            svc = get_service("smartthings")
            if svc:
                await svc.initialize()
                return svc
            return None
        except Exception as e:
            self.logger.warning(f"Could not get SmartThings service: {e}")
            return None

    async def _load_stored_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load SmartThings connection from DB for a user."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.get_smartthings_connection(user_id)
        except Exception as e:
            self.logger.warning(f"Could not load smartthings connection: {e}")
        return None

    async def _save_connection(
        self,
        user_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: str,
        installed_app_id: str,
        location_id: str,
    ) -> bool:
        """Persist SmartThings connection to DB."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.save_smartthings_connection(
                    user_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    installed_app_id,
                    location_id,
                )
        except Exception as e:
            self.logger.warning(f"Could not save smartthings connection: {e}")
        return False

    async def _analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """
        Analyze user intent and extract device name using OpenAI.

        IMPORTANT: Device names are extracted EXACTLY as the user typed them,
        never translated. This ensures matching against SmartThings API labels.

        Returns:
            Dict with 'intent' and optional 'device_name', 'brightness', 'temperature'
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
            "extracted EXACTLY as they typed it (NEVER translate it). "
            'For example, if the user says "bedroom light", return "bedroom light", '
            'NOT "luz do quarto". If the user says "luz da sala", return "luz da sala", '
            "NOT \"living room light\". The device name must match the user's exact words.\n"
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
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_completion_tokens=100,
            )

            import json

            raw = (response.choices[0].message.content or "").strip()
            # Remove markdown code fences if present
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

    async def _find_device_by_name(
        self,
        smartthings: Any,
        device_name: Optional[str],
        access_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a device by partial name match.

        Returns the best matching device dict, or None.
        """
        if not device_name:
            return None

        try:
            devices = await smartthings.get_devices(access_token=access_token)
            name_lower = device_name.lower()

            for device in devices:
                label = (device.get("label") or device.get("name") or "").lower()
                if name_lower in label or label in name_lower:
                    return device

            # Fuzzy: check if any word matches
            for device in devices:
                label = (device.get("label") or device.get("name") or "").lower()
                for word in name_lower.split():
                    if len(word) > 2 and word in label:
                        return device

            return None
        except Exception as e:
            self.logger.warning(f"Device lookup failed: {e}")
            return None

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """
        Process smart home queries and commands.

        Args:
            prompt: User's smart home query or command
            context: Execution context with optional access_token

        Returns:
            AgentResponse with device data or command result
        """
        lang = get_user_lang(context)

        # Get a valid token via the OAuth2 token manager (auto-refreshes)
        token_manager = get_smartthings_token_manager()
        access_token = await token_manager.get_valid_token()

        # Allow explicit context override (e.g. per-user OAuth connection)
        access_token = (
            context.get("smartthings_access_token")
            or context.get("access_token")
            or access_token
        )

        # Get SmartThings service
        smartthings = await self._get_smartthings_service()
        if not smartthings:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("smarthome_service_unavailable", lang=lang),
                error="SmartThings service not available",
            )

        # Check if we have any token at all
        if not access_token and not smartthings.access_token:
            import os
            from urllib.parse import urlencode

            client_id = os.getenv("SMARTTHINGS_CLIENT_ID", "")
            redirect_uri = os.getenv("SMARTTHINGS_REDIRECT_URI", "")
            user_id = context.get("user_id", "unknown")

            if client_id and redirect_uri:
                params = urlencode(
                    {
                        "client_id": client_id,
                        "redirect_uri": redirect_uri,
                        "response_type": "code",
                        "scope": "r:devices:* x:devices:* r:locations:* w:devices:*",
                        "state": user_id,
                    }
                )
                oauth_url = f"https://api.smartthings.com/oauth/authorize?{params}"
                connect_msg = t(
                    "smarthome_not_connected", lang=lang, url=oauth_url
                )
            else:
                connect_msg = t("smarthome_not_connected_no_config", lang=lang)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=connect_msg,
                data={"needs_connection": True},
            )

        # Analyze intent
        analysis = await self._analyze_intent(prompt)
        intent = analysis["intent"]
        device_name = analysis.get("device_name")

        try:
            if intent == "list_devices":
                return await self._handle_list_devices(
                    smartthings, access_token, lang
                )

            elif intent == "device_status":
                return await self._handle_device_status(
                    smartthings, device_name, access_token, lang
                )

            elif intent == "turn_on":
                brightness = analysis.get("brightness")
                return await self._handle_turn_on(
                    smartthings, device_name, brightness, access_token, lang
                )

            elif intent == "turn_off":
                return await self._handle_turn_off(
                    smartthings, device_name, access_token, lang
                )

            elif intent == "set_brightness":
                brightness = analysis.get("brightness", 50)
                return await self._handle_set_brightness(
                    smartthings, device_name, brightness, access_token, lang
                )

            elif intent == "lock":
                return await self._handle_lock(
                    smartthings, device_name, access_token, lang
                )

            elif intent == "unlock":
                return await self._handle_unlock(
                    smartthings, device_name, access_token, lang
                )

            elif intent == "thermostat":
                temperature = analysis.get("temperature", 22)
                return await self._handle_thermostat(
                    smartthings, device_name, temperature, access_token, lang
                )

            else:
                return await self._handle_general(
                    smartthings, prompt, access_token, lang
                )

        except Exception as e:
            self.logger.error(
                f"SmartHomeAgent failed for intent '{intent}': {e}", exc_info=True
            )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("smarthome_command_error", lang=lang, error=str(e)),
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_list_devices(
        self, smartthings: Any, access_token: Optional[str], lang: str
    ) -> AgentResponse:
        """List all smart home devices."""
        devices = await smartthings.get_devices(access_token=access_token)

        if not devices:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_no_devices", lang=lang),
                data={"devices": []},
            )

        lines = [t("smarthome_devices_header", lang=lang)]
        unnamed = t("smarthome_device_unnamed", lang=lang)
        unknown_type = t("smarthome_device_unknown_type", lang=lang)
        for i, device in enumerate(devices, 1):
            label = device.get("label") or device.get("name") or unnamed
            dtype = device.get("deviceTypeName", device.get("type", unknown_type))
            lines.append(f"{i}. **{label}** — {dtype}")

        lines.append(t("smarthome_devices_total", lang=lang, count=len(devices)))

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"devices": devices, "count": len(devices)},
        )

    async def _handle_device_status(
        self,
        smartthings: Any,
        device_name: Optional[str],
        access_token: Optional[str],
        lang: str,
    ) -> AgentResponse:
        """Get status of a specific device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "smarthome_device_not_found",
                    lang=lang,
                    name=device_name or "unknown",
                ),
                data={"found": False},
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")
        status = await smartthings.get_device_status(
            device_id, access_token=access_token
        )

        # Extract switch state if available
        main_comp = status.get("components", {}).get("main", {})
        switch_state = main_comp.get("switch", {}).get("switch", {}).get("value", "N/A")

        if switch_state == "on":
            state_text = t("smarthome_status_on", lang=lang)
        elif switch_state == "off":
            state_text = t("smarthome_status_off", lang=lang)
        else:
            state_text = switch_state

        response = f"📊 Status: {label}\n\n" f"Estado: {state_text}"

        # Add temperature if available
        temp = (
            main_comp.get("temperatureMeasurement", {})
            .get("temperature", {})
            .get("value")
        )
        if temp is not None:
            response += f"\nTemperatura: {temp}°C"

        # Add humidity if available
        humidity = (
            main_comp.get("relativeHumidityMeasurement", {})
            .get("humidity", {})
            .get("value")
        )
        if humidity is not None:
            response += f"\nHumidity: {humidity}%"

        # Add brightness if available
        level = main_comp.get("switchLevel", {}).get("level", {}).get("value")
        if level is not None:
            response += f"\nBrightness: {level}%"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data={"device": label, "status": status},
        )

    async def _handle_turn_on(
        self,
        smartthings: Any,
        device_name: Optional[str],
        brightness: Optional[int],
        access_token: Optional[str],
        lang: str,
    ) -> AgentResponse:
        """Turn on a device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "smarthome_device_not_found",
                    lang=lang,
                    name=device_name or "unknown",
                ),
                data={"found": False},
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        if brightness is not None:
            success = await smartthings.turn_on_light(
                device_id, brightness=brightness, access_token=access_token
            )
            msg = (
                t("smarthome_turned_on_brightness", lang=lang, label=label, brightness=brightness)
                if success
                else t("smarthome_turn_on_error", lang=lang, label=label)
            )
        else:
            success = await smartthings.turn_on_device(
                device_id, access_token=access_token
            )
            msg = (
                t("smarthome_turned_on", lang=lang, label=label)
                if success
                else t("smarthome_turn_on_error", lang=lang, label=label)
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "turn_on", "success": success},
        )

    async def _handle_turn_off(
        self,
        smartthings: Any,
        device_name: Optional[str],
        access_token: Optional[str],
        lang: str,
    ) -> AgentResponse:
        """Turn off a device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "smarthome_device_not_found",
                    lang=lang,
                    name=device_name or "unknown",
                ),
                data={"found": False},
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.turn_off_device(
            device_id, access_token=access_token
        )
        msg = (
            t("smarthome_turned_off", lang=lang, label=label)
            if success
            else t("smarthome_turn_off_error", lang=lang, label=label)
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "turn_off", "success": success},
        )

    async def _handle_set_brightness(
        self,
        smartthings: Any,
        device_name: Optional[str],
        brightness: int,
        access_token: Optional[str],
        lang: str,
    ) -> AgentResponse:
        """Set brightness for a light device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "smarthome_device_not_found",
                    lang=lang,
                    name=device_name or "unknown",
                ),
                data={"found": False},
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.turn_on_light(
            device_id, brightness=brightness, access_token=access_token
        )

        msg = (
            t("smarthome_brightness_set", lang=lang, label=label, brightness=brightness)
            if success
            else t("smarthome_brightness_error", lang=lang, label=label)
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={
                "device": label,
                "action": "set_brightness",
                "brightness": brightness,
                "success": success,
            },
        )

    async def _handle_lock(
        self,
        smartthings: Any,
        device_name: Optional[str],
        access_token: Optional[str],
        lang: str,
    ) -> AgentResponse:
        """Lock a smart lock."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_lock_not_found", lang=lang),
                data={"found": False},
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.lock_door(device_id, access_token=access_token)
        msg = (
            t("smarthome_locked", lang=lang, label=label)
            if success
            else t("smarthome_lock_error", lang=lang, label=label)
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "lock", "success": success},
        )

    async def _handle_unlock(
        self,
        smartthings: Any,
        device_name: Optional[str],
        access_token: Optional[str],
        lang: str,
    ) -> AgentResponse:
        """Unlock a smart lock."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_lock_not_found", lang=lang),
                data={"found": False},
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.unlock_door(device_id, access_token=access_token)
        msg = (
            t("smarthome_unlocked", lang=lang, label=label)
            if success
            else t("smarthome_unlock_error", lang=lang, label=label)
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "unlock", "success": success},
        )

    async def _handle_thermostat(
        self,
        smartthings: Any,
        device_name: Optional[str],
        temperature: float,
        access_token: Optional[str],
        lang: str,
    ) -> AgentResponse:
        """Set thermostat temperature."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_thermostat_not_found", lang=lang),
                data={"found": False},
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.set_thermostat_temperature(
            device_id, temperature, access_token=access_token
        )

        msg = (
            t("smarthome_thermostat_set", lang=lang, label=label, temperature=temperature)
            if success
            else t("smarthome_thermostat_error", lang=lang, label=label)
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={
                "device": label,
                "action": "thermostat",
                "temperature": temperature,
                "success": success,
            },
        )

    async def _handle_general(
        self, smartthings: Any, prompt: str, access_token: Optional[str], lang: str
    ) -> AgentResponse:
        """Handle general smart home questions using GPT with device context."""
        # Gather device list for context
        unnamed = t("smarthome_device_unnamed", lang=lang)
        context_text = "Devices not available."
        try:
            devices = await smartthings.get_devices(access_token=access_token)
            if devices:
                device_list = []
                for d in devices[:20]:
                    label = d.get("label") or d.get("name") or unnamed
                    dtype = d.get("deviceTypeName", "")
                    device_list.append(f"- {label} ({dtype})")
                context_text = "Devices:\n" + "\n".join(device_list)
        except Exception as e:
            self.logger.warning(f"Could not gather device context: {e}")

        openai_svc = get_service("openai")
        if not openai_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("smarthome_ai_unavailable", lang=lang),
                error="OpenAI service not available",
            )

        await openai_svc.initialize()

        lang_instruction = {
            "pt": "Responda em Português.",
            "es": "Responde en Español.",
        }.get(lang, "Respond in English.")

        system_prompt = (
            f"You are a SmartThings smart home assistant.\n\n"
            f"User's devices:\n{context_text}\n\n"
            f"Answer smart home questions helpfully and concisely.\n"
            f"{lang_instruction}"
        )

        try:
            response_text = await openai_svc.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                model="gpt-4o-mini",
                temperature=0.7,
                max_tokens=500,
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(response_text or "").strip(),
                data={"method": "general_ai"},
            )

        except Exception as e:
            self.logger.error(f"General smart home query failed: {e}", exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("smarthome_general_error", lang=lang, error=str(e)),
                error=str(e),
            )

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
