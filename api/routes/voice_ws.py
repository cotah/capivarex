# -*- coding: utf-8 -*-
"""
Voice WebSocket Route
=====================
Endpoint WebSocket para pipeline completo de voz em tempo real.
Fluxo: áudio binário → STT (Whisper) → LLM (orquestrador) → TTS (ElevenLabs) → áudio base64
"""

from __future__ import annotations

import base64
import json
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
    token: str = "",
    conversation_id: str = "",
) -> None:
    """
    WebSocket de voz em tempo real.

    Auth: Token can be provided via:
    1. Query param: ?token=xxx (legacy, less secure)
    2. First JSON message: {"type": "auth", "token": "xxx"} (preferred, secure)

    Protocolo:
    - Cliente envia: bytes de áudio (webm/mp4/wav)
    - Servidor responde com JSON:
      { "type": "transcription", "text": "..." }
      { "type": "response", "text": "...", "response_type": "...", "data": {...}, "conversation_title": "..." }
      { "type": "audio", "audio_base64": "...", "content_type": "audio/mpeg" }
      { "type": "error", "message": "..." }
    """
    await websocket.accept()

    # Helper — must be defined right after accept() so it's available everywhere
    async def _safe_send(data: dict) -> bool:
        """Send JSON to the client, returning False if the connection is closed."""
        try:
            await websocket.send_json(data)
            return True
        except (WebSocketDisconnect, RuntimeError, Exception):
            return False

    # ── If no token in URL, wait for auth message ────────────────────────
    if not token:
        try:
            import asyncio

            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            auth_msg = json.loads(raw)
            if auth_msg.get("type") == "auth":
                token = auth_msg.get("token", "")
                conversation_id = (
                    auth_msg.get("conversation_id", conversation_id) or conversation_id
                )
            if not token:
                await _safe_send({"type": "error", "message": "Auth required"})
                await websocket.close(code=1008)
                return
        except Exception:
            await _safe_send({"type": "error", "message": "Auth timeout"})
            await websocket.close(code=1008)
            return

    # ── Init (auth + DB + services) — wrapped in try/except ──────────────
    try:
        from api.middleware.webapp_auth import SUPABASE_PUBLIC_KEY

        jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "")

        strategies: list[tuple[str, dict]] = []
        if SUPABASE_PUBLIC_KEY:
            strategies.append(
                (
                    "es256",
                    {
                        "key": SUPABASE_PUBLIC_KEY,
                        "algorithms": ["ES256"],
                        "options": {"verify_aud": False},
                    },
                )
            )
        if jwt_secret:
            strategies.append(
                (
                    "hs256_aud",
                    {
                        "key": jwt_secret,
                        "algorithms": ["HS256"],
                        "audience": "authenticated",
                    },
                )
            )
            strategies.append(
                (
                    "hs256_noaud",
                    {
                        "key": jwt_secret,
                        "algorithms": ["HS256"],
                        "options": {"verify_aud": False},
                    },
                )
            )

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
            await _safe_send({"type": "error", "message": "Invalid token"})
            await websocket.close(code=1008)
            return

        sub_value: str = payload["sub"]

        db = _get_db()

        # Supabase tokens: sub = user UUID.  Legacy tokens: sub = email.
        import uuid as _uuid

        try:
            _uuid.UUID(sub_value)
            user_resp = (
                db.table("users")
                .select("id, plan, email")
                .eq("id", sub_value)
                .execute()
            )
        except (ValueError, AttributeError):
            user_resp = (
                db.table("users")
                .select("id, plan, email")
                .eq("email", sub_value)
                .execute()
            )

        if not user_resp.data:
            await _safe_send({"type": "error", "message": "User not found"})
            await websocket.close(code=1008)
            return

        user = user_resp.data[0]
        user_id = str(user["id"])
        user_plan = user.get("plan", "professional")

        # ── Verify conversation belongs to user ──────────────────────────
        conv_resp = (
            db.table("webapp_conversations")
            .select("id")
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not conv_resp.data:
            await _safe_send({"type": "error", "message": "Conversation not found"})
            await websocket.close(code=1008)
            return

        # ── Services ─────────────────────────────────────────────────────
        stt_service = get_service("whisper")
        tts_service = get_service("openai_tts")  # OpenAI TTS — cheaper than ElevenLabs
        redis_svc = get_service("redis")
        orchestrator = get_agent("orchestrator")

        if not stt_service:
            await _safe_send({"type": "error", "message": "STT service not available"})
            await websocket.close(code=1011)
            return

        if not stt_service.is_initialized():
            await stt_service.initialize()
        if tts_service and not tts_service.is_initialized():
            await tts_service.initialize()
        if redis_svc and not redis_svc.is_initialized():
            await redis_svc.initialize()

    except (WebSocketDisconnect, RuntimeError):
        logger.info("VoiceWS: client disconnected during init")
        return
    except Exception as init_err:
        logger.error("VoiceWS: init failed: {}", init_err)
        await _safe_send({"type": "error", "message": "Initialization failed"})
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return

    logger.info(
        "VoiceWS: user={} conv={} connected, stt={}, tts={}",
        user_id[:8],
        conversation_id[:8],
        stt_service.is_initialized(),
        tts_service.is_initialized() if tts_service else False,
    )

    # ── Main loop ────────────────────────────────────────────────────────

    try:
        while True:
            # Receive audio bytes from client
            audio_bytes = await websocket.receive_bytes()

            if not audio_bytes or len(audio_bytes) < 500:
                await _safe_send({"type": "error", "message": "Audio too short"})
                continue

            logger.info("VoiceWS [{}]: received {} bytes of audio", user_id[:8], len(audio_bytes))

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
                logger.warning("VoiceWS [{}]: STT returned empty transcript", user_id[:8])
                await _safe_send(
                    {"type": "error", "message": "Could not transcribe audio"}
                )
                continue

            logger.info("VoiceWS [{}]: STT → '{}'", user_id[:8], transcript[:80])
            await _safe_send({"type": "transcription", "text": transcript})

            # ── Context ──────────────────────────────────────────────────────
            conversation_context: List[Dict[str, Any]] = []
            try:
                conversation_context = (
                    await redis_svc.get_conversation_context(user_id=user_id, last_n=10)
                    or []
                )
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
                db.table("webapp_messages").insert(
                    {
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "role": "user",
                        "text": transcript,
                        "source": "voice",
                    }
                ).execute()
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

                # Build voice-aware context for the agent
                # The "source": "voice" flag triggers the dedicated voice prompt
                # in chat_agent.py (get_voice_chat_prompt instead of get_chat_prompt)
                voice_context = {
                    "history": history,
                    "user_plan": user_plan,
                    "source": "voice",
                }

                # Call target agent directly (not ChatService — it sends
                # "token" messages that break the voice WebSocket protocol)
                target_agent = get_agent(action) or get_agent("chat")
                agent_result = await target_agent.execute(
                    transcript, voice_context
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
                await _safe_send({"type": "error", "message": "No response generated"})
                continue

            logger.info(
                "VoiceWS [{}]: LLM → {} chars",
                user_id[:8], len(response_text),
            )

            # Save assistant message
            try:
                db.table("webapp_messages").insert(
                    {
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "role": "assistant",
                        "text": response_text,
                        "source": "voice",
                    }
                ).execute()
            except Exception as db_err:
                logger.warning("VoiceWS: failed to save assistant msg: {}", db_err)

            # Send text response
            agent_data = (
                getattr(agent_result, "data", None) if "agent_result" in dir() else None
            )
            await _safe_send(
                {
                    "type": "response",
                    "text": response_text,
                    "response_type": "text",
                    "data": agent_data if isinstance(agent_data, dict) else None,
                    "conversation_title": None,
                }
            )

            # ── TTS ──────────────────────────────────────────────────────────
            try:
                if tts_service:
                    # Auto-initialize if needed (e.g. lazy startup)
                    if not tts_service.is_initialized():
                        logger.info("VoiceWS [{}]: initializing TTS service...", user_id[:8])
                        await tts_service.initialize()

                    logger.info("VoiceWS [{}]: calling TTS for {} chars...", user_id[:8], len(response_text[:4096]))
                    tts_audio = await tts_service.text_to_speech(
                        text=response_text[:4096],
                    )
                    if tts_audio:
                        audio_b64 = base64.b64encode(tts_audio).decode()
                        logger.info(
                            "VoiceWS [{}]: TTS OK → {} bytes audio, sending to client",
                            user_id[:8], len(tts_audio),
                        )
                        await _safe_send(
                            {
                                "type": "audio",
                                "audio_base64": audio_b64,
                                "content_type": "audio/mpeg",
                            }
                        )
                    else:
                        logger.warning("VoiceWS [{}]: TTS returned empty audio!", user_id[:8])
                else:
                    logger.warning("VoiceWS [{}]: no TTS service available — voice disabled", user_id[:8])
            except Exception as e:
                logger.error("VoiceWS [{}]: TTS FAILED: {}", user_id[:8], e, exc_info=True)

            # ── Background: memory + personal info extraction ────────────
            from utils.safe_task import safe_create_task as _safe_task

            try:
                from services.business.rag_service import extract_and_save_memory

                _safe_task(
                    extract_and_save_memory(user_id, transcript),
                    name="voice_rag_memory",
                )
            except Exception:
                pass
            try:
                from services.business.user_profile_service import (
                    extract_and_save_personal_info,
                )

                _safe_task(
                    extract_and_save_personal_info(user_id, transcript),
                    name="voice_personal_info",
                )
            except Exception:
                pass

            # Redis: cache conversation context
            try:
                if redis_svc and redis_svc.is_initialized():
                    _safe_task(
                        redis_svc.save_conversation_message(
                            user_id, {"role": "user", "content": transcript}
                        ),
                        name="voice_redis_user",
                    )
                    _safe_task(
                        redis_svc.save_conversation_message(
                            user_id, {"role": "assistant", "content": response_text}
                        ),
                        name="voice_redis_assistant",
                    )
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.info("VoiceWS: user={} disconnected", user_id[:8])
    except RuntimeError as e:
        # Starlette throws RuntimeError("WebSocket is not connected") when
        # receive_bytes() is called on a WS that the client already closed.
        # This is normal — NOT an error. Just log and exit.
        if "not connected" in str(e).lower() or "accept" in str(e).lower():
            logger.info("VoiceWS: user={} connection lost (RuntimeError)", user_id[:8])
        else:
            logger.opt(exception=True).error(
                "VoiceWS error for user={}: {}", user_id[:8], e
            )
            await _safe_send({"type": "error", "message": "Internal server error"})
    except Exception as e:
        logger.opt(exception=True).error(
            "VoiceWS error for user={}: {}", user_id[:8], e
        )
        await _safe_send({"type": "error", "message": "Internal server error"})
