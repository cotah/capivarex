# -*- coding: utf-8 -*-
"""
Voice Pipeline API Routes
=========================
Endpoints para o pipeline completo de voz:
  - POST /api/voice/pipeline   — áudio → texto → LLM → áudio (pipeline completo)
  - POST /api/voice/tts        — texto → áudio (TTS only, já existe, mantido)
  - POST /api/voice/stt        — áudio → texto (STT only, já existe, mantido)
  - GET  /api/voice/stream/tts — streaming TTS (NOVO)
  - GET  /api/voice/languages  — idiomas suportados (já existe, mantido)
  - GET  /api/voice/voices     — vozes disponíveis (já existe, mantido)

NOTA: Este arquivo COMPLEMENTA api/routes/voice.py existente.
Adicione as rotas novas ao router existente:

    # Em api/routes/voice.py, no final:
    from api.routes.voice_pipeline_routes import (
        pipeline_endpoint,
        stream_tts_endpoint,
    )
    router.add_api_route("/pipeline", pipeline_endpoint, methods=["POST"])
    router.add_api_route("/stream/tts", stream_tts_endpoint, methods=["POST"])

Ou importe o router_pipeline e inclua no app_factory:
    app.include_router(router_pipeline, prefix="/api/voice")
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from agents import get_agent
from api.dependencies.auth import get_current_user
from api.middleware.rate_limit import limiter
from services.core import get_service

logger = logging.getLogger(__name__)

router_pipeline = APIRouter(tags=["voice-pipeline"])

# Diretório de áudios temporários
_AUDIO_TEMP_DIR = Path(tempfile.gettempdir()) / "superbot_audio"
_AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Extensões de áudio aceitas
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}
MAX_AUDIO_SIZE_MB = 25  # limite da API Whisper


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PipelineResponse(BaseModel):
    """Resposta do pipeline completo STT→LLM→TTS."""
    transcript: Optional[str] = Field(None, description="Texto transcrito do áudio de entrada")
    response_text: Optional[str] = Field(None, description="Resposta gerada pelo LLM")
    audio_filename: Optional[str] = Field(None, description="Nome do arquivo de áudio de resposta")
    audio_url: Optional[str] = Field(None, description="URL para baixar o áudio de resposta")
    language: str = Field("pt", description="Idioma detectado/usado")
    metrics: Dict = Field(default_factory=dict, description="Métricas de latência por etapa")
    warning: Optional[str] = Field(None, description="Aviso não-fatal (ex: TTS falhou, retornando texto)")


class StreamTTSRequest(BaseModel):
    """Request para streaming TTS."""
    text: str = Field(..., min_length=1, max_length=4800, description="Texto a converter em áudio")
    voice: Optional[str] = Field(None, description="Nome da voz (rachel, adam, bella, ...)")
    language: str = Field("pt", description="Código do idioma (pt, en, es, ...)")

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Texto não pode ser vazio")
        return v.strip()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_pipeline_service():
    """Obtém o VoicePipelineService, lançando 503 se indisponível."""
    svc = get_service("voice_pipeline")
    if svc is None:
        raise HTTPException(status_code=503, detail="Voice pipeline indisponível")
    return svc


def _validate_audio_file(file: UploadFile) -> None:
    """Valida extensão e tamanho do arquivo de áudio."""
    if file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Extensão '{ext}' não suportada. Use: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}",
            )


def _voice_name_to_id(voice_name: Optional[str], language: str) -> Optional[str]:
    """Converte nome da voz (rachel, adam) para voice_id ElevenLabs."""
    from services.ai.elevenlabs_service import PORTUGUESE_VOICES
    if voice_name:
        return PORTUGUESE_VOICES.get(voice_name.lower())
    return None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router_pipeline.post(
    "/pipeline",
    response_model=PipelineResponse,
    summary="Pipeline completo: áudio → LLM → áudio",
    description=(
        "Recebe um arquivo de áudio, transcreve com Whisper (STT), "
        "processa com o OrchestratorAgent (LLM) e retorna resposta em áudio (TTS). "
        "Se o TTS falhar, retorna apenas o texto da resposta com um aviso."
    ),
)
@limiter.limit("10/minute")
async def pipeline_endpoint(
    request: Request,
    audio: UploadFile = File(..., description="Arquivo de áudio (mp3, wav, ogg, m4a, webm)"),
    language: str = Form("pt", description="Código do idioma (pt, en, es, ...)"),
    voice: Optional[str] = Form(None, description="Nome da voz para TTS (rachel, adam, bella, ...)"),
    return_audio: bool = Form(True, description="Se True, gera áudio de resposta"),
    current_user: Dict = Depends(get_current_user),
) -> PipelineResponse:
    """Pipeline completo de voz: áudio de entrada → resposta em áudio."""
    _validate_audio_file(audio)

    # Salva upload em arquivo temporário
    suffix = Path(audio.filename or "audio.ogg").suffix.lower()
    tmp_path = _AUDIO_TEMP_DIR / f"in_{uuid.uuid4().hex[:8]}{suffix}"

    try:
        content = await audio.read()

        # Valida tamanho (25MB = limite Whisper API)
        if len(content) > MAX_AUDIO_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"Arquivo muito grande. Máximo: {MAX_AUDIO_SIZE_MB}MB",
            )

        tmp_path.write_bytes(content)

        pipeline_svc = _get_pipeline_service()
        if not pipeline_svc.is_initialized():
            await pipeline_svc.initialize()

        user_id = current_user.get("sub") or current_user.get("id", "anonymous")
        voice_id = _voice_name_to_id(voice, language)

        result = await pipeline_svc.process_audio(
            audio_path=str(tmp_path),
            user_id=user_id,
            language=language,
            voice_id=voice_id,
            return_audio=return_audio,
        )

        # Monta URL de download se áudio foi gerado
        audio_url = None
        if result.get("audio_filename"):
            audio_url = f"/api/voice/audio/{result['audio_filename']}"

        warning = None
        if result.get("error") and result.get("response_text"):
            # TTS falhou mas temos texto — aviso não-fatal
            warning = result["error"]

        return PipelineResponse(
            transcript=result.get("transcript"),
            response_text=result.get("response_text"),
            audio_filename=result.get("audio_filename"),
            audio_url=audio_url,
            language=result.get("language", language),
            metrics=result.get("metrics", {}),
            warning=warning,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Pipeline error: %s", e)
        raise HTTPException(status_code=500, detail=f"Erro no pipeline de voz: {str(e)}")
    finally:
        # Limpa arquivo de entrada
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@router_pipeline.post(
    "/stream/tts",
    summary="Streaming TTS: texto → áudio em chunks",
    description=(
        "Converte texto em áudio e retorna em streaming (chunked transfer). "
        "Ideal para respostas longas — o cliente começa a reproduzir antes "
        "do áudio completo estar pronto."
    ),
    response_class=StreamingResponse,
)
@limiter.limit("20/minute")
async def stream_tts_endpoint(
    request: Request,
    body: StreamTTSRequest,
    current_user: Dict = Depends(get_current_user),
) -> StreamingResponse:
    """Streaming TTS — retorna áudio em chunks conforme é gerado."""
    pipeline_svc = _get_pipeline_service()
    if not pipeline_svc.is_initialized():
        await pipeline_svc.initialize()

    voice_id = _voice_name_to_id(body.voice, body.language)

    async def audio_generator():
        try:
            async for chunk in pipeline_svc.stream_tts(
                text=body.text,
                voice_id=voice_id,
                language=body.language,
            ):
                yield chunk
        except Exception as e:
            logger.error("Streaming TTS error: %s", e)
            # Não podemos lançar HTTPException dentro de um generator async
            # O cliente receberá uma resposta truncada — comportamento esperado

    return StreamingResponse(
        content=audio_generator(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=response.mp3",
            "X-Voice-Language": body.language,
        },
    )


@router_pipeline.get(
    "/pipeline/health",
    summary="Health check do pipeline de voz",
    description="Verifica disponibilidade de cada componente do pipeline (STT, LLM, TTS).",
)
async def pipeline_health(
    current_user: Dict = Depends(get_current_user),
) -> Dict:
    """Retorna status de cada componente do pipeline."""
    from services.core import get_service

    whisper_svc = get_service("whisper")
    elevenlabs_svc = get_service("elevenlabs")
    orchestrator = get_agent("orchestrator")

    return {
        "stt": {
            "service": "WhisperService",
            "available": whisper_svc is not None,
            "initialized": whisper_svc.is_initialized() if whisper_svc else False,
        },
        "llm": {
            "service": "OrchestratorAgent",
            "available": orchestrator is not None,
        },
        "tts": {
            "service": "ElevenLabsService",
            "available": elevenlabs_svc is not None,
            "initialized": elevenlabs_svc.is_initialized() if elevenlabs_svc else False,
        },
        "pipeline": {
            "status": "operational" if all([whisper_svc, orchestrator, elevenlabs_svc]) else "degraded",
        },
    }
