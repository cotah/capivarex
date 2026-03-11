"""
Whisper Service - Refactored with BaseService architecture.

Provides:
- Speech-to-text conversion via OpenAI Whisper
- Audio translation to English
- Metrics tracking
"""

import os
import logging
import time
from io import BytesIO
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()

logger = logging.getLogger(__name__)

# Supported languages
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "pt": "Portugues",
    "en": "English",
    "es": "Espanol",
    "fr": "Francais",
    "de": "Deutsch",
    "it": "Italiano",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
}


@register_service("whisper")
class WhisperService(BaseService):
    """
    Whisper service for speech-to-text conversion.

    Features:
    - Speech-to-text from file path
    - Speech-to-text from bytes
    - Audio translation to English
    - Automatic retry on failures
    - Metrics tracking
    """

    def __init__(self, name: str = "whisper", config: Optional[Dict[str, Any]] = None):
        """Initialise the Whisper transcription service."""
        super().__init__(name, config)
        self.api_key: Optional[str] = None
        self.client: Optional[AsyncOpenAI] = None

    async def _initialize(self) -> None:
        """Initialize Whisper service (uses OpenAI API)."""
        self.api_key = os.environ.get("OPENAI_API_KEY")

        if not self.api_key:
            raise ServiceUnavailableError(
                "OPENAI_API_KEY not found in environment variables"
            )

        self.client = AsyncOpenAI(api_key=self.api_key)
        self.logger.info("Whisper service initialized successfully")

    async def _health_check(self) -> bool:
        """Check if Whisper service is healthy."""
        return self.client is not None and self.api_key is not None

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def speech_to_text(
        self,
        audio_file_path: str,
        language: str = "pt",
        model: str = "whisper-1",
        response_format: str = "json",
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Convert audio file to text using Whisper.

        Args:
            audio_file_path: Path to the audio file
            language: Language code (pt, en, es, etc)
            model: Whisper model (whisper-1)
            response_format: Response format (json, text, srt, verbose_json, vtt)
            temperature: Sampling temperature (0.0-1.0)

        Returns:
            Dict with transcribed text and metadata

        Raises:
            RuntimeError: If the request fails
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        try:
            with open(audio_file_path, "rb") as audio_file:
                transcript = await self.client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    language=language,
                    response_format="verbose_json",
                    temperature=temperature,
                    prompt=(
                        "Transcreva exatamente o que foi dito em português. "
                        "Se não houver fala humana clara, retorne texto vazio."
                    ),
                )

            # Check no_speech_prob to filter Whisper hallucinations
            no_speech_prob = getattr(transcript, "no_speech_prob", 0.0)
            if not no_speech_prob and hasattr(transcript, "segments"):
                segments = transcript.segments or []
                if segments:
                    no_speech_prob = max(
                        getattr(s, "no_speech_prob", 0.0) for s in segments
                    )

            if no_speech_prob > 0.6:
                result = {"text": "", "language": language, "model": model}
            elif hasattr(transcript, "text"):
                result = {
                    "text": transcript.text,
                    "language": language,
                    "model": model,
                }
            else:
                result = {
                    "text": str(transcript),
                    "language": language,
                    "model": model,
                }

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            self.logger.info(f"Speech-to-text successful: {len(result['text'])} chars")
            return result

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error in speech-to-text: {e}")
            raise RuntimeError(f"Erro ao converter audio em texto: {str(e)}")

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def speech_to_text_from_bytes(
        self,
        audio_bytes: bytes,
        filename: str = "audio.mp3",
        language: str = "pt",
        model: str = "whisper-1",
        response_format: str = "json",
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Convert audio bytes to text using Whisper.

        Args:
            audio_bytes: Audio file bytes
            filename: Filename for identification
            language: Language code (pt, en, es, etc)
            model: Whisper model (whisper-1)
            response_format: Response format (json, text, srt, verbose_json, vtt)
            temperature: Sampling temperature (0.0-1.0)

        Returns:
            Dict with transcribed text and metadata

        Raises:
            RuntimeError: If the request fails
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        try:
            audio_file = BytesIO(audio_bytes)
            audio_file.name = filename

            transcript = await self.client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                language=language,
                response_format="verbose_json",
                temperature=temperature,
                prompt=(
                    "Transcreva exatamente o que foi dito em português. "
                    "Se não houver fala humana clara, retorne texto vazio."
                ),
            )

            # Check no_speech_prob to filter Whisper hallucinations
            no_speech_prob = getattr(transcript, "no_speech_prob", 0.0)
            if not no_speech_prob and hasattr(transcript, "segments"):
                segments = transcript.segments or []
                if segments:
                    no_speech_prob = max(
                        getattr(s, "no_speech_prob", 0.0) for s in segments
                    )

            if no_speech_prob > 0.6:
                result = {"text": "", "language": language, "model": model}
            elif hasattr(transcript, "text"):
                result = {
                    "text": transcript.text,
                    "language": language,
                    "model": model,
                }
            else:
                result = {
                    "text": str(transcript),
                    "language": language,
                    "model": model,
                }

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            self.logger.info(
                f"Speech-to-text (from bytes) successful: {len(result['text'])} chars"
            )
            return result

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error in speech-to-text from bytes: {e}")
            raise RuntimeError(f"Erro ao converter audio em texto: {str(e)}")

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def translate_audio(
        self,
        audio_file_path: str,
        model: str = "whisper-1",
        response_format: str = "json",
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Translate audio to English using Whisper.

        Args:
            audio_file_path: Path to the audio file
            model: Whisper model (whisper-1)
            response_format: Response format (json, text, srt, verbose_json, vtt)
            temperature: Sampling temperature (0.0-1.0)

        Returns:
            Dict with translated text and metadata

        Raises:
            RuntimeError: If the request fails
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        try:
            with open(audio_file_path, "rb") as audio_file:
                translation = await self.client.audio.translations.create(
                    model=model,
                    file=audio_file,
                    response_format=response_format,
                    temperature=temperature,
                )

            if response_format == "json":
                result = {
                    "text": translation.text,
                    "language": "en",
                    "model": model,
                }
            else:
                result = {
                    "text": str(translation),
                    "language": "en",
                    "model": model,
                }

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            self.logger.info(
                f"Audio translation successful: {len(result['text'])} chars"
            )
            return result

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error in audio translation: {e}")
            raise RuntimeError(f"Erro ao traduzir audio: {str(e)}")


# Singleton getter
_whisper_service: Optional[WhisperService] = None


def get_whisper_service() -> WhisperService:
    """Get global whisper service instance."""
    global _whisper_service
    if _whisper_service is None:
        from services.core import get_service

        _whisper_service = get_service("whisper")
    return _whisper_service
