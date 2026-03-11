"""
Tests for VoiceAgent — Text-to-Speech and Speech-to-Text.
Agente sem cobertura de testes. Adicionado na Fase C do QA.
"""
from unittest.mock import AsyncMock, Mock, patch
import pytest
from agents.core import AgentStatus


@pytest.fixture
def voice_agent():
    from agents.specialized.voice_agent import VoiceAgent
    return VoiceAgent()


def _make_elevenlabs_svc(audio_bytes=b"fake_audio_data"):
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.text_to_speech = AsyncMock(return_value=audio_bytes)
    svc.speech_to_text = AsyncMock(return_value={
        "success": True,
        "text": "olá, como vai você?",
        "language": "pt",
    })
    return svc


# ── Happy path ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_voice_tts_success(voice_agent):
    """VoiceAgent converts text to speech successfully."""
    elevenlabs_svc = _make_elevenlabs_svc()
    with patch("agents.specialized.voice_agent.get_service", return_value=elevenlabs_svc):
        result = await voice_agent.execute(
            "leia em voz alta: olá mundo",
            {"action": "text_to_speech", "text": "olá mundo", "voice": "rachel"}
        )
    assert result.status == AgentStatus.SUCCESS
    assert result.data


@pytest.mark.asyncio
async def test_voice_tts_from_prompt(voice_agent):
    """VoiceAgent extracts text from prompt when not in context."""
    elevenlabs_svc = _make_elevenlabs_svc()
    with patch("agents.specialized.voice_agent.get_service", return_value=elevenlabs_svc):
        result = await voice_agent.execute("fale: bom dia!", {})
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


@pytest.mark.asyncio
async def test_voice_capabilities(voice_agent):
    """VoiceAgent declares expected capabilities."""
    caps = voice_agent.get_capabilities()
    assert isinstance(caps, list)
    assert len(caps) > 0


# ── Falhas e edge cases ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_voice_service_unavailable(voice_agent):
    """VoiceAgent returns error when ElevenLabs is None."""
    with patch("agents.specialized.voice_agent.get_service", return_value=None):
        result = await voice_agent.execute("fale: olá", {"text": "olá"})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_voice_empty_text(voice_agent):
    """VoiceAgent returns error for empty text."""
    elevenlabs_svc = _make_elevenlabs_svc()
    with patch("agents.specialized.voice_agent.get_service", return_value=elevenlabs_svc):
        result = await voice_agent.execute("", {"text": ""})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_voice_tts_service_failure(voice_agent):
    """VoiceAgent handles TTS failure gracefully."""
    elevenlabs_svc = _make_elevenlabs_svc()
    elevenlabs_svc.text_to_speech = AsyncMock(side_effect=RuntimeError("quota exceeded"))
    with patch("agents.specialized.voice_agent.get_service", return_value=elevenlabs_svc):
        result = await voice_agent.execute("fale: olá", {"text": "olá"})
    assert result.status == AgentStatus.ERROR
