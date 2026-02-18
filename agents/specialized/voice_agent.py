"""
Voice Agent - Text-to-speech and speech-to-text.

Refactored to use new BaseAgent architecture.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)


@register_agent("voice")
class VoiceAgent(BaseAgent):
    """
    Voice agent for text-to-speech and speech-to-text.

    Handles:
    - Text-to-speech conversion (TTS)
    - Speech-to-text transcription (STT)
    - Multiple voice options
    - Multiple language support
    """

    def __init__(self):
        super().__init__(
            name="voice",
            description="Text-to-speech and speech-to-text"
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Execute voice operation based on context.

        Context can contain:
        - action: "text_to_speech" or "speech_to_text"
        - text: Text to convert to audio (TTS)
        - audio_path: Path to audio file (STT)
        - audio_bytes: Bytes of audio file (STT)
        - voice: Voice name for TTS (optional)
        - language: Language for STT (optional, default: pt)

        Args:
            prompt: User's prompt (used as text for TTS if no text in context)
            context: Execution context with action parameters

        Returns:
            AgentResponse with audio file path (TTS) or transcribed text (STT)
        """
        action = context.get("action", "text_to_speech")

        if action == "text_to_speech":
            return await self._text_to_speech(prompt, context)
        elif action == "speech_to_text":
            return await self._speech_to_text(prompt, context)
        else:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Acao de voz nao reconhecida: {action}",
                error=f"Unknown voice action: {action}"
            )

    async def _text_to_speech(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Convert text to audio.

        Args:
            text: Fallback text to convert
            context: Context with optional text override and voice selection

        Returns:
            AgentResponse with audio file path
        """
        try:
            # Use text from context if available, otherwise use prompt
            text_to_convert = context.get("text", text)

            if not text_to_convert or len(text_to_convert.strip()) == 0:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Erro: Texto vazio para conversao em audio.",
                    error="Empty text for TTS"
                )

            # Get ElevenLabs service
            elevenlabs_svc = get_service("elevenlabs")
            if not elevenlabs_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Servico de voz nao disponivel.",
                    error="ElevenLabs service not available"
                )

            await elevenlabs_svc.initialize()

            # Get voice configuration
            voice_name = context.get("voice", "rachel")
            try:
                from services.ai.elevenlabs_service import PORTUGUESE_VOICES
            except ImportError:
                PORTUGUESE_VOICES = {}
            voice_id = PORTUGUESE_VOICES.get(
                voice_name,
                PORTUGUESE_VOICES.get("rachel", voice_name)
            )

            # Convert text to audio
            audio_bytes = await elevenlabs_svc.text_to_speech(
                text=text_to_convert,
                voice_id=voice_id
            )

            # Save audio to temporary file
            output_path = context.get("output_path")
            if not output_path:
                temp_dir = Path(tempfile.gettempdir()) / "superbot_audio"
                temp_dir.mkdir(parents=True, exist_ok=True)
                output_path = temp_dir / f"tts_{os.urandom(8).hex()}.mp3"

            with open(output_path, "wb") as f:
                f.write(audio_bytes)

            self.logger.info(
                f"Text-to-speech completed: {len(text_to_convert)} chars -> {output_path}"
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=str(output_path),
                data={
                    "audio_path": str(output_path),
                    "text_length": len(text_to_convert),
                    "voice": voice_name
                },
                metadata={
                    "type": "audio",
                    "file_path": str(output_path),
                    "format": "mp3"
                }
            )

        except Exception as e:
            self.logger.error(
                f"VoiceAgent TTS failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao converter texto em audio: {str(e)}",
                error=str(e)
            )

    async def _speech_to_text(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Convert audio to text.

        Args:
            prompt: User's prompt (unused for STT)
            context: Context with audio_path or audio_bytes

        Returns:
            AgentResponse with transcribed text
        """
        try:
            audio_path = context.get("audio_path")
            audio_bytes = context.get("audio_bytes")
            language = context.get("language", "pt")

            if not audio_path and not audio_bytes:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Erro: Nenhum arquivo de audio fornecido.",
                    error="No audio file provided"
                )

            # Get Whisper service
            whisper_svc = get_service("whisper")
            if not whisper_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Servico de transcricao nao disponivel.",
                    error="Whisper service not available"
                )

            await whisper_svc.initialize()

            # Convert audio to text
            if audio_bytes:
                result = await whisper_svc.speech_to_text_from_bytes(
                    audio_bytes=audio_bytes,
                    language=language
                )
            else:
                result = await whisper_svc.speech_to_text(
                    audio_file_path=audio_path,
                    language=language
                )

            transcribed_text = result.get("text", "")

            self.logger.info(
                f"Speech-to-text completed: {len(transcribed_text)} chars"
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=transcribed_text,
                data={
                    "transcribed_text": transcribed_text,
                    "language": language,
                    "text_length": len(transcribed_text)
                }
            )

        except Exception as e:
            self.logger.error(
                f"VoiceAgent STT failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao converter audio em texto: {str(e)}",
                error=str(e)
            )

    def get_available_voices(self) -> Dict[str, str]:
        """Return available voices from ElevenLabs service."""
        try:
            from services.ai.elevenlabs_service import PORTUGUESE_VOICES
            return PORTUGUESE_VOICES
        except Exception as e:
            self.logger.warning(f"Could not get available voices: {e}")
        return {}

    def get_supported_languages(self) -> Dict[str, str]:
        """Return supported languages from Whisper service."""
        try:
            from services.media.whisper_service import SUPPORTED_LANGUAGES
            return SUPPORTED_LANGUAGES
        except Exception as e:
            self.logger.warning(f"Could not get supported languages: {e}")
        return {}

    def get_capabilities(self) -> List[str]:
        """Get voice agent capabilities."""
        return [
            "text_to_speech",
            "speech_to_text",
            "audio_generation",
            "transcription"
        ]
