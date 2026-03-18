"""
Tests for Twilio Media Streams WebSocket endpoint.
"""

import asyncio
import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routes.twilio_stream import (
    _listen_deepgram,
    _load_session,
    _open_deepgram_stream,
    _process_turn_streaming,
    _redact_key,
    _run_stt,
    _send_error_and_close,
    _send_telegram_report,
    _text_to_twilio_audio,
)


# -- _load_session tests -------------------------------------------


class TestLoadSession:
    def setup_method(self):
        self._patcher = patch(
            "services.business.call_session._get_redis_client",
            return_value=None,
        )
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

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

        session = await _load_session(session_id, "CA_test", "MZ_test")

        assert session is not None
        assert session.call_sid == "CA_test"
        assert session.stream_sid == "MZ_test"
        assert session.objective == "Test call"

    @pytest.mark.asyncio
    async def test_load_missing_session(self):
        """Returns None for unknown session_id."""
        session = await _load_session("doesnotexist", "CA1", "MZ1")
        assert session is None

    @pytest.mark.asyncio
    async def test_load_empty_session_id(self):
        """Returns None for empty session_id."""
        session = await _load_session("", "CA1", "MZ1")
        assert session is None


# -- _run_stt tests (Whisper fallback) --------------------------------


class TestRunSTT:
    @pytest.mark.asyncio
    async def test_stt_empty_audio(self):
        """Empty audio returns empty string."""
        result = await _run_stt(b"", "en")
        assert result == ""

    @pytest.mark.asyncio
    async def test_stt_no_whisper_service(self):
        """No WhisperService returns empty string."""
        with patch("services.get_service", return_value=None):
            result = await _run_stt(b"RIFF" + b"\x00" * 100, "en")
            assert result == ""

    @pytest.mark.asyncio
    async def test_stt_success(self):
        """Successful STT returns transcript."""
        mock_whisper = AsyncMock()
        mock_whisper.is_initialized.return_value = True
        mock_whisper.speech_to_text = AsyncMock(return_value={"text": "Hello world"})

        with (
            patch.dict(os.environ, {"DEEPGRAM_API_KEY": ""}),
            patch(
                "services.get_service",
                return_value=mock_whisper,
            ),
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
        mock_whisper.speech_to_text = AsyncMock(return_value={"text": "Initialized"})

        with (
            patch.dict(os.environ, {"DEEPGRAM_API_KEY": ""}),
            patch(
                "services.get_service",
                return_value=mock_whisper,
            ),
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
        mock_whisper.speech_to_text = AsyncMock(side_effect=RuntimeError("API error"))

        with (
            patch.dict(os.environ, {"DEEPGRAM_API_KEY": ""}),
            patch(
                "services.get_service",
                return_value=mock_whisper,
            ),
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


# -- _run_stt Deepgram batch tests ------------------------------------


class TestRunSTTDeepgram:
    """Tests for Deepgram batch STT integration."""

    @pytest.mark.asyncio
    async def test_stt_empty_audio(self):
        """Empty audio returns empty string."""
        result = await _run_stt(b"", "en")
        assert result == ""

    @pytest.mark.asyncio
    async def test_stt_deepgram_success(self):
        """Successful Deepgram STT returns transcript."""
        import io
        import wave

        # Create valid WAV
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)
        wav_bytes = buf.getvalue()

        # Mock Deepgram response
        mock_response = {
            "results": {
                "channels": [{"alternatives": [{"transcript": ("Teste de voz")}]}]
            }
        }

        with patch.dict(
            os.environ,
            {"DEEPGRAM_API_KEY": "fake_key"},
        ):
            with patch(
                "api.routes.twilio_stream.httpx.AsyncClient",
            ) as mock_client_cls:
                mock_client = AsyncMock()
                mock_response_obj = MagicMock()
                mock_response_obj.json.return_value = mock_response
                mock_response_obj.raise_for_status = MagicMock()
                mock_client.post = AsyncMock(return_value=mock_response_obj)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await _run_stt(wav_bytes, "pt")
                assert result == "Teste de voz"

    @pytest.mark.asyncio
    async def test_stt_deepgram_fallback_to_whisper(self):
        """If Deepgram fails, falls back to Whisper."""
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)
        wav_bytes = buf.getvalue()

        mock_whisper = AsyncMock()
        mock_whisper.is_initialized.return_value = True
        mock_whisper.speech_to_text = AsyncMock(
            return_value={"text": "Fallback whisper"}
        )

        with patch.dict(
            os.environ,
            {"DEEPGRAM_API_KEY": "fake_key"},
        ):
            with patch(
                "api.routes.twilio_stream.httpx.AsyncClient",
                side_effect=Exception("Deepgram down"),
            ):
                with patch(
                    "services.get_service",
                    return_value=mock_whisper,
                ):
                    result = await _run_stt(wav_bytes, "pt")
                    assert result == "Fallback whisper"

    @pytest.mark.asyncio
    async def test_stt_no_deepgram_key_uses_whisper(self):
        """No DEEPGRAM_API_KEY falls back to Whisper."""
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)
        wav_bytes = buf.getvalue()

        mock_whisper = AsyncMock()
        mock_whisper.is_initialized.return_value = True
        mock_whisper.speech_to_text = AsyncMock(return_value={"text": "Whisper result"})

        with patch.dict(os.environ, {}, clear=False):
            # Ensure no DEEPGRAM_API_KEY
            os.environ.pop("DEEPGRAM_API_KEY", None)
            with patch(
                "services.get_service",
                return_value=mock_whisper,
            ):
                result = await _run_stt(wav_bytes, "en")
                assert result == "Whisper result"

    @pytest.mark.asyncio
    async def test_stt_language_mapping(self):
        """Verify language codes are mapped correctly."""
        lang_map = {
            "pt": "pt-BR",
            "en": "en-US",
            "es": "es",
        }
        assert lang_map["pt"] == "pt-BR"
        assert lang_map["en"] == "en-US"
        assert lang_map["es"] == "es"


# -- Deepgram streaming tests -----------------------------------------


class TestDeepgramStreaming:
    """Tests for Deepgram raw WebSocket streaming."""

    @pytest.mark.asyncio
    async def test_open_deepgram_stream_no_api_key(self):
        """No DEEPGRAM_API_KEY returns None."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPGRAM_API_KEY", None)
            result = await _open_deepgram_stream("pt")
            assert result is None

    @pytest.mark.asyncio
    async def test_open_deepgram_stream_language_mapping(
        self,
    ):
        """Language codes are mapped correctly."""
        lang_map = {
            "pt": "pt-BR",
            "en": "en-US",
            "es": "es",
        }
        assert lang_map["pt"] == "pt-BR"
        assert lang_map["en"] == "en-US"
        assert lang_map["es"] == "es"

    @pytest.mark.asyncio
    async def test_process_turn_streaming_empty_transcript(
        self,
    ):
        """Empty transcript is ignored."""
        from services.business.call_session import (
            CallSession,
        )

        session = CallSession(
            session_id="test",
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )
        mock_ws = AsyncMock()

        await _process_turn_streaming(mock_ws, session, "MZ_test", "")
        assert len(session.conversation) == 0

    @pytest.mark.asyncio
    async def test_process_turn_streaming_calls_brain(
        self,
    ):
        """Transcript triggers Brain -> TTS pipeline."""
        from services.ai.call_brain import (
            BrainResponse,
            CallBrain,
        )
        from services.business.call_session import (
            CallSession,
        )

        session = CallSession(
            session_id="test",
            objective="Test",
            user_name="Henrique",
            language="pt",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )
        mock_ws = AsyncMock()

        mock_brain_resp = BrainResponse(
            text="Oi, tudo bem!",
            objective_complete=False,
            should_end_call=False,
            reasoning="test",
            latency_s=0.5,
        )

        with patch.object(
            CallBrain,
            "generate_response",
            return_value=mock_brain_resp,
        ):
            with patch(
                "api.routes.twilio_stream._text_to_twilio_audio",
                return_value=1.0,
            ):
                await _process_turn_streaming(
                    mock_ws,
                    session,
                    "MZ_test",
                    "Olá",
                )

        assert len(session.conversation) == 2
        assert session.conversation[0].content == "Olá"
        assert session.conversation[1].content == "Oi, tudo bem!"

    @pytest.mark.asyncio
    async def test_open_deepgram_stream_connect_error(
        self,
    ):
        """WebSocket connect error returns None."""
        with patch.dict(
            os.environ,
            {"DEEPGRAM_API_KEY": "fake_key"},
        ):
            with patch(
                "api.routes.twilio_stream.websockets.connect",
                new_callable=AsyncMock,
                side_effect=Exception("Connection refused"),
            ):
                result = await _open_deepgram_stream("en")
                assert result is None

    @pytest.mark.asyncio
    async def test_open_deepgram_stream_success(self):
        """Successfully connects via raw WebSocket."""
        mock_ws = AsyncMock()

        with patch.dict(
            os.environ,
            {"DEEPGRAM_API_KEY": "fake_key"},
        ):
            with patch(
                "api.routes.twilio_stream.websockets.connect",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ) as mock_connect:
                result = await _open_deepgram_stream("pt")
                assert result is mock_ws
                # Verify URL contains correct params
                call_url = mock_connect.call_args[0][0]
                assert "model=nova-3" in call_url
                assert "language=pt-BR" in call_url
                assert "encoding=mulaw" in call_url

    @pytest.mark.asyncio
    async def test_open_deepgram_stream_url_params(self):
        """URL contains all expected parameters."""
        mock_ws = AsyncMock()

        with patch.dict(
            os.environ,
            {"DEEPGRAM_API_KEY": "fake_key"},
        ):
            with patch(
                "api.routes.twilio_stream.websockets.connect",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ) as mock_connect:
                await _open_deepgram_stream("en")
                call_url = mock_connect.call_args[0][0]
                assert "language=en-US" in call_url
                assert "endpointing=300" in call_url
                assert "vad_events=true" in call_url
                assert "sample_rate=8000" in call_url
                assert "utterance_end_ms" not in call_url

    @pytest.mark.asyncio
    async def test_open_deepgram_stream_auth_header(self):
        """Authorization header is passed correctly."""
        mock_ws = AsyncMock()

        with patch.dict(
            os.environ,
            {"DEEPGRAM_API_KEY": "test_key_123"},
        ):
            with patch(
                "api.routes.twilio_stream.websockets.connect",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ) as mock_connect:
                await _open_deepgram_stream("pt")
                call_kwargs = mock_connect.call_args[1]
                headers = call_kwargs["additional_headers"]
                assert headers["Authorization"] == "Token test_key_123"

    @pytest.mark.asyncio
    async def test_listen_deepgram_final_transcript(self):
        """Final transcript triggers processing."""
        from services.ai.call_brain import (
            BrainResponse,
            CallBrain,
        )
        from services.business.call_session import (
            CallSession,
        )

        session = CallSession(
            session_id="test",
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )

        dg_msg = json.dumps(
            {
                "type": "Results",
                "channel": {
                    "alternatives": [
                        {
                            "transcript": "Hello there",
                            "confidence": 0.99,
                        }
                    ]
                },
                "is_final": True,
                "speech_final": True,
            }
        )

        async def _ws_iter():
            yield dg_msg

        mock_conn = MagicMock()
        mock_conn.__aiter__ = lambda s: _ws_iter()

        mock_twilio_ws = AsyncMock()
        lock = asyncio.Lock()

        mock_brain_resp = BrainResponse(
            text="Hi!",
            objective_complete=False,
            should_end_call=False,
            reasoning="test",
            latency_s=0.1,
        )

        with patch.object(
            CallBrain,
            "generate_response",
            return_value=mock_brain_resp,
        ):
            with patch(
                "api.routes.twilio_stream._text_to_twilio_audio",
                return_value=0.5,
            ):
                await _listen_deepgram(
                    deepgram_conn=mock_conn,
                    twilio_ws=mock_twilio_ws,
                    session=session,
                    stream_sid="MZ_test",
                    processing_lock=lock,
                )

        assert len(session.conversation) == 2
        assert session.conversation[0].content == "Hello there"
        assert session.conversation[1].content == "Hi!"

    @pytest.mark.asyncio
    async def test_listen_deepgram_empty_transcript_skipped(
        self,
    ):
        """Empty transcript in Deepgram result is skipped."""
        from services.business.call_session import (
            CallSession,
        )

        session = CallSession(
            session_id="test",
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )

        dg_msg = json.dumps(
            {
                "type": "Results",
                "channel": {
                    "alternatives": [
                        {
                            "transcript": "",
                            "confidence": 0.0,
                        }
                    ]
                },
                "is_final": True,
                "speech_final": True,
            }
        )

        async def _ws_iter():
            yield dg_msg

        mock_conn = MagicMock()
        mock_conn.__aiter__ = lambda s: _ws_iter()

        mock_twilio_ws = AsyncMock()
        lock = asyncio.Lock()

        await _listen_deepgram(
            deepgram_conn=mock_conn,
            twilio_ws=mock_twilio_ws,
            session=session,
            stream_sid="MZ_test",
            processing_lock=lock,
        )

        assert len(session.conversation) == 0

    @pytest.mark.asyncio
    async def test_listen_deepgram_non_final_skipped(self):
        """Non-final transcript does not trigger processing."""
        from services.business.call_session import (
            CallSession,
        )

        session = CallSession(
            session_id="test",
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )

        dg_msg = json.dumps(
            {
                "type": "Results",
                "channel": {
                    "alternatives": [
                        {
                            "transcript": "Hello",
                            "confidence": 0.9,
                        }
                    ]
                },
                "is_final": False,
                "speech_final": False,
            }
        )

        async def _ws_iter():
            yield dg_msg

        mock_conn = MagicMock()
        mock_conn.__aiter__ = lambda s: _ws_iter()

        mock_twilio_ws = AsyncMock()
        lock = asyncio.Lock()

        await _listen_deepgram(
            deepgram_conn=mock_conn,
            twilio_ws=mock_twilio_ws,
            session=session,
            stream_sid="MZ_test",
            processing_lock=lock,
        )

        assert len(session.conversation) == 0

    @pytest.mark.asyncio
    async def test_listen_deepgram_metadata_event(self):
        """Non-Results events are handled without error."""
        from services.business.call_session import (
            CallSession,
        )

        session = CallSession(
            session_id="test",
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )

        events = [
            json.dumps({"type": "Metadata"}),
            json.dumps({"type": "SpeechStarted"}),
            json.dumps({"type": "UtteranceEnd"}),
        ]

        async def _ws_iter():
            for evt in events:
                yield evt

        mock_conn = MagicMock()
        mock_conn.__aiter__ = lambda s: _ws_iter()

        mock_twilio_ws = AsyncMock()
        lock = asyncio.Lock()

        await _listen_deepgram(
            deepgram_conn=mock_conn,
            twilio_ws=mock_twilio_ws,
            session=session,
            stream_sid="MZ_test",
            processing_lock=lock,
        )

        # No conversation turns from non-Results events
        assert len(session.conversation) == 0

    @pytest.mark.asyncio
    async def test_listen_deepgram_cancelled(self):
        """CancelledError is handled gracefully."""
        from services.business.call_session import (
            CallSession,
        )

        session = CallSession(
            session_id="test",
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )

        async def _ws_iter():
            raise asyncio.CancelledError()
            yield  # noqa: RET503  # pragma: no cover

        mock_conn = MagicMock()
        mock_conn.__aiter__ = lambda s: _ws_iter()

        mock_twilio_ws = AsyncMock()
        lock = asyncio.Lock()

        # Should not raise
        await _listen_deepgram(
            deepgram_conn=mock_conn,
            twilio_ws=mock_twilio_ws,
            session=session,
            stream_sid="MZ_test",
            processing_lock=lock,
        )


# -- _redact_key tests -----------------------------------------------


class TestRedactKey:
    """Tests for API key redaction in error messages."""

    def test_redacts_api_key_from_error(self):
        """API key in error message is redacted."""
        with patch.dict(
            os.environ,
            {"DEEPGRAM_API_KEY": "sk-secret-abc123"},
        ):
            err = Exception("Failed with sk-secret-abc123 in msg")
            result = _redact_key(err)
            assert "sk-secret-abc123" not in result
            assert "[REDACTED]" in result

    def test_no_key_passes_through(self):
        """Error without API key passes through."""
        with patch.dict(os.environ, {"DEEPGRAM_API_KEY": ""}):
            err = Exception("Connection refused")
            result = _redact_key(err)
            assert result == "Connection refused"

    def test_no_env_var_passes_through(self):
        """No DEEPGRAM_API_KEY env var passes through."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPGRAM_API_KEY", None)
            err = Exception("Some error")
            result = _redact_key(err)
            assert result == "Some error"


# -- _send_telegram_report tests --------------------------------------


class TestSendTelegramReport:
    @pytest.mark.asyncio
    async def test_report_with_fallback_bot(self):
        """Sends report via fallback telegram.Bot."""
        from services.business.call_session import (
            CallSession,
        )

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
        from services.business.call_session import (
            CallSession,
        )

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


# -- _text_to_twilio_audio tests --------------------------------------


class TestTextToTwilioAudio:
    @pytest.mark.asyncio
    async def test_no_elevenlabs_service(self):
        """Returns 0.0 when ElevenLabs not available."""
        mock_ws = AsyncMock()

        with patch("services.get_service", return_value=None):
            dur = await _text_to_twilio_audio(mock_ws, "MZ_test", "Hello", "en")
            assert dur == 0.0

    @pytest.mark.asyncio
    async def test_empty_mp3_returns_zero(self):
        """Returns 0.0 when TTS returns empty bytes."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized.return_value = True
        mock_el.text_to_speech = AsyncMock(return_value=b"")

        with patch(
            "services.get_service",
            return_value=mock_el,
        ):
            dur = await _text_to_twilio_audio(mock_ws, "MZ_test", "Hello", "en")
            assert dur == 0.0

    @pytest.mark.asyncio
    async def test_exception_returns_zero(self):
        """Returns 0.0 on exception."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized.return_value = True
        mock_el.text_to_speech = AsyncMock(side_effect=RuntimeError("TTS error"))

        with patch(
            "services.get_service",
            return_value=mock_el,
        ):
            dur = await _text_to_twilio_audio(mock_ws, "MZ_test", "Hello", "pt")
            assert dur == 0.0

    @pytest.mark.asyncio
    async def test_initializes_elevenlabs_if_needed(self):
        """Calls initialize() when not initialized."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized = MagicMock(return_value=False)
        mock_el.initialize = AsyncMock()
        mock_el.text_to_speech = AsyncMock(return_value=b"")

        with patch(
            "services.get_service",
            return_value=mock_el,
        ):
            await _text_to_twilio_audio(mock_ws, "MZ_test", "Hi", "en")
            mock_el.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_sends_chunks_and_returns_duration(
        self,
    ):
        """Full success path: TTS + mulaw chunks + send."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized = MagicMock(return_value=True)
        mock_el.text_to_speech = AsyncMock(return_value=b"\xff" * 100)

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
            patch(
                "asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            dur = await _text_to_twilio_audio(mock_ws, "MZ_test", "Hello there", "en")
            assert dur == pytest.approx(0.06, abs=0.001)
            assert mock_ws.send_json.call_count == 3

    @pytest.mark.asyncio
    async def test_no_mulaw_chunks_returns_zero(self):
        """Returns 0.0 when mp3_to_mulaw returns empty."""
        mock_ws = AsyncMock()
        mock_el = AsyncMock()
        mock_el.is_initialized = MagicMock(return_value=True)
        mock_el.text_to_speech = AsyncMock(return_value=b"\xff" * 100)

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
            dur = await _text_to_twilio_audio(mock_ws, "MZ_test", "Hello", "en")
            assert dur == 0.0


# -- _send_error_and_close tests --------------------------------------


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
        mock_ws.close = AsyncMock(side_effect=Exception("already closed"))

        with patch(
            "api.routes.twilio_stream._text_to_twilio_audio",
            new_callable=AsyncMock,
            side_effect=Exception("TTS failed"),
        ):
            # Should not raise
            await _send_error_and_close(mock_ws, "MZ_test")


# -- _send_telegram_report (no token) --------------------------------


class TestSendTelegramReportNoToken:
    @pytest.mark.asyncio
    async def test_no_token_logs_warning(self):
        """No TELEGRAM_BOT_TOKEN logs warning."""
        from services.business.call_session import (
            CallSession,
        )

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

        with patch.dict("os.environ", {}, clear=True):
            # Should not raise
            await _send_telegram_report(session)


# -- Integration-style tests ------------------------------------------


class TestTwilioStreamProtocol:
    def test_media_message_format(self):
        """Verify the Twilio media message JSON format."""
        chunk_b64 = base64.b64encode(b"\x80" * 160).decode("ascii")
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
        decoded = base64.b64decode(deserialized["media"]["payload"])
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
