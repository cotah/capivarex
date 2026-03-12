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
from typing import Any, Dict, List, Optional

import jwt
from jwt.exceptions import PyJWTError

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agents import get_agent
from api.routes._helpers import _get_db
from services.business.chat_service import ChatService
from services.core import get_service

from loguru import logger

router_voice_ws = APIRouter(tags=["Voice WebSocket"])

SECRET_KEY = os.environ.get("SECRET_KEY", "")
ALGORITHM = os.environ.get("ALGORITHM", "HS256")

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

    # ── Auth ──────────────────────────────────────────────────────────────────
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        if not email:
            await websocket.send_json({"type": "error", "message": "Invalid token"})
            await websocket.close(code=1008)
            return
    except PyJWTError:
        await websocket.send_json({"type": "error", "message": "Invalid token"})
        await websocket.close(code=1008)
        return

    db = _get_db()
    user_resp = db.table("users").select("id, plan, email").eq("email", email).execute()
    if not user_resp.data:
        await websocket.send_json({"type": "error", "message": "User not found"})
        await websocket.close(code=1008)
        return

    user = user_resp.data[0]
    user_id = str(user["id"])
    user_plan = user.get("plan", "free")

    # ── Verify conversation belongs to user ──────────────────────────────────
    conv_resp = (
        db.table("conversations")
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
    stt_service = get_service("speech_to_text")
    tts_service = get_service("text_to_speech")
    redis_svc = get_service("redis")
    orchestrator = get_agent("orchestrator")

    logger.info("VoiceWS: user={} conv={} connected", user_id[:8], conversation_id[:8])

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
                stt_result = await stt_service.transcribe(
                    audio_path=str(tmp_path),
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
                    db.table("messages")
                    .select("role, content, created_at")
                    .eq("conversation_id", conversation_id)
                    .order("created_at", desc=False)
                    .limit(20)
                    .execute()
                )
                conversation_context = [
                    {"role": m["role"], "content": m["content"]}
                    for m in (hist_resp.data or [])
                ]

            # Save user message
            db.table("messages").insert({
                "conversation_id": conversation_id,
                "role": "user",
                "content": transcript,
            }).execute()

            # ── LLM ──────────────────────────────────────────────────────────
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in conversation_context
                if m.get("role") and m.get("content")
            ]
            history.append({"role": "user", "content": transcript})
            history = history[-10:]

            orchestrator_resp = await orchestrator.execute(
                transcript, {"history": history, "user_plan": user_plan}
            )
            action = (
                orchestrator_resp.response
                if hasattr(orchestrator_resp, "response")
                else str(orchestrator_resp)
            )
            valid_actions = {
                "chat", "search", "dev", "image", "video", "finance",
                "weather", "calendar", "traffic", "car", "voice",
            }
            if action not in valid_actions:
                action = "chat"

            chat_service = ChatService(
                websocket=websocket,
                user_id=user_id,
                user_plan=user_plan,
            )
            full_response = await chat_service.dispatch(
                action, transcript, {"action": action}, history
            )

            response_text = (
                full_response.get("text") or full_response.get("response") or ""
                if isinstance(full_response, dict)
                else str(full_response)
            )

            if not response_text:
                await websocket.send_json({"type": "error", "message": "No response generated"})
                continue

            # Save assistant message
            db.table("messages").insert({
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": response_text,
            }).execute()

            # Send text response
            await websocket.send_json({
                "type": "response",
                "text": response_text,
                "response_type": full_response.get("type", "text") if isinstance(full_response, dict) else "text",
                "data": full_response.get("data") if isinstance(full_response, dict) else None,
                "conversation_title": full_response.get("conversation_title") if isinstance(full_response, dict) else None,
            })

            # ── TTS ──────────────────────────────────────────────────────────
            try:
                tts_result = await tts_service.synthesize(
                    text=response_text[:1000],
                    voice="rachel",
                    language="pt",
                )
                if tts_result and tts_result.get("audio_data"):
                    audio_b64 = base64.b64encode(tts_result["audio_data"]).decode()
                    await websocket.send_json({
                        "type": "audio",
                        "audio_base64": audio_b64,
                        "content_type": tts_result.get("content_type", "audio/mpeg"),
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
