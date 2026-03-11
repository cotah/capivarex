"""
api/routes/twilio_stream.py
=============================
WebSocket endpoint for Twilio Media Streams.

Architecture:
  Twilio <-> This Handler <-> Deepgram (streaming STT)
                  |
            CallBrain (GPT) -> ElevenLabs (TTS)
                  |
            Response audio -> Twilio

Audio flow (ZERO conversion for STT):
  Twilio sends mulaw 8kHz -> forward raw bytes to Deepgram WebSocket
  Deepgram transcribes in real-time -> sends final transcript on speech end
  -> GPT generates response -> ElevenLabs TTS -> mulaw chunks -> Twilio
"""

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio-stream"])

# Temp directory for audio files (only used for Whisper fallback)
_AUDIO_TMP = Path(tempfile.gettempdir()) / "superbot_audio"
_AUDIO_TMP.mkdir(parents=True, exist_ok=True)


@router.websocket("/ws/twilio-stream")
async def twilio_media_stream(websocket: WebSocket):
    """
    Main WebSocket handler for Twilio Media Streams.

    Each connection = one phone call.
    Uses Deepgram streaming for real-time STT with minimum latency.
    """
    await websocket.accept()

    session = None
    stream_sid: Optional[str] = None
    call_sid: Optional[str] = None
    deepgram_conn = None
    deepgram_task = None

    # Deepgram sends partial results; we only act on
    # is_final=True with speech_final=True
    processing_lock = asyncio.Lock()
    is_speaking = False

    try:
        async for raw_message in websocket.iter_text():
            data = json.loads(raw_message)
            event = data.get("event")

            # ── CONNECTED ────────────────────────────────
            if event == "connected":
                logger.info(
                    "Twilio stream connected (protocol: %s)",
                    data.get("protocol"),
                )

            # ── START ─────────────────────────────────────
            elif event == "start":
                start_data = data.get("start", {})
                stream_sid = start_data.get("streamSid")
                call_sid = start_data.get("callSid")

                custom_params = start_data.get(
                    "customParameters", {}
                )
                session_id = custom_params.get(
                    "session_id", ""
                )

                logger.info(
                    "Call started: call_sid=%s stream_sid=%s "
                    "session_id=%s",
                    call_sid,
                    stream_sid,
                    session_id[:8] if session_id else "none",
                )

                # Load session
                session = await _load_session(
                    session_id, call_sid, stream_sid
                )

                if session is None:
                    logger.error(
                        "No session for session_id=%s "
                        "— closing",
                        session_id[:8],
                    )
                    await _send_error_and_close(
                        websocket, stream_sid
                    )
                    break

                # Open Deepgram streaming WebSocket
                deepgram_conn = (
                    await _open_deepgram_stream(
                        session.language,
                    )
                )

                if deepgram_conn is None:
                    logger.error(
                        "Failed to open Deepgram stream "
                        "— closing call"
                    )
                    await _send_error_and_close(
                        websocket, stream_sid
                    )
                    break

                # Background task: listen for transcripts
                deepgram_task = asyncio.create_task(
                    _listen_deepgram(
                        deepgram_conn=deepgram_conn,
                        twilio_ws=websocket,
                        session=session,
                        stream_sid=stream_sid,
                        processing_lock=processing_lock,
                    )
                )

                # Send greeting
                is_speaking = True
                await _send_greeting(
                    websocket, session, stream_sid
                )
                is_speaking = False

            # ── MEDIA ─────────────────────────────────────
            elif event == "media":
                if (
                    session is None
                    or deepgram_conn is None
                ):
                    continue

                # Don't forward while bot is speaking (echo)
                if is_speaking:
                    continue

                # Forward raw mulaw directly — NO conversion!
                payload = (
                    data.get("media", {}).get("payload", "")
                )
                if payload:
                    audio_bytes = base64.b64decode(payload)
                    try:
                        await deepgram_conn.send(
                            audio_bytes
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to send to Deepgram: %s",
                            _redact_key(e),
                        )

            # ── STOP ──────────────────────────────────────
            elif event == "stop":
                logger.info("Call stopped: %s", call_sid)
                break

    except WebSocketDisconnect:
        logger.info(
            "Twilio stream disconnected: call_sid=%s",
            call_sid,
        )
    except Exception as e:
        logger.error(
            "Twilio stream error: %s", e, exc_info=True
        )
        if session:
            session.mark_failed(f"WebSocket error: {e}")
    finally:
        # Cleanup Deepgram WebSocket
        if deepgram_conn:
            try:
                await deepgram_conn.close()
            except Exception:
                pass
        if deepgram_task:
            deepgram_task.cancel()
            try:
                await deepgram_task
            except (asyncio.CancelledError, Exception):
                pass
        if session:
            if session.result.value == "unknown":
                session.mark_hangup()
            session.finalize()
            await _send_telegram_report(session)


# =================================================================
# DEEPGRAM STREAMING
# =================================================================


def _redact_key(error) -> str:
    """Redact Deepgram API key from any error string."""
    msg = str(error)
    api_key = os.getenv("DEEPGRAM_API_KEY", "")
    if api_key and api_key in msg:
        msg = msg.replace(api_key, "[REDACTED]")
    return msg


async def _open_deepgram_stream(language: str):
    """
    Open a streaming WebSocket to Deepgram.

    Uses the raw ``wss://api.deepgram.com/v1/listen`` endpoint
    with query-string params, exactly as the Deepgram docs specify.
    Configured for Twilio's audio format: mulaw, 8 kHz, mono.

    Args:
        language: Language code (pt, en, es)

    Returns:
        websockets connection or None on failure
    """
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        logger.error("DEEPGRAM_API_KEY not set")
        return None

    lang_map = {
        "pt": "pt-BR",
        "en": "en-US",
        "es": "es",
    }
    dg_language = lang_map.get(language, "pt-BR")

    # Build URL exactly as Deepgram docs specify
    base = "wss://api.deepgram.com/v1/listen"
    params = (
        f"model=nova-3"
        f"&language={dg_language}"
        f"&encoding=mulaw"
        f"&sample_rate=8000"
        f"&channels=1"
        f"&punctuate=true"
        f"&endpointing=300"
        f"&interim_results=false"
        f"&vad_events=true"
    )
    url = f"{base}?{params}"
    headers = {"Authorization": f"Token {api_key}"}

    try:
        ws = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=5,
            ping_timeout=20,
        )
        logger.info(
            "Deepgram streaming connected (lang=%s)",
            dg_language,
        )
        return ws
    except Exception as e:
        logger.error(
            "Deepgram streaming connection failed: %s",
            _redact_key(e),
        )
        return None


async def _listen_deepgram(
    deepgram_conn,
    twilio_ws: WebSocket,
    session,
    stream_sid: str,
    processing_lock: asyncio.Lock,
):
    """
    Background task: listen for Deepgram transcript events
    via raw WebSocket JSON messages.

    When a final transcript arrives (person stopped talking),
    process it through GPT -> TTS -> Twilio.
    """
    try:
        async for raw_message in deepgram_conn:
            data = json.loads(raw_message)
            msg_type = data.get("type", "")

            if msg_type == "Results":
                channel = data.get("channel", {})
                alternatives = channel.get(
                    "alternatives", [{}]
                )
                transcript = (
                    alternatives[0]
                    .get("transcript", "")
                    .strip()
                )
                is_final = data.get("is_final", False)
                speech_final = data.get(
                    "speech_final", False
                )

                if not transcript:
                    continue

                if is_final and speech_final:
                    logger.info(
                        'Session %s Deepgram final: '
                        '"%s"',
                        session.session_id[:8],
                        transcript[:100],
                    )

                    async with processing_lock:
                        await _process_turn_streaming(
                            twilio_ws=twilio_ws,
                            session=session,
                            stream_sid=stream_sid,
                            transcript=transcript,
                        )

                        if session.should_end_call():
                            await _end_call(
                                twilio_ws,
                                session,
                                stream_sid,
                            )
                            return

            elif msg_type == "SpeechStarted":
                logger.debug("Deepgram: speech started")
            elif msg_type == "UtteranceEnd":
                logger.debug("Deepgram: utterance end")
            elif msg_type == "Metadata":
                logger.debug(
                    "Deepgram metadata received"
                )

    except asyncio.CancelledError:
        logger.info("Deepgram listener cancelled")
    except Exception as e:
        logger.error(
            "Deepgram listener error: %s",
            _redact_key(e),
        )


async def _process_turn_streaming(
    twilio_ws: WebSocket,
    session,
    stream_sid: str,
    transcript: str,
):
    """
    Process a conversation turn from streaming transcript.

    Replaces the old _process_turn() — no WAV conversion
    or batch STT. Just: transcript -> GPT -> TTS -> Twilio.
    """
    from services.ai.call_brain import CallBrain
    from services.business.call_session import CallStatus

    if not transcript:
        return

    session.status = CallStatus.PROCESSING
    session.add_user_turn(transcript)

    # ── GPT Brain ────────────────────────────────────────
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
        'Session %s Brain (%.2fs): "%s" '
        "| complete=%s end=%s",
        session.session_id[:8],
        brain_resp.latency_s,
        brain_resp.text[:100],
        brain_resp.objective_complete,
        brain_resp.should_end_call,
    )

    # ── TTS + Send ───────────────────────────────────────
    if brain_resp.text:
        session.status = CallStatus.SPEAKING
        audio_duration = await _text_to_twilio_audio(
            twilio_ws,
            stream_sid,
            brain_resp.text,
            session.language,
        )
        session.add_assistant_turn(
            brain_resp.text,
            audio_duration_s=audio_duration,
        )

    # ── Update state ─────────────────────────────────────
    if brain_resp.objective_complete:
        session.mark_objective_complete(brain_resp.text)

    if brain_resp.should_end_call:
        return

    session.status = CallStatus.LISTENING


# =================================================================
# INTERNAL FUNCTIONS (unchanged)
# =================================================================


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


# =================================================================
# STT / TTS / TWILIO AUDIO HELPERS
# =================================================================


async def _run_stt(wav_bytes: bytes, language: str) -> str:
    """
    Run Deepgram STT on WAV audio bytes (batch fallback).

    NOT used in the main streaming path — kept as fallback
    for cases where streaming is unavailable.

    Falls back to Whisper if Deepgram is unavailable.

    Args:
        wav_bytes: WAV audio file bytes
        language: Language hint (pt, en, es)

    Returns:
        Transcribed text (empty string on failure)
    """
    if not wav_bytes:
        return ""

    # Map our language codes to Deepgram's
    lang_map = {
        "pt": "pt-BR",  # Brazilian Portuguese
        "en": "en-US",
        "es": "es",
    }
    dg_language = lang_map.get(language, "pt-BR")

    # ── Try Deepgram first ───────────────────────────────
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if deepgram_key:
        try:
            url = "https://api.deepgram.com/v1/listen"
            headers = {
                "Authorization": f"Token {deepgram_key}",
                "Content-Type": "audio/wav",
            }
            params = {
                "model": "nova-3",
                "language": dg_language,
                "smart_format": "true",
                "punctuate": "true",
                "numerals": "true",
            }

            async with httpx.AsyncClient(
                timeout=10.0,
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    params=params,
                    content=wav_bytes,
                )
                response.raise_for_status()

                data = response.json()
                transcript = (
                    data.get("results", {})
                    .get("channels", [{}])[0]
                    .get("alternatives", [{}])[0]
                    .get("transcript", "")
                    .strip()
                )

                logger.info(
                    "Deepgram STT: '%s' (lang=%s, %d bytes)",
                    transcript[:100],
                    dg_language,
                    len(wav_bytes),
                )
                return transcript

        except Exception as e:
            logger.warning(
                "Deepgram STT failed, falling back to "
                "Whisper: %s",
                _redact_key(e),
            )

    # ── Fallback: Whisper ────────────────────────────────
    try:
        from services import get_service

        whisper_svc = get_service("whisper")
        if not whisper_svc:
            logger.error(
                "Neither Deepgram nor Whisper available "
                "for STT"
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
        logger.error(
            "Whisper STT fallback also failed: %s",
            e,
            exc_info=True,
        )
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

    Uses python-telegram-bot directly (lightweight).

    Guards:
    - None session or missing chat_id -> log and return
    - Tries Markdown first, falls back to plain text
    - Logs the full report as last resort if send fails
    """
    if session is None:
        logger.warning(
            "_send_telegram_report called with None session"
        )
        return

    chat_id = getattr(session, "telegram_chat_id", 0)
    if not chat_id:
        logger.warning(
            "Cannot send report: no telegram_chat_id "
            "on session %s",
            getattr(session, "session_id", "?"),
        )
        return

    try:
        report = session.generate_report()
    except Exception as e:
        logger.error(
            "Failed to generate report: %s",
            e,
            exc_info=True,
        )
        return

    from telegram import Bot as TelegramBot

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning(
            "Cannot send report: no TELEGRAM_BOT_TOKEN"
        )
        logger.info("Call report (not sent):\n%s", report)
        return

    try:
        tg_bot = TelegramBot(token=token)
    except Exception as e:
        logger.error(
            "Failed to create Telegram bot: %s", e
        )
        logger.info("Call report (not sent):\n%s", report)
        return

    # Try Markdown first, fall back to plain text
    try:
        await tg_bot.send_message(
            chat_id=chat_id,
            text=report,
            parse_mode="Markdown",
        )
        logger.info(
            "Report sent to Telegram chat %s", chat_id
        )
        return
    except Exception as md_err:
        logger.warning(
            "Markdown send failed (%s), "
            "retrying as plain text",
            md_err,
        )

    # Fallback: strip markdown and send as plain text
    try:
        plain = (
            report.replace("*", "")
            .replace("`", "")
            .replace("_", "")
        )
        await tg_bot.send_message(
            chat_id=chat_id, text=plain
        )
        logger.info(
            "Report sent (plain text) to Telegram chat %s",
            chat_id,
        )
    except Exception as e:
        logger.error(
            "Failed to send Telegram report: %s",
            e,
            exc_info=True,
        )
        logger.info("Call report (not sent):\n%s", report)
