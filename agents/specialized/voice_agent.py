"""
Voice Agent - Text-to-speech and speech-to-text.

FIX [2025-02]: Adicionada função _strip_markdown_for_tts() que remove
formatação Markdown antes de enviar texto ao ElevenLabs.

FIX [2025-02 v2]:
  - Adicionado get_capabilities() (retornava [] por herdar BaseAgent)
  - Adicionado try/except no _handle_tts para capturar RuntimeError do ElevenLabs
    (ex: quota exceeded) e retornar AgentResponse.ERROR em vez de propagar

FIX [2026-02]:
  - Adicionado _extract_speech_text() para extrair o texto real a ser falado
    de comandos como "me mande um audio dizendo Eu te amo" → "Eu te amo"
  - Sem esta correção, o ElevenLabs lia o comando inteiro em vez do conteúdo.
"""

import logging
import re
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Dict, List


from agents.core import AgentResponse, AgentStatus, BaseAgent, register_agent
from services import get_service


logger = logging.getLogger(__name__)


# ─── Markdown stripping ───────────────────────────────────────────────────────
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff"
    "\U00002600-\U000026ff"
    "\U00002700-\U000027bf"
    "\U000023f0-\U000023fa"
    "\U0000fe00-\U0000fe0f"
    "\U0000200d"
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "]+",
    flags=re.UNICODE,
)


def _strip_markdown_for_tts(text: str) -> str:
    """Remove Markdown formatting for cleaner TTS output."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s*[\-\*\+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s+", "", text, flags=re.MULTILINE)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"^[\-_\*]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


# ─── Speech text extraction patterns ──────────────────────────────────────────
# Patterns to extract the actual text to be spoken from voice commands.
# E.g.: "me manda um audio dizendo Eu te amo" → "Eu te amo"
_SPEECH_EXTRACT_PATTERNS = [
    # PT: "dizendo X", "que diz X", "que diga X", "falando X"
    re.compile(
        r"(?:dizendo|que\s+diz|que\s+diga|falando|com\s+(?:o\s+)?texto"
        r"|com\s+a\s+(?:frase|mensagem)|a\s+dizer)\s+(.+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # PT: "diz X", "diga X", "fala X" (after audio/voz keyword)
    re.compile(
        r"(?:audio|áudio|voz|voice)\s+(?:que\s+)?(?:diz|diga|fala|fale)\s+(.+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # EN: "saying X", "that says X", "with text X"
    re.compile(
        r"(?:saying|that\s+says?|with\s+(?:the\s+)?(?:text|message|words?))\s+(.+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # Direct quotes after audio/voice command: "manda audio 'Eu te amo'"
    re.compile(
        r"""(?:audio|áudio|voz|voice)\s+['\"\u201c\u201d\u2018\u2019](.+?)['\"\u201c\u201d\u2018\u2019]""",
        re.IGNORECASE,
    ),
]

# Patterns that indicate the message is a voice command (not raw text)
_IS_VOICE_COMMAND = re.compile(
    r"(?:mand[ae]|envi[ae]|gera?|cria?|faz(?:er)?|produz|fa[çz]a)\s+"
    r"(?:um\s+|uma\s+|o\s+)?(?:audio|áudio|voz|mensagem\s+de\s+voz|voice\s+(?:message|note))"
    r"|(?:audio|áudio|voice)\s+(?:message|note|msg)"
    r"|(?:send|make|create|generate)\s+(?:a\s+|an\s+)?(?:audio|voice)",
    re.IGNORECASE,
)


def _extract_speech_text(prompt: str) -> str:
    """
    Extract the actual text to be spoken from a voice command.

    Examples:
        "me manda um audio dizendo Eu te amo" → "Eu te amo"
        "faz um audio falando bom dia amor" → "bom dia amor"
        "manda audio que diz olá mundo" → "olá mundo"
        "send an audio saying hello world" → "hello world"
        "gera audio com o texto boas festas" → "boas festas"

    If the prompt doesn't match any extraction pattern, or if it's not
    a voice command (e.g., raw text sent directly for TTS), returns
    the original prompt unchanged.
    """
    # Only try to extract if this looks like a voice command
    if not _IS_VOICE_COMMAND.search(prompt):
        return prompt

    for pattern in _SPEECH_EXTRACT_PATTERNS:
        match = pattern.search(prompt)
        if match:
            extracted = match.group(1).strip()
            # Remove trailing punctuation artifacts from command parsing
            extracted = extracted.rstrip(".")
            if extracted:
                return extracted

    # It's a voice command but we couldn't extract the text
    # Return the prompt as-is (better than nothing)
    return prompt


# ─── Voice map ────────────────────────────────────────────────────────────────
PORTUGUESE_VOICES = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "bella": "EXAVITQu4vr4xnSDxMaL",
    "antoni": "ErXwobaYiN019PkySvjV",
    "elli": "MF3mGyEYCl7XYWbV9V6O",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "arnold": "VR6AewLTigWG4xSOukaG",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "sam": "yoZ06aMxZJJ28mfd3POQ",
}


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
        super().__init__(name="voice", description="Text-to-speech and speech-to-text")

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        action = context.get("action", "text_to_speech")
        if action == "speech_to_text":
            return await self._handle_stt(prompt, context)
        else:
            return await self._handle_tts(prompt, context)

    async def _handle_tts(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Handle text-to-speech conversion."""
        text = prompt or context.get("text", "")
        text_to_convert = context.get("text", text)

        # ── FIX [2026-02]: Extrair o texto real do comando de voz ──
        # Antes: "me manda um audio dizendo Eu te amo" → TTS falava tudo
        # Agora: "me manda um audio dizendo Eu te amo" → TTS fala "Eu te amo"
        text_to_convert = _extract_speech_text(text_to_convert)
        logger.debug("TTS text after extraction: '%s'", text_to_convert[:100])

        if not text_to_convert or len(text_to_convert.strip()) == 0:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro: Texto vazio para conversao em audio.",
                error="Empty text for TTS",
            )

        # Strip markdown antes de enviar ao ElevenLabs
        text_to_convert = _strip_markdown_for_tts(text_to_convert)

        if not text_to_convert:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro: Texto ficou vazio após remoção de formatação.",
                error="Text empty after markdown stripping",
            )

        elevenlabs_svc = get_service("elevenlabs")
        if not elevenlabs_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Serviço ElevenLabs indisponível.",
                error="ElevenLabs service not found",
            )

        voice_name = context.get("voice", "rachel")
        voice_id = PORTUGUESE_VOICES.get(
            voice_name,
            PORTUGUESE_VOICES.get("rachel", voice_name),
        )

        # FIX: try/except para capturar erros do ElevenLabs (quota, network, etc.)
        try:
            audio_bytes = await elevenlabs_svc.text_to_speech(
                text=text_to_convert,
                voice_id=voice_id,
            )
        except Exception as e:
            self.logger.error("TTS failed: %s", e, exc_info=True)
            err_lower = str(e).lower()
            if "quota" in err_lower or "limit" in err_lower:
                msg = "Quota de voz atingida. Tenta mais tarde."
            elif "unauthorized" in err_lower or "401" in err_lower:
                msg = "Chave ElevenLabs inválida ou expirada."
            else:
                msg = f"Erro ao gerar áudio: {e}"
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=msg,
                error=str(e),
            )

        output_path = context.get("output_path")
        if not output_path:
            tmp_dir = mkdtemp()
            output_path = str(Path(tmp_dir) / "voice_output.mp3")

        Path(output_path).write_bytes(audio_bytes)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Áudio gerado com sucesso.",
            data={"audio_path": output_path, "voice": voice_name},
        )

    async def _handle_stt(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Handle speech-to-text transcription."""
        audio_path = context.get("audio_path")
        if not audio_path:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nenhum ficheiro de áudio fornecido.",
                error="No audio_path in context",
            )

        openai_svc = get_service("openai")
        if not openai_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Serviço OpenAI indisponível.",
                error="OpenAI service not found",
            )

        try:
            transcript = await openai_svc.transcribe_audio(audio_path)
        except Exception as e:
            self.logger.error("STT failed: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro na transcrição: {e}",
                error=str(e),
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=transcript,
            data={"transcript": transcript},
        )

    def get_capabilities(self) -> List[str]:
        return [
            "text_to_speech",
            "speech_to_text",
            "tts",
            "stt",
            "voice_generation",
            "audio_generation",
            "transcription",
        ]
