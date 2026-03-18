"""
ElevenLabs Service - Refactored with BaseService architecture.

Provides:
- Text-to-speech conversion
- Voice listing
- User info
- Metrics tracking
"""

import os
import logging
import time
from typing import Dict, Any, Optional

import httpx
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()

logger = logging.getLogger(__name__)

# Pre-configured Portuguese voices
PORTUGUESE_VOICES: Dict[str, str] = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "antoni": "ErXwobaYiN019PkySvjV",
    "bella": "EXAVITQu4vr4xnSDxMaL",
    "elli": "MF3mGyEYCl7XYWbV9V6O",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "arnold": "VR6AewLTigWG4xSOukaG",
    "sam": "yoZ06aMxZJJ28mfd3POQ",
}


@register_service("elevenlabs")
class ElevenLabsService(BaseService):
    """
    ElevenLabs service for text-to-speech conversion.

    Features:
    - Text-to-speech with multiple voices
    - Voice listing
    - User info / credits
    - Automatic retry on failures
    - Metrics tracking
    """

    def __init__(
        self, name: str = "elevenlabs", config: Optional[Dict[str, Any]] = None
    ):
        """Initialise the ElevenLabs TTS service."""
        super().__init__(name, config)
        self.api_key: Optional[str] = None
        self.base_url: str = "https://api.elevenlabs.io/v1"

    async def _initialize(self) -> None:
        """Initialize ElevenLabs service."""
        self.api_key = os.environ.get("ELEVENLABS_API_KEY")

        if not self.api_key:
            raise ServiceUnavailableError(
                "ELEVENLABS_API_KEY not found in environment variables"
            )

        self.logger.info("ElevenLabs service initialized successfully")

    async def _health_check(self) -> bool:
        """Check if ElevenLabs service is healthy."""
        if not self.api_key:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/user",
                    headers={"xi-api-key": self.api_key, "Accept": "application/json"},
                )
                return response.status_code == 200
        except Exception as e:
            self.logger.error(f"ElevenLabs health check failed: {e}")
            return False

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def text_to_speech(
        self,
        text: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        model_id: str = "eleven_multilingual_v2",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        use_speaker_boost: bool = True,
    ) -> bytes:
        """
        Convert text to speech using ElevenLabs.

        Args:
            text: Text to convert
            voice_id: ElevenLabs voice ID
            model_id: Model to use
            stability: Voice stability (0.0-1.0)
            similarity_boost: Similarity boost (0.0-1.0)
            style: Style parameter (0.0-1.0)
            use_speaker_boost: Whether to use speaker boost

        Returns:
            Audio bytes (MP3 format)

        Raises:
            RuntimeError: If the request fails
        """
        if not self.api_key:
            await self.initialize()

        start_time = time.time()

        try:
            url = f"{self.base_url}/text-to-speech/{voice_id}"

            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self.api_key,
            }

            data = {
                "text": text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity_boost,
                    "style": style,
                    "use_speaker_boost": use_speaker_boost,
                },
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=data, headers=headers)
                response.raise_for_status()

                latency = time.time() - start_time
                self._track_call(latency, error=False)

                self.logger.info(
                    f"Text-to-speech successful: {len(text)} chars -> {len(response.content)} bytes"
                )
                return response.content

        except httpx.HTTPError as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error in text-to-speech: {e}")
            raise RuntimeError(f"Erro ao converter texto em audio: {str(e)}")

    async def get_voices(self) -> Dict[str, Any]:
        """
        Get list of available voices.

        Returns:
            Dictionary with voice information

        Raises:
            RuntimeError: If the request fails
        """
        if not self.api_key:
            await self.initialize()

        try:
            url = f"{self.base_url}/voices"

            headers = {
                "Accept": "application/json",
                "xi-api-key": self.api_key,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPError as e:
            self.logger.error(f"Error getting voices: {e}")
            raise RuntimeError(f"Erro ao buscar vozes: {str(e)}")

    async def get_user_info(self) -> Dict[str, Any]:
        """
        Get user information (credits, etc).

        Returns:
            Dictionary with user information

        Raises:
            RuntimeError: If the request fails
        """
        if not self.api_key:
            await self.initialize()

        try:
            url = f"{self.base_url}/user"

            headers = {
                "Accept": "application/json",
                "xi-api-key": self.api_key,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPError as e:
            self.logger.error(f"Error getting user info: {e}")
            raise RuntimeError(f"Erro ao buscar informacoes do usuario: {str(e)}")


# Singleton getter
_elevenlabs_service: Optional[ElevenLabsService] = None


def get_elevenlabs_service() -> ElevenLabsService:
    """Get global ElevenLabs service instance."""
    global _elevenlabs_service
    if _elevenlabs_service is None:
        from services.core import get_service

        _elevenlabs_service = get_service("elevenlabs")
    return _elevenlabs_service
