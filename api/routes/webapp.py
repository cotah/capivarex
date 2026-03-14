"""
WebApp Routes — Chat, Conversations, Insights, Services, Activity, Smarts, Finance.

REST endpoints for the webapp frontend.  Authentication is handled by
Supabase JWT (``verify_webapp_user``).  Message processing reuses the
existing orchestrator → agent dispatch pipeline.
"""

import base64
import glob
import json as _json
import os
import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from agents import get_agent
from api.middleware.webapp_auth import verify_webapp_user
from api.routes._helpers import _get_db, _get_service_or_503, temp_upload
from models.schemas import (
    NoteUpdateRequest,
    WebAppChatRequest,
    WebAppChatResponse,
    WebAppConversationRename,
)
from services.business.quota_service import QuotaExceededError
from services.ai.model_config import VISION_MODEL
from services.core import get_service

router = APIRouter()


# ====================================================================
# POST /chat — send a message and get an agent response
# ====================================================================


@router.post("/chat", response_model=WebAppChatResponse)
async def webapp_chat(
    body: WebAppChatRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Process a user message through the orchestrator and agents.

    1. Create or reuse a conversation.
    2. Persist the user message.
    3. Route via orchestrator → specialised agent.
    4. Persist the assistant response.
    5. Return the response with metadata.
    """
    db = _get_db()
    conversation_id = body.conversation_id

    try:
        # --- 0. Quota enforcement (QuotaService) ---
        try:
            quota_svc = get_service("quota")
            if quota_svc:
                await quota_svc.check_and_consume(user_id, "gpt_tokens")
        except QuotaExceededError as qe:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "quota_exceeded",
                    "message": str(qe),
                    "upgrade_url": "/pricing",
                },
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Quota check failed (allowing): {e}")

        # --- 1. Resolve / create conversation ---
        if conversation_id:
            conv = (
                db.table("webapp_conversations")
                .select("id")
                .eq("id", conversation_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not conv.data:
                raise HTTPException(
                    status_code=404, detail="Conversation not found"
                )
        else:
            conv = (
                db.table("webapp_conversations")
                .insert({"user_id": user_id})
                .execute()
            )
            conversation_id = conv.data[0]["id"]

        # --- 2. Save user message ---
        (
            db.table("webapp_messages")
            .insert(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "role": "user",
                    "text": body.message,
                    "source": "webapp",
                }
            )
            .execute()
        )

        # --- 2b. Fetch relevant memories for context ---
        from services.business.rag_service import (
            get_relevant_memories,
            format_memories_for_context,
        )
        memories = []
        try:
            memories = await get_relevant_memories(user_id, body.message, limit=5)
        except Exception:
            pass  # memória é best-effort, nunca bloqueia o chat

        memory_context = format_memories_for_context(memories)

        # --- 3. Orchestrate ---
        context = {
            "user_id": user_id,
            "source": "webapp",
            "conversation_id": conversation_id,
            "memory_context": memory_context,
        }

        orchestrator = get_agent("orchestrator")
        if not orchestrator:
            raise HTTPException(
                status_code=503, detail="Orchestrator agent unavailable"
            )

        decision = await orchestrator.process(body.message, context)
        agent_name = decision.response if decision.response else "chat"

        # Se a mensagem contém um ficheiro anexado, NUNCA usar o agente image
        # (que gera imagens). O agente image é para GERAR, não para ANALISAR.
        has_file_attachment = (
            "[File:" in body.message or "[Imagem recebida:" in body.message
        )
        if has_file_attachment and agent_name == "image":
            logger.info(
                "WebApp chat: file attachment detected — overriding agent "
                "'image' → 'chat'"
            )
            agent_name = "chat"

        logger.info(
            f"WebApp chat: user={user_id[:8]} msg='{body.message[:80]}'"
            f" → agent='{agent_name}' reason='{decision.response}'"
        )

        # --- 3b. Vision: se for imagem, analisa com GPT-4o ---
        if has_file_attachment and agent_name == "chat":
            vision_description = None
            file_id_match = re.search(r"upload_([a-f0-9\-]+)", body.message)
            if file_id_match:
                partial_id = file_id_match.group(1)
                UPLOAD_PERSIST_DIR = "/tmp/capivarex_uploads"
                matches = glob.glob(f"{UPLOAD_PERSIST_DIR}/{partial_id}*")
                if matches:
                    img_path = matches[0]
                    try:
                        import openai as openai_module

                        oai_client = openai_module.OpenAI(
                            api_key=os.getenv("OPENAI_API_KEY")
                        )
                        with open(img_path, "rb") as f:
                            img_b64 = base64.b64encode(f.read()).decode("utf-8")
                        ext = os.path.splitext(img_path)[1].lower().lstrip(".")
                        mime = {
                            "jpg": "image/jpeg",
                            "jpeg": "image/jpeg",
                            "png": "image/png",
                            "gif": "image/gif",
                            "webp": "image/webp",
                        }.get(ext, "image/jpeg")
                        user_question = (
                            body.message.split("\n\n")[0]
                            or "O que achas desta imagem?"
                        )
                        vision_resp = oai_client.chat.completions.create(
                            model=VISION_MODEL,
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": user_question},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:{mime};base64,{img_b64}"
                                            },
                                        },
                                    ],
                                }
                            ],
                            max_tokens=800,
                        )
                        vision_description = (
                            vision_resp.choices[0].message.content
                        )
                        logger.info(
                            "WebApp chat: GPT-4o vision analysed image {}"
                            ", chars={}",
                            partial_id,
                            len(vision_description),
                        )
                    except Exception as ve:
                        logger.warning(
                            "WebApp chat: GPT-4o vision failed: {}", ve
                        )

            if vision_description:
                assistant_msg_data = (
                    db.table("webapp_messages")
                    .insert(
                        {
                            "conversation_id": conversation_id,
                            "user_id": user_id,
                            "role": "assistant",
                            "text": vision_description,
                            "agent": "chat",
                            "type": "text",
                            "data": {"method": "vision"},
                            "source": "webapp",
                        }
                    )
                    .execute()
                )
                db.table("webapp_conversations").update(
                    {"updated_at": datetime.now(timezone.utc).isoformat()}
                ).eq("id", conversation_id).execute()
                conversation_title = None
                try:
                    msg_count = (
                        db.table("webapp_messages")
                        .select("id", count="exact")
                        .eq("conversation_id", conversation_id)
                        .execute()
                    )
                    if msg_count.count == 2:
                        raw_title = body.message.split("\n\n")[0][:50]
                        title = raw_title + (
                            "..."
                            if len(body.message.split("\n\n")[0]) > 50
                            else ""
                        )
                        db.table("webapp_conversations").update(
                            {"title": title}
                        ).eq("id", conversation_id).execute()
                        conversation_title = title
                except Exception:
                    pass
                return WebAppChatResponse(
                    response=vision_description,
                    agent="chat",
                    type="text",
                    data={"method": "vision"},
                    conversation_id=conversation_id,
                    message_id=assistant_msg_data.data[0]["id"],
                    conversation_title=conversation_title,
                )

        # --- 4. Execute the specialised agent ---
        agent = get_agent(agent_name)
        if not agent:
            agent = get_agent("chat")
            agent_name = "chat"

        result = await agent.process(body.message, context)

        response_text = result.response or ""
        response_type = (
            result.metadata.get("type", "text") if result.metadata else "text"
        )
        response_data = result.data or {}

        logger.info(
            f"WebApp chat: agent='{agent_name}'"
            f" response='{response_text[:100]}'"
            f" type='{response_type}'"
            f" data_keys={list(response_data.keys())}"
        )

        # --- 4b. Convert local file paths to serveable URLs ---
        if response_data.get("image_paths"):
            response_data["image_urls"] = [
                f"/api/images/{os.path.basename(p)}"
                for p in response_data["image_paths"]
            ]
            # Don't also set image_url to avoid duplicates
        elif response_data.get("image_path"):
            filename = os.path.basename(response_data["image_path"])
            response_data["image_url"] = f"/api/images/{filename}"

        if response_data.get("video_path"):
            filename = os.path.basename(response_data["video_path"])
            response_data["video_url"] = f"/api/videos/{filename}"

        # --- 5. Save assistant message ---
        assistant_msg = (
            db.table("webapp_messages")
            .insert(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "role": "assistant",
                    "text": response_text,
                    "agent": agent_name,
                    "type": response_type,
                    "data": response_data,
                    "source": "webapp",
                }
            )
            .execute()
        )

        # RAG: extract and save memory from user message (background, non-blocking)
        import asyncio as _asyncio
        from services.business.rag_service import extract_and_save_memory
        _asyncio.create_task(
            extract_and_save_memory(user_id, body.message)
        )

        # Personal info extraction (name, birthday, address → user_context)
        from services.business.user_profile_service import extract_and_save_personal_info
        _asyncio.create_task(
            extract_and_save_personal_info(user_id, body.message)
        )

        # Redis: cache conversation context for short-term memory
        try:
            redis_svc = get_service("redis")
            if redis_svc and redis_svc.is_initialized():
                _asyncio.create_task(
                    redis_svc.save_conversation_message(
                        user_id, {"role": "user", "content": body.message}
                    )
                )
                if response_text:
                    _asyncio.create_task(
                        redis_svc.save_conversation_message(
                            user_id, {"role": "assistant", "content": response_text}
                        )
                    )
        except Exception:
            pass  # Redis is best-effort

        # --- 6. Touch conversation updated_at ---
        db.table("webapp_conversations").update(
            {"updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", conversation_id).execute()

        # --- 7. Auto-title on first message ---
        conversation_title = None
        try:
            msg_count = (
                db.table("webapp_messages")
                .select("id", count="exact")
                .eq("conversation_id", conversation_id)
                .execute()
            )
            if msg_count.count == 2:
                raw_title = body.message[:50]
                title = raw_title + ("..." if len(body.message) > 50 else "")
                db.table("webapp_conversations").update(
                    {"title": title}
                ).eq("id", conversation_id).execute()
                conversation_title = title
        except Exception:
            pass  # auto-title is best-effort, don't block the response

        return WebAppChatResponse(
            response=response_text,
            agent=agent_name,
            type=response_type,
            data=response_data,
            conversation_id=conversation_id,
            message_id=assistant_msg.data[0]["id"],
            conversation_title=conversation_title,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp chat error: {type(e).__name__}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to process message")


# ====================================================================
# POST /chat/stream — SSE streaming chat
# ====================================================================


@router.post("/chat/stream")
async def webapp_chat_stream(
    body: WebAppChatRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Stream chat response via Server-Sent Events (SSE).

    Events:
    - {"type":"start","agent":"chat"} — agent selected
    - {"type":"token","content":"..."} — streamed token
    - {"type":"done","response":"...","message_id":"...","conversation_title":"..."} — final
    - {"type":"error","detail":"..."} — on failure
    """
    db = _get_db()
    conversation_id = body.conversation_id

    # --- Pre-stream setup (quota, conversation, orchestration) ---
    try:
        # Quota
        try:
            quota_svc = get_service("quota")
            if quota_svc:
                await quota_svc.check_and_consume(user_id, "gpt_tokens")
        except QuotaExceededError as qe:
            raise HTTPException(status_code=429, detail={"error": "quota_exceeded", "message": str(qe)})
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Quota check failed (allowing): {e}")

        # Conversation
        if conversation_id:
            conv = db.table("webapp_conversations").select("id").eq("id", conversation_id).eq("user_id", user_id).limit(1).execute()
            if not conv.data:
                raise HTTPException(status_code=404, detail="Conversation not found")
        else:
            conv = db.table("webapp_conversations").insert({"user_id": user_id, "title": body.message[:50]}).execute()
            conversation_id = conv.data[0]["id"]

        # Save user message
        db.table("webapp_messages").insert({
            "conversation_id": conversation_id,
            "user_id": user_id,
            "role": "user",
            "text": body.message,
            "source": "webapp",
        }).execute()

        # Memories
        from services.business.rag_service import get_relevant_memories, format_memories_for_context
        memories = []
        try:
            memories = await get_relevant_memories(user_id, body.message, limit=5)
        except Exception:
            pass
        memory_context = format_memories_for_context(memories)

        # Orchestrate
        context = {
            "user_id": user_id,
            "source": "webapp",
            "conversation_id": conversation_id,
            "memory_context": memory_context,
        }

        orchestrator = get_agent("orchestrator")
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Orchestrator unavailable")

        decision = await orchestrator.process(body.message, context)
        agent_name = decision.response if decision.response else "chat"

        has_file = "[File:" in body.message or "[Imagem recebida:" in body.message
        if has_file and agent_name == "image":
            agent_name = "chat"

        logger.info(f"WebApp stream: user={user_id[:8]} msg='{body.message[:60]}' → agent='{agent_name}'")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"WebApp stream setup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to setup stream")

    # --- SSE Generator ---
    async def event_generator():
        """Yield SSE events."""
        full_response = ""
        try:
            yield f"data: {_json.dumps({'type': 'start', 'agent': agent_name, 'conversation_id': conversation_id})}\n\n"

            agent = get_agent(agent_name)
            if not agent:
                agent = get_agent("chat")

            # Only chat agent supports streaming
            if agent_name == "chat" and hasattr(agent, "stream_execute"):
                async for token in agent.stream_execute(body.message, context):
                    if token.startswith("[ERROR:"):
                        yield f"data: {_json.dumps({'type': 'error', 'detail': token})}\n\n"
                        return
                    full_response += token
                    yield f"data: {_json.dumps({'type': 'token', 'content': token})}\n\n"
            else:
                # Non-streaming agents: execute normally, send full response
                result = await agent.process(body.message, context)
                full_response = result.response or ""
                response_data = result.data or {}
                # Send full response as single token
                yield f"data: {_json.dumps({'type': 'token', 'content': full_response})}\n\n"
                # Send data if present (images, etc)
                if response_data:
                    yield f"data: {_json.dumps({'type': 'data', 'data': response_data})}\n\n"

            # Save assistant message to DB
            response_type = "text"
            response_data_final = {}
            if agent_name != "chat" and 'result' in dir():
                response_type = result.metadata.get("type", "text") if result.metadata else "text"
                response_data_final = result.data or {}

            assistant_msg = db.table("webapp_messages").insert({
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": "assistant",
                "text": full_response,
                "agent": agent_name,
                "type": response_type,
                "data": response_data_final,
                "source": "webapp",
            }).execute()

            message_id = assistant_msg.data[0]["id"] if assistant_msg.data else ""

            # Background tasks (non-blocking)
            from services.business.rag_service import extract_and_save_memory
            from services.business.user_profile_service import extract_and_save_personal_info
            asyncio.create_task(extract_and_save_memory(user_id, body.message))
            asyncio.create_task(extract_and_save_personal_info(user_id, body.message))

            # Redis cache
            try:
                redis_svc = get_service("redis")
                if redis_svc and redis_svc.is_initialized():
                    asyncio.create_task(redis_svc.save_conversation_message(user_id, {"role": "user", "content": body.message}))
                    if full_response:
                        asyncio.create_task(redis_svc.save_conversation_message(user_id, {"role": "assistant", "content": full_response}))
            except Exception:
                pass

            # Update conversation
            db.table("webapp_conversations").update(
                {"updated_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", conversation_id).execute()

            # Auto-title
            conversation_title = None
            try:
                msg_count = db.table("webapp_messages").select("id", count="exact").eq("conversation_id", conversation_id).execute()
                if msg_count.count == 2:
                    title = body.message[:50] + ("..." if len(body.message) > 50 else "")
                    db.table("webapp_conversations").update({"title": title}).eq("id", conversation_id).execute()
                    conversation_title = title
            except Exception:
                pass

            # Final done event
            yield f"data: {_json.dumps({'type': 'done', 'response': full_response, 'message_id': message_id, 'conversation_title': conversation_title, 'agent': agent_name})}\n\n"

        except Exception as e:
            logger.error(f"WebApp stream error: {e}", exc_info=True)
            yield f"data: {_json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ====================================================================
# GET /conversations — list user conversations
# ====================================================================


@router.get("/conversations")
async def list_conversations(user_id: str = Depends(verify_webapp_user)):
    """List the user's conversations, most-recent first (max 50)."""
    db = _get_db()

    try:
        result = (
            db.table("webapp_conversations")
            .select("id, title, updated_at, created_at")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
        )

        conv_ids = [c["id"] for c in result.data or []]
        if not conv_ids:
            logger.info(
                f"WebApp: user={user_id[:8]} listed 0 conversations"
            )
            return {"conversations": []}

        # Batch: fetch ALL messages for these conversations (2 queries total)
        all_msgs = (
            db.table("webapp_messages")
            .select("conversation_id, text, created_at")
            .in_("conversation_id", conv_ids)
            .order("created_at", desc=True)
            .execute()
        )

        # Build counts + previews in Python (zero extra queries)
        from collections import Counter

        counts: Counter = Counter()
        previews: dict[str, str] = {}
        for msg in all_msgs.data or []:
            cid = msg["conversation_id"]
            counts[cid] += 1
            if cid not in previews:
                previews[cid] = (msg.get("text") or "")[:100]

        conversations = []
        for conv in result.data:
            cid = conv["id"]
            conversations.append(
                {
                    "id": cid,
                    "title": conv["title"] or "New conversation",
                    "created_at": conv["created_at"],
                    "updated_at": conv["updated_at"],
                    "message_count": counts.get(cid, 0),
                    "preview": previews.get(cid, ""),
                }
            )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" listed {len(conversations)} conversations"
        )
        return {"conversations": conversations}

    except Exception as e:
        logger.error(
            f"WebApp list_conversations error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to list conversations"
        )


# ====================================================================
# POST /conversations — create an empty conversation
# ====================================================================


@router.post("/conversations", status_code=201)
async def create_conversation(user_id: str = Depends(verify_webapp_user)):
    """Create a new empty conversation."""
    db = _get_db()

    try:
        result = (
            db.table("webapp_conversations")
            .insert({"user_id": user_id})
            .execute()
        )
        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" created conversation {result.data[0]['id'][:8]}"
        )
        return result.data[0]

    except Exception as e:
        logger.error(
            f"WebApp create_conversation error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to create conversation"
        )


# ====================================================================
# GET /conversations/{conversation_id} — get conversation with messages
# ====================================================================


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Return a conversation and all its messages."""
    db = _get_db()

    try:
        conv = (
            db.table("webapp_conversations")
            .select("*")
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not conv.data:
            raise HTTPException(
                status_code=404, detail="Conversation not found"
            )

        messages = (
            db.table("webapp_messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .execute()
        )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" loaded conversation {conversation_id[:8]}"
            f" ({len(messages.data)} messages)"
        )
        return {
            "conversation_id": conversation_id,
            "title": conv.data[0].get("title"),
            "messages": messages.data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp get_conversation error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to get conversation"
        )


# ====================================================================
# DELETE /conversations/{conversation_id}
# ====================================================================


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Delete a conversation and all its messages (cascade)."""
    db = _get_db()

    try:
        db.table("webapp_conversations").delete().eq(
            "id", conversation_id
        ).eq("user_id", user_id).execute()

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" deleted conversation {conversation_id[:8]}"
        )
        return {"deleted": True}

    except Exception as e:
        logger.error(
            f"WebApp delete_conversation error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to delete conversation"
        )


# ====================================================================
# PATCH /conversations/{conversation_id} — rename
# ====================================================================


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    body: WebAppConversationRename,
    user_id: str = Depends(verify_webapp_user),
):
    """Rename a conversation."""
    db = _get_db()

    try:
        result = (
            db.table("webapp_conversations")
            .update({"title": body.title})
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404, detail="Conversation not found"
            )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" renamed conversation {conversation_id[:8]}"
            f" → '{body.title[:40]}'"
        )
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp rename_conversation error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to rename conversation"
        )


# ====================================================================
# INTERNAL HELPERS
# ====================================================================

_AGENT_ICONS: dict[str, str] = {
    "music": "\U0001f3b5",
    "calendar": "\U0001f4c5",
    "email": "\U0001f4e7",
    "mercado": "\U0001f6d2",
    "smarthome": "\U0001f4a1",
    "weather": "\U0001f324\ufe0f",
    "search": "\U0001f50d",
    "research": "\U0001f50d",
    "finance": "\U0001f4ca",
    "crypto": "\U0001f4b0",
    "car": "\U0001f697",
    "timer": "\u23f0",
    "reminder": "\U0001f514",
    "notes": "\U0001f4dd",
    "dev": "\U0001f4bb",
    "github": "\U0001f419",
    "restaurant": "\U0001f37d\ufe0f",
    "traffic": "\U0001f6a6",
    "translate": "\U0001f310",
    "image": "\U0001f5bc\ufe0f",
    "tracking": "\U0001f4e6",
    "youtube": "\u25b6\ufe0f",
    "voice": "\U0001f3a4",
    "chat": "\U0001f4ac",
}

_AGENT_SERVICES: dict[str, str] = {
    "music": "Spotify",
    "calendar": "Google Calendar",
    "email": "Gmail",
    "mercado": "Shopping",
    "smarthome": "Smart Home",
    "car": "Smartcar",
    "github": "GitHub",
    "youtube": "YouTube",
}

_ALL_PROVIDERS = ["google", "spotify", "smartcar", "tuya", "github"]


def _get_chat_id(db, user_id: str) -> Optional[str]:
    """Resolve a Supabase UUID to the user's Telegram chat_id.

    The ``users`` table links ``id`` (UUID) ↔ ``telegram_chat_id``.
    Returns ``None`` if the user hasn't linked Telegram or doesn't exist
    in the users table (webapp-only users).
    """
    try:
        result = (
            db.table("users")
            .select("telegram_chat_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if result.data:
            chat_id = result.data[0].get("telegram_chat_id")
            return str(chat_id) if chat_id else None
        return None
    except Exception:
        return None


def _month_range(month: Optional[str] = None):
    """Return (start_iso, end_iso) for a given ``YYYY-MM`` month string.

    Defaults to the current month.
    """
    if month:
        try:
            dt = datetime.strptime(month, "%Y-%m")
        except ValueError:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    year, mon = dt.year, dt.month
    start = f"{year}-{mon:02d}-01"
    if mon == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{mon + 1:02d}-01"
    return start, end, f"{year}-{mon:02d}"


# ====================================================================
# INSIGHTS — Grocery stats from mercado_compras / mercado_itens
# ====================================================================


@router.get("/insights/grocery/stats")
async def grocery_stats(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
    user_id: str = Depends(verify_webapp_user),
):
    """Aggregated stats for a month: total spent, trips, average per trip."""
    db = _get_db()

    try:
        chat_id = _get_chat_id(db, user_id)
        if not chat_id:
            return {"total_spent": 0, "trips": 0, "avg_per_trip": 0, "month": month or ""}

        start, end, label = _month_range(month)

        result = (
            db.table("mercado_compras")
            .select("total")
            .eq("chat_id", chat_id)
            .gte("data_compra", start)
            .lt("data_compra", end)
            .execute()
        )

        rows = result.data or []
        totals = [float(r.get("total") or 0) for r in rows]
        total_spent = round(sum(totals), 2)
        trips = len(totals)
        avg = round(total_spent / trips, 2) if trips else 0

        logger.info(
            f"WebApp: user={user_id[:8]} grocery_stats"
            f" month={label} total={total_spent} trips={trips}"
        )
        return {
            "total_spent": total_spent,
            "trips": trips,
            "avg_per_trip": avg,
            "month": label,
        }

    except Exception as e:
        logger.error(
            f"WebApp grocery_stats error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return {"total_spent": 0, "trips": 0, "avg_per_trip": 0, "month": month or ""}


@router.get("/insights/grocery/monthly")
async def grocery_monthly(
    months: int = Query(6, ge=1, le=24),
    user_id: str = Depends(verify_webapp_user),
):
    """Monthly spending for the last N months."""
    db = _get_db()

    try:
        chat_id = _get_chat_id(db, user_id)
        if not chat_id:
            return {"months": []}

        now = datetime.now(timezone.utc)
        results = []

        for i in range(months - 1, -1, -1):
            year = now.year
            mon = now.month - i
            while mon <= 0:
                mon += 12
                year -= 1

            start = f"{year}-{mon:02d}-01"
            if mon == 12:
                end_date = f"{year + 1}-01-01"
            else:
                end_date = f"{year}-{mon + 1:02d}-01"

            rows = (
                db.table("mercado_compras")
                .select("total")
                .eq("chat_id", chat_id)
                .gte("data_compra", start)
                .lt("data_compra", end_date)
                .execute()
            )

            total = round(
                sum(float(r.get("total") or 0) for r in (rows.data or [])),
                2,
            )
            results.append({"month": f"{year}-{mon:02d}", "total": total})

        logger.info(
            f"WebApp: user={user_id[:8]} grocery_monthly"
            f" {len(results)} months returned"
        )
        return {"months": results}

    except Exception as e:
        logger.error(
            f"WebApp grocery_monthly error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return {"months": []}


@router.get("/insights/grocery/stores")
async def grocery_stores(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
    user_id: str = Depends(verify_webapp_user),
):
    """Ranking of stores by spending for a given month."""
    db = _get_db()

    try:
        chat_id = _get_chat_id(db, user_id)
        if not chat_id:
            return {"stores": []}

        start, end, _ = _month_range(month)

        result = (
            db.table("mercado_compras")
            .select("mercado, total")
            .eq("chat_id", chat_id)
            .gte("data_compra", start)
            .lt("data_compra", end)
            .execute()
        )

        store_data: dict[str, dict] = {}
        for row in result.data or []:
            name = row.get("mercado") or "Unknown"
            amount = float(row.get("total") or 0)
            if name not in store_data:
                store_data[name] = {"total": 0.0, "trips": 0}
            store_data[name]["total"] += amount
            store_data[name]["trips"] += 1

        grand_total = sum(s["total"] for s in store_data.values()) or 1
        stores = sorted(
            [
                {
                    "name": name,
                    "total": round(info["total"], 2),
                    "percentage": round(info["total"] / grand_total * 100),
                    "trips": info["trips"],
                }
                for name, info in store_data.items()
            ],
            key=lambda x: x["total"],
            reverse=True,
        )

        logger.info(
            f"WebApp: user={user_id[:8]} grocery_stores"
            f" {len(stores)} stores returned"
        )
        return {"stores": stores}

    except Exception as e:
        logger.error(
            f"WebApp grocery_stores error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return {"stores": []}


@router.get("/insights/grocery/products")
async def grocery_products(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(verify_webapp_user),
):
    """Products purchased with quantity and average price."""
    db = _get_db()

    try:
        chat_id = _get_chat_id(db, user_id)
        if not chat_id:
            return {"products": []}

        start, end, _ = _month_range(month)

        result = (
            db.table("mercado_itens")
            .select("produto, quantidade, preco_total, preco_unitario")
            .eq("chat_id", chat_id)
            .gte("data_compra", start)
            .lt("data_compra", end)
            .execute()
        )

        product_data: dict[str, dict] = {}
        for row in result.data or []:
            name = row.get("produto") or "Unknown"
            qty = float(row.get("quantidade") or 0)
            price = float(row.get("preco_total") or 0)

            if name not in product_data:
                product_data[name] = {"quantity": 0.0, "total": 0.0, "count": 0}
            product_data[name]["quantity"] += qty
            product_data[name]["total"] += price
            product_data[name]["count"] += 1

        products = sorted(
            [
                {
                    "name": name,
                    "quantity": round(info["quantity"], 2),
                    "avg_price": round(
                        info["total"] / info["count"], 2
                    )
                    if info["count"]
                    else 0,
                    "total": round(info["total"], 2),
                }
                for name, info in product_data.items()
            ],
            key=lambda x: x["total"],
            reverse=True,
        )[:limit]

        logger.info(
            f"WebApp: user={user_id[:8]} grocery_products"
            f" {len(products)} products returned"
        )
        return {"products": products}

    except Exception as e:
        logger.error(
            f"WebApp grocery_products error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return {"products": []}


# ====================================================================
# SERVICES STATUS — OAuth connection status per provider
# ====================================================================


@router.get("/services/status")
async def services_status(user_id: str = Depends(verify_webapp_user)):
    """Return the OAuth connection status for each provider."""
    db = _get_db()

    try:
        chat_id = _get_chat_id(db, user_id)

        user_ids_to_check = [user_id]
        if chat_id:
            user_ids_to_check.append(str(chat_id))

        connected: dict[str, dict] = {}

        result = (
            db.table("user_oauth_tokens")
            .select("provider, active, updated_at")
            .in_("user_id", user_ids_to_check)
            .execute()
        )
        for token in result.data or []:
            provider = token.get("provider")
            if provider:
                connected[provider] = {
                    "connected": bool(token.get("active", False)),
                    "updated_at": token.get("updated_at"),
                }

        services = {}
        for provider in _ALL_PROVIDERS:
            services[provider] = connected.get(
                provider, {"connected": False}
            )

        status_summary = ", ".join(
            f"{k}={'connected' if v.get('connected') else 'no'}"
            for k, v in services.items()
        )
        logger.info(
            f"WebApp: user={user_id[:8]} services status: {status_summary}"
        )
        return {"services": services}

    except Exception as e:
        logger.error(
            f"WebApp services_status error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        services = {p: {"connected": False} for p in _ALL_PROVIDERS}
        return {"services": services}


# ====================================================================
# ACTIVITY FEED — recent assistant interactions
# ====================================================================


@router.get("/activity")
async def activity_feed(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(verify_webapp_user),
):
    """Recent activity feed from webapp assistant messages."""
    db = _get_db()

    try:
        result = (
            db.table("webapp_messages")
            .select("id, text, agent, type, source, created_at, role")
            .eq("user_id", user_id)
            .eq("role", "assistant")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        activities = []
        for msg in result.data or []:
            agent = msg.get("agent") or "chat"
            activities.append(
                {
                    "id": msg["id"],
                    "icon": _AGENT_ICONS.get(agent, "\U0001f916"),
                    "description": (msg.get("text") or "")[:150],
                    "service": _AGENT_SERVICES.get(agent, "CAPIVAREX"),
                    "agent": f"{agent.title()} Agent",
                    "timestamp": msg.get("created_at"),
                    "type": msg.get("type", "text"),
                }
            )

        logger.info(
            f"WebApp: user={user_id[:8]} activity feed:"
            f" {len(activities)} items"
        )
        return {"activities": activities, "has_more": len(activities) == limit}

    except Exception as e:
        logger.error(
            f"WebApp activity_feed error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return {"activities": [], "has_more": False}


# ====================================================================
# SMARTS — Smart home devices & vehicles (placeholder with OAuth check)
# ====================================================================


@router.get("/smarts/devices")
async def smart_devices(user_id: str = Depends(verify_webapp_user)):
    """List smart home devices if smart home is connected."""
    db = _get_db()

    try:
        chat_id = _get_chat_id(db, user_id)

        user_ids_to_check = [user_id]
        if chat_id:
            user_ids_to_check.append(str(chat_id))

        token = (
            db.table("user_oauth_tokens")
            .select("active")
            .in_("user_id", user_ids_to_check)
            .eq("provider", "tuya")
            .limit(1)
            .execute()
        )

        if not token.data or not token.data[0].get("active"):
            logger.info(f"WebApp: user={user_id[:8]} smarts/devices: not connected")
            return {"devices": [], "connected": False}

        logger.info(f"WebApp: user={user_id[:8]} smarts/devices: connected")
        return {
            "devices": [],
            "connected": True,
            "message": "Use chat to control devices: 'turn on living room lights'",
        }

    except Exception as e:
        logger.error(
            f"WebApp smart_devices error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return {"devices": [], "connected": False}


@router.get("/smarts/vehicles")
async def smart_vehicles(user_id: str = Depends(verify_webapp_user)):
    """List vehicles if Smartcar is connected."""
    db = _get_db()

    try:
        chat_id = _get_chat_id(db, user_id)

        user_ids_to_check = [user_id]
        if chat_id:
            user_ids_to_check.append(str(chat_id))

        token = (
            db.table("user_oauth_tokens")
            .select("active")
            .in_("user_id", user_ids_to_check)
            .eq("provider", "smartcar")
            .limit(1)
            .execute()
        )

        if not token.data or not token.data[0].get("active"):
            logger.info(f"WebApp: user={user_id[:8]} smarts/vehicles: not connected")
            return {"vehicles": [], "connected": False}

        logger.info(f"WebApp: user={user_id[:8]} smarts/vehicles: connected")
        return {
            "vehicles": [],
            "connected": True,
            "message": "Use chat for vehicle info: 'where is my car?'",
        }

    except Exception as e:
        logger.error(
            f"WebApp smart_vehicles error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return {"vehicles": [], "connected": False}


# ====================================================================
# FINANCE — Portfolio & news (placeholder)
# ====================================================================


@router.get("/finance/portfolio")
async def finance_portfolio(user_id: str = Depends(verify_webapp_user)):
    """Stocks and crypto the user tracks (placeholder)."""
    logger.info(f"WebApp: user={user_id[:8]} finance/portfolio requested")
    return {
        "stocks": [],
        "crypto": [],
        "message": "Use chat to add stocks: 'track AAPL'",
    }


@router.get("/finance/news")
async def finance_news(
    limit: int = Query(10, ge=1, le=50),
    user_id: str = Depends(verify_webapp_user),
):
    """Financial news (placeholder)."""
    logger.info(f"WebApp: user={user_id[:8]} finance/news requested")
    return {
        "news": [],
        "message": "Financial news coming soon",
    }


# ====================================================================
# USER PROFILE — get and update user profile
# ====================================================================


class UserProfileUpdateRequest(BaseModel):
    """Campos editáveis do perfil do usuário."""

    name: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    language: Optional[str] = None
    preferred_language: Optional[str] = None
    phone_number: Optional[str] = None


@router.get("/user/me")
async def get_user_me(user_id: str = Depends(verify_webapp_user)):
    """Return the authenticated user's profile data."""
    db = _get_db()

    try:
        result = (
            db.table("users")
            .select(
                "id, email, full_name, display_name, phone_number,"
                " preferred_language, plan, messages_used,"
                " messages_limit, created_at"
            )
            .eq("id", user_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404, detail="User not found"
            )

        row = result.data[0]

        # Map DB column names → frontend field names
        return {
            "id": row.get("id"),
            "email": row.get("email"),
            "name": row.get("full_name") or row.get("display_name") or "",
            "phone_number": row.get("phone_number"),
            "language": row.get("preferred_language") or "en",
            "plan": row.get("plan") or "free",
            "messages_used": row.get("messages_used") or 0,
            "messages_limit": row.get("messages_limit") or 30,
            "created_at": row.get("created_at"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp: get_user_me error user={user_id[:8]}: {e}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch user profile"
        )


@router.patch("/user/profile")
async def update_user_profile(
    body: UserProfileUpdateRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Update the authenticated user's editable profile fields."""
    db = _get_db()

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=400, detail="No fields to update"
        )

    # Whitelist — nunca permitir sobrescrever campos de sistema
    for forbidden in ("id", "user_id", "plan", "email", "created_at"):
        update_data.pop(forbidden, None)

    # Map frontend field names → DB column names
    field_map = {
        "name": "full_name",
        "language": "preferred_language",
    }
    db_data = {}
    for key, value in update_data.items():
        db_key = field_map.get(key, key)
        db_data[db_key] = value

    if not db_data:
        raise HTTPException(
            status_code=400, detail="No fields to update"
        )

    try:
        db.table("users").update(db_data).eq(
            "id", user_id
        ).execute()

        logger.info(
            f"WebApp: user={user_id[:8]} profile updated"
            f" fields={list(db_data.keys())}"
        )
        return {"ok": True, "updated": list(db_data.keys())}

    except Exception as e:
        logger.error(
            f"WebApp: update_user_profile error"
            f" user={user_id[:8]}: {e}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to update profile"
        )


# ====================================================================
# QUOTA — daily message usage for frontend progress bar
# ====================================================================


@router.get("/quota")
async def get_quota(user_id: str = Depends(verify_webapp_user)):
    """Return current daily message quota for the authenticated user."""
    db = _get_db()

    try:
        # Fonte da verdade: tabela users (plan + limits)
        user_result = (
            db.table("users")
            .select("plan, messages_limit")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )

        if not user_result.data:
            return {
                "plan": "free",
                "messages_used": 0,
                "messages_limit": 30,
                "quota_pct": 0.0,
                "is_unlimited": False,
                "messages_remaining": 30,
            }

        u = user_result.data[0]
        plan = u.get("plan") or "free"
        limit = u.get("messages_limit") or 30
        is_unlimited = limit >= 999999

        # Fonte da verdade para uso: tenant_usage (QuotaService)
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        period_start = _dt.now(_tz.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        usage_result = (
            db.table("tenant_usage")
            .select("used")
            .eq("tenant_id", f"user-{user_id}")
            .eq("resource", "messages")
            .gte("period_start", period_start)
            .order("period_start", desc=True)
            .limit(1)
            .execute()
        )
        used = (
            usage_result.data[0].get("used", 0)
            if usage_result.data
            else 0
        )

        # Sincronizar users.messages_used como cache (best-effort)
        try:
            db.table("users").update(
                {"messages_used": used}
            ).eq("id", user_id).execute()
        except Exception:
            pass  # não crítico

        quota_pct = (
            0.0
            if is_unlimited
            else round((used / limit) * 100, 1)
            if limit > 0
            else 100.0
        )

        logger.info(
            f"WebApp: user={user_id[:8]} quota"
            f" plan={plan} used={used}/{limit}"
        )
        return {
            "plan": plan,
            "messages_used": used,
            "messages_limit": limit,
            "quota_pct": quota_pct,
            "is_unlimited": is_unlimited,
            "messages_remaining": (
                0 if is_unlimited else max(0, limit - used)
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp: get_quota error user={user_id[:8]}: {e}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch quota"
        )


# ====================================================================
# WEATHER — server-side proxy (keeps API key on server)
# ====================================================================


@router.get("/weather")
async def get_weather(
    q: str = Query(..., min_length=1),
    user_id: str = Depends(verify_webapp_user),
):
    """Proxy server-side para WeatherAPI — mantém API key no servidor."""
    api_key = os.getenv("WEATHER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503, detail="Weather service not configured"
        )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.weatherapi.com/v1/forecast.json",
                params={"key": api_key, "q": q, "days": 6, "aqi": "no", "alerts": "no"},
                timeout=10.0,
            )

            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail="Weather API error",
                )

            logger.info(
                f"WebApp: user={user_id[:8]} weather q='{q}'"
            )
            return resp.json()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp weather error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502, detail="Weather service unavailable"
        )


# ====================================================================
# NOTES — CRUD for user notes
# ====================================================================


@router.get("/notes")
async def list_notes(user_id: str = Depends(verify_webapp_user)):
    """List all notes for the authenticated user."""
    db = _get_db()

    try:
        result = (
            db.table("notes")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" listed {len(result.data or [])} notes"
        )
        return result.data or []

    except Exception as e:
        logger.error(
            f"WebApp list_notes error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to list notes")


@router.post("/notes", status_code=201)
async def create_note(
    body: dict,
    user_id: str = Depends(verify_webapp_user),
):
    """Create a new note."""
    db = _get_db()

    try:
        result = (
            db.table("notes")
            .insert({**body, "user_id": user_id})
            .execute()
        )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" created note {result.data[0]['id'][:8]}"
        )
        return result.data[0]

    except Exception as e:
        logger.error(
            f"WebApp create_note error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to create note")


@router.patch("/notes/{note_id}")
async def update_note(
    note_id: str,
    body: NoteUpdateRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Update an existing note."""
    db = _get_db()

    try:
        update_data = {k: v for k, v in body.model_dump(exclude_none=True).items()}
        result = (
            db.table("notes")
            .update(update_data)
            .eq("id", note_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Note not found")

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" updated note {note_id[:8]}"
        )
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp update_note error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update note")


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Delete a note."""
    db = _get_db()

    try:
        db.table("notes").delete().eq(
            "id", note_id
        ).eq("user_id", user_id).execute()

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" deleted note {note_id[:8]}"
        )
        return Response(status_code=204)

    except Exception as e:
        logger.error(
            f"WebApp delete_note error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to delete note"
        )


# ====================================================================
# VOICE — STT (transcribe) + TTS (synthesize)
# ====================================================================


@router.post("/voice/transcribe")
async def voice_transcribe(
    audio: UploadFile = File(...),
    user_id: str = Depends(verify_webapp_user),
):
    """Transcribe an audio file using Whisper (speech-to-text).

    Accepts any common audio format (mp3, wav, ogg, webm, m4a).
    Returns the transcribed text, detected language, and model used.
    """
    whisper = _get_service_or_503("whisper", "Whisper STT")

    try:
        async with temp_upload(audio, prefix="voice_stt") as path:
            result = await whisper.speech_to_text(path, language="pt")

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" voice/transcribe len={len(result.get('text', ''))}"
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "WebApp voice/transcribe error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(
            status_code=500, detail="Failed to transcribe audio"
        )


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice_id: str = Field(default="21m00Tcm4TlvDq8ikWAM")


@router.post("/voice/synthesize")
async def voice_synthesize(
    body: SynthesizeRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Synthesize text to speech using ElevenLabs (TTS).

    Returns the audio as a base64-encoded MP3 string.
    """
    tts = _get_service_or_503("elevenlabs", "ElevenLabs TTS")

    try:
        audio_bytes = await tts.text_to_speech(
            body.text, voice_id=body.voice_id
        )
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" voice/synthesize chars={len(body.text)}"
            f" audio_bytes={len(audio_bytes)}"
        )
        return {
            "audio_base64": audio_b64,
            "content_type": "audio/mpeg",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "WebApp voice/synthesize error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(
            status_code=500, detail="Failed to synthesize speech"
        )


# ====================================================================
# MEMORY — user preferences / memory stored by agents
# ====================================================================


@router.get("/memory")
async def get_memory(user_id: str = Depends(verify_webapp_user)):
    """Return all memory entries for the authenticated user."""
    db = _get_db()

    try:
        result = (
            db.table("user_memory")
            .select(
                "id, key, value, content, category,"
                " confidence, source, created_at, updated_at"
            )
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )

        # Suporte a ambos os schemas: antigo (key/value) e novo RAG
        # (content/category).  O frontend MemoryCard usa key+value,
        # portanto fazemos fallback cruzado para que memórias RAG
        # também apareçam corretamente.
        memories = []
        for row in result.data or []:
            key = row.get("key") or row.get("category") or "memory"
            value = row.get("value") or row.get("content") or ""
            memories.append({
                "id": row.get("id"),
                "key": key,
                "value": value,
                "content": row.get("content") or row.get("value") or "",
                "category": row.get("category") or row.get("key") or "general",
                "confidence": row.get("confidence"),
                "source": row.get("source", ""),
                "created_at": row.get("created_at", ""),
                "updated_at": row.get("updated_at", ""),
            })

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" memory entries={len(memories)}"
        )
        return {"memories": memories}

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "WebApp memory error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(
            status_code=500, detail="Failed to get memory"
        )


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Delete a specific memory entry for the authenticated user."""
    db = _get_db()

    try:
        db.table("user_memory").delete().eq(
            "id", memory_id
        ).eq("user_id", user_id).execute()

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" deleted memory {memory_id[:8]}"
        )
        return Response(status_code=204)

    except Exception as e:
        logger.error(
            f"WebApp memory delete error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to delete memory"
        )


@router.post("/memory", status_code=201)
async def upsert_memory(
    body: dict,
    user_id: str = Depends(verify_webapp_user),
):
    """Upsert a memory entry for the authenticated user."""
    key = body.get("key", "").strip()
    value = body.get("value", "").strip()
    if not key or not value:
        raise HTTPException(
            status_code=422, detail="key and value are required"
        )

    try:
        from services.business.rag_service import upsert_memory_with_embedding
        success = await upsert_memory_with_embedding(
            user_id=user_id,
            key=key,
            value=value,
            source="webapp_manual",
            category=body.get("category", "general"),
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to upsert memory")

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" upserted memory key={key[:30]}"
        )
        return {"ok": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp memory upsert error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to upsert memory"
        )


# ====================================================================
# REMINDERS — list + toggle
# ====================================================================


@router.get("/reminders")
async def list_reminders(user_id: str = Depends(verify_webapp_user)):
    """List all reminders for the authenticated user."""
    db = _get_db()

    try:
        result = (
            db.table("reminders")
            .select("*")
            .eq("user_id", user_id)
            .order("remind_at", desc=False)
            .execute()
        )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" reminders={len(result.data or [])}"
        )
        return result.data or []

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "WebApp list_reminders error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(
            status_code=500, detail="Failed to list reminders"
        )


@router.patch("/reminders/{reminder_id}")
async def update_reminder(
    reminder_id: str,
    body: dict,
    user_id: str = Depends(verify_webapp_user),
):
    """Update a reminder (e.g. toggle enabled, change remind_at)."""
    db = _get_db()

    try:
        result = (
            db.table("reminders")
            .update(body)
            .eq("id", reminder_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404, detail="Reminder not found"
            )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" updated reminder {reminder_id[:8]}"
        )
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "WebApp update_reminder error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(
            status_code=500, detail="Failed to update reminder"
        )


# ---------------------------------------------------------------------------
# Security Events (Sprint 8+)
# ---------------------------------------------------------------------------

@router.get("/security/events")
async def get_security_events(
    limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Depends(verify_webapp_user),
):
    """
    Return the most recent security events for the current user,
    plus a 24-hour summary (failed logins, last login info).
    """
    db = _get_db()
    try:
        # Fetch recent events for this user
        result = (
            db.table("security_events")
            .select("id, event_type, severity, ip_address, endpoint, created_at, details")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        events = result.data or []

        # Build summary: auth failures in last 24h
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        failures_result = (
            db.table("security_events")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("event_type", "auth_failure")
            .gte("created_at", cutoff)
            .execute()
        )
        auth_failures_24h = failures_result.count or 0

        # Last successful login
        last_login_result = (
            db.table("security_events")
            .select("created_at, ip_address")
            .eq("user_id", user_id)
            .eq("event_type", "auth_success")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        last_login_row = last_login_result.data[0] if last_login_result.data else None

        return {
            "events": events,
            "summary": {
                "total_events": len(events),
                "auth_failures_24h": auth_failures_24h,
                "last_login": last_login_row["created_at"] if last_login_row else None,
                "last_login_ip": last_login_row["ip_address"] if last_login_row else None,
            },
        }
    except Exception as e:
        err_str = str(e)
        # PGRST205: table doesn't exist yet in PostgREST schema cache.
        # Return a graceful empty response so the frontend doesn't break
        # while the migration 005_create_security_events.sql is being applied.
        if "PGRST205" in err_str or "schema cache" in err_str:
            logger.warning(
                "security_events table not in schema cache (PGRST205) — "
                "run migration 005_create_security_events.sql in Supabase."
            )
            return {
                "events": [],
                "summary": {
                    "total_events": 0,
                    "auth_failures_24h": 0,
                    "last_login": None,
                    "last_login_ip": None,
                },
            }
        logger.opt(exception=True).error(
            "WebApp security_events error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to load security events")


# ====================================================================
# PROACTIVITY FEED — proactive alerts & insights for the webapp
# ====================================================================

# Whitelist of columns the user may update via PUT /proactivity/preferences
_PROACTIVITY_PREF_WHITELIST = frozenset({
    "proactive_enabled",
    "notify_weather",
    "notify_traffic",
    "notify_reminders",
})

# Defaults returned when no row exists yet
_PROACTIVITY_PREF_DEFAULTS = {
    "proactive_enabled": True,
    "notify_weather": True,
    "notify_traffic": True,
    "notify_reminders": True,
}


@router.get("/proactivity/feed")
async def proactivity_feed(
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(verify_webapp_user),
):
    """List proactive alerts / insights for the authenticated user.

    Optional query params:
    - ``unread_only``: if True, return only unread items.
    - ``limit`` / ``offset``: pagination.
    """
    db = _get_db()

    try:
        query = (
            db.table("proactivity_feed")
            .select("id, type, title, message, metadata, is_read, created_at, read_at")
            .eq("user_id", user_id)
        )

        if unread_only:
            query = query.eq("is_read", False)

        result = (
            query
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        items = result.data or []

        # Count total unread for badge
        unread_result = (
            db.table("proactivity_feed")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("is_read", False)
            .execute()
        )
        unread_count = unread_result.count or 0

        logger.info(
            f"WebApp: user={user_id[:8]} proactivity/feed"
            f" items={len(items)} unread={unread_count}"
        )
        return {
            "items": items,
            "unread_count": unread_count,
            "has_more": len(items) == limit,
        }

    except Exception as e:
        err_str = str(e)
        if "PGRST205" in err_str or "schema cache" in err_str:
            logger.warning(
                "proactivity_feed table not in schema cache — "
                "run migration 006_create_proactivity_feed.sql in Supabase."
            )
            return {"items": [], "unread_count": 0, "has_more": False}
        logger.error(
            f"WebApp proactivity/feed error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to load proactivity feed"
        )


@router.patch("/proactivity/feed/{item_id}/read")
async def mark_feed_item_read(
    item_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Mark a single proactivity feed item as read."""
    db = _get_db()

    try:
        result = (
            db.table("proactivity_feed")
            .update({
                "is_read": True,
                "read_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Feed item not found")

        logger.info(
            f"WebApp: user={user_id[:8]} marked feed item {item_id[:8]} as read"
        )
        return {"ok": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp proactivity/feed read error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to mark feed item as read"
        )


@router.patch("/proactivity/feed/read-all")
async def mark_all_feed_read(
    user_id: str = Depends(verify_webapp_user),
):
    """Mark all proactivity feed items as read for the authenticated user."""
    db = _get_db()

    try:
        now = datetime.now(timezone.utc).isoformat()
        db.table("proactivity_feed").update({
            "is_read": True,
            "read_at": now,
        }).eq("user_id", user_id).eq("is_read", False).execute()

        logger.info(
            f"WebApp: user={user_id[:8]} marked all feed items as read"
        )
        return {"ok": True}

    except Exception as e:
        logger.error(
            f"WebApp proactivity/feed read-all error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to mark all feed items as read"
        )


@router.get("/proactivity/preferences")
async def get_proactivity_preferences(
    user_id: str = Depends(verify_webapp_user),
):
    """Return the user's proactivity preferences with defaults."""
    db = _get_db()

    try:
        fields = ", ".join(_PROACTIVITY_PREF_WHITELIST)
        result = (
            db.table("user_preferences")
            .select(fields)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

        prefs = result.data if result.data else {}
        # Merge with defaults so the frontend always gets every key
        merged = {**_PROACTIVITY_PREF_DEFAULTS, **{k: v for k, v in prefs.items() if v is not None}}

        logger.info(
            f"WebApp: user={user_id[:8]} proactivity/preferences"
            f" enabled={merged.get('proactive_enabled')}"
        )
        return merged

    except Exception as e:
        logger.error(
            f"WebApp proactivity/preferences GET error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        # Graceful fallback — never block the frontend
        return _PROACTIVITY_PREF_DEFAULTS.copy()


class ProactivityPreferencesUpdate(BaseModel):
    """Payload for PUT /proactivity/preferences."""

    proactive_enabled: Optional[bool] = None
    notify_weather: Optional[bool] = None
    notify_traffic: Optional[bool] = None
    notify_reminders: Optional[bool] = None


@router.put("/proactivity/preferences")
async def update_proactivity_preferences(
    body: ProactivityPreferencesUpdate,
    user_id: str = Depends(verify_webapp_user),
):
    """Update the user's proactivity preferences.

    Only whitelisted fields are accepted; unknown keys are silently dropped.
    """
    db = _get_db()

    # Build update dict — only include non-None fields from whitelist
    update_data = {
        k: v
        for k, v in body.model_dump(exclude_none=True).items()
        if k in _PROACTIVITY_PREF_WHITELIST
    }

    if not update_data:
        raise HTTPException(
            status_code=422,
            detail="No valid preference fields provided",
        )

    try:
        result = (
            db.table("user_preferences")
            .upsert(
                {"user_id": user_id, **update_data},
                on_conflict="user_id",
            )
            .execute()
        )

        saved = result.data[0] if result.data else update_data

        logger.info(
            f"WebApp: user={user_id[:8]} proactivity/preferences updated"
            f" fields={list(update_data.keys())}"
        )
        return {
            k: saved.get(k, _PROACTIVITY_PREF_DEFAULTS.get(k))
            for k in _PROACTIVITY_PREF_WHITELIST
        }

    except Exception as e:
        logger.error(
            f"WebApp proactivity/preferences PUT error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to update proactivity preferences"
        )


# ====================================================================
# MARKETPLACE — integration catalog, status & disconnect
# ====================================================================

_INTEGRATIONS_CATALOG = [
    {
        "id": "google_calendar",
        "name": "Google Calendar",
        "description": "Gerencie sua agenda, crie eventos e receba lembretes",
        "category": "productivity",
        "icon": "calendar",
        "requires_oauth": True,
        "provider": "google",
        "available_plans": ["me", "everywhere"],
    },
    {
        "id": "spotify",
        "name": "Spotify",
        "description": "Controle sua música, descubra playlists e artistas",
        "category": "entertainment",
        "icon": "music",
        "requires_oauth": True,
        "provider": "spotify",
        "available_plans": ["me", "everywhere"],
    },
    {
        "id": "smartcar",
        "name": "Smartcar",
        "description": "Monitore e controle seu veículo conectado",
        "category": "automotive",
        "icon": "car",
        "requires_oauth": True,
        "provider": "smartcar",
        "available_plans": ["everywhere"],
    },
    {
        "id": "tuya",
        "name": "Smart Home (Tuya)",
        "description": "Control lights, plugs, sensors, thermostats and more",
        "category": "home",
        "icon": "home",
        "requires_oauth": True,
        "provider": "tuya",
        "available_plans": ["me", "everywhere"],
    },
    {
        "id": "github",
        "name": "GitHub",
        "description": "Gerencie repositórios, issues e pull requests",
        "category": "development",
        "icon": "code",
        "requires_oauth": True,
        "provider": "github",
        "available_plans": ["me", "everywhere"],
    },
    {
        "id": "telegram",
        "name": "Telegram Bot",
        "description": "Acesse o CAPIVAREX diretamente pelo Telegram",
        "category": "messaging",
        "icon": "message",
        "requires_oauth": False,
        "provider": "telegram",
        "available_plans": ["free", "me", "everywhere"],
    },
    {
        "id": "twilio_voice",
        "name": "Chamadas de Voz",
        "description": "Faça e receba chamadas telefônicas com o CAPIVAREX",
        "category": "communication",
        "icon": "phone",
        "requires_oauth": False,
        "provider": "twilio",
        "available_plans": ["everywhere"],
    },
]


@router.get("/market/integrations")
async def list_integrations(
    category: Optional[str] = Query(None),
    user_id: str = Depends(verify_webapp_user),
):
    """Lista todas as integrações disponíveis com status de conexão do usuário."""
    db = _get_db()

    try:
        # Buscar tokens OAuth ativos do usuário
        tokens_result = (
            db.table("user_oauth_tokens")
            .select("provider, expires_at")
            .eq("user_id", user_id)
            .execute()
        )
        connected_providers = {
            t["provider"] for t in (tokens_result.data or [])
        }

        # Buscar plano do usuário
        user_result = (
            db.table("users")
            .select("plan")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        user_plan = (
            user_result.data[0].get("plan", "free")
            if user_result.data
            else "free"
        )

        # Montar resposta com status de conexão
        integrations = []
        for integration in _INTEGRATIONS_CATALOG:
            if category and integration["category"] != category:
                continue

            is_connected = integration["provider"] in connected_providers
            is_available = user_plan in integration["available_plans"]

            integrations.append({
                **integration,
                "connected": is_connected,
                "is_connected": is_connected,
                "is_available": is_available,
                "upgrade_required": not is_available,
            })

        logger.info(
            f"WebApp: user={user_id[:8]} market/integrations"
            f" total={len(integrations)} connected={len(connected_providers)}"
            f" plan={user_plan}"
        )
        return {"integrations": integrations, "user_plan": user_plan}

    except Exception as e:
        logger.error(
            f"WebApp market/integrations error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to list integrations"
        )


@router.get("/market/integrations/{integration_id}/status")
async def get_integration_status(
    integration_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Retorna o status de conexão de uma integração específica."""
    db = _get_db()

    try:
        integration = next(
            (i for i in _INTEGRATIONS_CATALOG if i["id"] == integration_id),
            None,
        )
        if not integration:
            raise HTTPException(
                status_code=404, detail="Integration not found"
            )

        token_result = (
            db.table("user_oauth_tokens")
            .select("provider, expires_at, created_at")
            .eq("user_id", user_id)
            .eq("provider", integration["provider"])
            .execute()
        )

        is_connected = bool(token_result.data)
        token_data = token_result.data[0] if is_connected else None

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" market/integrations/{integration_id}/status"
            f" connected={is_connected}"
        )
        return {
            "integration_id": integration_id,
            "is_connected": is_connected,
            "provider": integration["provider"],
            "connected_at": (
                token_data.get("created_at") if token_data else None
            ),
            "expires_at": (
                token_data.get("expires_at") if token_data else None
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp market/integrations status error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to get integration status"
        )


@router.delete("/market/integrations/{integration_id}/disconnect")
async def disconnect_integration(
    integration_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Desconecta (remove tokens de) uma integração."""
    db = _get_db()

    try:
        integration = next(
            (i for i in _INTEGRATIONS_CATALOG if i["id"] == integration_id),
            None,
        )
        if not integration:
            raise HTTPException(
                status_code=404, detail="Integration not found"
            )

        db.table("user_oauth_tokens").delete().eq(
            "user_id", user_id
        ).eq("provider", integration["provider"]).execute()

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" disconnected integration {integration_id}"
        )
        return {
            "success": True,
            "integration_id": integration_id,
            "is_connected": False,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp market disconnect error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to disconnect integration"
        )


# ====================================================================
# VOICE CALLS — initiate, history, status
# ====================================================================


class InitiateCallRequest(BaseModel):
    """Payload para iniciar uma chamada de voz via Twilio."""

    phone_number: str
    message: str = "Olá! Aqui é o CAPIVAREX. Como posso ajudar?"




@router.post("/calls/initiate")
async def initiate_call(
    body: InitiateCallRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Inicia uma chamada de voz via Twilio."""
    db = _get_db()

    try:
        # Verificar se o usuário tem plano que suporta chamadas
        user_result = (
            db.table("users")
            .select("plan, phone_number")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        user_data = (
            user_result.data[0] if user_result.data else {}
        )
        user_plan = user_data.get("plan", "free")

        if user_plan not in ("everywhere",):
            raise HTTPException(
                status_code=403,
                detail="Voice calls require the Everywhere plan",
            )

        # Tentar iniciar via serviço Twilio existente
        call_sid = ""
        try:
            twilio_svc = get_service("twilio")
            if twilio_svc:
                twiml = (
                    f"<Response><Say voice='alice'"
                    f" language='pt-BR'>{body.message}</Say></Response>"
                )
                call_result = await twilio_svc.make_call(
                    tenant_id=user_id,
                    to_number=body.phone_number,
                    twiml_or_url=twiml,
                )
                call_sid = call_result.get("call_sid", "")
        except Exception as twilio_err:
            logger.warning(
                "Twilio service error (falling back to mock): %s",
                twilio_err,
            )
            call_sid = f"mock_{user_id[:8]}"

        if not call_sid:
            call_sid = f"mock_{user_id[:8]}"

        # Salvar log da chamada
        log_result = (
            db.table("call_logs")
            .insert(
                {
                    "user_id": user_id,
                    "phone_number": body.phone_number,
                    "status": "initiated",
                    "twilio_call_sid": call_sid,
                }
            )
            .execute()
        )
        call_id = (
            log_result.data[0]["id"] if log_result.data else None
        )

        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" calls/initiate to={body.phone_number}"
            f" sid={call_sid}"
        )
        return {
            "success": True,
            "call_id": call_id,
            "call_sid": call_sid,
            "status": "initiated",
            "phone_number": body.phone_number,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp calls/initiate error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to initiate call"
        )


@router.get("/calls/history")
async def get_call_history(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(verify_webapp_user),
):
    """Retorna o histórico de chamadas do usuário."""
    db = _get_db()

    try:
        result = (
            db.table("call_logs")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        calls = result.data or []
        logger.info(
            f"WebApp: user={user_id[:8]}"
            f" calls/history total={len(calls)}"
        )
        return {"calls": calls, "total": len(calls)}

    except Exception as e:
        err_str = str(e)
        if "PGRST205" in err_str or "schema cache" in err_str:
            logger.warning(
                "call_logs table not in schema cache (PGRST205) — "
                "ensure the call_logs table exists in Supabase."
            )
            return {"calls": [], "total": 0}
        logger.error(
            f"WebApp calls/history error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch call history"
        )


@router.get("/calls/{call_id}/status")
async def get_call_status(
    call_id: str,
    user_id: str = Depends(verify_webapp_user),
):
    """Retorna o status atual de uma chamada."""
    db = _get_db()

    try:
        result = (
            db.table("call_logs")
            .select("*")
            .eq("id", call_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404, detail="Call not found"
            )

        return result.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"WebApp calls/status error: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch call status"
        )
