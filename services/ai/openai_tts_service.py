# -*- coding: utf-8 -*-
"""
OpenAI TTS Service
==================
Text-to-Speech using OpenAI's tts-1 model.
Used for voice chat in the WebApp — much cheaper than ElevenLabs.

ElevenLabs is kept for phone calls (Twilio) where premium quality is needed.
OpenAI TTS is used for voice chat where cost-efficiency matters.

Pricing: $15 per 1M characters (vs ElevenLabs ~$300/1M).
Voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer
"""

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

# Available OpenAI TTS voices
OPENAI_TTS_VOICES: Dict[str, str] = {
    "alloy": "alloy",         # Neutral, balanced
    "ash": "ash",             # Clear, composed
    "ballad": "ballad",       # Warm, melodic
    "coral": "coral",         # Warm, conversational
    "echo": "echo",           # Smooth, clear
    "fable": "fable",         # Expressive, British
    "nova": "nova",           # Warm, friendly
    "onyx": "onyx",           # Deep, authoritative
    "sage": "sage",           # Wise, calm
    "shimmer": "shimmer",     # Bright, energetic
}

# Default voice for CAPIVAREX voice chat
DEFAULT_VOICE = "nova"


@register_service("openai_tts")
class OpenAITTSService(BaseService):
    """
    OpenAI Text-to-Speech service using tts-1 model.

    Usage:
        tts = get_service("openai_tts")
        audio_bytes = await tts.text_to_speech("Olá, como posso ajudar?")
    """

    def __init__(
        self, name: str = "openai_tts", config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(name, config)
        self.api_key: Optional[str] = None
        self.base_url: str = "https://api.openai.com/v1/audio/speech"
        self.model: str = "tts-1"

    async def _initialize(self) -> None:
        """Initialize OpenAI TTS service."""
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ServiceUnavailableError(
                "OPENAI_API_KEY not found — OpenAI TTS cannot initialize"
            )
        self.model = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
        self.logger.info(
            "OpenAI TTS service initialized (model=%s, voice=%s)",
            self.model, DEFAULT_VOICE,
        )

    async def _health_check(self) -> bool:
        """Check if OpenAI API is reachable."""
        return bool(self.api_key)

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def text_to_speech(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        model: Optional[str] = None,
        speed: float = 1.0,
        response_format: str = "mp3",
    ) -> bytes:
        """
        Convert text to speech using OpenAI TTS.

        Args:
            text: Text to convert (max 4096 chars)
            voice: Voice name (alloy, ash, coral, echo, fable, nova, onyx, sage, shimmer)
            model: TTS model (tts-1 or tts-1-hd). Defaults to service config.
            speed: Speed multiplier (0.25 to 4.0)
            response_format: Audio format (mp3, opus, aac, flac, wav, pcm)

        Returns:
            Audio bytes in the requested format

        Raises:
            RuntimeError: If the request fails
        """
        if not self.api_key:
            await self.initialize()

        # Truncate to OpenAI's 4096 char limit
        text = text[:4096]

        if not text.strip():
            raise RuntimeError("Empty text for TTS")

        start_time = time.time()

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            data = {
                "model": model or self.model,
                "input": text,
                "voice": voice if voice in OPENAI_TTS_VOICES else DEFAULT_VOICE,
                "speed": max(0.25, min(4.0, speed)),
                "response_format": response_format,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.base_url, json=data, headers=headers
                )
                response.raise_for_status()

                latency = time.time() - start_time
                self._track_call(latency, error=False)

                self.logger.info(
                    "OpenAI TTS: %d chars → %d bytes (%.2fs, voice=%s)",
                    len(text), len(response.content), latency, voice,
                )
                return response.content

        except httpx.HTTPStatusError as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("OpenAI TTS HTTP error: %s — %s", e.response.status_code, e)
            raise RuntimeError(f"OpenAI TTS failed: {e.response.status_code}")
        except httpx.HTTPError as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error("OpenAI TTS error: %s", e)
            raise RuntimeError(f"OpenAI TTS failed: {e}")
