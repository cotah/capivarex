"""
services/business/call_session.py
===================================
Manages state for AI-powered phone calls via Twilio Media Streams.

Each active call has a CallSession that tracks:
- Objective (what the call should accomplish)
- Audio buffer (incoming mulaw chunks from the person)
- Conversation history (for GPT context)
- Voice Activity Detection state
- Call status and metrics

Lifecycle:
    1. TwilioAgent creates a PendingCall with objective + user info
    2. Twilio connects via WebSocket -> PendingCall becomes active CallSession
    3. WebSocket handler feeds audio chunks -> CallSession buffers + detects speech
    4. When person stops talking -> CallSession triggers processing
    5. After processing (STT->GPT->TTS) -> response sent back via WebSocket
    6. Call ends -> CallSession generates report -> sent to Telegram

Usage:
    from services.business.call_session import (
        register_pending_call,
        get_pending_call,
        CallSession,
    )

    # In TwilioAgent:
    session_id = register_pending_call(
        objective="Reserve a table for 2 at 8pm",
        user_name="Henrique",
        language="pt",
        phone_number="+353894434456",
        telegram_chat_id=123456,
        telegram_user_id=789,
    )

    # In WebSocket handler:
    pending = get_pending_call(session_id)
    session = CallSession.from_pending(pending)
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.audio_converter import (
    is_speech,
    mulaw_chunks_to_wav,
    mulaw_duration_seconds,
)

logger = logging.getLogger(__name__)


# -- Enums -------------------------------------------------------------------


class CallStatus(str, Enum):
    """Status of a call session."""

    PENDING = "pending"
    GREETING = "greeting"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class CallResult(str, Enum):
    """Outcome of the call."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"
    HANGUP = "hangup"
    TIMEOUT = "timeout"


# -- Data Classes -------------------------------------------------------------


@dataclass
class PendingCall:
    """
    Created by TwilioAgent before the call connects.
    Holds all info the WebSocket handler needs to start the session.
    """

    session_id: str
    objective: str
    user_name: str
    language: str
    phone_number: str
    telegram_chat_id: int
    telegram_user_id: int
    extra_context: str = ""
    greeting: str = ""
    created_at: float = field(default_factory=time.time)
    EXPIRY_SECONDS: int = 30

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.EXPIRY_SECONDS


@dataclass
class ConversationTurn:
    """Single turn in the call conversation."""

    role: str  # "assistant" (bot) or "user" (person on phone)
    content: str
    timestamp: float = field(default_factory=time.time)
    audio_duration_s: float = 0.0


# -- Call Session -------------------------------------------------------------


class CallSession:
    """
    Manages the full state of an active AI phone call.

    Handles audio buffering, VAD (voice activity detection),
    conversation tracking, and lifecycle management.
    """

    # -- Configuration --------------------------------------------------------
    MAX_DURATION_S: int = 180
    MAX_TURNS: int = 20
    SILENCE_THRESHOLD_MS: int = 1500
    SPEECH_RMS_THRESHOLD: int = 50
    MIN_SPEECH_DURATION_S: float = 0.3
    MAX_SPEECH_DURATION_S: float = 30.0

    def __init__(
        self,
        session_id: str,
        objective: str,
        user_name: str,
        language: str,
        phone_number: str,
        telegram_chat_id: int,
        telegram_user_id: int,
        extra_context: str = "",
        greeting: str = "",
    ):
        # Identity
        self.session_id = session_id
        self.call_sid: Optional[str] = None
        self.stream_sid: Optional[str] = None

        # Call info
        self.objective = objective
        self.user_name = user_name
        self.language = language
        self.phone_number = phone_number
        self.telegram_chat_id = telegram_chat_id
        self.telegram_user_id = telegram_user_id
        self.extra_context = extra_context
        self.greeting = greeting

        # State
        self.status: CallStatus = CallStatus.PENDING
        self.result: CallResult = CallResult.UNKNOWN
        self.result_details: str = ""

        # Conversation
        self.conversation: List[ConversationTurn] = []

        # Audio buffering & VAD
        self.audio_buffer: bytearray = bytearray()
        self._silence_start: Optional[float] = None
        self._speech_detected: bool = False
        self._last_speech_time: float = 0.0

        # Metrics
        self.started_at: float = time.time()
        self.ended_at: Optional[float] = None
        self._turn_count: int = 0
        self._stt_total_latency: float = 0.0
        self._llm_total_latency: float = 0.0
        self._tts_total_latency: float = 0.0

    # -- Factory --------------------------------------------------------------

    @classmethod
    def from_pending(cls, pending: PendingCall) -> "CallSession":
        """Create an active CallSession from a PendingCall."""
        session = cls(
            session_id=pending.session_id,
            objective=pending.objective,
            user_name=pending.user_name,
            language=pending.language,
            phone_number=pending.phone_number,
            telegram_chat_id=pending.telegram_chat_id,
            telegram_user_id=pending.telegram_user_id,
            extra_context=pending.extra_context,
            greeting=pending.greeting,
        )
        session.status = CallStatus.GREETING
        return session

    # -- Audio Buffer & VAD ---------------------------------------------------

    def add_audio_chunk(self, mulaw_bytes: bytes) -> None:
        """
        Add an incoming audio chunk from Twilio.

        Updates the audio buffer and VAD state.

        Args:
            mulaw_bytes: Raw mulaw audio bytes (typically 160 bytes = 20ms)
        """
        self.audio_buffer.extend(mulaw_bytes)

        if is_speech(mulaw_bytes, threshold=self.SPEECH_RMS_THRESHOLD):
            self._speech_detected = True
            self._silence_start = None
            self._last_speech_time = time.time()
        else:
            if self._speech_detected and self._silence_start is None:
                self._silence_start = time.time()

    def should_process(self) -> bool:
        """
        Determine if accumulated audio should be processed.

        Returns True when:
        1. Speech was detected AND silence lasted > SILENCE_THRESHOLD_MS
        2. OR speech has been continuous for > MAX_SPEECH_DURATION_S

        Returns False when:
        - No speech detected yet
        - Person is still speaking
        - Already processing
        """
        if self.status == CallStatus.PROCESSING:
            return False

        if not self._speech_detected:
            return False

        audio_duration = mulaw_duration_seconds(bytes(self.audio_buffer))

        # Force-process if speech too long
        if audio_duration > self.MAX_SPEECH_DURATION_S:
            logger.info(
                "Session %s: force-process after %.1fs of speech",
                self.session_id[:8],
                audio_duration,
            )
            return True

        # Check silence duration
        if self._silence_start is not None:
            silence_ms = (time.time() - self._silence_start) * 1000
            if silence_ms >= self.SILENCE_THRESHOLD_MS:
                if audio_duration < self.MIN_SPEECH_DURATION_S:
                    self.clear_audio_buffer()
                    return False
                return True

        return False

    def get_audio_for_processing(self) -> bytes:
        """
        Get the accumulated audio as WAV bytes for Whisper.

        Returns WAV bytes and resets the audio buffer.
        """
        if not self.audio_buffer:
            return b""

        mulaw_bytes = bytes(self.audio_buffer)
        wav_bytes = mulaw_chunks_to_wav(mulaw_bytes)

        duration = mulaw_duration_seconds(mulaw_bytes)
        logger.info(
            "Session %s: %.1fs audio -> %d bytes WAV",
            self.session_id[:8],
            duration,
            len(wav_bytes),
        )

        self.clear_audio_buffer()
        return wav_bytes

    def clear_audio_buffer(self) -> None:
        """Reset the audio buffer and VAD state."""
        self.audio_buffer = bytearray()
        self._speech_detected = False
        self._silence_start = None

    # -- Conversation Management ----------------------------------------------

    def add_assistant_turn(
        self, text: str, audio_duration_s: float = 0.0
    ) -> None:
        """Record what the bot said."""
        self.conversation.append(
            ConversationTurn(
                role="assistant",
                content=text,
                audio_duration_s=audio_duration_s,
            )
        )
        self._turn_count += 1

    def add_user_turn(
        self, text: str, audio_duration_s: float = 0.0
    ) -> None:
        """Record what the person on the phone said."""
        self.conversation.append(
            ConversationTurn(
                role="user",
                content=text,
                audio_duration_s=audio_duration_s,
            )
        )

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get conversation as OpenAI messages format."""
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self.conversation
        ]

    def get_last_user_message(self) -> str:
        """Get the most recent thing the person said."""
        for turn in reversed(self.conversation):
            if turn.role == "user":
                return turn.content
        return ""

    # -- Status & Lifecycle ---------------------------------------------------

    def should_end_call(self) -> bool:
        """
        Determine if the call should end.

        Returns True when:
        - Max duration exceeded
        - Max turns exceeded
        - Status already terminal
        """
        if self.status in (
            CallStatus.COMPLETED,
            CallStatus.FAILED,
            CallStatus.TIMEOUT,
        ):
            return True

        elapsed = time.time() - self.started_at
        if elapsed > self.MAX_DURATION_S:
            self.status = CallStatus.TIMEOUT
            self.result = CallResult.TIMEOUT
            self.result_details = (
                f"Call exceeded {self.MAX_DURATION_S}s limit"
            )
            logger.warning(
                "Session %s: timeout after %.0fs",
                self.session_id[:8],
                elapsed,
            )
            return True

        if self._turn_count >= self.MAX_TURNS:
            self.status = CallStatus.COMPLETED
            self.result = CallResult.PARTIAL
            self.result_details = f"Reached max {self.MAX_TURNS} turns"
            logger.info(
                "Session %s: max turns reached", self.session_id[:8]
            )
            return True

        return False

    def mark_objective_complete(self, details: str = "") -> None:
        """Mark the call objective as completed."""
        self.status = CallStatus.COMPLETED
        self.result = CallResult.SUCCESS
        self.result_details = details or "Objective completed"
        logger.info(
            "Session %s: objective complete — %s",
            self.session_id[:8],
            details,
        )

    def mark_failed(self, reason: str = "") -> None:
        """Mark the call as failed."""
        self.status = CallStatus.FAILED
        self.result = CallResult.FAILED
        self.result_details = reason or "Call failed"
        logger.warning(
            "Session %s: failed — %s", self.session_id[:8], reason
        )

    def mark_hangup(self) -> None:
        """Mark that the person hung up."""
        self.status = CallStatus.COMPLETED
        self.result = CallResult.HANGUP
        self.result_details = "Person hung up"

    def finalize(self) -> None:
        """Finalize the session (call ended)."""
        self.ended_at = time.time()
        if self.status not in (
            CallStatus.COMPLETED,
            CallStatus.FAILED,
            CallStatus.TIMEOUT,
        ):
            self.status = CallStatus.COMPLETED

    # -- Metrics --------------------------------------------------------------

    def record_stt_latency(self, latency_s: float) -> None:
        self._stt_total_latency += latency_s

    def record_llm_latency(self, latency_s: float) -> None:
        self._llm_total_latency += latency_s

    def record_tts_latency(self, latency_s: float) -> None:
        self._tts_total_latency += latency_s

    @property
    def duration_s(self) -> float:
        """Total call duration in seconds."""
        end = self.ended_at or time.time()
        return end - self.started_at

    @property
    def metrics(self) -> Dict[str, Any]:
        """All metrics for the call."""
        return {
            "duration_s": round(self.duration_s, 1),
            "turns": self._turn_count,
            "stt_total_latency_s": round(self._stt_total_latency, 2),
            "llm_total_latency_s": round(self._llm_total_latency, 2),
            "tts_total_latency_s": round(self._tts_total_latency, 2),
            "avg_turn_latency_s": round(
                (
                    self._stt_total_latency
                    + self._llm_total_latency
                    + self._tts_total_latency
                )
                / max(self._turn_count, 1),
                2,
            ),
        }

    # -- Report ---------------------------------------------------------------

    def generate_report(self) -> str:
        """
        Generate a Telegram-friendly report of the call.

        Returns:
            Markdown-formatted string for Telegram
        """
        result_emoji = {
            CallResult.SUCCESS: "\u2705",
            CallResult.PARTIAL: "\u26a0\ufe0f",
            CallResult.FAILED: "\u274c",
            CallResult.HANGUP: "\U0001f4f5",
            CallResult.TIMEOUT: "\u23f0",
            CallResult.UNKNOWN: "\u2753",
        }
        emoji = result_emoji.get(self.result, "\u2753")

        minutes = int(self.duration_s // 60)
        seconds = int(self.duration_s % 60)
        duration_str = (
            f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
        )

        lines = [
            "\U0001f4de **Call completed**\n",
            f"\U0001f4f1 To: `{self.phone_number}`",
            f"\u23f1\ufe0f Duration: {duration_str}",
            f"\U0001f30d Language: {self.language.upper()}",
            f"\U0001f504 Turns: {self._turn_count}",
            "",
            f"{emoji} **Result: {self.result.value}**",
        ]

        if self.result_details:
            lines.append(f"_{self.result_details}_")

        if self.conversation:
            lines.append("\n\U0001f4dd **Transcript:**")
            for turn in self.conversation:
                icon = "\U0001f916" if turn.role == "assistant" else "\U0001f464"
                lines.append(f'{icon} "{turn.content}"')

        m = self.metrics
        lines.append(f"\n\u26a1 Avg response: {m['avg_turn_latency_s']}s")
        lines.append(f"\U0001f511 Session: `{self.session_id[:12]}...`")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session to dict (for logging/debugging)."""
        return {
            "session_id": self.session_id,
            "call_sid": self.call_sid,
            "objective": self.objective,
            "user_name": self.user_name,
            "language": self.language,
            "phone_number": self.phone_number,
            "status": self.status.value,
            "result": self.result.value,
            "result_details": self.result_details,
            "conversation": [
                {
                    "role": t.role,
                    "content": t.content,
                    "duration": t.audio_duration_s,
                }
                for t in self.conversation
            ],
            "metrics": self.metrics,
        }


# =============================================================================
# PENDING CALLS REGISTRY (in-memory)
# =============================================================================

_PENDING_CALLS: Dict[str, PendingCall] = {}


def register_pending_call(
    objective: str,
    user_name: str,
    language: str,
    phone_number: str,
    telegram_chat_id: int,
    telegram_user_id: int,
    extra_context: str = "",
    greeting: str = "",
) -> str:
    """
    Register a pending call. Called by TwilioAgent BEFORE making the call.

    The session_id is passed to Twilio via TwiML <Stream> parameter.
    When Twilio connects via WebSocket, the handler uses this ID
    to retrieve the call objective and context.

    Args:
        objective: What the call should accomplish
        user_name: Name of the user
        language: Language for the call (pt, en, es)
        phone_number: Number being called
        telegram_chat_id: Where to send report
        telegram_user_id: Who requested the call
        extra_context: Additional context for GPT
        greeting: Custom greeting (optional)

    Returns:
        session_id to pass to Twilio
    """
    _cleanup_expired()

    session_id = uuid.uuid4().hex[:16]

    _PENDING_CALLS[session_id] = PendingCall(
        session_id=session_id,
        objective=objective,
        user_name=user_name,
        language=language,
        phone_number=phone_number,
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
        extra_context=extra_context,
        greeting=greeting,
    )

    logger.info(
        "Registered pending call %s -> %s (objective: %s)",
        session_id[:8],
        phone_number,
        objective[:60],
    )

    return session_id


def get_pending_call(session_id: str) -> Optional[PendingCall]:
    """
    Retrieve and remove a pending call. Called by WebSocket handler.

    Returns None if session_id not found or expired.
    """
    pending = _PENDING_CALLS.pop(session_id, None)
    if pending is None:
        logger.warning("Pending call not found: %s", session_id[:8])
        return None
    if pending.is_expired:
        logger.warning("Pending call expired: %s", session_id[:8])
        return None
    return pending


def get_pending_calls_count() -> int:
    """Get number of pending calls (for monitoring)."""
    _cleanup_expired()
    return len(_PENDING_CALLS)


def _cleanup_expired() -> None:
    """Remove expired pending calls."""
    expired = [
        sid for sid, p in _PENDING_CALLS.items() if p.is_expired
    ]
    for sid in expired:
        del _PENDING_CALLS[sid]
        logger.debug("Cleaned up expired pending call: %s", sid[:8])
