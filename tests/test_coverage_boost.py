# -*- coding: utf-8 -*-
"""
Coverage boost tests — exercise uncovered code paths in low-coverage modules.

Target: +50 statements to push coverage from 78.64% to ≥79%.
"""

import audioop
import os
import struct

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.crypto_service import CryptoService  # noqa: E402
from services.integrations.gmail_service import (  # noqa: E402
    _extract_body,
    _extract_email,
    _extract_name,
)
from services.integrations.tracking_service import (  # noqa: E402
    CARRIER_CODES,
    TrackingService,
    _fmt_date,
    _parse_event,
    _STATUS_MAP,
)
from services.integrations.twilio_service import (  # noqa: E402
    PHONE_POOL,
    _best_number,
    _utcnow,
)
from services.integrations.youtube_service import (  # noqa: E402
    _format_count,
    _iso_to_readable,
    YouTubeService,
)
from utils.audio_converter import (
    calculate_rms,
    is_speech,
    mulaw_chunks_to_wav,
    mulaw_duration_seconds,
    mulaw_to_pcm,
    pcm_to_wav_bytes,
    resample_pcm,
    wav_duration_seconds,
)


class TestAudioConverter:
    """Tests for audio_converter utility functions."""

    def test_mulaw_to_pcm(self):
        """mulaw_to_pcm converts µ-law bytes to PCM."""
        # 160 bytes of silence (µ-law 0xFF = silence)
        mulaw = b"\xff" * 160
        pcm = mulaw_to_pcm(mulaw)
        # PCM is 2 bytes per sample, so 160 mulaw → 320 PCM
        assert len(pcm) == 320

    def test_resample_pcm_same_rate(self):
        """resample_pcm returns input unchanged when rates match."""
        data = b"\x00\x00" * 100
        result = resample_pcm(data, 8000, 8000)
        assert result == data

    def test_resample_pcm_different_rate(self):
        """resample_pcm resamples 8kHz → 16kHz."""
        data = b"\x00\x00" * 800  # 800 samples
        result = resample_pcm(data, 8000, 16000)
        # 16kHz should produce roughly 2x samples
        assert len(result) > len(data)

    def test_pcm_to_wav_bytes(self):
        """pcm_to_wav_bytes wraps PCM in WAV container."""
        pcm = b"\x00\x00" * 1600
        wav = pcm_to_wav_bytes(pcm, 16000)
        # WAV has header + PCM data
        assert len(wav) > len(pcm)
        # Should start with RIFF header
        assert wav[:4] == b"RIFF"

    def test_mulaw_chunks_to_wav_empty(self):
        """mulaw_chunks_to_wav returns empty bytes for empty input."""
        assert mulaw_chunks_to_wav(b"") == b""

    def test_mulaw_chunks_to_wav_valid(self):
        """mulaw_chunks_to_wav converts µ-law to WAV."""
        mulaw = b"\xff" * 800  # 800 bytes = 0.1s at 8kHz
        wav = mulaw_chunks_to_wav(mulaw)
        assert len(wav) > 0
        assert wav[:4] == b"RIFF"

    def test_calculate_rms_empty(self):
        """calculate_rms returns 0.0 for empty bytes."""
        assert calculate_rms(b"") == 0.0

    def test_calculate_rms_silence(self):
        """calculate_rms returns low value for silence."""
        silence = b"\x00\x00" * 160
        rms = calculate_rms(silence, 2)
        assert rms == 0.0

    def test_calculate_rms_loud(self):
        """calculate_rms returns positive for loud audio."""
        # Create a simple sine-ish pattern (alternating max values)
        loud = struct.pack("<" + "h" * 160, *([32000, -32000] * 80))
        rms = calculate_rms(loud, 2)
        assert rms > 0

    def test_calculate_rms_invalid_data(self):
        """calculate_rms returns 0.0 for invalid data."""
        assert calculate_rms(b"\x00", 2) == 0.0  # odd length → audioop error

    def test_is_speech_empty(self):
        """is_speech returns False for empty bytes."""
        assert is_speech(b"") is False

    def test_is_speech_silence(self):
        """is_speech returns False for silence."""
        silence = b"\xff" * 160  # µ-law silence
        assert is_speech(silence, threshold=50) is False

    def test_is_speech_loud(self):
        """is_speech returns True for loud audio."""
        # Create loud PCM, then convert to µ-law
        loud_pcm = struct.pack("<" + "h" * 160, *([20000, -20000] * 80))
        loud_mulaw = audioop.lin2ulaw(loud_pcm, 2)
        assert is_speech(loud_mulaw, threshold=50) is True

    def test_mulaw_duration_seconds_empty(self):
        """mulaw_duration_seconds returns 0.0 for empty bytes."""
        assert mulaw_duration_seconds(b"") == 0.0

    def test_mulaw_duration_seconds_valid(self):
        """mulaw_duration_seconds calculates correctly."""
        # 8000 bytes = 1 second at 8kHz
        assert mulaw_duration_seconds(b"\xff" * 8000) == 1.0
        assert mulaw_duration_seconds(b"\xff" * 4000) == 0.5

    def test_wav_duration_seconds_empty(self):
        """wav_duration_seconds returns 0.0 for empty bytes."""
        assert wav_duration_seconds(b"") == 0.0

    def test_wav_duration_seconds_invalid(self):
        """wav_duration_seconds returns 0.0 for invalid data."""
        assert wav_duration_seconds(b"not a wav file") == 0.0

    def test_wav_duration_seconds_valid(self):
        """wav_duration_seconds calculates correctly for valid WAV."""
        pcm = b"\x00\x00" * 16000  # 1 second at 16kHz
        wav = pcm_to_wav_bytes(pcm, 16000)
        duration = wav_duration_seconds(wav)
        assert abs(duration - 1.0) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 2: services/integrations/tracking_service.py
# Lines: helpers, _validate_number, _resolve_carrier_code, _fmt_date,
#        _parse_event, _normalize, _STATUS_MAP
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrackingHelpers:
    """Tests for tracking_service helper functions."""

    def test_fmt_date_valid(self):
        """_fmt_date formats UTC timestamp correctly."""
        result = _fmt_date("2026-03-04T15:30:00+00:00")
        assert "04/03/2026" in result
        assert "15:30" in result

    def test_fmt_date_none(self):
        """_fmt_date returns empty string for None."""
        assert _fmt_date(None) == ""

    def test_fmt_date_empty(self):
        """_fmt_date returns empty string for empty string."""
        assert _fmt_date("") == ""

    def test_fmt_date_invalid(self):
        """_fmt_date returns truncated string for invalid date."""
        result = _fmt_date("not-a-date-at-all-1234567890")
        assert len(result) <= 16

    def test_fmt_date_zulu(self):
        """_fmt_date handles Z suffix."""
        result = _fmt_date("2026-03-04T10:00:00Z")
        assert "04/03/2026" in result

    def test_parse_event(self):
        """_parse_event normalizes 17TRACK event dict."""
        ev = {"a": "2026-03-04T10:00:00Z", "b": "Arrived", "c": "Dublin"}
        result = _parse_event(ev)
        assert result["location"] == "Dublin"
        assert result["message"] == "Arrived"
        assert "04/03/2026" in result["date"]

    def test_parse_event_empty(self):
        """_parse_event handles empty dict."""
        result = _parse_event({})
        assert result["location"] == ""
        assert result["message"] == ""

    def test_parse_event_z_field(self):
        """_parse_event prefers 'z' over 'b' for message."""
        ev = {"b": "raw", "z": "formatted", "d": "Ireland"}
        result = _parse_event(ev)
        assert result["message"] == "formatted"
        assert result["location"] == "Ireland"

    def test_status_map_coverage(self):
        """_STATUS_MAP has expected entries."""
        assert 0 in _STATUS_MAP
        assert 40 in _STATUS_MAP  # Delivered
        assert 20 in _STATUS_MAP  # In transit

    def test_carrier_codes_coverage(self):
        """CARRIER_CODES has common carriers."""
        assert "an post" in CARRIER_CODES
        assert "dhl" in CARRIER_CODES
        assert "fedex" in CARRIER_CODES
        assert "correios" in CARRIER_CODES


class TestTrackingValidation:
    """Tests for TrackingService validation methods."""

    def test_validate_number_valid(self):
        """Valid tracking numbers pass validation."""
        TrackingService._validate_number("AB123456789CD")

    def test_validate_number_too_short(self):
        """Short numbers are rejected."""
        with pytest.raises(ValueError, match="inválido"):
            TrackingService._validate_number("AB")

    def test_validate_number_too_long(self):
        """Long numbers are rejected."""
        with pytest.raises(ValueError, match="inválido"):
            TrackingService._validate_number("A" * 51)

    def test_validate_number_empty(self):
        """Empty string is rejected."""
        with pytest.raises(ValueError):
            TrackingService._validate_number("")

    def test_resolve_carrier_code_int(self):
        """Int carrier code is returned as-is."""
        assert TrackingService._resolve_carrier_code(100011) == 100011

    def test_resolve_carrier_code_str_name(self):
        """String carrier name is resolved."""
        assert TrackingService._resolve_carrier_code("an post") == 100011
        assert TrackingService._resolve_carrier_code("DHL") == 300004

    def test_resolve_carrier_code_str_numeric(self):
        """Numeric string is converted to int."""
        assert TrackingService._resolve_carrier_code("100011") == 100011

    def test_resolve_carrier_code_unknown(self):
        """Unknown carrier returns None."""
        assert TrackingService._resolve_carrier_code("unknown_carrier_xyz") is None

    def test_resolve_carrier_code_none(self):
        """None returns None."""
        assert TrackingService._resolve_carrier_code(None) is None

    def test_normalize(self):
        """_normalize produces expected output structure."""
        svc = TrackingService.__new__(TrackingService)
        item = {
            "carrier": 100011,
            "track": {
                "b": 20,
                "c": "20.01",
                "d": "IE",
                "e": "CN",
                "w2": "An Post",
                "z0": {"a": "2026-03-04T10:00:00Z", "b": "In transit", "c": "Dublin"},
                "z1": [
                    {"a": "2026-03-04T10:00:00Z", "b": "In transit", "c": "Dublin"},
                    {"a": "2026-03-03T08:00:00Z", "b": "Departed", "c": "Shanghai"},
                ],
            },
        }
        result = svc._normalize("AB123456789CD", item)
        assert result["tracking_number"] == "AB123456789CD"
        assert result["carrier"] == "An Post"
        assert result["status_code"] == 20
        assert result["status_emoji"] == "🚚"
        assert result["delivered"] is False
        assert result["total_events"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 3: services/integrations/twilio_service.py
# Lines: _best_number, _utcnow, pool helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestTwilioHelpers:
    """Tests for twilio_service helper functions."""

    def test_utcnow_returns_aware(self):
        """_utcnow returns timezone-aware datetime."""
        dt = _utcnow()
        assert dt.tzinfo is not None

    def test_best_number_us(self):
        """_best_number returns US number for US destination."""
        result = _best_number("US")
        assert result is not None
        assert result["id"] == "us_1"

    def test_best_number_default(self):
        """_best_number returns fallback for unknown country."""
        result = _best_number("ZZ")
        assert result is not None

    def test_best_number_no_active(self):
        """_best_number returns None if no active numbers."""
        with patch(
            "services.integrations.twilio_service.PHONE_POOL",
            [{"active": False, "number": None, "region": []}],
        ):
            result = _best_number("US")
            assert result is None

    def test_phone_pool_structure(self):
        """PHONE_POOL has expected structure."""
        assert len(PHONE_POOL) >= 1
        us = [n for n in PHONE_POOL if n["id"] == "us_1"]
        assert len(us) == 1
        assert us[0]["active"] is True
        assert us[0]["number"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 4: utils/__init__.py (67% → 100%)
# ═══════════════════════════════════════════════════════════════════════════════


class TestUtilsInit:
    """Tests that utils package exports are accessible."""

    def test_imports_available(self):
        """Key functions are importable from utils."""
        from utils import (
            calculate_rms,
            is_speech,
            mulaw_chunks_to_wav,
            mulaw_duration_seconds,
        )

        assert callable(calculate_rms)
        assert callable(is_speech)
        assert callable(mulaw_chunks_to_wav)
        assert callable(mulaw_duration_seconds)


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 5: services/integrations/youtube_service.py
# Lines: 28, 57-63, 66-80, 83-85 (helpers + init + health + cleanup)
# ═══════════════════════════════════════════════════════════════════════════════


class TestYouTubeHelpers:
    """Tests for YouTube helper functions."""

    def test_iso_to_readable_hours(self):
        """ISO duration with hours."""
        assert _iso_to_readable("PT1H30M15S") == "1:30:15"

    def test_iso_to_readable_minutes(self):
        """ISO duration without hours."""
        assert _iso_to_readable("PT5M30S") == "5:30"

    def test_iso_to_readable_seconds_only(self):
        """ISO duration with seconds only."""
        assert _iso_to_readable("PT45S") == "0:45"

    def test_iso_to_readable_invalid(self):
        """Invalid duration returns as-is."""
        assert _iso_to_readable("invalid") == "invalid"

    def test_iso_to_readable_none(self):
        """None duration."""
        result = _iso_to_readable(None)
        assert result is None or result == ""

    def test_format_count_millions(self):
        """Format count >= 1M."""
        assert _format_count(1_500_000) == "1.5M"

    def test_format_count_thousands(self):
        """Format count >= 1K."""
        assert _format_count(2_500) == "2.5K"

    def test_format_count_small(self):
        """Format count < 1K."""
        assert _format_count(42) == "42"

    def test_format_count_invalid(self):
        """Format count with invalid input."""
        assert _format_count("not_a_number") == "N/A"

    def test_format_count_none(self):
        """Format count with None."""
        assert _format_count(None) == "N/A"


class TestYouTubeServiceInit:
    """Tests for YouTubeService initialization edge cases."""

    @pytest.mark.asyncio
    async def test_init_without_api_key(self):
        """Init raises without YOUTUBE_API_KEY."""
        from services.core import ServiceUnavailableError

        svc = YouTubeService.__new__(YouTubeService)
        svc.name = "youtube"
        svc.logger = __import__("logging").getLogger("test")

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ServiceUnavailableError):
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_health_check_no_key(self):
        """Health check returns False without key."""
        svc = YouTubeService.__new__(YouTubeService)
        svc._api_key = None
        svc._client = None
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_no_client(self):
        """Cleanup with no client does nothing."""
        svc = YouTubeService.__new__(YouTubeService)
        svc._client = None
        await svc._cleanup()
        assert svc._client is None

    @pytest.mark.asyncio
    async def test_cleanup_with_client(self):
        """Cleanup closes client."""
        svc = YouTubeService.__new__(YouTubeService)
        svc._client = AsyncMock()
        await svc._cleanup()
        assert svc._client is None


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 6: services/voice_pipeline_service.py
# Lines: 76-91, 94 (init + health check)
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoicePipelineInit:
    """Tests for VoicePipelineService initialization."""

    @pytest.mark.asyncio
    async def test_init_no_services(self):
        """Init without whisper or elevenlabs logs warnings."""
        from services.voice_pipeline_service import VoicePipelineService

        svc = VoicePipelineService.__new__(VoicePipelineService)
        svc.name = "voice_pipeline"
        svc.logger = __import__("logging").getLogger("test")
        svc._whisper = None
        svc._elevenlabs = None

        with patch("services.core.get_service", return_value=None):
            await svc._initialize()

        assert svc._whisper is None
        assert svc._elevenlabs is None

    @pytest.mark.asyncio
    async def test_init_with_uninitialized_services(self):
        """Init initializes services that aren't ready yet."""
        from services.voice_pipeline_service import VoicePipelineService

        mock_whisper = MagicMock()
        mock_whisper.is_initialized.return_value = False
        mock_whisper.initialize = AsyncMock()
        mock_elevenlabs = MagicMock()
        mock_elevenlabs.is_initialized.return_value = False
        mock_elevenlabs.initialize = AsyncMock()

        svc = VoicePipelineService.__new__(VoicePipelineService)
        svc.name = "voice_pipeline"
        svc.logger = __import__("logging").getLogger("test")
        svc._whisper = None
        svc._elevenlabs = None

        def _fake_get_service(name):
            return {"whisper": mock_whisper, "elevenlabs": mock_elevenlabs}.get(name)

        with patch("services.core.get_service", side_effect=_fake_get_service):
            await svc._initialize()

        mock_whisper.initialize.assert_awaited_once()
        mock_elevenlabs.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_with_youtube_api_key(self):
        """YouTubeService init succeeds with valid API key."""
        svc = YouTubeService.__new__(YouTubeService)
        svc.name = "youtube"
        svc.logger = __import__("logging").getLogger("test")
        svc._api_key = None
        svc._client = None

        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key-123"}):
            await svc._initialize()

        assert svc._api_key == "test-key-123"
        assert svc._client is not None
        # Cleanup
        await svc._client.aclose()

    @pytest.mark.asyncio
    async def test_health_check_no_services(self):
        """Health check returns False without any service."""
        from services.voice_pipeline_service import VoicePipelineService

        svc = VoicePipelineService.__new__(VoicePipelineService)
        svc._whisper = None
        svc._elevenlabs = None
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_with_whisper(self):
        """Health check returns True with whisper available."""
        from services.voice_pipeline_service import VoicePipelineService

        svc = VoicePipelineService.__new__(VoicePipelineService)
        svc._whisper = AsyncMock()
        svc._elevenlabs = None
        result = await svc._health_check()
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 7: services/business/crypto_service.py
# Lines: 115-123 (init), 129-131 (health_check exception)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCryptoServiceInit:
    """Tests for CryptoService initialization and health check."""

    @pytest.mark.asyncio
    async def test_initialize_creates_client(self):
        """_initialize creates an httpx client."""
        svc = CryptoService.__new__(CryptoService)
        svc.name = "crypto"
        svc.logger = __import__("logging").getLogger("test")
        svc._http = None
        svc._cache = {}

        await svc._initialize()

        assert svc._http is not None
        # Cleanup
        await svc._http.aclose()

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        """_health_check returns False on network error."""
        svc = CryptoService.__new__(CryptoService)
        svc.name = "crypto"
        svc.logger = __import__("logging").getLogger("test")
        mock_http = AsyncMock()
        mock_http.get.side_effect = Exception("Connection refused")
        svc._http = mock_http

        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """_health_check returns True on 200."""
        svc = CryptoService.__new__(CryptoService)
        svc.name = "crypto"
        svc.logger = __import__("logging").getLogger("test")
        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http.get.return_value = mock_resp
        svc._http = mock_http

        result = await svc._health_check()
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 8: services/integrations/gmail_service.py
# Lines: 139, 141 (list_emails query params), 203-205 (metadata exception)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGmailHelpers:
    """Tests for Gmail module-level helper functions."""

    def test_extract_email_with_brackets(self):
        assert _extract_email("João <joao@email.com>") == "joao@email.com"

    def test_extract_email_plain(self):
        assert _extract_email("joao@email.com") == "joao@email.com"

    def test_extract_email_empty(self):
        assert _extract_email("") == ""

    def test_extract_name_with_brackets(self):
        assert _extract_name("João Silva <joao@email.com>") == "João Silva"

    def test_extract_name_quoted(self):
        assert _extract_name('"João Silva" <joao@email.com>') == "João Silva"

    def test_extract_name_plain(self):
        assert _extract_name("joao@email.com") == "joao@email.com"

    def test_extract_body_text_plain(self):
        import base64

        encoded = base64.urlsafe_b64encode(b"Hello world").decode()
        payload = {"mimeType": "text/plain", "body": {"data": encoded}}
        assert _extract_body(payload) == "Hello world"

    def test_extract_body_text_html(self):
        import base64

        html = "<p>Hello <b>world</b></p>"
        encoded = base64.urlsafe_b64encode(html.encode()).decode()
        payload = {"mimeType": "text/html", "body": {"data": encoded}}
        result = _extract_body(payload)
        assert "Hello" in result
        assert "<p>" not in result

    def test_extract_body_multipart(self):
        import base64

        encoded = base64.urlsafe_b64encode(b"Found it").decode()
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": encoded}},
            ],
        }
        assert _extract_body(payload) == "Found it"

    def test_extract_body_empty(self):
        assert _extract_body({}) == ""

    def test_extract_body_no_data(self):
        payload = {"mimeType": "text/plain", "body": {}}
        assert _extract_body(payload) == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 9: agents/specialized/twilio_agent.py
# Lines: 91, 98-101 (_resolve_user_name fallback paths)
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveUserName:
    """Tests for twilio_agent._resolve_user_name."""

    def test_from_user_dict_full_name(self):
        from agents.specialized.twilio_agent import _resolve_user_name

        result = _resolve_user_name({"user": {"full_name": "Henrique"}})
        assert result == "Henrique"

    def test_from_user_name_key(self):
        from agents.specialized.twilio_agent import _resolve_user_name

        result = _resolve_user_name({"user_name": "Henrique"})
        assert result == "Henrique"

    def test_from_username(self):
        from agents.specialized.twilio_agent import _resolve_user_name

        result = _resolve_user_name({"username": "henrique_bot"})
        assert result == "henrique_bot"

    def test_fallback_user(self):
        from agents.specialized.twilio_agent import _resolve_user_name

        result = _resolve_user_name({})
        assert result == "User"


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 10: agents/specialized/translate_agent.py
# Lines: 61-63 (_normalize_lang wrapper)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTranslateAgentNormalizeLang:
    """Tests for translate_agent._normalize_lang."""

    def test_normalize_known_language(self):
        from agents.specialized.translate_agent import _normalize_lang

        result = _normalize_lang("english")
        assert result == "en" or result == "english"

    def test_normalize_code(self):
        from agents.specialized.translate_agent import _normalize_lang

        result = _normalize_lang("pt")
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 11: agents/specialized/traffic_agent.py
# Lines: 45-53 (_get_service method)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrafficAgentGetService:
    """Tests for traffic_agent._get_service."""

    @pytest.mark.asyncio
    async def test_get_service_success(self):
        from agents.specialized.traffic_agent import TrafficAgent

        agent = TrafficAgent.__new__(TrafficAgent)
        agent.name = "traffic"
        agent.logger = __import__("logging").getLogger("test")

        mock_svc = AsyncMock()
        with patch(
            "agents.specialized.traffic_agent.get_service",
            return_value=mock_svc,
        ):
            result = await agent._get_traffic_service()

        assert result is mock_svc
        mock_svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_service_none(self):
        from agents.specialized.traffic_agent import TrafficAgent

        agent = TrafficAgent.__new__(TrafficAgent)
        agent.name = "traffic"
        agent.logger = __import__("logging").getLogger("test")

        with patch(
            "agents.specialized.traffic_agent.get_service",
            return_value=None,
        ):
            result = await agent._get_traffic_service()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_service_exception(self):
        from agents.specialized.traffic_agent import TrafficAgent

        agent = TrafficAgent.__new__(TrafficAgent)
        agent.name = "traffic"
        agent.logger = __import__("logging").getLogger("test")

        with patch(
            "agents.specialized.traffic_agent.get_service",
            side_effect=Exception("unavailable"),
        ):
            result = await agent._get_traffic_service()

        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# Alvo 12: agents/specialized/timer_agent.py
# Lines: 76, 89 (parse edge cases)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimerAgentParsing:
    """Tests for timer_agent parsing helpers."""

    def test_parse_clock_time_out_of_range(self):
        from agents.specialized.timer_agent import _parse_clock_time

        assert _parse_clock_time("25:00") is None

    def test_parse_clock_time_minute_out_of_range(self):
        from agents.specialized.timer_agent import _parse_clock_time

        assert _parse_clock_time("10:99") is None

    def test_parse_duration_no_match(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("hello world") is None

    def test_parse_duration_seconds(self):
        from agents.specialized.timer_agent import _parse_duration

        result = _parse_duration("30 seconds")
        assert result is not None
        assert result == 30.0

    def test_parse_duration_hours(self):
        from agents.specialized.timer_agent import _parse_duration

        result = _parse_duration("2 hours")
        assert result is not None
        assert result == 7200


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT CLEANER — LLM extraction paths (30 uncovered lines)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptCleanerExtraction:
    """Cover uncovered extraction helper paths in PromptCleanerService."""

    @pytest.mark.asyncio
    async def test_clean_car(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        result = await svc._clean_car("lock my car", {})
        assert result["action"] == "car"

    @pytest.mark.asyncio
    async def test_extract_location_no_client(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        svc._openai_client = None
        result = await svc._extract_location("Dublin weather")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_location_exception(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        svc._openai_client = AsyncMock()
        svc._openai_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("api error")
        )
        result = await svc._extract_location("weather in Cork")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_location_empty_response(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = ""
        svc._openai_client = AsyncMock()
        svc._openai_client.chat.completions.create = AsyncMock(return_value=resp)
        result = await svc._extract_location("weather")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_stock_symbol_no_client(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        svc._openai_client = None
        result = await svc._extract_stock_symbol("AAPL price")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_stock_symbol_invalid(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = ""
        svc._openai_client = AsyncMock()
        svc._openai_client.chat.completions.create = AsyncMock(return_value=resp)
        result = await svc._extract_stock_symbol("what is the stock?")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_stock_symbol_exception(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        svc._openai_client = AsyncMock()
        svc._openai_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("api error")
        )
        result = await svc._extract_stock_symbol("TSLA")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_traffic_no_client(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        svc._openai_client = None
        result = await svc._extract_traffic_locations("Dublin to Cork")
        assert result["origin"] == "Dublin"
        assert result["destination"] == "Cork"

    @pytest.mark.asyncio
    async def test_extract_traffic_bad_format(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = "just one place"
        svc._openai_client = AsyncMock()
        svc._openai_client.chat.completions.create = AsyncMock(return_value=resp)
        result = await svc._extract_traffic_locations("traffic")
        assert result["origin"] == "Dublin"

    @pytest.mark.asyncio
    async def test_extract_traffic_empty_parts(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = "|"
        svc._openai_client = AsyncMock()
        svc._openai_client.chat.completions.create = AsyncMock(return_value=resp)
        result = await svc._extract_traffic_locations("traffic")
        assert result["origin"] == "Dublin"

    @pytest.mark.asyncio
    async def test_extract_traffic_exception(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        svc._openai_client = AsyncMock()
        svc._openai_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        result = await svc._extract_traffic_locations("Dublin Cork")
        assert result["origin"] == "Dublin"

    @pytest.mark.asyncio
    async def test_clean_default(self):
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        result = await svc._clean_default("hello world", {})
        assert result["action"] == "chat"
        assert result["prompt"] == "hello world"

    @pytest.mark.asyncio
    async def test_clean_with_error_fallback(self):
        """Covers lines 137-146: cleaner raises exception."""
        from services.business.prompt_cleaner import PromptCleanerService

        svc = PromptCleanerService()
        svc._initialized = True
        svc._cleaners = {"bad": AsyncMock(side_effect=RuntimeError("boom"))}
        with patch.object(svc, "_track_call"):
            result = await svc.clean_for_agent("bad", "hello", {})
        assert result["prompt"] == "hello"
        assert result["action"] == "bad"


# ═══════════════════════════════════════════════════════════════════════════════
# CRYPTO SERVICE — uncovered error paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestCryptoServiceErrors:
    """Cover error/edge paths in CryptoService."""

    @pytest.mark.asyncio
    async def test_health_check_false_when_no_client(self):
        svc = CryptoService()
        svc._client = None
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        svc = CryptoService()
        svc._client = AsyncMock()
        svc._client.get = AsyncMock(side_effect=RuntimeError("conn error"))
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_get_price_coin_not_in_response(self):
        """Covers line 178: coin_id not in raw response."""
        svc = CryptoService()
        svc._initialized = True
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # empty, no coin_id key
        mock_response.raise_for_status = MagicMock()
        svc._http = AsyncMock()
        svc._http.get = AsyncMock(return_value=mock_response)
        svc._cache = {}
        with pytest.raises(ValueError, match="Dados não encontrados"):
            await svc.get_price("bitcoin")

    @pytest.mark.asyncio
    async def test_get_price_rate_limit(self):
        """Covers lines 170-171: 429 rate limit."""
        import httpx

        svc = CryptoService()
        svc._initialized = True
        svc._cache = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        error = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=mock_resp
        )
        svc._http = AsyncMock()
        svc._http.get = AsyncMock(side_effect=error)
        with pytest.raises(RuntimeError, match="Rate limit"):
            await svc.get_price("bitcoin")

    @pytest.mark.asyncio
    async def test_get_price_connection_error(self):
        """Covers line 173: connection error."""
        import httpx

        svc = CryptoService()
        svc._initialized = True
        svc._cache = {}
        svc._http = AsyncMock()
        svc._http.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        with pytest.raises(RuntimeError, match="Falha na conexão"):
            await svc.get_price("bitcoin")


# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH SERVICE — uncovered init/health paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestSearchServicePaths:
    """Cover uncovered paths in SearchService."""

    @pytest.mark.asyncio
    async def test_health_check_no_client(self):
        from services.business.search_service import SearchService

        svc = SearchService()
        svc._client = None
        svc._api_key = None
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        from services.business.search_service import SearchService

        svc = SearchService()
        svc._api_key = "fake"
        svc._client = AsyncMock()
        svc._client.post = AsyncMock(side_effect=RuntimeError("network error"))
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup(self):
        from services.business.search_service import SearchService

        svc = SearchService()
        svc._client = AsyncMock()
        await svc._cleanup()
        assert svc._client is None

    @pytest.mark.asyncio
    async def test_init_missing_key(self):
        from services.business.search_service import SearchService

        svc = SearchService()
        with patch.dict("os.environ", {}, clear=False):
            if "SERPER_API_KEY" in os.environ:
                del os.environ["SERPER_API_KEY"]
            with pytest.raises(Exception):
                await svc._initialize()
