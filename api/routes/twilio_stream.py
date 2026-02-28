"""
api/routes/twilio_stream.py
=============================
WebSocket endpoint for Twilio Media Streams.

Receives real-time audio from phone calls, processes through
STT -> GPT -> TTS pipeline, and sends audio responses back.

Protocol (Twilio Media Streams):
- Twilio sends JSON messages over WebSocket
- Events: "connected", "start", "media", "stop"
- Audio format: mulaw, 8000 Hz, mono, base64-encoded
- We send back: {"event":"media","streamSid":"...","media":{"payload":"base64..."}}

Lifecycle:
    1. Twilio opens WebSocket after person answers
    2. "connected" -> log
    3. "start" -> get session_id from params, load CallSession, send greeting
    4. "media" -> accumulate audio, VAD, when silence -> process pipeline
    5. "stop" -> finalize session, send report to Telegram
"""

import asyncio
import base64
import json
import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio-stream"])

# Temp directory for Whisper audio files
_AUDIO_TMP = Path(tempfile.gettempdir()) / "superbot_audio"
_AUDIO_TMP.mkdir(parents=True, exist_ok=True)


@router.websocket("/ws/twilio-stream")
async def twilio_media_stream(websocket: WebSocket):
    """
    Main WebSocket handler for Twilio Media Streams.

    Each connection = one phone call.
    """
    await websocket.accept()

    session = None
    stream_sid: Optional[str] = None
    call_sid: Optional[str] = None

    try:
        async for raw_message in websocket.iter_text():
            data = json.loads(raw_message)
            event = data.get("event")

            # -- CONNECTED ------------------------------------------------
            if event == "connected":
                logger.info(
                    "Twilio stream connected (protocol: %s)",
                    data.get("protocol"),
                )

            # -- START ----------------------------------------------------
            elif event == "start":
                start_data = data.get("start", {})
                stream_sid = start_data.get("streamSid")
                call_sid = start_data.get("callSid")

                custom_params = start_data.get(
                    "customParameters", {}
                )
                session_id = custom_params.get("session_id", "")

                logger.info(
                    "Call started: call_sid=%s stream_sid=%s "
                    "session_id=%s",
                    call_sid,
                    stream_sid,
                    session_id[:8] if session_id else "none",
                )

                session = await _load_session(
                    session_id, call_sid, stream_sid
                )

                if session is None:
                    logger.error(
                        "No session found for session_id=%s "
                        "— closing",
                        session_id[:8],
                    )
                    await _send_error_and_close(
                        websocket, stream_sid
                    )
                    break

                await _send_greeting(
                    websocket, session, stream_sid
                )

            # -- MEDIA ----------------------------------------------------
            elif event == "media":
                if session is None:
                    continue

                payload = (
                    data.get("media", {}).get("payload", "")
                )
                if not payload:
                    continue

                audio_bytes = base64.b64decode(payload)
                session.add_audio_chunk(audio_bytes)

                if session.should_process():
                    await _process_turn(
                        websocket, session, stream_sid
                    )

                    if session.should_end_call():
                        await _end_call(
                            websocket, session, stream_sid
                        )
                        break

            # -- STOP -----------------------------------------------------
            elif event == "stop":
                logger.info("Call stopped: %s", call_sid)
                if session:
                    if session.result.value == "unknown":
                        session.mark_hangup()
                    session.finalize()
                    await _send_telegram_report(session)
                break

    except WebSocketDisconnect:
        logger.info(
            "Twilio stream disconnected: call_sid=%s", call_sid
        )
        if session:
            if session.result.value == "unknown":
                session.mark_hangup()
            session.finalize()
            await _send_telegram_report(session)

    except Exception as e:
        logger.error(
            "Twilio stream error: %s", e, exc_info=True
        )
        if session:
            session.mark_failed(f"WebSocket error: {e}")
            session.finalize()
            await _send_telegram_report(session)


# =====================================================================
# INTERNAL FUNCTIONS
# =====================================================================


async def _load_session(
    session_id: str, call_sid: str, stream_sid: str
):
    """Load CallSession from pending registry."""
    from services.business.call_session import (
        CallSession,
        get_pending_call,
    )

    if not session_id:
        logger.error(
            "No session_id in Twilio stream start params"
        )
        return None

    pending = get_pending_call(session_id)
    if pending is None:
        return None

    session = CallSession.from_pending(pending)
    session.call_sid = call_sid
    session.stream_sid = stream_sid

    logger.info(
        "Session loaded: %s -> %s (objective: %s)",
        session.session_id[:8],
        session.phone_number,
        session.objective[:60],
    )

    return session


async def _send_greeting(
    websocket: WebSocket, session, stream_sid: str
):
    """Generate and send the initial greeting."""
    from services.ai.call_brain import CallBrain
    from services.business.call_session import CallStatus

    session.status = CallStatus.GREETING

    brain = CallBrain()
    greeting_resp = await brain.generate_greeting(
        objective=session.objective,
        user_name=session.user_name,
        language=session.language,
        key_details=session.extra_context,
        custom_greeting=session.greeting,
    )

    if greeting_resp.text:
        audio_sent = await _text_to_twilio_audio(
            websocket,
            stream_sid,
            greeting_resp.text,
            session.language,
        )
        session.add_assistant_turn(
            greeting_resp.text, audio_duration_s=audio_sent
        )
        session.record_tts_latency(greeting_resp.latency_s)

    session.status = CallStatus.LISTENING
    logger.info(
        "Greeting sent for session %s",
        session.session_id[:8],
    )


async def _process_turn(
    websocket: WebSocket, session, stream_sid: str
):
    """
    Full pipeline for one conversation turn:
    1. Get accumulated audio -> WAV
    2. STT (Whisper) -> text
    3. Brain (GPT) -> response text
    4. TTS (ElevenLabs) -> audio
    5. Send audio back to Twilio
    """
    from services.ai.call_brain import CallBrain
    from services.business.call_session import CallStatus

    session.status = CallStatus.PROCESSING

    # -- 1. Get audio -------------------------------------------------
    wav_bytes = session.get_audio_for_processing()
    if not wav_bytes:
        session.status = CallStatus.LISTENING
        return

    # -- 2. STT (Whisper) ---------------------------------------------
    stt_start = time.time()
    transcript = await _run_stt(wav_bytes, session.language)
    stt_latency = time.time() - stt_start
    session.record_stt_latency(stt_latency)

    if not transcript or transcript.strip() == "":
        logger.info(
            "Session %s: empty transcript, resuming listening",
            session.session_id[:8],
        )
        session.status = CallStatus.LISTENING
        return

    logger.info(
        'Session %s STT (%.2fs): "%s"',
        session.session_id[:8],
        stt_latency,
        transcript[:100],
    )

    session.add_user_turn(transcript)

    # -- 3. Brain (GPT) -----------------------------------------------
    brain = CallBrain()
    brain_resp = await brain.generate_response(
        objective=session.objective,
        user_name=session.user_name,
        language=session.language,
        key_details=session.extra_context,
        extra_context="",
        conversation_history=(
            session.get_conversation_history()[:-1]
        ),
        latest_speech=transcript,
    )

    session.record_llm_latency(brain_resp.latency_s)

    logger.info(
        'Session %s Brain (%.2fs): "%s" | complete=%s end=%s',
        session.session_id[:8],
        brain_resp.latency_s,
        brain_resp.text[:100],
        brain_resp.objective_complete,
        brain_resp.should_end_call,
    )

    # -- 4. TTS (ElevenLabs) + Send -----------------------------------
    if brain_resp.text:
        session.status = CallStatus.SPEAKING
        audio_duration = await _text_to_twilio_audio(
            websocket,
            stream_sid,
            brain_resp.text,
            session.language,
        )
        session.add_assistant_turn(
            brain_resp.text, audio_duration_s=audio_duration
        )

    # -- 5. Update session state --------------------------------------
    if brain_resp.objective_complete:
        session.mark_objective_complete(brain_resp.text)

    if brain_resp.should_end_call:
        return

    session.status = CallStatus.LISTENING


async def _end_call(
    websocket: WebSocket, session, stream_sid: str
):
    """Send goodbye and end the call."""
    from services.ai.call_brain import CallBrain

    # Generate goodbye
    brain = CallBrain()
    goodbye_resp = await brain.generate_goodbye(
        language=session.language,
        result=session.result.value,
        result_details=session.result_details,
    )

    if goodbye_resp.text:
        await _text_to_twilio_audio(
            websocket,
            stream_sid,
            goodbye_resp.text,
            session.language,
        )
        session.add_assistant_turn(goodbye_resp.text)

    # Finalize
    session.finalize()
    await _send_telegram_report(session)

    logger.info(
        "Call ended: session=%s result=%s duration=%.0fs "
        "turns=%d",
        session.session_id[:8],
        session.result.value,
        session.duration_s,
        session._turn_count,
    )


# =====================================================================
# STT / TTS / TWILIO AUDIO HELPERS
# =====================================================================


async def _run_stt(wav_bytes: bytes, language: str) -> str:
    """
    Run Whisper STT on WAV audio bytes.

    Saves to temp file (Whisper API requires a file), transcribes,
    deletes.

    Args:
        wav_bytes: WAV audio file bytes
        language: Language hint for Whisper

    Returns:
        Transcribed text (empty string on failure)
    """
    if not wav_bytes:
        return ""

    try:
        from services import get_service

        whisper_svc = get_service("whisper")
        if not whisper_svc:
            logger.error(
                "WhisperService not available for STT"
            )
            return ""

        if not whisper_svc.is_initialized():
            await whisper_svc.initialize()

        filename = f"stt_{uuid.uuid4().hex[:8]}.wav"
        filepath = _AUDIO_TMP / filename

        try:
            filepath.write_bytes(wav_bytes)

            result = await whisper_svc.speech_to_text(
                audio_file_path=str(filepath),
                language=language,
            )

            return result.get("text", "").strip()

        finally:
            if filepath.exists():
                filepath.unlink()

    except Exception as e:
        logger.error("STT failed: %s", e, exc_info=True)
        return ""


async def _text_to_twilio_audio(
    websocket: WebSocket,
    stream_sid: str,
    text: str,
    language: str,
) -> float:
    """
    Convert text to speech and send as audio to Twilio.

    Pipeline: text -> ElevenLabs (MP3) -> mulaw chunks -> Twilio WS

    Args:
        websocket: Active Twilio WebSocket
        stream_sid: Twilio stream SID
        text: Text to speak
        language: Language code (for voice selection)

    Returns:
        Audio duration in seconds
    """
    from services import get_service
    from services.voice_pipeline_service import DEFAULT_VOICES
    from utils.audio_converter import mp3_to_mulaw_chunks

    try:
        elevenlabs_svc = get_service("elevenlabs")
        if not elevenlabs_svc:
            logger.error(
                "ElevenLabsService not available for TTS"
            )
            return 0.0

        if not elevenlabs_svc.is_initialized():
            await elevenlabs_svc.initialize()

        lang_code = language[:2]
        voice_id = DEFAULT_VOICES.get(
            lang_code, DEFAULT_VOICES.get("en")
        )

        tts_start = time.time()
        mp3_bytes = await elevenlabs_svc.text_to_speech(
            text=text,
            voice_id=voice_id,
        )
        tts_latency = time.time() - tts_start

        if not mp3_bytes:
            logger.warning("ElevenLabs returned empty audio")
            return 0.0

        mulaw_chunks = mp3_to_mulaw_chunks(
            mp3_bytes, chunk_duration_ms=20
        )

        if not mulaw_chunks:
            logger.warning(
                "No mulaw chunks generated from MP3"
            )
            return 0.0

        for chunk_b64 in mulaw_chunks:
            media_message = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {
                    "payload": chunk_b64,
                },
            }
            await websocket.send_json(media_message)

        audio_duration_s = len(mulaw_chunks) * 0.02

        logger.info(
            "TTS sent: %d chars -> %d chunks "
            "(%.1fs audio, %.2fs TTS latency)",
            len(text),
            len(mulaw_chunks),
            audio_duration_s,
            tts_latency,
        )

        # Small delay to let Twilio buffer audio
        await asyncio.sleep(audio_duration_s * 0.8)

        return audio_duration_s

    except Exception as e:
        logger.error(
            "TTS->Twilio failed: %s", e, exc_info=True
        )
        return 0.0


async def _send_error_and_close(
    websocket: WebSocket, stream_sid: str
):
    """Send a brief error message and close the WebSocket."""
    try:
        await _text_to_twilio_audio(
            websocket,
            stream_sid or "",
            "Sorry, there was a technical issue. "
            "Please try again later.",
            "en",
        )
    except Exception:
        pass

    try:
        await websocket.close()
    except Exception:
        pass


async def _send_telegram_report(session):
    """
    Send call report back to the user's Telegram chat.

    Uses python-telegram-bot directly as a lightweight fallback.
    """
    try:
        report = session.generate_report()

        import os

        from telegram import Bot as TelegramBot

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if token:
            tg_bot = TelegramBot(token=token)
            await tg_bot.send_message(
                chat_id=session.telegram_chat_id,
                text=report,
                parse_mode="Markdown",
            )
            logger.info(
                "Report sent to Telegram chat %s",
                session.telegram_chat_id,
            )
        else:
            logger.warning(
                "Cannot send report: no TELEGRAM_BOT_TOKEN"
            )

    except Exception as e:
        logger.error(
            "Failed to send Telegram report: %s",
            e,
            exc_info=True,
        )
        logger.info(
            "Call report (not sent):\n%s",
            session.generate_report(),
        )
