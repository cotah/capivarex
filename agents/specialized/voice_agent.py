"""
Voice Agent - Text-to-speech and speech-to-text.

FIX [2025-02]: Adicionada função _strip_markdown_for_tts() que remove
               formatação Markdown antes de enviar texto ao ElevenLabs.
               Sem este fix, o bot lia em voz alta: "asterisco asterisco
               Alarme configurado asterisco asterisco" em vez de "Alarme configurado".
"""

import logging
import re
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Dict

from agents.core import AgentResponse, AgentStatus, BaseAgent, register_agent
from services import get_service

logger = logging.getLogger(__name__)


# ─── Markdown stripping ───────────────────────────────────────────────────────

# Ranges de emojis Unicode mais comuns
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # Emoticons
    "\U0001f300-\U0001f5ff"  # Símbolos & Pictogramas
    "\U0001f680-\U0001f6ff"  # Transporte & Mapa
    "\U0001f1e0-\U0001f1ff"  # Bandeiras
    "\U00002600-\U000026ff"  # Símbolos Miscelâneos
    "\U00002700-\U000027bf"  # Dingbats
    "\U000023f0-\U000023ff"  # Relógios e temporizadores
    "\U0000231a-\U0000231b"  # Relógio de pulso
    "\U000025aa-\U000025fe"  # Quadrados pequenos
    "\U00002b50-\U00002b55"  # Estrelas
    "\U0001f900-\U0001f9ff"  # Suplemento de símbolos
    "\U0001fa00-\U0001fa6f"  # Símbolos de xadrez
    "\U0001fa70-\U0001faff"  # Emojis de símbolos
    "]+",
    flags=re.UNICODE,
)


def _strip_markdown_for_tts(text: str) -> str:
    """
    Remove formatação Markdown e emojis para leitura TTS.

    Converte:
      **Texto**          → Texto
      *Texto*            → Texto
      # Título           → Título
      • Item             → Item
      [link](url)        → link
      `código`           → código (sem backticks)
      ⏱️ Emoji          → (removido)

    Args:
        text: Texto com possível formatação Markdown

    Returns:
        Texto limpo adequado para síntese de voz
    """
    if not text:
        return text

    # Remove bold e italic (***texto***, **texto**, *texto*)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text, flags=re.DOTALL)

    # Remove headers markdown (# ## ###)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Remove bullet points (• - * +)
    text = re.sub(r"^\s*[•\-\*\+]\s+", "", text, flags=re.MULTILINE)

    # Remove links markdown [texto](url) → texto
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Remove inline code e code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Remove underscore italic _texto_
    text = re.sub(r"_(.+?)_", r"\1", text)

    # Remove emojis
    text = _EMOJI_RE.sub("", text)

    # Remove linhas com apenas separadores (---, ___, ***)
    text = re.sub(r"^[\-_\*]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Normaliza espaços e newlines excessivos
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


# ─── Agent ────────────────────────────────────────────────────────────────────


@register_agent("voice")
class VoiceAgent(BaseAgent):
    """
    Voice agent for text-to-speech and speech-to-text.

    Handles:
    - Text-to-speech conversion (TTS) via ElevenLabs
    - Speech-to-text transcription (STT) via OpenAI Whisper
    - Multiple voice options
    - Multiple language support
    """

    def __init__(self):
        """Initialise the voice agent."""
        super().__init__(name="voice", description="Text-to-speech and speech-to-text")

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
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
            AgentResponse with audio file path or transcription
        """
        action = context.get("action", "text_to_speech")

        if action == "speech_to_text":
            return await self._handle_stt(prompt, context)
        else:
            return await self._handle_tts(prompt, context)

    async def _handle_tts(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Handle text-to-speech conversion."""
        text = prompt or context.get("text", "")
        text_to_convert = context.get("text", text)

        if not text_to_convert or len(text_to_convert.strip()) == 0:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro: Texto vazio para conversao em audio.",
                error="Empty text for TTS",
            )

        # FIX: Strip markdown antes de enviar ao ElevenLabs.
        # Sem este fix, o bot lê "asterisco asterisco Alarme configurado asterisco asterisco"
        # em vez de "Alarme configurado".
        text_to_convert = _strip_markdown_for_tts(text_to_convert)

        if not text_to_convert:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro: Texto ficou vazio após remoção de formatação.",
                error="Text empty after markdown stripping",
            )

        # Get ElevenLabs service
        elevenlabs_svc = get_service("elevenlabs")
        if not elevenlabs_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Servico de voz nao disponivel.",
                error="ElevenLabs service not available",
            )

        await elevenlabs_svc.initialize()

        # Get voice configuration
        voice_name = context.get("voice", "rachel")
        try:
            from services.ai.elevenlabs_service import PORTUGUESE_VOICES
        except ImportError:
            PORTUGUESE_VOICES = {}
        voice_id = PORTUGUESE_VOICES.get(
            voice_name, PORTUGUESE_VOICES.get("rachel", voice_name)
        )

        # Convert text to audio
        audio_bytes = await elevenlabs_svc.text_to_speech(
            text=text_to_convert, voice_id=voice_id
        )

        # Save audio to temporary file
        output_path = context.get("output_path")
        if not output_path:
            temp_dir = Path(mkdtemp())
            output_path = str(temp_dir / "voice_output.mp3")

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        self.logger.info(
            "TTS completed: %d chars → %s (voice: %s)",
            len(text_to_convert),
            output_path,
            voice_name,
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"Áudio gerado com sucesso: {output_path}",
            data={
                "audio_path": output_path,
                "voice": voice_name,
                "text_length": len(text_to_convert),
            },
        )

    async def _handle_stt(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Handle speech-to-text transcription."""
        audio_path = context.get("audio_path")
        audio_bytes = context.get("audio_bytes")
        language = context.get("language", "pt")

        if not audio_path and not audio_bytes:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro: Nenhum arquivo de audio fornecido para transcrição.",
                error="No audio file provided",
            )

        openai_svc = get_service("openai")
        if not openai_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Serviço OpenAI não disponível para transcrição.",
                error="OpenAI service not available",
            )

        if not openai_svc.is_initialized():
            await openai_svc.initialize()

        try:
            client = openai_svc.get_client()

            if audio_bytes:
                # Write bytes to temp file
                temp_dir = Path(mkdtemp())
                audio_path = str(temp_dir / "input_audio.ogg")
                with open(audio_path, "wb") as f:
                    f.write(audio_bytes)

            with open(audio_path, "rb") as audio_file:
                transcription = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                )

            text = transcription.text or ""
            self.logger.info("STT completed: '%s...'", text[:50])

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=text,
                data={
                    "transcription": text,
                    "language": language,
                },
            )

        except Exception as e:
            self.logger.error("STT error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro na transcrição: {str(e)}",
                error=str(e),
            )
