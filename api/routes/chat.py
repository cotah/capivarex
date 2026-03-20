"""
Chat Routes (Refactored)

Endpoints REST e WebSocket para chat com GPT.
Uses agents (get_agent) and services (get_service) instead of direct imports.
"""

# FIX E402: all imports at top of file
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import jwt
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from jwt.exceptions import PyJWTError
from pydantic import BaseModel

from agents import get_agent
from api.dependencies import (
    get_current_user,
    get_authenticated_processor,
    RequestProcessor,
)
from api.middleware.rate_limit import limiter
from api.routes._helpers import _get_db
from autofix import record_exception
from models.schemas import Conversation, ConversationCreate, Message
from services.business.chat_service import ChatService
from services.core import get_service

# Module access control — added for capivara subscription system
from capivarex_modules.access_service import get_module_access_service

load_dotenv()

# JWT config (same env vars used by the original auth module)
SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")
ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")

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


@router.post(
    "/conversations/", response_model=Conversation, status_code=status.HTTP_201_CREATED
)
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
    conv_response = (
        db.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("user_id", current_user["id"])
        .execute()
    )
    if not conv_response.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
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

_AGENT_MAP: Dict[str, tuple] = {
    # Grupo 1 — Core Business (ativos)
    "weather": ("weather", "execute"),
    "finance": ("finance", "execute"),
    "calendar": ("calendar", "process"),
    "research": ("research", "execute"),
    "chat": ("chat", "execute"),
    "voice": ("voice", "execute"),
    # "image":     ("image",     "execute"),  # DISABLED: Fora do escopo executivo atual (Grupo 3)
    # "video":     ("video",     "execute"),  # DISABLED: Fora do escopo executivo atual (Grupo 3)
    # "traffic":   ("traffic",   "execute"),  # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "dev":       ("dev",       "execute"),  # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "github":    ("github",    "execute"),  # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "smarthome": ("smarthome", "execute"),  # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
}
_VALID_INTENTS = frozenset(_AGENT_MAP) | {"car"}


def _build_request_context(request: ChatStreamRequest) -> Dict[str, Any]:
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
        "user_plan": request.user_plan or "professional",
        "user": None,
    }


async def _detect_intent(message: str, context: Dict[str, Any]) -> str:
    orchestrator = get_agent("orchestrator")
    orch_response = await orchestrator.execute(message, context)
    intent = (
        orch_response.response
        if hasattr(orch_response, "response")
        else str(orch_response)
    )
    return intent if intent in _VALID_INTENTS else "chat"


async def _execute_car_agent(message: str, context: Dict[str, Any]) -> Any:
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
    return await car_agent.process(
        message,
        {
            "user_id": user_id,
            "vehicle_id": vehicle_id,
            "access_token": access_token,
        },
    )


def _normalize_result(intent: str, agent_result: Any) -> Dict[str, Any]:
    if hasattr(agent_result, "to_dict"):
        return {"intent": intent, "type": intent, "result": agent_result.to_dict()}
    if isinstance(agent_result, dict):
        return {"intent": intent, "type": intent, "result": agent_result}
    return {"intent": intent, "type": "text", "text": str(agent_result)}


def _build_error_payload() -> Dict[str, Any]:
    return {
        "intent": "chat",
        "type": "error",
        "text": "Nao foi possivel processar sua solicitacao.",
    }


# ---------------------------------------------------------------------------
# /stream endpoint
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
    context["request_id"] = processor.request_id
    if processor.user_context:
        context["user"] = processor.user_context.model_dump()

    try:
        intent = await _detect_intent(body.message, context)
        if intent == "car":
            agent_result = await _execute_car_agent(body.message, context)
        else:
            agent_name, method = _AGENT_MAP.get(intent, ("chat", "execute"))

            # --- Module access check (capivara subscription system) ---
            _user_id = context.get("user", {}).get("id") if context.get("user") else None
            if _user_id and agent_name not in ("chat", "orchestrator"):
                _access_svc = get_module_access_service()
                _access_result = await _access_svc.check_agent_access(_user_id, agent_name)
                if not _access_result.allowed:
                    payload = {
                        "intent": "module_locked",
                        "type": "module_locked",
                        "text": _access_result.upgrade_message or "This feature requires an upgrade.",
                        "module_name": _access_result.module_name,
                        "reason": _access_result.reason,
                    }

                    async def event_generator():
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                    return StreamingResponse(event_generator(), media_type="text/event-stream")
            # --- End module access check ---

            agent = get_agent(agent_name)
            handler = getattr(agent, method) if agent else None
            if handler:
                agent_result = await handler(body.message, context)
            else:
                chat_fallback = get_agent("chat")
                agent_result = (
                    await chat_fallback.execute(body.message, context)
                    if chat_fallback
                    else None
                )
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
    """WebSocket para chat em tempo real com streaming."""
    ws_user_id = "unknown"
    db = _get_db()

    await websocket.accept()
    try:
        # Auth
        auth_data = await websocket.receive_json()
        if auth_data.get("type") != "auth" or not auth_data.get("token"):
            await websocket.close(code=1008, reason="Invalid auth message")
            return

        token = auth_data.get("token")
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email: Optional[str] = payload.get("sub")
            if email is None:
                await websocket.close(code=1008, reason="Invalid token")
                return
        except PyJWTError:
            await websocket.close(code=1008, reason="Invalid token")
            return

        user_response = db.table("users").select("*").eq("email", email).execute()
        user = user_response.data[0] if user_response.data else None
        if not user:
            await websocket.close(code=1008, reason="User not found")
            return

        user_id = user["id"]
        ws_user_id = str(user_id)
        user_plan = user.get("plan", "professional")

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

        redis_svc = _get_redis()
        prompt_cleaner_svc = get_service("prompt_cleaner")
        chat_service = ChatService(
            websocket=websocket,
            user_id=str(user_id),
            user_plan=user_plan,
        )

        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_message = message_data.get("message", "")
            if not user_message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            conversation_context: List[Dict[str, Any]] = []
            try:
                conversation_context = (
                    await redis_svc.get_conversation_context(
                        user_id=user_id,
                        last_n=10,
                    )
                    or []
                )
            except Exception as e:
                logger.warning("Redis context fetch failed for user %s: %s", user_id, e)
                conversation_context = []

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
                        "timestamp": msg.get("created_at")
                        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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

            user_msg_data = {
                "conversation_id": conversation_id,
                "role": "user",
                "content": user_message,
            }
            db.table("messages").insert(user_msg_data).execute()

            user_msg = {
                "role": "user",
                "content": user_message,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            try:
                await redis_svc.save_conversation_message(
                    user_id=user_id,
                    message=user_msg,
                    max_messages=20,
                    expire_seconds=3600,
                )
                await redis_svc.refresh_conversation_ttl(
                    user_id=user_id, expire_seconds=3600
                )
            except Exception as e:
                logger.warning(
                    "Redis user message save failed for user %s: %s", user_id, e
                )

            history = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in conversation_context
                if msg.get("role") and msg.get("content") is not None
            ]
            history.append({"role": "user", "content": user_message})
            history = history[-10:]

            orchestrator = get_agent("orchestrator")
            context_for_orchestrator: Dict[str, Any] = {
                "history": history,
                "user_plan": user_plan,
            }
            orchestrator_resp = await orchestrator.execute(
                user_message, context_for_orchestrator
            )
            action = (
                orchestrator_resp.response
                if hasattr(orchestrator_resp, "response")
                else str(orchestrator_resp)
            )

            valid_actions = {
                "chat",
                "search",
                "dev",
                "image",
                "video",
                "finance",
                "weather",
                "calendar",
                "traffic",
                "car",
                "voice",
            }
            if action not in valid_actions:
                action = "chat"

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

            # --- Module access check (capivara subscription system) ---
            if action not in ("chat", "orchestrator"):
                _ws_access_svc = get_module_access_service()
                _ws_access = await _ws_access_svc.check_agent_access(str(user_id), action)
                if not _ws_access.allowed:
                    await websocket.send_json({
                        "type": "module_locked",
                        "content": _ws_access.upgrade_message or "This feature requires an upgrade.",
                        "module_name": _ws_access.module_name,
                        "reason": _ws_access.reason,
                    })
                    continue
            # --- End module access check ---

            full_response = await chat_service.dispatch(
                action, user_message, decision, history
            )

            if full_response:
                assistant_msg_data = {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": full_response,
                }
                response = db.table("messages").insert(assistant_msg_data).execute()
                message_id = response.data[0]["id"] if response.data else None

                assistant_msg = {
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }
                try:
                    await redis_svc.save_conversation_message(
                        user_id=user_id,
                        message=assistant_msg,
                        max_messages=20,
                        expire_seconds=3600,
                    )
                    await redis_svc.refresh_conversation_ttl(
                        user_id=user_id, expire_seconds=3600
                    )
                except Exception as e:
                    logger.warning(
                        "Redis assistant message save failed for user %s: %s",
                        user_id,
                        e,
                    )

                db.table("conversations").update(
                    {"updated_at": datetime.now(timezone.utc).isoformat()}
                ).eq("id", conversation_id).execute()

                await websocket.send_json({"type": "done", "message_id": message_id})
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": "Nao foi possivel gerar uma resposta.",
                    }
                )

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
