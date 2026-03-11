# services/business/chat_service.py
"""
Chat orchestration service.

Extracts the per-action dispatch logic that was previously inlined inside
the WebSocket handler in ``api/routes/chat.py``. Each action (search, dev,
image, video, voice, finance, calendar, weather, traffic, car, chat) is now
a focused ``_handle_<action>`` method, keeping the WebSocket loop thin and
testable.
"""

# FIX F401: removed unused `import json` and `Optional`
import logging
from typing import Any, Dict, List

from fastapi import WebSocket

from agents import get_agent
from services.core import get_service

logger = logging.getLogger("capivarex.chat_service")


class ChatService:
    """Orchestrates agent execution for WebSocket chat sessions."""

    def __init__(
        self,
        websocket: WebSocket,
        user_id: str,
        user_plan: str,
    ):
        """Initialise a ChatService bound to a single WebSocket session.

        Args:
            websocket: The active FastAPI WebSocket connection.
            user_id: Authenticated user identifier.
            user_plan: Subscription plan (basic, pro, enterprise).
        """
        self.ws = websocket
        self.user_id = user_id
        self.user_plan = user_plan
        self._openai_svc = get_service("openai")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        action: str,
        user_message: str,
        decision: Dict[str, Any],
        history: List[Dict[str, Any]],
    ) -> str:
        """Dispatch *action* to the appropriate handler.

        Returns the full response text produced by the handler.
        """
        handler = self._ACTION_HANDLERS.get(action)
        if handler:
            return await handler(self, user_message, decision, history)
        return await self._handle_fallback(user_message, decision, history)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_search(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        """Busca via SearchAgent (Serper API)."""
        query = decision.get("query", user_message)
        await self._send_system(f"Pesquisando sobre: {query}...")

        try:
            search_agent = get_agent("search")
            if not search_agent:
                return (
                    "Serviço de busca não disponível. "
                    "Configure a SERPER_API_KEY no .env."
                )

            context = {
                "query": query,
                "user_id": getattr(self, "_user_id", None),
            }
            result = await search_agent.execute(query, context)

            if result and result.response:
                for char in result.response:
                    await self.ws.send_json({"type": "token", "content": char})
                return result.response

            return "Não encontrei resultados para essa busca."

        except Exception as e:
            logger.error("SearchAgent error: %s", e, exc_info=True)
            return f"Erro na pesquisa: {e}"

    async def _handle_dev(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        dev_prompt = decision.get("prompt")
        if not dev_prompt:
            await self._send_error("DEV prompt missing")
            return ""
        await self._send_system("Gerando codigo...")
        try:
            anthropic_svc = get_service("anthropic")
            if not anthropic_svc:
                await self._send_error("Anthropic service unavailable")
                return ""
            full = ""
            async for chunk in anthropic_svc.generate_code_stream(dev_prompt):
                await self.ws.send_json({"type": "token", "content": chunk})
                full += chunk
            return full
        except Exception as e:
            await self._send_error(f"Erro no DEV Agent: {e}")
            return ""

    async def _handle_image(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        prompt = decision.get("description", decision.get("prompt", user_message))
        await self._send_system(f"Gerando imagem: {prompt}...")
        try:
            image_svc = get_service("image")
            if not image_svc:
                raise RuntimeError("Image service unavailable")
            result = await image_svc.generate_image(
                prompt=prompt, user_plan=self.user_plan
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error", "Falha ao gerar imagem"))
            image_path = result.get("image_path")
            if not image_path:
                raise RuntimeError("Image generation returned no path")
            await self.ws.send_json(
                {"type": "result", "content_type": "image", "url": image_path}
            )
            return f"Imagem gerada com sucesso: {image_path}"
        except Exception as e:
            await self._send_error(f"Erro ao gerar imagem: {e}")
            return ""

    async def _handle_video(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        prompt = decision.get("prompt", user_message)
        duration = int(decision.get("duration", 5))
        ratio = decision.get("ratio", "16:9")
        await self._send_system(f"Gerando video: {prompt}...")
        try:
            video_svc = get_service("video")
            if not video_svc:
                raise RuntimeError("Video service unavailable")
            result = await video_svc.generate_text_to_video(
                prompt=prompt,
                user_plan=self.user_plan,
                duration=duration,
                ratio=ratio,
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error", "Falha ao gerar video"))
            video_url = result.get("video_url")
            if not video_url:
                raise RuntimeError("Video generation returned no URL")
            response_text = (
                f"Video gerado com sucesso.\n"
                f"URL: {video_url}\n"
                f"Modelo: {result.get('model_used')}\n"
                f"Duracao: {result.get('duration')}s\n"
                f"Ratio: {result.get('ratio')}"
            )
            await self.ws.send_json(
                {"type": "result", "content_type": "text", "text": response_text}
            )
            return response_text
        except Exception as e:
            await self._send_error(f"Erro ao gerar video: {e}")
            return ""

    async def _handle_voice(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        await self._send_system("Gerando audio...")
        try:
            voice_agent = get_agent("voice")
            if not voice_agent:
                raise RuntimeError("Voice agent unavailable")
            voice_context = {
                "action": decision.get("action", "text_to_speech"),
                "text": decision.get("text", user_message),
                "voice": decision.get("voice", "rachel"),
                "user_id": self.user_id,
            }
            result = await voice_agent.execute(
                decision.get("text", user_message), voice_context
            )
            result_text = (
                result.response if hasattr(result, "response") else str(result)
            )
            if result_text.startswith("Erro"):
                raise RuntimeError(result_text)
            await self.ws.send_json(
                {"type": "result", "content_type": "audio", "url": result_text}
            )
            return f"Audio gerado: {result_text}"
        except Exception as e:
            await self._send_error(f"Erro ao gerar audio: {e}")
            return f"Erro ao gerar audio: {e}"

    async def _handle_finance(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        symbol = decision.get("symbol", "AAPL")
        await self._send_system(f"Consultando cotacao para {symbol}...")
        try:
            finance_svc = get_service("finance")
            if not finance_svc:
                raise RuntimeError("Finance service unavailable")
            quote = await finance_svc.get_quote(symbol)
            response_text = (
                f"**Cotacao de {quote.get('name') or symbol} ({quote.get('symbol') or symbol})**\n"
                f"- Preco: ${quote.get('price', 0):.2f} ({quote.get('currency', 'N/A')})\n"
                f"- Variacao: {quote.get('change', 0):.2f} ({quote.get('percent_change', 0):.2f}%)\n"
                f"- Max. do Dia: ${quote.get('high', 0):.2f}\n"
                f"- Min. do Dia: ${quote.get('low', 0):.2f}"
            )
            await self.ws.send_json(
                {"type": "result", "content_type": "text", "text": response_text}
            )
            return response_text
        except Exception as e:
            await self._send_error(f"Erro ao consultar financas: {e}")
            return ""

    async def _handle_calendar(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        await self._send_system("Consultando seu calendario...")
        try:
            calendar_agent = get_agent("calendar")
            if not calendar_agent:
                raise RuntimeError("Calendar agent unavailable")
            calendar_context = {
                "user_id": self.user_id,
                "tenant_id": "default",
                "channel": "websocket",
                "action": decision.get("action"),
                "event_params": decision.get("event_params", {}),
            }
            result = await calendar_agent.process(user_message, calendar_context)
            if hasattr(result, "to_dict"):
                result = result.to_dict()
            if result.get("success") or result.get("status") == "success":
                response_text = result.get(
                    "response", "Informacoes do calendario processadas."
                )
                events = result.get("events", result.get("data", {}).get("events", []))
                if events:
                    response_text += "\n\n**Eventos:**\n"
                    for event in events:
                        response_text += (
                            f"- {event.get('summary', 'Sem titulo')} "
                            f"em {event.get('start', 'Data nao disponivel')}\n"
                        )
            else:
                response_text = result.get(
                    "error",
                    result.get("response", "Nao foi possivel acessar o calendario."),
                )
            await self.ws.send_json(
                {"type": "result", "content_type": "text", "text": response_text}
            )
            return response_text
        except Exception as e:
            logger.exception("Calendar agent error: %s", e)
            await self._send_error(f"Erro ao consultar calendario: {e}")
            return ""

    async def _handle_weather(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        location = decision.get("location", "Dublin")
        await self._send_system(f"Verificando o tempo em {location}...")
        try:
            weather_svc = get_service("weather")
            if not weather_svc:
                raise RuntimeError("Weather service unavailable")
            weather = await weather_svc.get_forecast(location)
            location_data = weather.get("location", {})
            forecast_days = weather.get("forecast", [])
            if forecast_days:
                today = forecast_days[0]
                response_text = (
                    f"**Previsao do Tempo para {location_data.get('name', location)}, "
                    f"{location_data.get('region', '')}**\n"
                    f"- Condicao: {today.get('condition', 'N/A')}\n"
                    f"- Maxima: {today.get('max_temp_c', 'N/A')} C\n"
                    f"- Minima: {today.get('min_temp_c', 'N/A')} C\n"
                    f"- Chance de chuva: {today.get('chance_of_rain', 'N/A')}%"
                )
            else:
                response_text = (
                    f"Nao foi possivel obter previsao detalhada para {location}."
                )
            await self.ws.send_json(
                {"type": "result", "content_type": "text", "text": response_text}
            )
            return response_text
        except Exception as e:
            await self._send_error(f"Erro ao consultar o tempo: {e}")
            return ""

    async def _handle_traffic(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        origin = decision.get("origin", "Dublin")
        destination = decision.get("destination", "Cork")
        await self._send_system(
            f"Verificando trafego de {origin} para {destination}..."
        )
        try:
            traffic_svc = get_service("traffic")
            if not traffic_svc:
                raise RuntimeError("Traffic service unavailable")
            traffic_summary = await traffic_svc.get_traffic_summary(origin, destination)
            await self.ws.send_json({"type": "token", "content": traffic_summary})
            return traffic_summary
        except Exception as e:
            await self._send_error(f"Erro ao consultar trafego: {e}")
            return ""

    async def _handle_car(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        query = decision.get("query", user_message)
        await self._send_system("Verificando seu veiculo...")
        try:
            vehicle_db_svc = get_service("vehicle_db")
            car_svc = get_service("car")
            vehicle = None
            vehicle_id = None
            access_token = None
            if vehicle_db_svc:
                vehicle = await vehicle_db_svc.get_primary_vehicle(self.user_id)
                vehicle_id = vehicle.get("vehicle_id") if vehicle else None
                access_token = vehicle.get("access_token") if vehicle else None
                if vehicle and await vehicle_db_svc.is_token_expired(
                    self.user_id, vehicle_id
                ):
                    if car_svc:
                        new_tokens = await car_svc.refresh_access_token(
                            vehicle["refresh_token"]
                        )
                        if "error" not in new_tokens:
                            await vehicle_db_svc.update_tokens(
                                user_id=self.user_id,
                                vehicle_id=vehicle_id,
                                access_token=new_tokens["access_token"],
                                refresh_token=new_tokens["refresh_token"],
                                expires_in=new_tokens.get("expires_in", 7200),
                            )
                            access_token = new_tokens["access_token"]
            car_agent = get_agent("car")
            if car_agent:
                car_result = await car_agent.process(
                    query,
                    {
                        "user_id": self.user_id,
                        "vehicle_id": vehicle_id,
                        "access_token": access_token,
                    },
                )
                response_text = (
                    car_result.response
                    if hasattr(car_result, "response")
                    else str(car_result)
                )
            else:
                response_text = "Car agent unavailable"
            await self.ws.send_json(
                {"type": "result", "content_type": "text", "text": response_text}
            )
            return response_text
        except Exception as e:
            logger.exception("Car agent error: %s", e)
            await self._send_error(f"Erro ao consultar veiculo: {e}")
            return ""

    async def _handle_chat(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        try:
            chat_agent = get_agent("chat")
            if not chat_agent:
                raise RuntimeError("Chat agent unavailable")
            chat_context = {"history": history, "user_plan": self.user_plan}
            chat_result = await chat_agent.execute(user_message, chat_context)
            full_response = (
                chat_result.response
                if hasattr(chat_result, "response")
                else str(chat_result)
            )
            await self.ws.send_json({"type": "token", "content": full_response})
            return full_response
        except Exception as e:
            logger.exception("Chat agent error: %s", e)
            error_msg = f"Erro ao processar mensagem: {e}"
            await self._send_error(error_msg)
            return error_msg

    async def _handle_fallback(
        self, user_message: str, decision: Dict, history: List[Dict]
    ) -> str:
        await self._send_error("Acao desconhecida. Respondendo diretamente...")
        return await self._stream_openai(history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_system(self, content: str) -> None:
        await self.ws.send_json({"type": "system", "content": content})

    async def _send_error(self, content: str) -> None:
        await self.ws.send_json({"type": "error", "content": content})

    async def _stream_openai(self, messages: List[Dict]) -> str:
        full = ""
        if self._openai_svc:
            async for tok in self._openai_svc.stream_chat_completion(messages):
                full += tok
                await self.ws.send_json({"type": "token", "content": tok})
        return full

    # ------------------------------------------------------------------
    # Action dispatch table
    # ------------------------------------------------------------------

    _ACTION_HANDLERS: Dict[str, Any] = {
        "search": _handle_search,
        "dev": _handle_dev,
        "image": _handle_image,
        "video": _handle_video,
        "voice": _handle_voice,
        "finance": _handle_finance,
        "calendar": _handle_calendar,
        "weather": _handle_weather,
        "traffic": _handle_traffic,
        "car": _handle_car,
        "chat": _handle_chat,
    }
