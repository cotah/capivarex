"""
Car Agent - Controls electric vehicle via Smartcar API.

Refactored to use new BaseAgent architecture.
"""

import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)

# Valid intents for vehicle commands
VALID_INTENTS = {
    "connect", "battery", "location", "charge_status",
    "lock", "unlock", "start_charging", "stop_charging",
    "summary", "odometer", "general"
}


@register_agent("car")
class CarAgent(BaseAgent):
    """
    Car agent for electric vehicle control and queries.

    Handles:
    - Battery level and range queries
    - Vehicle location
    - Charge status
    - Lock/unlock commands
    - Start/stop charging
    - Vehicle summary
    - Odometer reading
    """

    def __init__(self):
        super().__init__(
            name="car",
            description="Controls electric vehicle via Smartcar API"
        )

    async def _get_car_service(self) -> Optional[Any]:
        """
        Get the car service, initializing if needed.

        Returns:
            Car service instance or None
        """
        try:
            car_svc = get_service("car")
            if car_svc:
                await car_svc.initialize()
                return car_svc
            return None
        except Exception as e:
            self.logger.warning(f"Could not get car service: {e}")
            return None

    async def _load_stored_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load Smartcar connection from DB for a user."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.get_car_connection(user_id)
        except Exception as e:
            self.logger.warning(f"Could not load car connection: {e}")
        return None

    async def _save_connection(
        self, user_id: str, vehicle_id: str,
        access_token: str, refresh_token: str, expires_at: str,
    ) -> bool:
        """Persist Smartcar connection to DB."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.save_car_connection(
                    user_id, vehicle_id, access_token, refresh_token, expires_at
                )
        except Exception as e:
            self.logger.warning(f"Could not save car connection: {e}")
        return False

    async def _analyze_intent(self, user_message: str) -> str:
        """
        Analyze user intent using OpenAI.

        Args:
            user_message: User's message about vehicle

        Returns:
            Intent category string
        """
        openai_svc = get_service("openai")
        if not openai_svc:
            return "general"

        await openai_svc.initialize()
        client = openai_svc.get_client()
        if not client:
            return "general"

        system_prompt = (
            "You are an intent classifier for electric vehicle queries.\n\n"
            "Analyze the user's message and classify it into ONE of these categories:\n\n"
            "- connect: User wants to connect their vehicle\n"
            "- battery: User asking about battery level or range\n"
            "- location: User asking where their car is\n"
            "- charge_status: User asking if car is charging\n"
            "- lock: User wants to lock the car\n"
            "- unlock: User wants to unlock the car\n"
            "- start_charging: User wants to start charging\n"
            "- stop_charging: User wants to stop charging\n"
            "- summary: User wants overall vehicle status\n"
            "- odometer: User asking about mileage/distance\n"
            "- general: Any other vehicle-related question\n\n"
            "Respond with ONLY the category name, nothing else."
        )

        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=20
            )

            intent = (response.choices[0].message.content or "").strip().lower()

            if intent not in VALID_INTENTS:
                return "general"

            return intent

        except Exception as e:
            self.logger.warning(f"Intent analysis failed: {e}")
            return "general"

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Process vehicle-related queries and commands.

        Args:
            prompt: User's vehicle query or command
            context: Execution context with optional:
                - user_id: User identifier
                - vehicle_id: Smartcar vehicle ID
                - access_token: Smartcar access token

        Returns:
            AgentResponse with vehicle data or command result
        """
        user_id = context.get("user_id", "")
        vehicle_id = context.get("vehicle_id")
        access_token = context.get("access_token")

        # If no vehicle connected, guide user to connect
        if not vehicle_id or not access_token:
            return await self._handle_no_vehicle(user_id)

        # Get car service
        car_service = await self._get_car_service()
        if not car_service:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Servico de veiculo nao disponivel.",
                error="Car service not available"
            )

        # Analyze user intent
        intent = await self._analyze_intent(prompt)

        # Route to appropriate handler
        try:
            if intent == "connect":
                return await self._handle_no_vehicle(user_id)
            elif intent == "battery":
                return await self._handle_battery(car_service, vehicle_id, access_token)
            elif intent == "location":
                return await self._handle_location(car_service, vehicle_id, access_token)
            elif intent == "charge_status":
                return await self._handle_charge_status(car_service, vehicle_id, access_token)
            elif intent == "lock":
                return await self._handle_lock(car_service, vehicle_id, access_token)
            elif intent == "unlock":
                return await self._handle_unlock(car_service, vehicle_id, access_token)
            elif intent == "start_charging":
                return await self._handle_start_charging(car_service, vehicle_id, access_token)
            elif intent == "stop_charging":
                return await self._handle_stop_charging(car_service, vehicle_id, access_token)
            elif intent == "summary":
                return await self._handle_summary(car_service, vehicle_id, access_token)
            elif intent == "odometer":
                return await self._handle_odometer(car_service, vehicle_id, access_token)
            else:
                return await self._handle_general(car_service, prompt, vehicle_id, access_token)

        except Exception as e:
            self.logger.error(f"CarAgent failed for intent '{intent}': {e}", exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar comando do veiculo: {str(e)}",
                error=str(e)
            )

    async def _handle_no_vehicle(self, user_id: str) -> AgentResponse:
        """Handle case when no vehicle is connected."""
        car_service = await self._get_car_service()

        connect_url = ""
        if car_service:
            try:
                connect_url = car_service.get_connect_url(user_id)
            except Exception as e:
                self.logger.warning(f"Could not get connect URL: {e}")

        response = (
            "Conecte seu Veiculo Eletrico\n\n"
            "Voce ainda nao conectou nenhum veiculo!\n\n"
            "Para conectar seu carro (Tesla, BMW, Audi, VW, Nissan, Ford, etc):\n\n"
            "1. Clique no link abaixo\n"
            "2. Faca login com suas credenciais do fabricante\n"
            "3. Autorize o acesso\n"
        )

        if connect_url:
            response += f"\nLink de Conexao: {connect_url}\n"

        response += (
            "\nApos conectar, voce podera:\n"
            "- Verificar nivel de bateria\n"
            "- Ver localizacao do carro\n"
            "- Trancar/destrancar remotamente\n"
            "- Controlar carregamento\n"
            "- Ver status completo\n\n"
            "Suporta 30+ marcas de veiculos eletricos!"
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data={"connect_url": connect_url, "needs_connection": True}
        )

    async def _handle_battery(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle battery level query."""
        battery = await car_service.get_battery_level(vehicle_id, access_token)

        if 'error' in battery:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao obter nivel de bateria: {battery['error']}",
                error=battery['error']
            )

        percentage = battery.get('percentage', 'N/A')
        range_km = battery.get('range_km', 'N/A')

        # Generate contextual status
        if isinstance(percentage, (int, float)) and percentage < 20:
            status = "BAIXA! Recomendo carregar logo."
        elif isinstance(percentage, (int, float)) and percentage < 50:
            status = "Moderada. Considere carregar em breve."
        else:
            status = "Otima! Voce tem autonomia suficiente."

        response = (
            f"Nivel de Bateria\n\n"
            f"Carga: {percentage}%\n"
            f"Autonomia: {range_km} km\n\n"
            f"{status}"
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=battery
        )

    async def _handle_location(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle location query."""
        location = await car_service.get_location(vehicle_id, access_token)

        if 'error' in location:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao obter localizacao: {location['error']}",
                error=location['error']
            )

        lat = location.get('latitude', 'N/A')
        lon = location.get('longitude', 'N/A')
        maps_link = f"https://www.google.com/maps?q={lat},{lon}"

        response = (
            f"Localizacao do Veiculo\n\n"
            f"Coordenadas: {lat}, {lon}\n\n"
            f"Ver no mapa: {maps_link}"
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data={**location, "maps_link": maps_link}
        )

    async def _handle_charge_status(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle charging status query."""
        charge = await car_service.get_charge_status(vehicle_id, access_token)

        if 'error' in charge:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao obter status de carregamento: {charge['error']}",
                error=charge['error']
            )

        is_plugged = charge.get('is_plugged_in', False)
        state = charge.get('state', 'UNKNOWN')

        if state == 'CHARGING':
            status = "Carregando agora!"
        elif state == 'FULLY_CHARGED':
            status = "Totalmente carregado! Pode desconectar."
        elif is_plugged:
            status = "Conectado mas nao carregando."
        else:
            status = "Nao conectado ao carregador."

        response = (
            f"Status de Carregamento\n\n"
            f"{status}\n\n"
            f"Plugado: {'Sim' if is_plugged else 'Nao'}\n"
            f"Estado: {state}"
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=charge
        )

    async def _handle_lock(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle lock command."""
        result = await car_service.lock_vehicle(vehicle_id, access_token)

        if 'error' in result:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao trancar veiculo: {result['error']}",
                error=result['error']
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Veiculo trancado com sucesso!\n\nSeu carro esta seguro agora.",
            data=result
        )

    async def _handle_unlock(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle unlock command."""
        result = await car_service.unlock_vehicle(vehicle_id, access_token)

        if 'error' in result:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao destrancar veiculo: {result['error']}",
                error=result['error']
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Veiculo destrancado com sucesso!\n\nVoce ja pode entrar.",
            data=result
        )

    async def _handle_start_charging(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle start charging command."""
        result = await car_service.start_charging(vehicle_id, access_token)

        if 'error' in result:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao iniciar carregamento: {result['error']}",
                error=result['error']
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Carregamento iniciado!\n\nSeu veiculo esta carregando agora.",
            data=result
        )

    async def _handle_stop_charging(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle stop charging command."""
        result = await car_service.stop_charging(vehicle_id, access_token)

        if 'error' in result:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao parar carregamento: {result['error']}",
                error=result['error']
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Carregamento parado!\n\nVoce pode desconectar o cabo agora.",
            data=result
        )

    async def _handle_summary(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle vehicle summary request."""
        summary = await car_service.get_vehicle_summary(vehicle_id, access_token)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=summary if isinstance(summary, str) else str(summary),
            data={"summary": summary}
        )

    async def _handle_odometer(
        self,
        car_service: Any,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle odometer query."""
        odometer = await car_service.get_odometer(vehicle_id, access_token)

        if 'error' in odometer:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao obter odometro: {odometer['error']}",
                error=odometer['error']
            )

        distance = odometer.get('distance_km', 'N/A')

        response = (
            f"Odometro\n\n"
            f"Distancia percorrida: {distance:,.0f} km"
            if isinstance(distance, (int, float))
            else f"Odometro\n\nDistancia percorrida: {distance} km"
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=odometer
        )

    async def _handle_general(
        self,
        car_service: Any,
        user_message: str,
        vehicle_id: str,
        access_token: str
    ) -> AgentResponse:
        """Handle general vehicle questions using GPT with context."""
        # Gather vehicle data for context
        context_text = "Vehicle data temporarily unavailable."
        try:
            info = await car_service.get_vehicle_info(vehicle_id, access_token)
            battery = await car_service.get_battery_level(vehicle_id, access_token)
            charge = await car_service.get_charge_status(vehicle_id, access_token)

            context_text = (
                f"Vehicle Information:\n"
                f"- Make: {info.get('make', 'N/A')}\n"
                f"- Model: {info.get('model', 'N/A')}\n"
                f"- Year: {info.get('year', 'N/A')}\n"
                f"- Battery: {battery.get('percentage', 'N/A')}%\n"
                f"- Range: {battery.get('range_km', 'N/A')} km\n"
                f"- Charging: {charge.get('state', 'N/A')}\n"
            )
        except Exception as e:
            self.logger.warning(f"Could not gather vehicle context: {e}")

        openai_svc = get_service("openai")
        if not openai_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Servico de IA nao disponivel para responder sua pergunta.",
                error="OpenAI service not available"
            )

        await openai_svc.initialize()

        system_prompt = (
            f"You are a helpful electric vehicle assistant.\n\n"
            f"Current vehicle status:\n{context_text}\n\n"
            f"Answer the user's question about their vehicle in a friendly, helpful way.\n"
            f"Keep responses concise but informative.\n"
            f"If you don't have specific data, be honest about it.\n\n"
            f"Respond in Portuguese (Brazil)."
        )

        try:
            response_text = await openai_svc.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
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
            self.logger.error(f"General car query failed: {e}", exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar sua pergunta: {str(e)}",
                error=str(e)
            )

    def get_capabilities(self) -> List[str]:
        """Get car agent capabilities."""
        return [
            "vehicle_control",
            "battery_status",
            "location",
            "lock_unlock",
            "charging_control",
            "odometer",
            "vehicle_summary"
        ]
