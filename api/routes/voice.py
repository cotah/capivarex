"""
Voice API Routes (Refactored)
Rotas para funcionalidades de voz (Text-to-Speech e Speech-to-Text).

Uses agents (get_agent) and services (get_service)
instead of direct imports from agents/ and services/.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents import get_agent
from api.dependencies.auth import get_current_user
from api.middleware.rate_limit import limiter
from services.core import get_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TextToSpeechRequest(BaseModel):
    """Request para conversao de texto em audio."""
    text: str
    voice: Optional[str] = "rachel"


class TextToSpeechResponse(BaseModel):
    """Response com informacoes do audio gerado."""
    audio_url: str
    text_length: int
    voice_used: str


class SpeechToTextResponse(BaseModel):
    """Response com texto transcrito."""
    text: str
    language: str
    audio_duration: Optional[float] = None


class VoicesResponse(BaseModel):
    """Response com vozes disponiveis."""
    voices: dict


class LanguagesResponse(BaseModel):
    """Response com idiomas suportados."""
    languages: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_voice_agent():
    """Get the voice agent from the registry."""
    agent = get_agent("voice")
    if agent is None:
        raise HTTPException(status_code=503, detail="Voice agent unavailable")
    return agent


def _get_elevenlabs_voices() -> Dict[str, str]:
    """Get available Portuguese voices from the ElevenLabs service."""
    elevenlabs_svc = get_service("elevenlabs")
    if elevenlabs_svc is not None:
        # The service module exposes PORTUGUESE_VOICES as a module-level constant
        from services.ai.elevenlabs_service import PORTUGUESE_VOICES
        return PORTUGUESE_VOICES
    # Fallback
    return {
        "rachel": "21m00Tcm4TlvDq8ikWAM",
        "adam": "pNInz6obpgDQGcFmaJgB",
        "antoni": "ErXwobaYiN019PkySvjV",
        "bella": "EXAVITQu4vr4xnSDxMaL",
        "elli": "MF3mGyEYCl7XYWbV9V6O",
        "josh": "TxGEqnHWrfWFTfGW9XjX",
        "arnold": "VR6AewLTigWG4xSOukaG",
        "sam": "yoZ06aMxZJJ28mfd3POQ",
    }


def _get_supported_languages() -> Dict[str, str]:
    """Get supported languages from the Whisper service."""
    whisper_svc = get_service("whisper")
    if whisper_svc is not None:
        from services.media.whisper_service import SUPPORTED_LANGUAGES
        return SUPPORTED_LANGUAGES
    # Fallback
    return {
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/text-to-speech", response_model=TextToSpeechResponse)
@limiter.limit("5/minute")
async def text_to_speech(request: Request, body: TextToSpeechRequest, current_user: Dict = Depends(get_current_user)) -> TextToSpeechResponse:
    """
    Converte texto em audio.

    Args:
        request: Objeto com texto e voz opcional.

    Returns:
        Informacoes do audio gerado.
    """
    try:
        if not body.text or len(body.text.strip()) == 0:
            raise HTTPException(status_code=400, detail="Texto nao pode ser vazio")

        # Criar diretorio temporario para audios
        temp_dir = Path(tempfile.gettempdir()) / "superbot_audio"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Gerar nome unico para o arquivo
        audio_filename = f"tts_{os.urandom(8).hex()}.mp3"
        audio_path = temp_dir / audio_filename

        # Executar agente de voz
        voice_agent = _get_voice_agent()
        result = await voice_agent.execute(
            prompt=body.text,
            context={
                "action": "text_to_speech",
                "text": body.text,
                "voice": body.voice,
                "output_path": str(audio_path),
            },
        )

        # Check result -- AgentResponse from refactored agent
        result_text = result.response if hasattr(result, "response") else str(result)
        if result_text.startswith("Erro"):
            raise HTTPException(status_code=500, detail=result_text)

        return TextToSpeechResponse(
            audio_url=f"/voice/audio/{audio_filename}",
            text_length=len(body.text),
            voice_used=body.voice,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in text-to-speech: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao converter texto em audio: {str(e)}",
        )


@router.post("/speech-to-text", response_model=SpeechToTextResponse)
async def speech_to_text(
    audio: UploadFile = File(...),
    language: str = Form("pt"),
    current_user: Dict = Depends(get_current_user),
) -> SpeechToTextResponse:
    """
    Converte audio em texto.

    Args:
        audio: Arquivo de audio (MP3, WAV, etc).
        language: Codigo do idioma (pt, en, es, etc).

    Returns:
        Texto transcrito.
    """
    try:
        audio_bytes = await audio.read()

        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Arquivo de audio vazio")

        voice_agent = _get_voice_agent()
        result = await voice_agent.execute(
            prompt="",
            context={
                "action": "speech_to_text",
                "audio_bytes": audio_bytes,
                "language": language,
            },
        )

        result_text = result.response if hasattr(result, "response") else str(result)
        if result_text.startswith("Erro"):
            raise HTTPException(status_code=500, detail=result_text)

        return SpeechToTextResponse(
            text=result_text,
            language=language,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in speech-to-text: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao converter audio em texto: {str(e)}",
        )


@router.get("/audio/{filename}")
async def get_audio(filename: str, current_user: Dict = Depends(get_current_user)) -> FileResponse:
    """
    Serve arquivo de audio gerado.

    Args:
        filename: Nome do arquivo de audio.

    Returns:
        Arquivo de audio.
    """
    try:
        temp_dir = Path(tempfile.gettempdir()) / "superbot_audio"
        audio_path = temp_dir / filename

        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo de audio nao encontrado")

        return FileResponse(
            path=str(audio_path),
            media_type="audio/mpeg",
            filename=filename,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error serving audio: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao servir audio: {str(e)}",
        )


@router.get("/voices", response_model=VoicesResponse)
async def get_voices(current_user: Dict = Depends(get_current_user)) -> VoicesResponse:
    """
    Retorna lista de vozes disponiveis.

    Returns:
        Dicionario com vozes disponiveis.
    """
    return VoicesResponse(voices=_get_elevenlabs_voices())


@router.get("/languages", response_model=LanguagesResponse)
async def get_languages(current_user: Dict = Depends(get_current_user)) -> LanguagesResponse:
    """
    Retorna lista de idiomas suportados.

    Returns:
        Dicionario com idiomas suportados.
    """
    return LanguagesResponse(languages=_get_supported_languages())
