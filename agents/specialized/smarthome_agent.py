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

    def _get_tuya_oauth(self) -> Optional[Any]:
        """Get the Tuya OAuth service."""
        try:
            from services.auth.tuya_oauth_service import get_tuya_oauth
            oauth = get_tuya_oauth()
            if oauth.client_id and oauth.client_secret:
                return oauth
            return None
        except Exception:
            return None

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
        for code in ["switch_led", "switch_1", "switch", "Power"]:
            success = await tuya.send_command(user_id, device_id, [{"code": code, "value": turn_on}])
            if success:
                action = t("smarthome_turned_on", lang=lang) if turn_on else t("smarthome_turned_off", lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=f"{action}: **{name}**",
                    data={"device_id": device_id, "action": "on" if turn_on else "off"},
                )
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=t("smarthome_command_error", lang=lang, error="Switch command not supported"),
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
            success = await tuya.send_command(user_id, device_id, [{"code": code, "value": tuya_brightness}])
            if success:
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=t("smarthome_brightness_set", lang=lang, name=name, brightness=brightness),
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
        success = await tuya.send_command(user_id, device_id, [{"code": "temp_set", "value": temperature}])
        if success:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_thermostat_set", lang=lang, name=name, temp=temperature),
            )
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=t("smarthome_command_error", lang=lang, error="Thermostat command failed"),
        )

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

        Priority: Tuya (user OAuth) → SmartThings (system tokens)
        """
        lang = get_user_lang(context)
        user_id = context.get("user_id", "")

        # --- Try Tuya first (user-level OAuth) ---
        tuya = self._get_tuya_oauth()
        if tuya and user_id:
            is_tuya_connected = await tuya.is_connected(user_id)
            if is_tuya_connected:
                return await self._execute_tuya(tuya, user_id, prompt, context, lang)

        # --- Fallback: SmartThings (system-level tokens) ---
        token_manager = get_smartthings_token_manager()
        access_token = await token_manager.get_valid_token()

        access_token = (
            context.get("smartthings_access_token")
            or context.get("access_token")
            or access_token
        )

        smartthings = await self._get_smartthings_service()
        if not smartthings:
            # No smart home provider available — prompt to connect
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_not_connected_tuya", lang=lang),
                data={"needs_connection": True},
            )

        if not access_token and not smartthings.access_token:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("smarthome_not_connected_tuya", lang=lang),
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

        response = t(
            "smarthome_status_label", lang=lang, label=label, state=state_text
        )

        # Add temperature if available
        temp = (
            main_comp.get("temperatureMeasurement", {})
            .get("temperature", {})
            .get("value")
        )
        if temp is not None:
            response += t("smarthome_temperature_label", lang=lang, value=temp)

        # Add humidity if available
        humidity = (
            main_comp.get("relativeHumidityMeasurement", {})
            .get("humidity", {})
            .get("value")
        )
        if humidity is not None:
            response += t("smarthome_humidity_label", lang=lang, value=humidity)

        # Add brightness if available
        level = main_comp.get("switchLevel", {}).get("level", {}).get("value")
        if level is not None:
            response += t("smarthome_brightness_label", lang=lang, value=level)

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
