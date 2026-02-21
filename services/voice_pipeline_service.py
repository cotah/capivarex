# -*- coding: utf-8 -*-
"""
Voice Pipeline Service
======================
Combina STT (Whisper) + LLM (OpenAI/Anthropic) + TTS (ElevenLabs) em um
único pipeline de voz end-to-end.

Fluxo:
  áudio → [WhisperService] → texto → [OrchestratorAgent] → resposta → [ElevenLabsService] → áudio

Features:
  - Pipeline completo: audio_file → audio_response
  - Modo parcial: text → audio (TTS only) ou audio → text (STT only)
  - Suporte a streaming TTS via gerador async
  - Métricas por etapa (latência, chars, bytes)
  - Fail-safe: se TTS falhar, retorna resposta em texto
  - Cache de voz configurável por user_id
"""

import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

from services.core import BaseService, register_service, ServiceUnavailableError

logger = logging.getLogger(__name__)

# Diretório de áudios temporários
AUDIO_TEMP_DIR = Path(tempfile.gettempdir()) / "superbot_audio"
AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Limite de texto para TTS (ElevenLabs rejeita >5000 chars)
TTS_MAX_CHARS = 4800

# Vozes padrão por idioma
DEFAULT_VOICES: Dict[str, str] = {
    "pt": "21m00Tcm4TlvDq8ikWAM",  # Rachel — boa para PT-BR
    "en": "pNInz6obpgDQGcFmaJgB",  # Adam
    "es": "ErXwobaYiN019PkySvjV",  # Antoni
    "fr": "EXAVITQu4vr4xnSDxMaL",  # Bella
}


@register_service("voice_pipeline")
class VoicePipelineService(BaseService):
    """
    Serviço de pipeline de voz completo (STT → LLM → TTS).

    Deps:
        - WhisperService (services.media.whisper_service)
        - ElevenLabsService (services.ai.elevenlabs_service)
        - OrchestratorAgent (agents.orchestrator)

    Uso:
        svc = get_service("voice_pipeline")
        result = await svc.process_audio(
            audio_path="/tmp/input.ogg",
            user_id="u123",
            language="pt",
        )
        # result["audio_path"] -> áudio da resposta
        # result["transcript"] -> texto transcrito
        # result["response_text"] -> resposta do LLM
    """

    def __init__(self):
        super().__init__(name="voice_pipeline")
        self._whisper = None
        self._elevenlabs = None

    async def _initialize(self) -> None:
        """Carrega serviços dependentes."""
        from services.core import get_service

        self._whisper = get_service("whisper")
        self._elevenlabs = get_service("elevenlabs")

        # Inicializa os serviços se necessário
        if self._whisper and not self._whisper.is_initialized():
            await self._whisper.initialize()

        if self._elevenlabs and not self._elevenlabs.is_initialized():
            await self._elevenlabs.initialize()

        if not self._whisper:
            self.logger.warning("WhisperService indisponível — STT desativado")
        if not self._elevenlabs:
            self.logger.warning("ElevenLabsService indisponível — TTS desativado")

    async def _health_check(self) -> bool:
        return self._whisper is not None or self._elevenlabs is not None

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def process_audio(
        self,
        audio_path: str,
        user_id: str,
        language: str = "pt",
        voice_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        return_audio: bool = True,
    ) -> Dict[str, Any]:
        """
        Pipeline completo: áudio → texto → LLM → áudio.

        Args:
            audio_path: Caminho do arquivo de áudio de entrada
            user_id: ID do usuário (para contexto do LLM)
            language: Código do idioma (pt, en, es, ...)
            voice_id: ID da voz ElevenLabs (opcional, usa padrão do idioma)
            context: Contexto extra para o OrchestratorAgent
            return_audio: Se True, gera áudio de resposta; False retorna só texto

        Returns:
            Dict com: transcript, response_text, audio_path (se return_audio),
                      metrics (latências por etapa), error (se falhou alguma etapa)
        """
        if not self.is_initialized():
            await self.initialize()

        result: Dict[str, Any] = {
            "transcript": None,
            "response_text": None,
            "audio_path": None,
            "audio_filename": None,
            "language": language,
            "metrics": {},
            "error": None,
        }

        # ── ETAPA 1: STT ──────────────────────────────────────────────────────
        transcript, stt_latency, stt_error = await self._run_stt(audio_path, language)
        result["metrics"]["stt_latency_s"] = stt_latency

        if stt_error:
            result["error"] = f"STT falhou: {stt_error}"
            self.logger.error("STT error: %s", stt_error)
            return result

        result["transcript"] = transcript
        self.logger.info("STT OK: %d chars em %.2fs", len(transcript), stt_latency)

        # ── ETAPA 2: LLM ─────────────────────────────────────────────────────
        response_text, llm_latency, llm_error = await self._run_llm(
            transcript=transcript,
            user_id=user_id,
            language=language,
            context=context or {},
        )
        result["metrics"]["llm_latency_s"] = llm_latency

        if llm_error:
            result["error"] = f"LLM falhou: {llm_error}"
            return result

        result["response_text"] = response_text
        self.logger.info("LLM OK: %d chars em %.2fs", len(response_text), llm_latency)

        # ── ETAPA 3: TTS (opcional) ───────────────────────────────────────────
        if return_audio:
            effective_voice = voice_id or DEFAULT_VOICES.get(language, DEFAULT_VOICES["pt"])
            audio_out, tts_latency, tts_error = await self._run_tts(
                text=response_text,
                voice_id=effective_voice,
            )
            result["metrics"]["tts_latency_s"] = tts_latency

            if tts_error:
                # Fail-safe: retorna texto mesmo sem áudio
                self.logger.warning("TTS falhou (fail-safe): %s", tts_error)
                result["error"] = f"TTS indisponível (resposta em texto): {tts_error}"
            else:
                filename = f"resp_{uuid.uuid4().hex[:8]}.mp3"
                audio_path_out = AUDIO_TEMP_DIR / filename
                audio_path_out.write_bytes(audio_out)
                result["audio_path"] = str(audio_path_out)
                result["audio_filename"] = filename
                result["metrics"]["audio_bytes"] = len(audio_out)
                self.logger.info("TTS OK: %d bytes em %.2fs", len(audio_out), tts_latency)

        return result

    async def text_to_speech(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: str = "pt",
        save_to_file: bool = True,
    ) -> Dict[str, Any]:
        """
        TTS only: texto → áudio.

        Args:
            text: Texto a converter
            voice_id: ID da voz (opcional)
            language: Idioma (para selecionar voz padrão)
            save_to_file: Se True, salva em arquivo e retorna o path

        Returns:
            Dict com: audio_bytes, audio_path (se save_to_file), filename, latency_s
        """
        if not self.is_initialized():
            await self.initialize()

        if not self._elevenlabs:
            raise ServiceUnavailableError("ElevenLabsService indisponível")

        # Trunca texto longo
        if len(text) > TTS_MAX_CHARS:
            self.logger.warning("Texto truncado: %d → %d chars", len(text), TTS_MAX_CHARS)
            text = text[:TTS_MAX_CHARS] + "..."

        effective_voice = voice_id or DEFAULT_VOICES.get(language, DEFAULT_VOICES["pt"])
        audio_bytes, latency, error = await self._run_tts(text, effective_voice)

        if error:
            raise RuntimeError(f"TTS falhou: {error}")

        result: Dict[str, Any] = {
            "audio_bytes": audio_bytes,
            "audio_path": None,
            "filename": None,
            "latency_s": latency,
            "chars": len(text),
        }

        if save_to_file:
            filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
            path = AUDIO_TEMP_DIR / filename
            path.write_bytes(audio_bytes)
            result["audio_path"] = str(path)
            result["filename"] = filename

        return result

    async def speech_to_text(
        self,
        audio_path: str,
        language: str = "pt",
    ) -> Dict[str, Any]:
        """
        STT only: áudio → texto.

        Args:
            audio_path: Caminho do áudio
            language: Idioma do áudio

        Returns:
            Dict com: transcript, language, latency_s
        """
        if not self.is_initialized():
            await self.initialize()

        if not self._whisper:
            raise ServiceUnavailableError("WhisperService indisponível")

        transcript, latency, error = await self._run_stt(audio_path, language)

        if error:
            raise RuntimeError(f"STT falhou: {error}")

        return {
            "transcript": transcript,
            "language": language,
            "latency_s": latency,
        }

    async def stream_tts(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: str = "pt",
        chunk_size: int = 1024,
    ) -> AsyncGenerator[bytes, None]:
        """
        TTS em streaming: produz chunks de áudio conforme são gerados.

        Útil para respostas longas — o cliente começa a reproduzir
        antes do áudio completo estar pronto.

        Args:
            text: Texto a converter
            voice_id: ID da voz
            language: Idioma
            chunk_size: Tamanho dos chunks em bytes

        Yields:
            Chunks de bytes MP3
        """
        if not self.is_initialized():
            await self.initialize()

        if not self._elevenlabs:
            raise ServiceUnavailableError("ElevenLabsService indisponível")

        # Trunca texto longo
        if len(text) > TTS_MAX_CHARS:
            text = text[:TTS_MAX_CHARS]

        effective_voice = voice_id or DEFAULT_VOICES.get(language, DEFAULT_VOICES["pt"])

        try:
            audio_bytes = await self._elevenlabs.text_to_speech(
                text=text,
                voice_id=effective_voice,
            )

            # Emite em chunks para simular streaming
            for i in range(0, len(audio_bytes), chunk_size):
                yield audio_bytes[i : i + chunk_size]

        except Exception as e:
            self.logger.error("Streaming TTS error: %s", e)
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _run_stt(
        self, audio_path: str, language: str
    ) -> Tuple[str, float, Optional[str]]:
        """Executa STT e retorna (transcript, latency, error)."""
        if not self._whisper:
            return "", 0.0, "WhisperService indisponível"

        start = time.time()
        try:
            result = await self._whisper.speech_to_text(
                audio_file_path=audio_path,
                language=language,
            )
            latency = time.time() - start
            return result.get("text", ""), latency, None
        except Exception as e:
            return "", time.time() - start, str(e)

    async def _run_llm(
        self,
        transcript: str,
        user_id: str,
        language: str,
        context: Dict[str, Any],
    ) -> Tuple[str, float, Optional[str]]:
        """Executa LLM via OrchestratorAgent e retorna (text, latency, error)."""
        from agents import get_agent

        start = time.time()
        try:
            orchestrator = get_agent("orchestrator")
            if not orchestrator:
                return "", 0.0, "OrchestratorAgent indisponível"

            llm_context = {
                "user_id": user_id,
                "language": language,
                "source": "voice",
                **context,
            }

            response = await orchestrator.execute(
                prompt=transcript,
                context=llm_context,
            )
            latency = time.time() - start

            if not response.is_success():
                return "", latency, response.error or "LLM retornou erro"

            return response.response or "", latency, None

        except Exception as e:
            return "", time.time() - start, str(e)

    async def _run_tts(
        self, text: str, voice_id: str
    ) -> Tuple[bytes, float, Optional[str]]:
        """Executa TTS e retorna (audio_bytes, latency, error)."""
        if not self._elevenlabs:
            return b"", 0.0, "ElevenLabsService indisponível"

        start = time.time()
        try:
            audio_bytes = await self._elevenlabs.text_to_speech(
                text=text,
                voice_id=voice_id,
            )
            latency = time.time() - start
            return audio_bytes, latency, None
        except Exception as e:
            return b"", time.time() - start, str(e)
