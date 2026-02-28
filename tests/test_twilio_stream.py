"""
Tests for Twilio Media Streams WebSocket endpoint.
"""
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routes.twilio_stream import (
    _load_session,
    _run_stt,
    _send_error_and_close,
    _send_telegram_report,
    _text_to_twilio_audio,
)


# -- _load_session tests -----------------------------------------------------


class TestLoadSession:
    @pytest.mark.asyncio
    async def test_load_valid_session(self):
        """Loads session from pending registry."""
        from services.business.call_session import (
            _PENDING_CALLS,
            register_pending_call,
        )

        _PENDING_CALLS.clear()

        session_id = register_pending_call(
            objective="Test call",
            user_name="Test",
            language="en",
            phone_number="+353123456",
            telegram_chat_id=1,
            telegram_user_id=1,
        )

        session = await _load_session(
            session_id, "CA_test", "MZ_test"
        )

        assert session is not None
        assert session.call_sid == "CA_test"
        assert session.stream_sid == "MZ_test"
        assert session.objective == "Test call"

    @pytest.mark.asyncio
    async def test_load_missing_session(self):
        """Returns None for unknown session_id."""
        session = await _load_session(
            "doesnotexist", "CA1", "MZ1"
        )
        assert session is None

    @pytest.mark.asyncio
    async def test_load_empty_session_id(self):
        """Returns None for empty session_id."""
        session = await _load_session("", "CA1", "MZ1")
        assert session is None


# -- _run_stt tests -----------------------------------------------------------


class TestRunSTT:
    @pytest.mark.asyncio
    async def test_stt_empty_audio(self):
        """Empty audio returns empty string."""
        result = await _run_stt(b"", "en")
        assert result == ""

    @pytest.mark.asyncio
    async def test_stt_no_whisper_service(self):
        """No WhisperService returns empty string."""
        with patch(
            "services.get_service", return_value=None
        ):
            result = await _run_stt(
                b"RIFF" + b"\x00" * 100, "en"
            )
            assert result == ""

    @pytest.mark.asyncio
    async def test_stt_success(self):
        """Successful STT returns transcript."""
        mock_whisper = AsyncMock()
        mock_whisper.is_initialized.return_value = True
        mock_whisper.speech_to_text = AsyncMock(
            return_value={"text": "Hello world"}
        )

        with patch(
            "services.get_service",
            return_value=mock_whisper,
        ):
            import io
            import wave

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * 16000)
            wav_bytes = buf.getvalue()

            result = await _run_stt(wav_bytes, "en")
            assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_stt_initializes_if_needed(self):
        """Calls initialize() when service not initialized."""
        mock_whisper = AsyncMock()
        mock_whisper.is_initialized = MagicMock(return_value=False)
        mock_whisper.initialize = AsyncMock()
        mock_whisper.speech_to_text = AsyncMock(
            return_value={"text": "Initialized"}
        )

        with patch(
            "services.get_service",
            return_value=mock_whisper,
        ):
            import io
            import wave

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * 8000)
            wav_bytes = buf.getvalue()

            result = await _run_stt(wav_bytes, "pt")
            assert result == "Initialized"
            mock_whisper.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_stt_exception_returns_empty(self):
        """Exception during STT returns empty string."""
        mock_whisper = AsyncMock()
        mock_whisper.is_initialized.return_value = True
        mock_whisper.speech_to_text = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        with patch(
            "services.get_service",
            return_value=mock_whisper,
        ):
            import io
            import wave

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * 8000)
            wav_bytes = buf.getvalue()

            result = await _run_stt(wav_bytes, "en")
            assert result == ""


# -- _send_telegram_report tests ----------------------------------------------


class TestSendTelegramReport:
    @pytest.mark.asyncio
    async def test_report_with_fallback_bot(self):
        """Sends report via fallback telegram.Bot."""
        from services.business.call_session import CallSession

        session = CallSession(
            session_id="test123",
            objective="Test",
            user_name="Henrique",
            language="en",
            phone_number="+353123",
            telegram_chat_id=123456,
            telegram_user_id=789,
        )
        session.mark_objective_complete("Done!")
        session.finalize()

        mock_bot_instance = AsyncMock()

        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_BOT_TOKEN": "fake_token"},
            ),
            patch(
                "telegram.Bot",
                return_value=mock_bot_instance,
            ),
        ):
            await _send_telegram_report(session)
            mock_bot_instance.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_report_logs_on_failure(self):
        """Logs report if sending fails."""
        from services.business.call_session import CallSession

        session = CallSession(
            session_id="test123",
            objective="Test",
            user_name="Henrique",
            language="en",
            phone_number="+353123",
            telegram_chat_id=123456,
            telegram_user_id=789,
        )
        session.finalize()

        with patch(
            "telegram.Bot",
            side_effect=Exception("no bot"),
        ):
            # Should not raise
            await _send_telegram_report(session)


# -- _text_to_twilio_audio tests -----------------------------------------------


class TestTextToTwilioAudio:
    @pytest.mark.asyncio
    async def test_no_elevenlabs_service(self):
        """Returns 0.0 when ElevenLabs not available."""
        mock_ws = AsyncMock()

        with patch(
            "services.get_service", return_value=None
        ):
            dur = await _text_to_twilio_audio(
                mock_ws, "MZ_test", "Hello", "en"
            )
            assert dur == 0.0

    @pytest.mark.asyncio
    async def test_empty_mp3_returns_zero(self):
        """Returns 0.0 when TTS returns empty bytes."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized.return_value = True
        mock_el.text_to_speech = AsyncMock(return_value=b"")

        with patch(
            "services.get_service", return_value=mock_el
        ):
            dur = await _text_to_twilio_audio(
                mock_ws, "MZ_test", "Hello", "en"
            )
            assert dur == 0.0

    @pytest.mark.asyncio
    async def test_exception_returns_zero(self):
        """Returns 0.0 on exception."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized.return_value = True
        mock_el.text_to_speech = AsyncMock(
            side_effect=RuntimeError("TTS error")
        )

        with patch(
            "services.get_service", return_value=mock_el
        ):
            dur = await _text_to_twilio_audio(
                mock_ws, "MZ_test", "Hello", "pt"
            )
            assert dur == 0.0

    @pytest.mark.asyncio
    async def test_initializes_elevenlabs_if_needed(self):
        """Calls initialize() when ElevenLabs not initialized."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized = MagicMock(return_value=False)
        mock_el.initialize = AsyncMock()
        mock_el.text_to_speech = AsyncMock(return_value=b"")

        with patch(
            "services.get_service", return_value=mock_el
        ):
            await _text_to_twilio_audio(
                mock_ws, "MZ_test", "Hi", "en"
            )
            mock_el.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_sends_chunks_and_returns_duration(self):
        """Full success path: TTS + mulaw chunks + send."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized = MagicMock(return_value=True)
        mock_el.text_to_speech = AsyncMock(
            return_value=b"\xff" * 100
        )

        fake_chunks = ["AAAA", "BBBB", "CCCC"]

        with (
            patch(
                "services.get_service",
                return_value=mock_el,
            ),
            patch(
                "utils.audio_converter.mp3_to_mulaw_chunks",
                return_value=fake_chunks,
            ),
            patch(
                "services.voice_pipeline_service.DEFAULT_VOICES",
                {"en": "voice_en", "pt": "voice_pt"},
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            dur = await _text_to_twilio_audio(
                mock_ws, "MZ_test", "Hello there", "en"
            )
            assert dur == pytest.approx(0.06, abs=0.001)
            assert mock_ws.send_json.call_count == 3

    @pytest.mark.asyncio
    async def test_no_mulaw_chunks_returns_zero(self):
        """Returns 0.0 when mp3_to_mulaw_chunks returns empty."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized = MagicMock(return_value=True)
        mock_el.text_to_speech = AsyncMock(
            return_value=b"\xff" * 100
        )

        with (
            patch(
                "services.get_service",
                return_value=mock_el,
            ),
            patch(
                "utils.audio_converter.mp3_to_mulaw_chunks",
                return_value=[],
            ),
            patch(
                "services.voice_pipeline_service.DEFAULT_VOICES",
                {"en": "voice_en"},
            ),
        ):
            dur = await _text_to_twilio_audio(
                mock_ws, "MZ_test", "Hello", "en"
            )
            assert dur == 0.0


# -- _send_error_and_close tests ----------------------------------------------


class TestSendErrorAndClose:
    @pytest.mark.asyncio
    async def test_closes_websocket(self):
        """Sends error audio and closes WebSocket."""
        mock_ws = AsyncMock()

        with patch(
            "api.routes.twilio_stream._text_to_twilio_audio",
            new_callable=AsyncMock,
            return_value=1.0,
        ):
            await _send_error_and_close(mock_ws, "MZ_test")
            mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        """Doesn't raise even if everything fails."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(
            side_effect=Exception("already closed")
        )

        with patch(
            "api.routes.twilio_stream._text_to_twilio_audio",
            new_callable=AsyncMock,
            side_effect=Exception("TTS failed"),
        ):
            # Should not raise
            await _send_error_and_close(mock_ws, "MZ_test")


# -- _send_telegram_report (no token) ----------------------------------------


class TestSendTelegramReportNoToken:
    @pytest.mark.asyncio
    async def test_no_token_logs_warning(self):
        """No TELEGRAM_BOT_TOKEN logs warning."""
        from services.business.call_session import CallSession

        session = CallSession(
            session_id="test123",
            objective="Test",
            user_name="Henrique",
            language="en",
            phone_number="+353123",
            telegram_chat_id=123456,
            telegram_user_id=789,
        )
        session.finalize()

        with patch.dict(
            "os.environ", {}, clear=True
        ):
            # Should not raise
            await _send_telegram_report(session)


# -- Integration-style test ---------------------------------------------------


class TestTwilioStreamProtocol:
    def test_media_message_format(self):
        """Verify the Twilio media message JSON format."""
        chunk_b64 = base64.b64encode(b"\x80" * 160).decode(
            "ascii"
        )
        message = {
            "event": "media",
            "streamSid": "MZ_test_123",
            "media": {
                "payload": chunk_b64,
            },
        }
        serialized = json.dumps(message)
        deserialized = json.loads(serialized)
        assert deserialized["event"] == "media"
        assert deserialized["streamSid"] == "MZ_test_123"
        decoded = base64.b64decode(
            deserialized["media"]["payload"]
        )
        assert len(decoded) == 160

    def test_start_event_parsing(self):
        """Verify parsing of Twilio start event."""
        start_event = {
            "event": "start",
            "start": {
                "streamSid": "MZ_abc123",
                "callSid": "CA_def456",
                "customParameters": {
                    "session_id": "sess_xyz789",
                },
            },
        }
        start_data = start_event.get("start", {})
        assert start_data.get("streamSid") == "MZ_abc123"
        assert start_data.get("callSid") == "CA_def456"
        custom = start_data.get("customParameters", {})
        assert custom.get("session_id") == "sess_xyz789"
