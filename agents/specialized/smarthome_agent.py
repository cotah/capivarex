"""
SmartHome Agent - Controls smart home devices via SmartThings API.

Refactored to use new BaseAgent architecture.
"""

import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)

# Valid intents for smart home commands
VALID_INTENTS = {
    "list_devices", "device_status", "turn_on", "turn_off",
    "set_brightness", "lock", "unlock", "thermostat", "general"
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
            name="smarthome",
            description="Controls smart home devices via SmartThings"
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
        self, user_id: str, access_token: str, refresh_token: str,
        expires_at: str, installed_app_id: str, location_id: str,
    ) -> bool:
        """Persist SmartThings connection to DB."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.save_smartthings_connection(
                    user_id, access_token, refresh_token,
                    expires_at, installed_app_id, location_id,
                )
        except Exception as e:
            self.logger.warning(f"Could not save smartthings connection: {e}")
        return False

    async def _analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """
        Analyze user intent and extract device name using OpenAI.

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
            "- \"intent\": one of: list_devices, device_status, turn_on, turn_off, "
            "set_brightness, lock, unlock, thermostat, general\n"
            "- \"device_name\": the device name mentioned (e.g. \"sala\", \"quarto\", \"TV\", \"ar condicionado\") or null\n"
            "- \"brightness\": brightness level 0-100 if mentioned, or null\n"
            "- \"temperature\": temperature value if mentioned, or null\n\n"
            "Examples:\n"
            "\"acenda as luzes da sala\" → {\"intent\":\"turn_on\",\"device_name\":\"sala\",\"brightness\":null,\"temperature\":null}\n"
            "\"apague a luz do quarto\" → {\"intent\":\"turn_off\",\"device_name\":\"quarto\",\"brightness\":null,\"temperature\":null}\n"
            "\"quais dispositivos tenho?\" → {\"intent\":\"list_devices\",\"device_name\":null,\"brightness\":null,\"temperature\":null}\n"
            "\"status da TV\" → {\"intent\":\"device_status\",\"device_name\":\"TV\",\"brightness\":null,\"temperature\":null}\n"
            "\"coloque o brilho em 50%\" → {\"intent\":\"set_brightness\",\"device_name\":null,\"brightness\":50,\"temperature\":null}\n"
            "\"tranque a porta\" → {\"intent\":\"lock\",\"device_name\":\"porta\",\"brightness\":null,\"temperature\":null}\n"
            "\"ajuste o ar para 22 graus\" → {\"intent\":\"thermostat\",\"device_name\":\"ar\",\"brightness\":null,\"temperature\":22}\n\n"
            "Return ONLY the JSON object, no other text."
        )

        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0,
                max_tokens=100
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

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Process smart home queries and commands.

        Args:
            prompt: User's smart home query or command
            context: Execution context with optional access_token

        Returns:
            AgentResponse with device data or command result
        """
        access_token = context.get("smartthings_access_token") or context.get("access_token")

        # Get SmartThings service
        smartthings = await self._get_smartthings_service()
        if not smartthings:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Serviço SmartThings não disponível. Verifique a configuração.",
                error="SmartThings service not available"
            )

        # Check if service has a token (either stored or from context)
        if not smartthings.access_token and not access_token:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    "🏠 SmartThings não conectado\n\n"
                    "Você precisa conectar sua conta SmartThings primeiro.\n"
                    "Use o endpoint /api/smartthings/auth para autenticar.\n\n"
                    "Após conectar, você poderá:\n"
                    "- Ligar/desligar luzes e dispositivos\n"
                    "- Ver status dos dispositivos\n"
                    "- Controlar termostato\n"
                    "- Trancar/destrancar portas"
                ),
                data={"needs_connection": True}
            )

        # Analyze intent
        analysis = await self._analyze_intent(prompt)
        intent = analysis["intent"]
        device_name = analysis.get("device_name")

        try:
            if intent == "list_devices":
                return await self._handle_list_devices(smartthings, access_token)

            elif intent == "device_status":
                return await self._handle_device_status(
                    smartthings, device_name, access_token
                )

            elif intent == "turn_on":
                brightness = analysis.get("brightness")
                return await self._handle_turn_on(
                    smartthings, device_name, brightness, access_token
                )

            elif intent == "turn_off":
                return await self._handle_turn_off(
                    smartthings, device_name, access_token
                )

            elif intent == "set_brightness":
                brightness = analysis.get("brightness", 50)
                return await self._handle_set_brightness(
                    smartthings, device_name, brightness, access_token
                )

            elif intent == "lock":
                return await self._handle_lock(smartthings, device_name, access_token)

            elif intent == "unlock":
                return await self._handle_unlock(smartthings, device_name, access_token)

            elif intent == "thermostat":
                temperature = analysis.get("temperature", 22)
                return await self._handle_thermostat(
                    smartthings, device_name, temperature, access_token
                )

            else:
                return await self._handle_general(smartthings, prompt, access_token)

        except Exception as e:
            self.logger.error(
                f"SmartHomeAgent failed for intent '{intent}': {e}",
                exc_info=True
            )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar comando de casa inteligente: {str(e)}",
                error=str(e)
            )

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_list_devices(
        self, smartthings: Any, access_token: Optional[str]
    ) -> AgentResponse:
        """List all smart home devices."""
        devices = await smartthings.get_devices(access_token=access_token)

        if not devices:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Nenhum dispositivo encontrado na sua conta SmartThings.",
                data={"devices": []}
            )

        lines = ["🏠 Seus Dispositivos SmartThings\n"]
        for i, device in enumerate(devices, 1):
            label = device.get("label") or device.get("name") or "Sem nome"
            dtype = device.get("deviceTypeName", device.get("type", "Desconhecido"))
            lines.append(f"{i}. **{label}** — {dtype}")

        lines.append(f"\nTotal: {len(devices)} dispositivos")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"devices": devices, "count": len(devices)}
        )

    async def _handle_device_status(
        self, smartthings: Any, device_name: Optional[str],
        access_token: Optional[str]
    ) -> AgentResponse:
        """Get status of a specific device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f"Não encontrei o dispositivo '{device_name or 'desconhecido'}'.\n"
                    "Diga 'listar dispositivos' para ver todos os disponíveis."
                ),
                data={"found": False}
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")
        status = await smartthings.get_device_status(device_id, access_token=access_token)

        # Extract switch state if available
        main_comp = status.get("components", {}).get("main", {})
        switch_state = (
            main_comp.get("switch", {}).get("switch", {}).get("value", "N/A")
        )

        response = (
            f"📊 Status: {label}\n\n"
            f"Estado: {'Ligado ✅' if switch_state == 'on' else 'Desligado ⭕' if switch_state == 'off' else switch_state}"
        )

        # Add temperature if available
        temp = main_comp.get("temperatureMeasurement", {}).get("temperature", {}).get("value")
        if temp is not None:
            response += f"\nTemperatura: {temp}°C"

        # Add humidity if available
        humidity = main_comp.get("relativeHumidityMeasurement", {}).get("humidity", {}).get("value")
        if humidity is not None:
            response += f"\nUmidade: {humidity}%"

        # Add brightness if available
        level = main_comp.get("switchLevel", {}).get("level", {}).get("value")
        if level is not None:
            response += f"\nBrilho: {level}%"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data={"device": label, "status": status}
        )

    async def _handle_turn_on(
        self, smartthings: Any, device_name: Optional[str],
        brightness: Optional[int], access_token: Optional[str]
    ) -> AgentResponse:
        """Turn on a device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f"Não encontrei o dispositivo '{device_name or 'desconhecido'}'.\n"
                    "Diga 'listar dispositivos' para ver todos os disponíveis."
                ),
                data={"found": False}
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        if brightness is not None:
            success = await smartthings.turn_on_light(
                device_id, brightness=brightness, access_token=access_token
            )
            msg = f"💡 {label} ligado com brilho em {brightness}%!" if success else f"❌ Erro ao ligar {label}."
        else:
            success = await smartthings.turn_on_device(device_id, access_token=access_token)
            msg = f"✅ {label} ligado!" if success else f"❌ Erro ao ligar {label}."

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "turn_on", "success": success}
        )

    async def _handle_turn_off(
        self, smartthings: Any, device_name: Optional[str],
        access_token: Optional[str]
    ) -> AgentResponse:
        """Turn off a device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f"Não encontrei o dispositivo '{device_name or 'desconhecido'}'.\n"
                    "Diga 'listar dispositivos' para ver todos os disponíveis."
                ),
                data={"found": False}
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.turn_off_device(device_id, access_token=access_token)
        msg = f"⭕ {label} desligado!" if success else f"❌ Erro ao desligar {label}."

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "turn_off", "success": success}
        )

    async def _handle_set_brightness(
        self, smartthings: Any, device_name: Optional[str],
        brightness: int, access_token: Optional[str]
    ) -> AgentResponse:
        """Set brightness for a light device."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f"Não encontrei o dispositivo '{device_name or 'desconhecido'}'.\n"
                    "Diga 'listar dispositivos' para ver todos os disponíveis."
                ),
                data={"found": False}
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.turn_on_light(
            device_id, brightness=brightness, access_token=access_token
        )

        msg = (
            f"💡 Brilho de {label} ajustado para {brightness}%!"
            if success
            else f"❌ Erro ao ajustar brilho de {label}."
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "set_brightness", "brightness": brightness, "success": success}
        )

    async def _handle_lock(
        self, smartthings: Any, device_name: Optional[str],
        access_token: Optional[str]
    ) -> AgentResponse:
        """Lock a smart lock."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Não encontrei a fechadura. Diga 'listar dispositivos' para ver todos.",
                data={"found": False}
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.lock_door(device_id, access_token=access_token)
        msg = f"🔒 {label} trancado!" if success else f"❌ Erro ao trancar {label}."

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "lock", "success": success}
        )

    async def _handle_unlock(
        self, smartthings: Any, device_name: Optional[str],
        access_token: Optional[str]
    ) -> AgentResponse:
        """Unlock a smart lock."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Não encontrei a fechadura. Diga 'listar dispositivos' para ver todos.",
                data={"found": False}
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.unlock_door(device_id, access_token=access_token)
        msg = f"🔓 {label} destrancado!" if success else f"❌ Erro ao destrancar {label}."

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "unlock", "success": success}
        )

    async def _handle_thermostat(
        self, smartthings: Any, device_name: Optional[str],
        temperature: float, access_token: Optional[str]
    ) -> AgentResponse:
        """Set thermostat temperature."""
        device = await self._find_device_by_name(smartthings, device_name, access_token)

        if not device:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Não encontrei o termostato. Diga 'listar dispositivos' para ver todos.",
                data={"found": False}
            )

        device_id = device.get("deviceId")
        label = device.get("label") or device.get("name")

        success = await smartthings.set_thermostat_temperature(
            device_id, temperature, access_token=access_token
        )

        msg = (
            f"🌡️ {label} ajustado para {temperature}°C!"
            if success
            else f"❌ Erro ao ajustar temperatura de {label}."
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS if success else AgentStatus.ERROR,
            response=msg,
            data={"device": label, "action": "thermostat", "temperature": temperature, "success": success}
        )

    async def _handle_general(
        self, smartthings: Any, prompt: str,
        access_token: Optional[str]
    ) -> AgentResponse:
        """Handle general smart home questions using GPT with device context."""
        # Gather device list for context
        context_text = "Dispositivos não disponíveis."
        try:
            devices = await smartthings.get_devices(access_token=access_token)
            if devices:
                device_list = []
                for d in devices[:20]:
                    label = d.get("label") or d.get("name") or "Sem nome"
                    dtype = d.get("deviceTypeName", "")
                    device_list.append(f"- {label} ({dtype})")
                context_text = "Dispositivos:\n" + "\n".join(device_list)
        except Exception as e:
            self.logger.warning(f"Could not gather device context: {e}")

        openai_svc = get_service("openai")
        if not openai_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Serviço de IA não disponível para responder sua pergunta.",
                error="OpenAI service not available"
            )

        await openai_svc.initialize()

        system_prompt = (
            f"Você é um assistente de casa inteligente SmartThings.\n\n"
            f"Dispositivos do usuário:\n{context_text}\n\n"
            f"Responda perguntas sobre a casa inteligente de forma útil e concisa.\n"
            f"Responda em Português (Brasil)."
        )

        try:
            response_text = await openai_svc.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                model="gpt-4o-mini",
                temperature=0.7,
                max_tokens=500
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(response_text or "").strip(),
                data={"method": "general_ai"}
            )

        except Exception as e:
            self.logger.error(f"General smart home query failed: {e}", exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar sua pergunta: {str(e)}",
                error=str(e)
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
