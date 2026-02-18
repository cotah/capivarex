"""
Chat Routes (Refactored)
Endpoints REST e WebSocket para chat com GPT.

Uses agents (get_agent) and services (get_service)
instead of direct imports from agents/ and services/.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.middleware.rate_limit import limiter
from models.schemas import Conversation, ConversationCreate, Message

# Refactored imports: registry-based access
from agents import get_agent
from api.routes._helpers import _get_db
from services.core import get_service
from autofix import record_exception

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: lazily resolve services and agents from their registries
# ---------------------------------------------------------------------------



def _get_redis():
    """Get the Redis service instance."""
    redis_svc = get_service("redis")
    if redis_svc is None:
        raise HTTPException(status_code=503, detail="Redis service unavailable")
    return redis_svc


def _get_openai_service():
    """Get the OpenAI service instance."""
    svc = get_service("openai")
    if svc is None:
        raise HTTPException(status_code=503, detail="OpenAI service unavailable")
    return svc


# JWT config (same env vars used by the original auth module)
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")
ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")


# ============================================
# REST ENDPOINTS
# ============================================

@router.get("/conversations/", response_model=List[Conversation])
async def list_conversations(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Lista todas as conversas do usuario autenticado."""
    db = _get_db()
    response = (
        db.table("conversations")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("updated_at", desc=True)
        .execute()
    )
    return response.data


@router.post("/conversations/", response_model=Conversation, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cria uma nova conversa."""
    db = _get_db()
    new_conversation = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": data.title,
    }

    response = db.table("conversations").insert(new_conversation).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create conversation")

    return response.data[0]


@router.get("/conversations/{conversation_id}/messages", response_model=List[Message])
async def get_messages(
    conversation_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Lista todas as mensagens de uma conversa."""
    db = _get_db()

    # Verificar se a conversa pertence ao usuario
    conv_response = (
        db.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not conv_response.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Buscar mensagens
    messages_response = (
        db.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .execute()
    )

    return messages_response.data


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    """Deleta uma conversa (e todas as mensagens em cascata)."""
    db = _get_db()

    conv_response = (
        db.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not conv_response.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.table("conversations").delete().eq("id", conversation_id).execute()

    return {"message": "Conversation deleted successfully"}


@router.delete("/clear")
async def clear_chat_cache(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Limpa apenas o cache de conversa no Redis para o usuario autenticado."""
    redis_svc = _get_redis()
    cleared = await redis_svc.clear_conversation(user_id=current_user["id"])
    return {
        "success": True,
        "cleared": cleared,
        "message": "Conversation cache cleared" if cleared else "No conversation found",
    }


class ChatStreamRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = None
    query: Optional[str] = None
    prompt: Optional[str] = None
    location: Optional[str] = None
    symbol: Optional[str] = None
    aspect_ratio: Optional[str] = None
    image_path: Optional[str] = None
    duration: Optional[int] = None
    ratio: Optional[str] = None
    user_plan: Optional[str] = None


# ---------------------------------------------------------------------------
# Strategy Pattern: intent → agent mapping
# ---------------------------------------------------------------------------

# Maps intent names to (agent_name, method_name) tuples.
# "execute" is the standard method; "process" is used by calendar/car.
_AGENT_MAP: Dict[str, tuple] = {
    "weather":  ("weather",  "execute"),
    "finance":  ("finance",  "execute"),
    "image":    ("image",    "execute"),
    "video":    ("video",    "execute"),
    "calendar": ("calendar", "process"),
    "traffic":  ("traffic",  "execute"),
    "research": ("research", "execute"),
    "dev":      ("dev",      "execute"),
    "chat":     ("chat",     "execute"),
}

_VALID_INTENTS = frozenset(_AGENT_MAP) | {"car"}


def _build_request_context(request: ChatStreamRequest) -> Dict[str, Any]:
    """Build the shared context dict from a ChatStreamRequest."""
    return {
        "history": request.history or [],
        "query": request.query,
        "prompt": request.prompt,
        "location": request.location,
        "symbol": request.symbol,
        "aspect_ratio": request.aspect_ratio,
        "image_path": request.image_path,
        "duration": request.duration,
        "ratio": request.ratio,
        "user_plan": request.user_plan or "basic",
        "user": None,
    }


async def _detect_intent(
    message: str, context: Dict[str, Any]
) -> str:
    """Use the orchestrator agent to classify the user intent."""
    orchestrator = get_agent("orchestrator")
    orch_response = await orchestrator.execute(message, context)
    intent = (
        orch_response.response
        if hasattr(orch_response, "response")
        else str(orch_response)
    )
    return intent if intent in _VALID_INTENTS else "chat"


async def _execute_car_agent(
    message: str, context: Dict[str, Any]
) -> Any:
    """Handle the 'car' intent — includes vehicle lookup & token refresh."""
    car_agent = get_agent("car")
    vehicle_db_svc = get_service("vehicle_db")
    car_svc = get_service("car")

    user_id = (
        str(context.get("user", {}).get("id", "guest"))
        if context.get("user")
        else "guest"
    )

    vehicle = None
    vehicle_id = None
    access_token = None

    if vehicle_db_svc:
        vehicle = await vehicle_db_svc.get_primary_vehicle(user_id)
        vehicle_id = vehicle.get("vehicle_id") if vehicle else None
        access_token = vehicle.get("access_token") if vehicle else None

        if vehicle and await vehicle_db_svc.is_token_expired(user_id, vehicle_id):
            if car_svc:
                new_tokens = await car_svc.refresh_access_token(
                    vehicle["refresh_token"]
                )
                if "error" not in new_tokens:
                    await vehicle_db_svc.update_tokens(
                        user_id=user_id,
                        vehicle_id=vehicle_id,
                        access_token=new_tokens["access_token"],
                        refresh_token=new_tokens["refresh_token"],
                        expires_in=new_tokens.get("expires_in", 7200),
                    )
                    access_token = new_tokens["access_token"]

    return await car_agent.process(message, {
        "user_id": user_id,
        "vehicle_id": vehicle_id,
        "access_token": access_token,
    })


def _normalize_result(intent: str, agent_result: Any) -> Dict[str, Any]:
    """Normalize an agent result into a JSON-serialisable SSE payload."""
    if hasattr(agent_result, "to_dict"):
        return {"intent": intent, "type": intent, "result": agent_result.to_dict()}
    if isinstance(agent_result, dict):
        return {"intent": intent, "type": intent, "result": agent_result}
    return {"intent": intent, "type": "text", "text": str(agent_result)}


def _build_error_payload() -> Dict[str, Any]:
    """Return the standard error payload for a failed stream request."""
    return {
        "intent": "chat",
        "type": "error",
        "text": "Nao foi possivel processar sua solicitacao.",
    }


# ---------------------------------------------------------------------------
# /stream endpoint  (refactored — complexity ≈ A5)
# ---------------------------------------------------------------------------

@router.post("/stream")
@limiter.limit("10/minute")
async def chat_stream(
    request: Request,
    body: ChatStreamRequest,
) -> StreamingResponse:
    """HTTP SSE endpoint that orchestrates intent detection and agent execution."""

    context = _build_request_context(body)

    try:
        intent = await _detect_intent(body.message, context)

        if intent == "car":
            agent_result = await _execute_car_agent(body.message, context)
        else:
            agent_name, method = _AGENT_MAP.get(intent, ("chat", "execute"))
            agent = get_agent(agent_name)
            handler = getattr(agent, method) if agent else None

            if handler:
                agent_result = await handler(body.message, context)
            else:
                chat_fallback = get_agent("chat")
                agent_result = await chat_fallback.execute(body.message, context) if chat_fallback else None

        payload = _normalize_result(intent, agent_result)

    except Exception as exc:
        logger.exception("HTTP chat stream failed: %s", exc)
        payload = _build_error_payload()

    async def event_generator():
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ============================================
# WEBSOCKET ENDPOINT
# ============================================

@router.websocket("/ws/{conversation_id}")
async def chat_websocket(
    websocket: WebSocket,
    conversation_id: str,
) -> None:
    """
    WebSocket para chat em tempo real com streaming.

    Fluxo de autenticacao:
        1. Cliente se conecta ao WebSocket
        2. Cliente envia: {"type": "auth", "token": "JWT_TOKEN"}
        3. Backend valida o token e autentica o usuario

    Fluxo de chat:
        1. Cliente envia: {"message": "Ola!"}
        2. Backend salva mensagem do usuario
        3. Backend faz streaming da resposta do GPT
        4. Cliente recebe: {"type": "token", "content": "..."} (multiplas vezes)
        5. Cliente recebe: {"type": "done", "message_id": 123}
    """

    ws_user_id = "unknown"
    db = _get_db()

    # 1. Aceitar conexao WebSocket
    await websocket.accept()

    try:
        # ============================
        # BLOCO DE AUTENTICACAO
        # ============================
        auth_data = await websocket.receive_json()

        if auth_data.get("type") != "auth" or not auth_data.get("token"):
            await websocket.close(code=1008, reason="Invalid auth message")
            return

        token = auth_data.get("token")

        # Validar JWT token
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email: Optional[str] = payload.get("sub")
            if email is None:
                await websocket.close(code=1008, reason="Invalid token")
                return
        except JWTError:
            await websocket.close(code=1008, reason="Invalid token")
            return

        # Buscar usuario
        user_response = db.table("users").select("*").eq("email", email).execute()
        user = user_response.data[0] if user_response.data else None

        if not user:
            await websocket.close(code=1008, reason="User not found")
            return

        user_id = user["id"]
        ws_user_id = str(user_id)
        user_plan = user.get("plan", "basic")

        # Verificar se a conversa pertence ao usuario
        conv_response = (
            db.table("conversations")
            .select("*")
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not conv_response.data:
            await websocket.close(code=1008, reason="Conversation not found")
            return

        # ============================
        # FIM DO BLOCO DE AUTENTICACAO
        # ============================

        # Resolve services
        redis_svc = _get_redis()
        openai_svc = _get_openai_service()
        prompt_cleaner_svc = get_service("prompt_cleaner")
        image_svc = get_service("image")
        video_svc = get_service("video")
        finance_svc = get_service("finance")
        weather_svc = get_service("weather")
        traffic_svc = get_service("traffic")
        vehicle_db_svc = get_service("vehicle_db")
        car_svc = get_service("car")

        # 6. Loop de chat
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_message = message_data.get("message", "")

            if not user_message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            # 8. Tentar recuperar contexto no Redis (ultimas 10 mensagens)
            conversation_context: List[Dict[str, Any]] = []
            try:
                conversation_context = await redis_svc.get_conversation_context(
                    user_id=user_id,
                    last_n=10,
                ) or []
            except Exception as e:
                logger.warning("Redis context fetch failed for user %s: %s", user_id, e)
                conversation_context = []

            # 9. Fallback Supabase em cache miss e warm-up do Redis
            if not conversation_context:
                history_response = (
                    db.table("messages")
                    .select("role, content, created_at")
                    .eq("conversation_id", conversation_id)
                    .order("created_at", desc=False)
                    .limit(20)
                    .execute()
                )

                conversation_context = [
                    {
                        "role": msg.get("role"),
                        "content": msg.get("content"),
                        "timestamp": msg.get("created_at") or (datetime.utcnow().isoformat() + "Z"),
                    }
                    for msg in (history_response.data or [])
                ]

                try:
                    for msg in conversation_context:
                        await redis_svc.save_conversation_message(
                            user_id=user_id,
                            message=msg,
                            max_messages=20,
                            expire_seconds=3600,
                        )
                except Exception as e:
                    logger.warning("Redis warm-up failed for user %s: %s", user_id, e)

            # 10. Salvar mensagem do usuario no banco (Supabase)
            user_msg_data = {
                "conversation_id": conversation_id,
                "role": "user",
                "content": user_message,
            }
            db.table("messages").insert(user_msg_data).execute()

            # 11. Salvar mensagem do usuario no Redis e renovar TTL
            user_msg = {
                "role": "user",
                "content": user_message,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            try:
                await redis_svc.save_conversation_message(
                    user_id=user_id,
                    message=user_msg,
                    max_messages=20,
                    expire_seconds=3600,
                )
                await redis_svc.refresh_conversation_ttl(user_id=user_id, expire_seconds=3600)
            except Exception as e:
                logger.warning("Redis user message save failed for user %s: %s", user_id, e)

            # 12. Formatar contexto para IA
            history = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in conversation_context
                if msg.get("role") and msg.get("content") is not None
            ]
            history.append({"role": "user", "content": user_message})
            history = history[-10:]

            # 13. ORQUESTRACAO: Usar OrchestratorAgent para decidir qual especialista usar
            orchestrator = get_agent("orchestrator")
            context_for_orchestrator: Dict[str, Any] = {
                "history": history,
                "user_plan": user_plan,
            }
            orchestrator_resp = await orchestrator.execute(user_message, context_for_orchestrator)
            action = (
                orchestrator_resp.response
                if hasattr(orchestrator_resp, "response")
                else str(orchestrator_resp)
            )

            # Fallback para chat se a decisao for invalida
            valid_actions = {
                "chat", "search", "dev", "image", "video",
                "finance", "weather", "calendar", "traffic", "car", "voice",
            }
            if action not in valid_actions:
                action = "chat"

            # 13.5. CLEAN PROMPT: preprocessar mensagem para o agente escolhido
            if prompt_cleaner_svc:
                cleaned_data = await prompt_cleaner_svc.clean_for_agent(
                    agent_type=action,
                    user_message=user_message,
                    context=context_for_orchestrator,
                )
                decision = cleaned_data
            else:
                decision = {"action": action}
            decision.setdefault("action", action)

            full_response = ""

            if action == "search":
                # ACAO: WEB SEARCH
                query = decision.get("query", user_message)

                await websocket.send_json({
                    "type": "system",
                    "content": f"Pesquisando sobre: {query}...",
                })

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

                    async for tok in openai_svc.stream_chat_completion(messages_with_context):
                        full_response += tok
                        await websocket.send_json({"type": "token", "content": tok})

                except Exception as e:
                    logger.exception("Search error: %s", e)
                    error_msg = (
                        "Desculpe, nao foi possivel realizar a pesquisa no momento. "
                        "Tentando responder com conhecimento base..."
                    )
                    await websocket.send_json({"type": "error", "content": error_msg})

                    # Fallback: responder sem pesquisa
                    async for tok in openai_svc.stream_chat_completion(history):
                        full_response += tok
                        await websocket.send_json({"type": "token", "content": tok})

            elif action == "dev":
                # ACAO: DEV AGENT (Anthropic Claude)
                dev_prompt = decision.get("prompt")
                if not dev_prompt:
                    await websocket.send_json({"type": "error", "content": "DEV prompt missing"})
                    continue

                await websocket.send_json({"type": "system", "content": "Gerando codigo..."})

                try:
                    anthropic_svc = get_service("anthropic")
                    if anthropic_svc:
                        async for chunk in anthropic_svc.generate_code_stream(dev_prompt):
                            await websocket.send_json({"type": "token", "content": chunk})
                            full_response += chunk
                    else:
                        await websocket.send_json({"type": "error", "content": "Anthropic service unavailable"})
                        continue
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": f"Erro no DEV Agent: {e}"})
                    continue

            # =================================================
            # IMAGE AGENT
            # =================================================
            elif action == "image":
                prompt = decision.get("description", decision.get("prompt", user_message))
                await websocket.send_json({"type": "system", "content": f"Gerando imagem: {prompt}..."})
                try:
                    if image_svc:
                        result = await image_svc.generate_image(
                            prompt=prompt,
                            user_plan=user_plan,
                        )
                    else:
                        raise RuntimeError("Image service unavailable")

                    if not result.get("success"):
                        raise RuntimeError(result.get("error", "Falha ao gerar imagem"))

                    image_path = result.get("image_path")
                    if not image_path:
                        raise RuntimeError("Image generation returned no path")

                    full_response = f"Imagem gerada com sucesso: {image_path}"
                    await websocket.send_json({
                        "type": "result",
                        "content_type": "image",
                        "url": image_path,
                    })
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": f"Erro ao gerar imagem: {e}"})
                    continue

            # =================================================
            # VIDEO AGENT
            # =================================================
            elif action == "video":
                prompt = decision.get("prompt", user_message)
                duration = int(decision.get("duration", 5))
                ratio = decision.get("ratio", "16:9")
                await websocket.send_json({"type": "system", "content": f"Gerando video: {prompt}..."})
                try:
                    if video_svc:
                        result = await video_svc.generate_text_to_video(
                            prompt=prompt,
                            user_plan=user_plan,
                            duration=duration,
                            ratio=ratio,
                        )
                    else:
                        raise RuntimeError("Video service unavailable")

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
                    full_response = response_text
                    await websocket.send_json({
                        "type": "result",
                        "content_type": "text",
                        "text": response_text,
                    })
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": f"Erro ao gerar video: {e}"})
                    continue

            # =================================================
            # VOICE AGENT
            # =================================================
            elif action == "voice":
                await websocket.send_json({"type": "system", "content": "Gerando audio..."})
                try:
                    voice_agent = get_agent("voice")
                    if not voice_agent:
                        raise RuntimeError("Voice agent unavailable")

                    voice_context = {
                        "action": decision.get("action", "text_to_speech"),
                        "text": decision.get("text", user_message),
                        "voice": decision.get("voice", "rachel"),
                        "user_id": user_id,
                    }
                    result = await voice_agent.execute(decision.get("text", user_message), voice_context)

                    # Result is an AgentResponse
                    result_text = result.response if hasattr(result, "response") else str(result)
                    if result_text.startswith("Erro"):
                        raise RuntimeError(result_text)

                    await websocket.send_json({
                        "type": "result",
                        "content_type": "audio",
                        "url": result_text,
                    })
                    full_response = f"Audio gerado: {result_text}"
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": f"Erro ao gerar audio: {e}"})
                    full_response = f"Erro ao gerar audio: {e}"

            # =================================================
            # FINANCE AGENT
            # =================================================
            elif action == "finance":
                symbol = decision.get("symbol", "AAPL")
                await websocket.send_json({"type": "system", "content": f"Consultando cotacao para {symbol}..."})
                try:
                    if finance_svc:
                        quote = finance_svc.get_quote(symbol)
                    else:
                        raise RuntimeError("Finance service unavailable")

                    response_text = (
                        f"**Cotacao de {quote.get('name') or symbol} ({quote.get('symbol') or symbol})**\n"
                        f"- Preco: ${quote.get('price', 0):.2f} ({quote.get('currency', 'N/A')})\n"
                        f"- Variacao: {quote.get('change', 0):.2f} ({quote.get('percent_change', 0):.2f}%)\n"
                        f"- Max. do Dia: ${quote.get('high', 0):.2f}\n"
                        f"- Min. do Dia: ${quote.get('low', 0):.2f}"
                    )
                    full_response = response_text
                    await websocket.send_json({
                        "type": "result",
                        "content_type": "text",
                        "text": response_text,
                    })
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": f"Erro ao consultar financas: {e}"})
                    continue

            # =================================================
            # CALENDAR AGENT
            # =================================================
            elif action == "calendar":
                await websocket.send_json({"type": "system", "content": "Consultando seu calendario..."})
                try:
                    calendar_agent = get_agent("calendar")
                    if not calendar_agent:
                        raise RuntimeError("Calendar agent unavailable")

                    calendar_context = {
                        "user_id": user_id,
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

                    full_response = response_text
                    await websocket.send_json({
                        "type": "result",
                        "content_type": "text",
                        "text": response_text,
                    })
                except Exception as e:
                    logger.exception("Calendar agent error: %s", e)
                    await websocket.send_json({"type": "error", "content": f"Erro ao consultar calendario: {e}"})
                    continue

            # =================================================
            # WEATHER AGENT
            # =================================================
            elif action == "weather":
                location = decision.get("location", "Dublin")
                await websocket.send_json({"type": "system", "content": f"Verificando o tempo em {location}..."})
                try:
                    if weather_svc:
                        weather = weather_svc.get_forecast(location)
                    else:
                        raise RuntimeError("Weather service unavailable")

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

                    full_response = response_text
                    await websocket.send_json({
                        "type": "result",
                        "content_type": "text",
                        "text": response_text,
                    })
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": f"Erro ao consultar o tempo: {e}"})
                    continue

            # =================================================
            # TRAFFIC AGENT
            # =================================================
            elif action == "traffic":
                origin = decision.get("origin", "Dublin")
                destination = decision.get("destination", "Cork")

                await websocket.send_json({
                    "type": "system",
                    "content": f"Verificando trafego de {origin} para {destination}...",
                })

                try:
                    if traffic_svc:
                        traffic_summary = traffic_svc.get_traffic_summary(origin, destination)
                    else:
                        raise RuntimeError("Traffic service unavailable")

                    full_response = traffic_summary
                    await websocket.send_json({"type": "token", "content": traffic_summary})
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": f"Erro ao consultar trafego: {e}"})
                    continue

            # =================================================
            # CAR AGENT (Electric Vehicle)
            # =================================================
            elif action == "car":
                query = decision.get("query", user_message)

                await websocket.send_json({"type": "system", "content": "Verificando seu veiculo..."})

                try:
                    car_user_id = str(user.get("id")) if user else "guest"

                    vehicle = None
                    vehicle_id = None
                    access_token = None

                    if vehicle_db_svc:
                        vehicle = await vehicle_db_svc.get_primary_vehicle(car_user_id)
                        vehicle_id = vehicle.get("vehicle_id") if vehicle else None
                        access_token = vehicle.get("access_token") if vehicle else None

                        # Check if token needs refresh
                        if vehicle and await vehicle_db_svc.is_token_expired(car_user_id, vehicle_id):
                            if car_svc:
                                new_tokens = await car_svc.refresh_access_token(vehicle["refresh_token"])
                                if "error" not in new_tokens:
                                    await vehicle_db_svc.update_tokens(
                                        user_id=car_user_id,
                                        vehicle_id=vehicle_id,
                                        access_token=new_tokens["access_token"],
                                        refresh_token=new_tokens["refresh_token"],
                                        expires_in=new_tokens.get("expires_in", 7200),
                                    )
                                    access_token = new_tokens["access_token"]

                    car_agent = get_agent("car")
                    if car_agent:
                        car_result = await car_agent.process(query, {
                            "user_id": car_user_id,
                            "vehicle_id": vehicle_id,
                            "access_token": access_token,
                        })
                        response_text = (
                            car_result.response
                            if hasattr(car_result, "response")
                            else str(car_result)
                        )
                    else:
                        response_text = "Car agent unavailable"

                    full_response = response_text
                    await websocket.send_json({
                        "type": "result",
                        "content_type": "text",
                        "text": response_text,
                    })
                except Exception as e:
                    logger.exception("Car agent error: %s", e)
                    await websocket.send_json({"type": "error", "content": f"Erro ao consultar veiculo: {e}"})
                    continue

            elif action == "chat":
                # ACAO: CHAT DIRETO
                try:
                    chat_agent = get_agent("chat")
                    if not chat_agent:
                        raise RuntimeError("Chat agent unavailable")

                    chat_context = {
                        "history": history,
                        "user_plan": user_plan,
                    }
                    chat_result = await chat_agent.execute(user_message, chat_context)
                    full_response = (
                        chat_result.response
                        if hasattr(chat_result, "response")
                        else str(chat_result)
                    )

                    await websocket.send_json({"type": "token", "content": full_response})
                except Exception as e:
                    logger.exception("Chat agent error: %s", e)
                    full_response = f"Erro ao processar mensagem: {e}"
                    await websocket.send_json({"type": "error", "content": full_response})

            else:
                # ACAO DESCONHECIDA (fallback)
                await websocket.send_json({
                    "type": "error",
                    "content": "Acao desconhecida. Respondendo diretamente...",
                })

                async for tok in openai_svc.stream_chat_completion(history):
                    full_response += tok
                    await websocket.send_json({"type": "token", "content": tok})

            # 14. Salvar resposta do assistente no banco
            if full_response:
                assistant_msg_data = {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": full_response,
                }
                response = db.table("messages").insert(assistant_msg_data).execute()
                message_id = response.data[0]["id"] if response.data else None

                # Salvar resposta no Redis e renovar TTL
                assistant_msg = {
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
                try:
                    await redis_svc.save_conversation_message(
                        user_id=user_id,
                        message=assistant_msg,
                        max_messages=20,
                        expire_seconds=3600,
                    )
                    await redis_svc.refresh_conversation_ttl(user_id=user_id, expire_seconds=3600)
                except Exception as e:
                    logger.warning("Redis assistant message save failed for user %s: %s", user_id, e)

                # 15. Atualizar updated_at da conversa
                db.table("conversations").update(
                    {"updated_at": datetime.now(timezone.utc).isoformat()}
                ).eq("id", conversation_id).execute()

                # 16. Enviar sinal de conclusao
                await websocket.send_json({"type": "done", "message_id": message_id})
            else:
                await websocket.send_json({
                    "type": "error",
                    "content": "Nao foi possivel gerar uma resposta.",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for conversation %s", conversation_id)
    except Exception as e:
        logger.exception(
            "Error in WebSocket conversation=%s user_id=%s",
            conversation_id,
            ws_user_id,
        )
        record_exception(
            chat_id=f"ws_{ws_user_id}",
            text=json.dumps(
                {
                    "channel": "websocket",
                    "endpoint": "chat_websocket",
                    "conversation_id": conversation_id,
                    "user_id": ws_user_id,
                },
                ensure_ascii=False,
            ),
            error=e,
            user_id=ws_user_id if ws_user_id != "unknown" else None,
        )
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            logger.exception("Failed to send websocket error payload")
