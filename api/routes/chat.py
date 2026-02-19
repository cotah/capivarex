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

from api.dependencies import get_current_user, get_authenticated_processor, RequestProcessor
from api.middleware.rate_limit import limiter
from models.schemas import Conversation, ConversationCreate, Message

# Refactored imports: registry-based access
from agents import get_agent
from api.routes._helpers import _get_db
from services.core import get_service
from autofix import record_exception
from services.business.chat_service import ChatService

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
    processor: RequestProcessor = Depends(get_authenticated_processor),
) -> StreamingResponse:
    """HTTP SSE endpoint that orchestrates intent detection and agent execution."""

    context = _build_request_context(body)
    # Enrich context with processor data
    context["request_id"] = processor.request_id
    if processor.user_context:
        context["user"] = processor.user_context.model_dump()

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

        # Resolve services needed for the message loop
        redis_svc = _get_redis()
        prompt_cleaner_svc = get_service("prompt_cleaner")

        # ChatService encapsulates per-action dispatch
        chat_service = ChatService(
            websocket=websocket,
            user_id=str(user_id),
            user_plan=user_plan,
        )

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

            # Delegate to ChatService (replaces the giant if/elif/else block)
            full_response = await chat_service.dispatch(
                action, user_message, decision, history,
            )

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
