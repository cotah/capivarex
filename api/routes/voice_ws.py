# -*- coding: utf-8 -*-
"""
Voice WebSocket Route
=====================
Endpoint WebSocket para pipeline completo de voz em tempo real.
Fluxo: áudio binário → STT (Whisper) → LLM (orquestrador) → TTS (ElevenLabs) → áudio base64
"""
from __future__ import annotations

import base64
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List

import jwt

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agents import get_agent
from api.routes._helpers import _get_db
from services.core import get_service

from loguru import logger

router_voice_ws = APIRouter(tags=["Voice WebSocket"])

_AUDIO_TEMP_DIR = Path(tempfile.gettempdir()) / "capivarex_voice_ws"
_AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)


@router_voice_ws.websocket("/voice/ws")
async def voice_websocket(
    websocket: WebSocket,
    token: str,
    conversation_id: str,
) -> None:
    """
    WebSocket de voz em tempo real.

    Protocolo:
    - Cliente envia: bytes de áudio (webm/mp4/wav)
    - Servidor responde com JSON:
      { "type": "transcription", "text": "..." }
      { "type": "response", "text": "...", "response_type": "...", "data": {...}, "conversation_title": "..." }
      { "type": "audio", "audio_base64": "...", "content_type": "audio/mpeg" }
      { "type": "error", "message": "..." }
    """
    await websocket.accept()

    # ── Auth — same multi-strategy as webapp_auth.verify_webapp_user ──────────
    from api.middleware.webapp_auth import SUPABASE_PUBLIC_KEY

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "")

    strategies: list[tuple[str, dict]] = []
    if SUPABASE_PUBLIC_KEY:
        strategies.append(("es256", {
            "key": SUPABASE_PUBLIC_KEY,
            "algorithms": ["ES256"],
            "options": {"verify_aud": False},
        }))
    if jwt_secret:
        strategies.append(("hs256_aud", {
            "key": jwt_secret,
            "algorithms": ["HS256"],
            "audience": "authenticated",
        }))
        strategies.append(("hs256_noaud", {
            "key": jwt_secret,
            "algorithms": ["HS256"],
            "options": {"verify_aud": False},
        }))

    payload = None
    for strat_name, kwargs in strategies:
        try:
            payload = jwt.decode(token, **kwargs)
            if payload.get("sub"):
                break
            payload = None
        except Exception:
            payload = None
            continue

    if not payload or not payload.get("sub"):
        await websocket.send_json({"type": "error", "message": "Invalid token"})
        await websocket.close(code=1008)
        return

    sub_value: str = payload["sub"]

    db = _get_db()

    # Supabase tokens: sub = user UUID.  Legacy tokens: sub = email.
    import uuid as _uuid
    try:
        _uuid.UUID(sub_value)
        user_resp = db.table("users").select("id, plan, email").eq("id", sub_value).execute()
    except (ValueError, AttributeError):
        user_resp = db.table("users").select("id, plan, email").eq("email", sub_value).execute()

    if not user_resp.data:
        await websocket.send_json({"type": "error", "message": "User not found"})
        await websocket.close(code=1008)
        return

    user = user_resp.data[0]
    user_id = str(user["id"])
    user_plan = user.get("plan", "free")

    # ── Verify conversation belongs to user ──────────────────────────────────
    conv_resp = (
        db.table("webapp_conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not conv_resp.data:
        await websocket.send_json({"type": "error", "message": "Conversation not found"})
        await websocket.close(code=1008)
        return

    # ── Services ─────────────────────────────────────────────────────────────
    stt_service = get_service("whisper")
    tts_service = get_service("elevenlabs")
    redis_svc = get_service("redis")
    orchestrator = get_agent("orchestrator")

    if not stt_service:
        await websocket.send_json({"type": "error", "message": "STT service not available"})
        await websocket.close(code=1011)
        return

    # Initialize services if needed (lazy-loaded)
    try:
        if not stt_service.is_initialized():
            await stt_service.initialize()
        if tts_service and not tts_service.is_initialized():
            await tts_service.initialize()
        if redis_svc and not redis_svc.is_initialized():
            await redis_svc.initialize()
    except Exception as init_err:
        logger.error("VoiceWS: service init failed: {}", init_err)
        await websocket.send_json({"type": "error", "message": "Service initialization failed"})
        await websocket.close(code=1011)
        return

    logger.info("VoiceWS: user={} conv={} connected, stt={}, tts={}",
                user_id[:8], conversation_id[:8],
                stt_service.is_initialized(), tts_service.is_initialized() if tts_service else False)

    try:
        while True:
            # Receive audio bytes from client
            audio_bytes = await websocket.receive_bytes()

            if not audio_bytes or len(audio_bytes) < 500:
                await websocket.send_json({"type": "error", "message": "Audio too short"})
                continue

            # ── STT ──────────────────────────────────────────────────────────
            tmp_path = _AUDIO_TEMP_DIR / f"{uuid.uuid4()}.webm"
            try:
                tmp_path.write_bytes(audio_bytes)
                stt_result = await stt_service.speech_to_text(
                    audio_file_path=str(tmp_path),
                    language="pt",
                )
                transcript = (stt_result.get("text") or "").strip()
            finally:
                tmp_path.unlink(missing_ok=True)

            if not transcript:
                await websocket.send_json({"type": "error", "message": "Could not transcribe audio"})
                continue

            await websocket.send_json({"type": "transcription", "text": transcript})

            # ── Context ──────────────────────────────────────────────────────
            conversation_context: List[Dict[str, Any]] = []
            try:
                conversation_context = await redis_svc.get_conversation_context(
                    user_id=user_id, last_n=10
                ) or []
            except Exception:
                pass

            if not conversation_context:
                hist_resp = (
                    db.table("webapp_messages")
                    .select("role, text, created_at")
                    .eq("conversation_id", conversation_id)
                    .order("created_at", desc=False)
                    .limit(20)
                    .execute()
                )
                conversation_context = [
                    {"role": m["role"], "content": m["text"]}
                    for m in (hist_resp.data or [])
                ]

            # Save user message
            try:
                db.table("webapp_messages").insert({
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "role": "user",
                    "text": transcript,
                    "source": "voice",
                }).execute()
            except Exception as db_err:
                logger.warning("VoiceWS: failed to save user msg: {}", db_err)

            # ── LLM ──────────────────────────────────────────────────────────
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in conversation_context
                if m.get("role") and m.get("content")
            ]
            history.append({"role": "user", "content": transcript})
            history = history[-10:]

            try:
                # Route via orchestrator
                orchestrator_resp = await orchestrator.execute(
                    transcript, {"history": history, "user_plan": user_plan}
                )
                action = (
                    orchestrator_resp.response
                    if hasattr(orchestrator_resp, "response")
                    else str(orchestrator_resp)
                )

                # Call target agent directly (not ChatService — it sends
                # "token" messages that break the voice WebSocket protocol)
                target_agent = get_agent(action) or get_agent("chat")
                agent_result = await target_agent.execute(
                    transcript, {"history": history, "user_plan": user_plan}
                )
                response_text = (
                    agent_result.response
                    if hasattr(agent_result, "response") and agent_result.response
                    else str(agent_result)
                )
            except Exception as llm_err:
                logger.error("VoiceWS LLM error: {}", llm_err)
                response_text = "Desculpa, houve um erro ao processar sua mensagem."

            if not response_text:
                await websocket.send_json({"type": "error", "message": "No response generated"})
                continue

            # Save assistant message
            try:
                db.table("webapp_messages").insert({
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "role": "assistant",
                    "text": response_text,
                    "source": "voice",
                }).execute()
            except Exception as db_err:
                logger.warning("VoiceWS: failed to save assistant msg: {}", db_err)

            # Send text response
            agent_data = getattr(agent_result, 'data', None) if 'agent_result' in dir() else None
            await websocket.send_json({
                "type": "response",
                "text": response_text,
                "response_type": "text",
                "data": agent_data if isinstance(agent_data, dict) else None,
                "conversation_title": None,
            })

            # ── TTS ──────────────────────────────────────────────────────────
            try:
                if tts_service and tts_service.is_initialized():
                    audio_bytes = await tts_service.text_to_speech(
                        text=response_text[:1000],
                    )
                    if audio_bytes:
                        audio_b64 = base64.b64encode(audio_bytes).decode()
                        await websocket.send_json({
                            "type": "audio",
                            "audio_base64": audio_b64,
                        "content_type": "audio/mpeg",
                    })
            except Exception as e:
                logger.warning("VoiceWS TTS failed for user={}: {}", user_id[:8], e)
                # TTS failure is non-fatal — text response already sent

    except WebSocketDisconnect:
        logger.info("VoiceWS: user={} disconnected", user_id[:8])
    except Exception as e:
        logger.opt(exception=True).error("VoiceWS error for user={}: {}", user_id[:8], e)
        try:
            await websocket.send_json({"type": "error", "message": "Internal server error"})
        except Exception:
            pass
