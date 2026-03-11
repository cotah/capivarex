# -*- coding: utf-8 -*-
"""
Tests para VoicePipelineService e voice_pipeline_routes.

Cobre:
  - Pipeline completo (STT → LLM → TTS)
  - TTS only
  - STT only
  - Streaming TTS
  - Edge cases: serviço indisponível, áudio inválido, texto longo, fail-safe TTS
  - Endpoints FastAPI com TestClient
  - Segurança: tamanho máximo de arquivo, extensões permitidas
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_whisper_service():
    """Mock do WhisperService com resposta de transcrição."""
    svc = AsyncMock()
    svc.is_initialized.return_value = True
    svc.speech_to_text = AsyncMock(
        return_value={
            "text": "Qual é a previsão do tempo para hoje?",
            "language": "pt",
            "model": "whisper-1",
        }
    )
    return svc


@pytest.fixture
def mock_elevenlabs_service():
    """Mock do ElevenLabsService com resposta de áudio fake."""
    svc = AsyncMock()
    svc.is_initialized.return_value = True
    svc.text_to_speech = AsyncMock(
        return_value=b"\xff\xfb\x90" * 1000
    )  # fake MP3 bytes
    return svc


@pytest.fixture
def mock_orchestrator():
    """Mock do OrchestratorAgent com resposta de texto."""
    agent = AsyncMock()
    mock_response = MagicMock()
    mock_response.is_success.return_value = True
    mock_response.response = "Hoje o tempo estará ensolarado com temperatura de 28°C."
    mock_response.error = None
    agent.execute = AsyncMock(return_value=mock_response)
    return agent


@pytest.fixture
def fake_audio_file(tmp_path):
    """Arquivo de áudio fake para testes."""
    audio = tmp_path / "test_audio.ogg"
    audio.write_bytes(b"OGG_FAKE_AUDIO_CONTENT_FOR_TESTING")
    return str(audio)


@pytest.fixture
def pipeline_service(mock_whisper_service, mock_elevenlabs_service):
    """VoicePipelineService com dependências mockadas."""
    from services.voice_pipeline_service import VoicePipelineService

    svc = VoicePipelineService()
    svc._whisper = mock_whisper_service
    svc._elevenlabs = mock_elevenlabs_service
    svc._initialized = True
    return svc


# ═══════════════════════════════════════════════════════════════════════════════
# 1. VOICE PIPELINE SERVICE — HAPPY PATHS
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoicePipelineServiceHappyPath:
    """Testa o pipeline completo com mocks bem-sucedidos."""

    @pytest.mark.asyncio
    async def test_process_audio_full_pipeline(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Pipeline completo deve retornar transcript, response_text e audio_path."""
        with patch("agents.get_agent", return_value=mock_orchestrator):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="user_001",
                language="pt",
                return_audio=True,
            )

        assert result["transcript"] == "Qual é a previsão do tempo para hoje?"
        assert (
            result["response_text"]
            == "Hoje o tempo estará ensolarado com temperatura de 28°C."
        )
        assert result["audio_path"] is not None
        assert result["audio_filename"] is not None
        assert result["error"] is None
        assert Path(result["audio_path"]).exists()

    @pytest.mark.asyncio
    async def test_process_audio_metrics_populated(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Pipeline deve preencher métricas de latência por etapa."""
        with patch("agents.get_agent", return_value=mock_orchestrator):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="pt",
            )

        metrics = result["metrics"]
        assert "stt_latency_s" in metrics
        assert "llm_latency_s" in metrics
        assert "tts_latency_s" in metrics
        assert metrics["stt_latency_s"] >= 0
        assert metrics["llm_latency_s"] >= 0

    @pytest.mark.asyncio
    async def test_process_audio_no_audio_return(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Com return_audio=False, não deve chamar TTS nem retornar audio_path."""
        with patch("agents.get_agent", return_value=mock_orchestrator):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="pt",
                return_audio=False,
            )

        assert result["audio_path"] is None
        assert result["response_text"] is not None
        # ElevenLabs não deve ter sido chamado
        pipeline_service._elevenlabs.text_to_speech.assert_not_called()

    @pytest.mark.asyncio
    async def test_text_to_speech_only(self, pipeline_service, tmp_path):
        """TTS-only deve retornar bytes e salvar arquivo."""
        result = await pipeline_service.text_to_speech(
            text="Olá, como posso ajudar?",
            language="pt",
            save_to_file=True,
        )

        assert result["audio_bytes"] == b"\xff\xfb\x90" * 1000
        assert result["audio_path"] is not None
        assert result["filename"] is not None
        assert result["chars"] == len("Olá, como posso ajudar?")
        assert Path(result["audio_path"]).exists()

    @pytest.mark.asyncio
    async def test_text_to_speech_no_file(self, pipeline_service):
        """TTS-only com save_to_file=False deve retornar só bytes."""
        result = await pipeline_service.text_to_speech(
            text="Teste sem arquivo",
            language="pt",
            save_to_file=False,
        )

        assert result["audio_bytes"] is not None
        assert len(result["audio_bytes"]) > 0
        assert result["audio_path"] is None

    @pytest.mark.asyncio
    async def test_speech_to_text_only(self, pipeline_service, fake_audio_file):
        """STT-only deve retornar transcript e latência."""
        result = await pipeline_service.speech_to_text(
            audio_path=fake_audio_file,
            language="pt",
        )

        assert result["transcript"] == "Qual é a previsão do tempo para hoje?"
        assert result["language"] == "pt"
        assert result["latency_s"] >= 0

    @pytest.mark.asyncio
    async def test_stream_tts_yields_chunks(self, pipeline_service):
        """stream_tts deve produzir chunks de bytes."""
        chunks = []
        async for chunk in pipeline_service.stream_tts(
            text="Texto para streaming de áudio",
            language="pt",
            chunk_size=512,
        ):
            chunks.append(chunk)

        assert len(chunks) > 0
        total_bytes = sum(len(c) for c in chunks)
        assert total_bytes == len(b"\xff\xfb\x90" * 1000)

    @pytest.mark.asyncio
    async def test_voice_id_override(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """voice_id explícito deve ser passado para ElevenLabs."""
        custom_voice = "yoZ06aMxZJJ28mfd3POQ"  # sam
        with patch("agents.get_agent", return_value=mock_orchestrator):
            await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                voice_id=custom_voice,
                language="pt",
            )

        call_kwargs = pipeline_service._elevenlabs.text_to_speech.call_args
        assert call_kwargs.kwargs.get("voice_id") == custom_voice or (
            call_kwargs.args and custom_voice in call_kwargs.args
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FAIL-SAFE E DEGRADAÇÃO GRACIOСА
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoicePipelineFailSafe:
    """Testa comportamento quando partes do pipeline falham."""

    @pytest.mark.asyncio
    async def test_tts_failure_returns_text_anyway(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Se TTS falhar, deve retornar response_text com aviso (não crashar)."""
        pipeline_service._elevenlabs.text_to_speech = AsyncMock(
            side_effect=RuntimeError("ElevenLabs 503")
        )

        with patch("agents.get_agent", return_value=mock_orchestrator):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="pt",
                return_audio=True,
            )

        # Texto deve estar presente mesmo sem áudio
        assert result["response_text"] is not None
        assert result["audio_path"] is None
        assert "error" in result  # aviso de falha do TTS

    @pytest.mark.asyncio
    async def test_stt_failure_stops_pipeline(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Se STT falhar, pipeline deve parar e retornar erro (sem chamar LLM)."""
        pipeline_service._whisper.speech_to_text = AsyncMock(
            side_effect=RuntimeError("Whisper timeout")
        )

        with patch("agents.get_agent", return_value=mock_orchestrator):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="pt",
            )

        assert result["transcript"] is None
        assert result["response_text"] is None
        assert result["error"] is not None
        assert "STT" in result["error"]
        mock_orchestrator.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_stops_pipeline(self, pipeline_service, fake_audio_file):
        """Se LLM falhar, pipeline deve parar antes do TTS."""
        failing_orchestrator = AsyncMock()
        mock_response = MagicMock()
        mock_response.is_success.return_value = False
        mock_response.error = "LLM overloaded"
        failing_orchestrator.execute = AsyncMock(return_value=mock_response)

        with patch("agents.get_agent", return_value=failing_orchestrator):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="pt",
            )

        assert result["response_text"] is None
        assert result["audio_path"] is None
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_whisper_service_unavailable(
        self, mock_elevenlabs_service, fake_audio_file
    ):
        """Pipeline sem WhisperService deve retornar erro claro."""
        from services.voice_pipeline_service import VoicePipelineService

        svc = VoicePipelineService()
        svc._whisper = None  # sem Whisper
        svc._elevenlabs = mock_elevenlabs_service
        svc._initialized = True

        result = await svc.process_audio(
            audio_path=fake_audio_file,
            user_id="u1",
            language="pt",
        )

        assert result["error"] is not None
        assert result["transcript"] is None

    @pytest.mark.asyncio
    async def test_elevenlabs_service_unavailable_tts_only(self, mock_whisper_service):
        """text_to_speech sem ElevenLabsService deve lançar ServiceUnavailableError."""
        from services.voice_pipeline_service import VoicePipelineService
        from services.core import ServiceUnavailableError

        svc = VoicePipelineService()
        svc._whisper = mock_whisper_service
        svc._elevenlabs = None
        svc._initialized = True

        with pytest.raises(ServiceUnavailableError):
            await svc.text_to_speech(text="Olá", language="pt")

    @pytest.mark.asyncio
    async def test_orchestrator_unavailable(self, pipeline_service, fake_audio_file):
        """Se OrchestratorAgent não existir, pipeline deve retornar erro gracioso."""
        with patch("agents.get_agent", return_value=None):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="pt",
            )

        assert result["error"] is not None
        assert "Orchestrator" in result["error"] or "LLM" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoicePipelineEdgeCases:
    """Testa edge cases e limites do pipeline."""

    @pytest.mark.asyncio
    async def test_text_truncated_at_max_chars(self, pipeline_service):
        """Texto maior que TTS_MAX_CHARS deve ser truncado antes de enviar."""
        from services.voice_pipeline_service import TTS_MAX_CHARS

        long_text = "A" * (TTS_MAX_CHARS + 500)
        await pipeline_service.text_to_speech(text=long_text, language="pt")

        call_args = pipeline_service._elevenlabs.text_to_speech.call_args
        actual_text = call_args.kwargs.get("text") or call_args.args[0]
        assert len(actual_text) <= TTS_MAX_CHARS + 10  # +10 para "..."

    @pytest.mark.asyncio
    async def test_stream_tts_truncates_long_text(self, pipeline_service):
        """stream_tts deve truncar texto longo."""
        from services.voice_pipeline_service import TTS_MAX_CHARS

        long_text = "B" * (TTS_MAX_CHARS + 1000)
        chunks = []
        async for chunk in pipeline_service.stream_tts(text=long_text, language="pt"):
            chunks.append(chunk)

        # Deve ter completado sem erro
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_default_voice_by_language(self, pipeline_service):
        """Voz padrão deve variar por idioma."""
        from services.voice_pipeline_service import DEFAULT_VOICES

        # PT e EN devem ter vozes diferentes
        assert DEFAULT_VOICES.get("pt") != DEFAULT_VOICES.get("en")

    @pytest.mark.asyncio
    async def test_audio_output_is_saved_to_temp_dir(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Arquivo de áudio de saída deve estar no diretório temporário."""
        from services.voice_pipeline_service import AUDIO_TEMP_DIR

        with patch("agents.get_agent", return_value=mock_orchestrator):
            result = await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="pt",
            )

        if result["audio_path"]:
            assert str(AUDIO_TEMP_DIR) in result["audio_path"]

    @pytest.mark.asyncio
    async def test_audio_filename_unique_per_call(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Cada chamada deve gerar um filename único."""
        with patch("agents.get_agent", return_value=mock_orchestrator):
            r1 = await pipeline_service.process_audio(
                audio_path=fake_audio_file, user_id="u1", language="pt"
            )
            r2 = await pipeline_service.process_audio(
                audio_path=fake_audio_file, user_id="u1", language="pt"
            )

        assert r1["audio_filename"] != r2["audio_filename"]

    @pytest.mark.asyncio
    async def test_stt_only_without_elevenlabs(
        self, mock_whisper_service, fake_audio_file
    ):
        """speech_to_text não precisa do ElevenLabs."""
        from services.voice_pipeline_service import VoicePipelineService

        svc = VoicePipelineService()
        svc._whisper = mock_whisper_service
        svc._elevenlabs = None
        svc._initialized = True

        result = await svc.speech_to_text(audio_path=fake_audio_file, language="pt")
        assert result["transcript"] is not None

    @pytest.mark.asyncio
    async def test_english_language_uses_english_voice(
        self, pipeline_service, mock_orchestrator, fake_audio_file
    ):
        """Idioma inglês deve usar voz padrão de inglês."""
        from services.voice_pipeline_service import DEFAULT_VOICES

        with patch("agents.get_agent", return_value=mock_orchestrator):
            await pipeline_service.process_audio(
                audio_path=fake_audio_file,
                user_id="u1",
                language="en",
                return_audio=True,
            )

        call_args = pipeline_service._elevenlabs.text_to_speech.call_args
        voice_used = call_args.kwargs.get("voice_id") or (
            call_args.args[1] if len(call_args.args) > 1 else None
        )
        assert voice_used == DEFAULT_VOICES.get("en")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TESTES DE ROTA FASTAPI
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoicePipelineRoutes:
    """Testa os endpoints FastAPI do pipeline de voz."""

    @pytest.fixture
    def client(self, pipeline_service, mock_orchestrator):
        """TestClient com pipeline mockado."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.voice_pipeline_routes import router_pipeline
        from api.dependencies.auth import get_current_user
        from api.middleware.rate_limit import limiter

        app = FastAPI()
        # Setup rate limiter state (required by @limiter.limit decorator)
        app.state.limiter = limiter
        app.include_router(router_pipeline, prefix="/api/voice")

        # Override FastAPI dependency for auth
        app.dependency_overrides[get_current_user] = lambda: {"sub": "user_test"}

        with (
            patch(
                "api.routes.voice_pipeline_routes.get_service",
                return_value=pipeline_service,
            ),
            patch("agents.get_agent", return_value=mock_orchestrator),
        ):
            yield TestClient(app)

        app.dependency_overrides.clear()

    def test_pipeline_endpoint_success(self, client, fake_audio_file):
        """POST /api/voice/pipeline deve retornar 200 com transcript e response."""
        with open(fake_audio_file, "rb") as f:
            response = client.post(
                "/api/voice/pipeline",
                files={"audio": ("test.ogg", f, "audio/ogg")},
                data={"language": "pt", "return_audio": "true"},
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "transcript" in data
        assert "response_text" in data

    def test_pipeline_endpoint_invalid_extension(self, client, tmp_path):
        """POST /api/voice/pipeline com extensão inválida deve retornar 400."""
        bad_file = tmp_path / "audio.txt"
        bad_file.write_bytes(b"not audio")

        with open(bad_file, "rb") as f:
            response = client.post(
                "/api/voice/pipeline",
                files={"audio": ("audio.txt", f, "text/plain")},
                data={"language": "pt"},
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 400

    def test_pipeline_endpoint_file_too_large(self, client, tmp_path):
        """POST /api/voice/pipeline com arquivo > 25MB deve retornar 413."""
        big_file = tmp_path / "big.mp3"
        big_file.write_bytes(b"0" * (26 * 1024 * 1024))  # 26MB

        with open(big_file, "rb") as f:
            response = client.post(
                "/api/voice/pipeline",
                files={"audio": ("big.mp3", f, "audio/mpeg")},
                data={"language": "pt"},
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 413

    def test_pipeline_health_endpoint(self, client):
        """GET /api/voice/pipeline/health deve retornar estrutura de status."""
        response = client.get(
            "/api/voice/pipeline/health",
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "stt" in data
        assert "llm" in data
        assert "tts" in data
        assert "pipeline" in data

    def test_stream_tts_endpoint_success(self, client):
        """POST /api/voice/stream/tts deve retornar streaming response."""
        response = client.post(
            "/api/voice/stream/tts",
            json={
                "text": "Olá, como posso ajudar?",
                "language": "pt",
            },
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 200
        assert "audio" in response.headers.get("content-type", "")
        assert len(response.content) > 0

    def test_stream_tts_empty_text_rejected(self, client):
        """POST /api/voice/stream/tts com texto vazio deve retornar 422."""
        response = client.post(
            "/api/voice/stream/tts",
            json={"text": "   ", "language": "pt"},
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 422

    def test_stream_tts_text_too_long_rejected(self, client):
        """POST /api/voice/stream/tts com texto > 4800 chars deve retornar 422."""
        response = client.post(
            "/api/voice/stream/tts",
            json={"text": "X" * 5000, "language": "pt"},
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TESTES DE SERVIÇOS INDIVIDUAIS (WhisperService + ElevenLabsService)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhisperService:
    """Testa WhisperService com mock do cliente OpenAI."""

    @pytest.mark.asyncio
    async def test_speech_to_text_success(self, tmp_path):
        """speech_to_text deve retornar dict com 'text' e 'language'."""
        from services.media.whisper_service import WhisperService

        # Cria arquivo de áudio fake
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake ogg data")

        svc = WhisperService()
        mock_client = AsyncMock()
        mock_transcript = MagicMock()
        mock_transcript.text = "texto transcrito"
        mock_transcript.no_speech_prob = 0.0
        mock_transcript.segments = []
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=mock_transcript
        )

        svc.client = mock_client
        svc._initialized = True

        result = await svc.speech_to_text(
            audio_file_path=str(audio_file),
            language="pt",
        )

        assert result["text"] == "texto transcrito"
        assert result["language"] == "pt"
        assert result["model"] == "whisper-1"

    @pytest.mark.asyncio
    async def test_speech_to_text_silence_filtered(self, tmp_path):
        """speech_to_text deve retornar texto vazio quando no_speech_prob > 0.6."""
        from services.media.whisper_service import WhisperService

        audio_file = tmp_path / "silence.ogg"
        audio_file.write_bytes(b"fake silence data")

        svc = WhisperService()
        mock_client = AsyncMock()
        mock_transcript = MagicMock()
        mock_transcript.text = "tchau tchau"
        mock_transcript.no_speech_prob = 0.0
        # Simulate high no_speech_prob in segments (Whisper hallucination)
        mock_segment = MagicMock()
        mock_segment.no_speech_prob = 0.85
        mock_transcript.segments = [mock_segment]
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=mock_transcript
        )

        svc.client = mock_client
        svc._initialized = True

        result = await svc.speech_to_text(
            audio_file_path=str(audio_file),
            language="pt",
        )

        assert result["text"] == ""
        assert result["language"] == "pt"

    @pytest.mark.asyncio
    async def test_speech_to_text_file_not_found(self, tmp_path):
        """speech_to_text deve lançar exceção para arquivo inexistente."""
        from services.media.whisper_service import WhisperService

        svc = WhisperService()
        svc.client = AsyncMock()
        svc._initialized = True

        with pytest.raises(Exception):
            await svc.speech_to_text(
                audio_file_path="/nonexistent/path/audio.ogg",
                language="pt",
            )

    @pytest.mark.asyncio
    async def test_speech_to_text_api_error(self, tmp_path):
        """speech_to_text deve propagar erro da API OpenAI."""
        from services.media.whisper_service import WhisperService

        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake")

        svc = WhisperService()
        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=RuntimeError("API Error 429")
        )
        svc.client = mock_client
        svc._initialized = True

        with pytest.raises(Exception):
            await svc.speech_to_text(str(audio_file), language="pt")

    @pytest.mark.asyncio
    async def test_translate_audio_success(self, tmp_path):
        """translate_audio deve retornar texto traduzido para inglês."""
        from services.media.whisper_service import WhisperService

        audio_file = tmp_path / "test_pt.ogg"
        audio_file.write_bytes(b"fake pt audio")

        svc = WhisperService()
        mock_client = AsyncMock()
        mock_translation = MagicMock()
        mock_translation.text = "translated text in english"
        mock_client.audio.translations.create = AsyncMock(return_value=mock_translation)
        svc.client = mock_client
        svc._initialized = True

        result = await svc.translate_audio(audio_file_path=str(audio_file))

        assert result["text"] == "translated text in english"
        assert result["language"] == "en"

    def test_supported_languages_includes_portuguese(self):
        """SUPPORTED_LANGUAGES deve incluir português."""
        from services.media.whisper_service import SUPPORTED_LANGUAGES

        assert "pt" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES


class TestElevenLabsService:
    """Testa ElevenLabsService com mock do cliente HTTP."""

    @pytest.mark.asyncio
    async def test_text_to_speech_success(self):
        """text_to_speech deve retornar bytes de áudio."""
        from services.ai.elevenlabs_service import ElevenLabsService

        svc = ElevenLabsService()
        svc.api_key = "test_key_placeholder"
        svc._initialized = True

        fake_audio = b"\xff\xfb\x90" * 500

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_audio
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(
            "services.ai.elevenlabs_service.httpx.AsyncClient", return_value=mock_client
        ):
            result = await svc.text_to_speech(
                text="Olá, sou o Jarvis",
                voice_id="21m00Tcm4TlvDq8ikWAM",
            )

        assert result == fake_audio

    @pytest.mark.asyncio
    async def test_text_to_speech_api_error(self):
        """text_to_speech deve propagar erro HTTP."""
        from services.ai.elevenlabs_service import ElevenLabsService
        import httpx

        svc = ElevenLabsService()
        svc.api_key = "test_key_placeholder"
        svc._initialized = True

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with patch(
            "services.ai.elevenlabs_service.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(Exception):
                await svc.text_to_speech(text="teste", voice_id="any_id")

    def test_portuguese_voices_dict_not_empty(self):
        """PORTUGUESE_VOICES deve ter pelo menos 5 vozes configuradas."""
        from services.ai.elevenlabs_service import PORTUGUESE_VOICES

        assert len(PORTUGUESE_VOICES) >= 5
        assert "rachel" in PORTUGUESE_VOICES

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """_health_check deve retornar True quando API responde 200."""
        from services.ai.elevenlabs_service import ElevenLabsService

        svc = ElevenLabsService()
        svc.api_key = "test_key_placeholder"
        svc._initialized = True

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "services.ai.elevenlabs_service.httpx.AsyncClient", return_value=mock_client
        ):
            result = await svc._health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_fails_without_key(self):
        """_health_check deve retornar False sem API key."""
        from services.ai.elevenlabs_service import ElevenLabsService

        svc = ElevenLabsService()
        svc.api_key = None
        svc._initialized = True

        result = await svc._health_check()
        assert result is False
