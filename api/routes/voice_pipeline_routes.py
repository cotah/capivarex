# -*- coding: utf-8 -*-
"""
Voice Pipeline API Routes
=========================
Endpoints para o pipeline completo de voz.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional  # FIX F401: removed unused `import os`

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse  # FIX F401: removed unused FileResponse
from pydantic import BaseModel, Field, field_validator

from agents import get_agent
from api.dependencies.auth import get_current_user
from api.middleware.rate_limit import limiter
from services.core import get_service

logger = logging.getLogger(__name__)

router_pipeline = APIRouter(tags=["voice-pipeline"])

_AUDIO_TEMP_DIR = Path(tempfile.gettempdir()) / "superbot_audio"
_AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".m4a",
    ".wav",
    ".webm",
    ".ogg",
}
MAX_AUDIO_SIZE_MB = 25


# ─── Schemas ────────────────────────────────────────────────────────────────────


class PipelineResponse(BaseModel):
    """Resposta do pipeline completo STT→LLM→TTS."""

    transcript: Optional[str] = Field(
        None, description="Texto transcrito do áudio de entrada"
    )
    response_text: Optional[str] = Field(None, description="Resposta gerada pelo LLM")
    audio_filename: Optional[str] = Field(
        None, description="Nome do arquivo de áudio de resposta"
    )
    audio_url: Optional[str] = Field(
        None, description="URL para baixar o áudio de resposta"
    )
    language: str = Field("pt", description="Idioma detectado/usado")
    metrics: Dict = Field(
        default_factory=dict, description="Métricas de latência por etapa"
    )
    warning: Optional[str] = Field(
        None, description="Aviso não-fatal (ex: TTS falhou, retornando texto)"
    )


class StreamTTSRequest(BaseModel):
    """Request para streaming TTS."""

    text: str = Field(
        ..., min_length=1, max_length=4800, description="Texto a converter em áudio"
    )
    voice: Optional[str] = Field(
        None, description="Nome da voz (rachel, adam, bella, ...)"
    )
    language: str = Field("pt", description="Código do idioma (pt, en, es, ...)")

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Texto não pode ser vazio")
        return v.strip()


# ─── Helpers ────────────────────────────────────────────────────────────────────


def _get_pipeline_service():
    svc = get_service("voice_pipeline")
    if svc is None:
        raise HTTPException(status_code=503, detail="Voice pipeline indisponível")
    return svc


def _validate_audio_file(file: UploadFile) -> None:
    if file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Extensão '{ext}' não suportada. Use: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}",
            )


def _voice_name_to_id(voice_name: Optional[str], language: str) -> Optional[str]:
    from services.ai.elevenlabs_service import PORTUGUESE_VOICES

    if voice_name:
        return PORTUGUESE_VOICES.get(voice_name.lower())
    return None


# ─── Endpoints ──────────────────────────────────────────────────────────────────


@router_pipeline.post(
    "/pipeline",
    response_model=PipelineResponse,
    summary="Pipeline completo: áudio → LLM → áudio",
)
@limiter.limit("10/minute")
async def pipeline_endpoint(
    request: Request,
    audio: UploadFile = File(
        ..., description="Arquivo de áudio (mp3, wav, ogg, m4a, webm)"
    ),
    language: str = Form("pt"),
    voice: Optional[str] = Form(None),
    return_audio: bool = Form(True),
    current_user: Dict = Depends(get_current_user),
) -> PipelineResponse:
    """Pipeline completo de voz: áudio de entrada → resposta em áudio."""
    _validate_audio_file(audio)

    suffix = Path(audio.filename or "audio.ogg").suffix.lower()
    tmp_path = _AUDIO_TEMP_DIR / f"in_{uuid.uuid4().hex[:8]}{suffix}"

    try:
        content = await audio.read()
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

        audio_url = None
        if result.get("audio_filename"):
            audio_url = f"/api/voice/audio/{result['audio_filename']}"

        warning = None
        if result.get("error") and result.get("response_text"):
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
        raise HTTPException(
            status_code=500, detail=f"Erro no pipeline de voz: {str(e)}"
        )
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@router_pipeline.post(
    "/stream/tts",
    summary="Streaming TTS: texto → áudio em chunks",
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
)
async def pipeline_health(
    current_user: Dict = Depends(get_current_user),
) -> Dict:
    """Retorna status de cada componente do pipeline."""
    from services.core import get_service as _gs

    whisper_svc = _gs("whisper")
    elevenlabs_svc = _gs("elevenlabs")
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
            "status": "operational"
            if all([whisper_svc, orchestrator, elevenlabs_svc])
            else "degraded",
        },
    }
