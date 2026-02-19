# services/business/chat_service.py
"""
Chat orchestration service.

Extracts the per-action dispatch logic that was previously inlined inside
the WebSocket handler in ``api/routes/chat.py``.  Each action (search,
dev, image, video, voice, finance, calendar, weather, traffic, car, chat)
is now a focused ``_handle_<action>`` method, keeping the WebSocket loop
thin and testable.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from agents import get_agent
from services.core import get_service

logger = logging.getLogger("capivarax.chat_service")


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

        # Lazily resolved services (set by caller or resolved on demand)
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
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Run a web search via Perplexity and stream a GPT-synthesised answer."""
        query = decision.get("query", user_message)
        await self._send_system(f"Pesquisando sobre: {query}...")

        try:
            perplexity_svc = get_service("perplexity")
            if perplexity_svc:
                search_results = await perplexity_svc.search(query)
            else:
                search_results = {"answer": "", "sources": []}

            search_answer = search_results.get("answer", "")
            sources = search_results.get("sources", [])

            context_prompt = (
                f"Com base nos seguintes resultados de pesquisa, responda a pergunta "
                f"original do usuario de forma clara e completa.\n\n"
                f"Pergunta do Usuario: {user_message}\n\n"
                f"Resultados da Pesquisa:\n{search_answer}\n\n"
                f"Fontes: {', '.join(sources[:5]) if sources else 'N/A'}"
            )

            messages_with_context = [
                {
                    "role": "system",
                    "content": (
                        "Voce e um assistente util que responde com base em "
                        "resultados de pesquisa. Seja claro, objetivo e cite "
                        "as fontes quando relevante."
                    ),
                },
                {"role": "user", "content": context_prompt},
            ]

            return await self._stream_openai(messages_with_context)

        except Exception as e:
            logger.exception("Search error: %s", e)
            await self._send_error(
                "Desculpe, nao foi possivel realizar a pesquisa no momento. "
                "Tentando responder com conhecimento base..."
            )
            return await self._stream_openai(history)

    async def _handle_dev(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Generate code via the Anthropic Claude service and stream tokens."""
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
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Generate an image from the prompt and send the result URL."""
        prompt = decision.get("description", decision.get("prompt", user_message))
        await self._send_system(f"Gerando imagem: {prompt}...")
        try:
            image_svc = get_service("image")
            if not image_svc:
                raise RuntimeError("Image service unavailable")

            result = await image_svc.generate_image(prompt=prompt, user_plan=self.user_plan)
            if not result.get("success"):
                raise RuntimeError(result.get("error", "Falha ao gerar imagem"))

            image_path = result.get("image_path")
            if not image_path:
                raise RuntimeError("Image generation returned no path")

            await self.ws.send_json({"type": "result", "content_type": "image", "url": image_path})
            return f"Imagem gerada com sucesso: {image_path}"
        except Exception as e:
            await self._send_error(f"Erro ao gerar imagem: {e}")
            return ""

    async def _handle_video(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Generate a text-to-video clip and send the resulting URL."""
        prompt = decision.get("prompt", user_message)
        duration = int(decision.get("duration", 5))
        ratio = decision.get("ratio", "16:9")
        await self._send_system(f"Gerando video: {prompt}...")
        try:
            video_svc = get_service("video")
            if not video_svc:
                raise RuntimeError("Video service unavailable")

            result = await video_svc.generate_text_to_video(
                prompt=prompt, user_plan=self.user_plan, duration=duration, ratio=ratio,
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
            await self.ws.send_json({"type": "result", "content_type": "text", "text": response_text})
            return response_text
        except Exception as e:
            await self._send_error(f"Erro ao gerar video: {e}")
            return ""

    async def _handle_voice(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Convert text to speech via the voice agent and send the audio URL."""
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
            result = await voice_agent.execute(decision.get("text", user_message), voice_context)
            result_text = result.response if hasattr(result, "response") else str(result)

            if result_text.startswith("Erro"):
                raise RuntimeError(result_text)

            await self.ws.send_json({"type": "result", "content_type": "audio", "url": result_text})
            return f"Audio gerado: {result_text}"
        except Exception as e:
            await self._send_error(f"Erro ao gerar audio: {e}")
            return f"Erro ao gerar audio: {e}"

    async def _handle_finance(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Fetch a stock quote from the finance service and send the summary."""
        symbol = decision.get("symbol", "AAPL")
        await self._send_system(f"Consultando cotacao para {symbol}...")
        try:
            finance_svc = get_service("finance")
            if not finance_svc:
                raise RuntimeError("Finance service unavailable")

            quote = finance_svc.get_quote(symbol)
            response_text = (
                f"**Cotacao de {quote.get('name') or symbol} ({quote.get('symbol') or symbol})**\n"
                f"- Preco: ${quote.get('price', 0):.2f} ({quote.get('currency', 'N/A')})\n"
                f"- Variacao: {quote.get('change', 0):.2f} ({quote.get('percent_change', 0):.2f}%)\n"
                f"- Max. do Dia: ${quote.get('high', 0):.2f}\n"
                f"- Min. do Dia: ${quote.get('low', 0):.2f}"
            )
            await self.ws.send_json({"type": "result", "content_type": "text", "text": response_text})
            return response_text
        except Exception as e:
            await self._send_error(f"Erro ao consultar financas: {e}")
            return ""

    async def _handle_calendar(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Delegate to the calendar agent and format the event list."""
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
                response_text = result.get("response", "Informacoes do calendario processadas.")
                events = result.get("events", result.get("data", {}).get("events", []))
                if events:
                    response_text += "\n\n**Eventos:**\n"
                    for event in events:
                        response_text += (
                            f"- {event.get('summary', 'Sem titulo')} "
                            f"em {event.get('start', 'Data nao disponivel')}\n"
                        )
            else:
                response_text = result.get("error", result.get("response", "Nao foi possivel acessar o calendario."))

            await self.ws.send_json({"type": "result", "content_type": "text", "text": response_text})
            return response_text
        except Exception as e:
            logger.exception("Calendar agent error: %s", e)
            await self._send_error(f"Erro ao consultar calendario: {e}")
            return ""

    async def _handle_weather(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Fetch a weather forecast and send a formatted summary."""
        location = decision.get("location", "Dublin")
        await self._send_system(f"Verificando o tempo em {location}...")
        try:
            weather_svc = get_service("weather")
            if not weather_svc:
                raise RuntimeError("Weather service unavailable")

            weather = weather_svc.get_forecast(location)
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
                response_text = f"Nao foi possivel obter previsao detalhada para {location}."

            await self.ws.send_json({"type": "result", "content_type": "text", "text": response_text})
            return response_text
        except Exception as e:
            await self._send_error(f"Erro ao consultar o tempo: {e}")
            return ""

    async def _handle_traffic(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Get a traffic summary between two locations and stream the result."""
        origin = decision.get("origin", "Dublin")
        destination = decision.get("destination", "Cork")
        await self._send_system(f"Verificando trafego de {origin} para {destination}...")
        try:
            traffic_svc = get_service("traffic")
            if not traffic_svc:
                raise RuntimeError("Traffic service unavailable")

            traffic_summary = traffic_svc.get_traffic_summary(origin, destination)
            await self.ws.send_json({"type": "token", "content": traffic_summary})
            return traffic_summary
        except Exception as e:
            await self._send_error(f"Erro ao consultar trafego: {e}")
            return ""

    async def _handle_car(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Query the electric vehicle via the car agent, refreshing tokens if needed."""
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

                if vehicle and await vehicle_db_svc.is_token_expired(self.user_id, vehicle_id):
                    if car_svc:
                        new_tokens = await car_svc.refresh_access_token(vehicle["refresh_token"])
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
                car_result = await car_agent.process(query, {
                    "user_id": self.user_id,
                    "vehicle_id": vehicle_id,
                    "access_token": access_token,
                })
                response_text = (
                    car_result.response if hasattr(car_result, "response") else str(car_result)
                )
            else:
                response_text = "Car agent unavailable"

            await self.ws.send_json({"type": "result", "content_type": "text", "text": response_text})
            return response_text
        except Exception as e:
            logger.exception("Car agent error: %s", e)
            await self._send_error(f"Erro ao consultar veiculo: {e}")
            return ""

    async def _handle_chat(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Handle a direct chat message via the general-purpose chat agent."""
        try:
            chat_agent = get_agent("chat")
            if not chat_agent:
                raise RuntimeError("Chat agent unavailable")

            chat_context = {"history": history, "user_plan": self.user_plan}
            chat_result = await chat_agent.execute(user_message, chat_context)
            full_response = (
                chat_result.response if hasattr(chat_result, "response") else str(chat_result)
            )
            await self.ws.send_json({"type": "token", "content": full_response})
            return full_response
        except Exception as e:
            logger.exception("Chat agent error: %s", e)
            error_msg = f"Erro ao processar mensagem: {e}"
            await self._send_error(error_msg)
            return error_msg

    async def _handle_fallback(
        self, user_message: str, decision: Dict, history: List[Dict],
    ) -> str:
        """Fall back to raw OpenAI streaming when the action is unrecognised."""
        await self._send_error("Acao desconhecida. Respondendo diretamente...")
        return await self._stream_openai(history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_system(self, content: str) -> None:
        """Send a system-type status message to the WebSocket client."""
        await self.ws.send_json({"type": "system", "content": content})

    async def _send_error(self, content: str) -> None:
        """Send an error-type message to the WebSocket client."""
        await self.ws.send_json({"type": "error", "content": content})

    async def _stream_openai(self, messages: List[Dict]) -> str:
        """Stream OpenAI tokens to the WebSocket and return the full text."""
        full = ""
        if self._openai_svc:
            async for tok in self._openai_svc.stream_chat_completion(messages):
                full += tok
                await self.ws.send_json({"type": "token", "content": tok})
        return full

    # ------------------------------------------------------------------
    # Action dispatch table
    #
    # Maps orchestrator action strings to handler methods.  Using a dict
    # instead of if/elif reduces cyclomatic complexity and makes it easy
    # to register new actions without touching the dispatch() method.
    # Handlers are stored as unbound functions; dispatch() passes *self*
    # explicitly so that they behave like normal instance methods.
    # ------------------------------------------------------------------

    _ACTION_HANDLERS: Dict[str, Any] = {
        "search":   _handle_search,
        "dev":      _handle_dev,
        "image":    _handle_image,
        "video":    _handle_video,
        "voice":    _handle_voice,
        "finance":  _handle_finance,
        "calendar": _handle_calendar,
        "weather":  _handle_weather,
        "traffic":  _handle_traffic,
        "car":      _handle_car,
        "chat":     _handle_chat,
    }
