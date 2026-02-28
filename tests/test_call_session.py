"""
Tests for CallSession — AI phone call state management.
"""
import time

from services.business.call_session import (
    CallResult,
    CallSession,
    CallStatus,
    PendingCall,
    _PENDING_CALLS,
    get_pending_call,
    get_pending_calls_count,
    register_pending_call,
)


# -- Helpers ------------------------------------------------------------------


def _make_session(**overrides) -> CallSession:
    """Create a CallSession with sensible defaults."""
    defaults = {
        "session_id": "test1234",
        "objective": "Reserve a table for 2 at 8pm",
        "user_name": "Henrique",
        "language": "en",
        "phone_number": "+353894434456",
        "telegram_chat_id": 123456,
        "telegram_user_id": 789,
    }
    defaults.update(overrides)
    return CallSession(**defaults)


def _make_pending(**overrides) -> PendingCall:
    """Create a PendingCall with sensible defaults."""
    defaults = {
        "session_id": "pend1234",
        "objective": "Reserve table",
        "user_name": "Henrique",
        "language": "pt",
        "phone_number": "+353894434456",
        "telegram_chat_id": 123456,
        "telegram_user_id": 789,
    }
    defaults.update(overrides)
    return PendingCall(**defaults)


# -- CallSession Tests --------------------------------------------------------


class TestCallSessionCreation:
    def test_create_session_default_status(self):
        session = _make_session()
        assert session.status == CallStatus.PENDING
        assert session.result == CallResult.UNKNOWN
        assert session.conversation == []
        assert len(session.audio_buffer) == 0

    def test_from_pending(self):
        pending = _make_pending()
        session = CallSession.from_pending(pending)
        assert session.session_id == pending.session_id
        assert session.objective == pending.objective
        assert session.user_name == pending.user_name
        assert session.status == CallStatus.GREETING


class TestAudioBufferAndVAD:
    def test_add_audio_chunk_accumulates(self):
        session = _make_session()
        session.add_audio_chunk(b"\x80" * 160)
        session.add_audio_chunk(b"\x80" * 160)
        assert len(session.audio_buffer) == 320

    def test_clear_audio_buffer(self):
        session = _make_session()
        session.add_audio_chunk(b"\x80" * 160)
        session._speech_detected = True
        session.clear_audio_buffer()
        assert len(session.audio_buffer) == 0
        assert session._speech_detected is False
        assert session._silence_start is None

    def test_should_process_no_speech(self):
        """No speech detected -> should not process."""
        session = _make_session()
        session.add_audio_chunk(b"\x80" * 160)
        assert session.should_process() is False

    def test_should_process_during_processing(self):
        """Already processing -> should not process again."""
        session = _make_session()
        session.status = CallStatus.PROCESSING
        session._speech_detected = True
        assert session.should_process() is False

    def test_should_process_force_cutoff(self):
        """Very long speech -> force process."""
        session = _make_session()
        session._speech_detected = True
        # Simulate 31 seconds of audio (8000 bytes/s x 31 = 248000 bytes)
        session.audio_buffer = bytearray(b"\x80" * 248_000)
        assert session.should_process() is True

    def test_should_process_after_silence(self):
        """Speech followed by silence -> should process."""
        session = _make_session()
        session._speech_detected = True
        # Add enough audio for MIN_SPEECH_DURATION_S (0.3s = 2400 bytes)
        session.audio_buffer = bytearray(b"\x80" * 4000)
        # Simulate silence started 2 seconds ago
        session._silence_start = time.time() - 2.0
        assert session.should_process() is True

    def test_should_process_ignores_very_short_speech(self):
        """Very short speech (noise) followed by silence -> clear, don't process."""
        session = _make_session()
        session._speech_detected = True
        # Very short audio (< MIN_SPEECH_DURATION_S)
        session.audio_buffer = bytearray(b"\x80" * 100)
        session._silence_start = time.time() - 2.0
        assert session.should_process() is False
        # Buffer should be cleared
        assert len(session.audio_buffer) == 0

    def test_get_audio_for_processing_returns_wav(self):
        """get_audio_for_processing returns WAV and clears buffer."""
        session = _make_session()
        # 1 second of mulaw silence
        session.audio_buffer = bytearray(b"\x80" * 8000)
        wav = session.get_audio_for_processing()
        assert len(wav) > 0
        # Starts with RIFF header
        assert wav[:4] == b"RIFF"
        # Buffer is cleared
        assert len(session.audio_buffer) == 0

    def test_get_audio_for_processing_empty(self):
        session = _make_session()
        assert session.get_audio_for_processing() == b""


class TestConversation:
    def test_add_turns(self):
        session = _make_session()
        session.add_assistant_turn("Hello!")
        session.add_user_turn("Hi, I'd like to book a table")
        assert len(session.conversation) == 2
        assert session.conversation[0].role == "assistant"
        assert session.conversation[1].role == "user"

    def test_get_conversation_history(self):
        session = _make_session()
        session.add_assistant_turn("Hello!")
        session.add_user_turn("Book a table please")
        history = session.get_conversation_history()
        assert history == [
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Book a table please"},
        ]

    def test_get_last_user_message(self):
        session = _make_session()
        session.add_assistant_turn("Hello!")
        session.add_user_turn("First message")
        session.add_assistant_turn("OK")
        session.add_user_turn("Second message")
        assert session.get_last_user_message() == "Second message"

    def test_get_last_user_message_empty(self):
        session = _make_session()
        assert session.get_last_user_message() == ""

    def test_turn_count_increments(self):
        session = _make_session()
        session.add_assistant_turn("Hello!")
        session.add_assistant_turn("How can I help?")
        assert session._turn_count == 2


class TestLifecycle:
    def test_should_end_call_on_timeout(self):
        session = _make_session()
        session.started_at = time.time() - 200  # 200s ago (limit is 180s)
        assert session.should_end_call() is True
        assert session.status == CallStatus.TIMEOUT

    def test_should_end_call_on_max_turns(self):
        session = _make_session()
        session._turn_count = 20
        assert session.should_end_call() is True
        assert session.result == CallResult.PARTIAL

    def test_should_end_call_on_completed(self):
        session = _make_session()
        session.status = CallStatus.COMPLETED
        assert session.should_end_call() is True

    def test_should_not_end_call_normal(self):
        session = _make_session()
        session.status = CallStatus.LISTENING
        assert session.should_end_call() is False

    def test_mark_objective_complete(self):
        session = _make_session()
        session.mark_objective_complete("Table reserved for 2 at 8pm")
        assert session.status == CallStatus.COMPLETED
        assert session.result == CallResult.SUCCESS
        assert "Table reserved" in session.result_details

    def test_mark_failed(self):
        session = _make_session()
        session.mark_failed("Restaurant is closed")
        assert session.status == CallStatus.FAILED
        assert session.result == CallResult.FAILED

    def test_mark_hangup(self):
        session = _make_session()
        session.mark_hangup()
        assert session.result == CallResult.HANGUP

    def test_finalize(self):
        session = _make_session()
        session.finalize()
        assert session.ended_at is not None
        assert session.status == CallStatus.COMPLETED


class TestMetrics:
    def test_duration(self):
        session = _make_session()
        session.started_at = time.time() - 60
        assert abs(session.duration_s - 60) < 1

    def test_record_latencies(self):
        session = _make_session()
        session.record_stt_latency(0.5)
        session.record_llm_latency(0.3)
        session.record_tts_latency(0.8)
        session._turn_count = 1
        m = session.metrics
        assert m["stt_total_latency_s"] == 0.5
        assert m["llm_total_latency_s"] == 0.3
        assert m["tts_total_latency_s"] == 0.8
        assert m["avg_turn_latency_s"] == 1.6

    def test_metrics_no_turns(self):
        session = _make_session()
        m = session.metrics
        assert m["avg_turn_latency_s"] == 0.0


class TestReport:
    def test_generate_report_contains_key_info(self):
        session = _make_session()
        session.mark_objective_complete("Reserved!")
        session.add_assistant_turn("Hello!")
        session.add_user_turn("Book a table")
        session.finalize()
        report = session.generate_report()
        assert "\U0001f4de" in report
        assert "+353894434456" in report
        assert "\u2705" in report
        assert "Hello!" in report
        assert "Book a table" in report

    def test_to_dict(self):
        session = _make_session()
        session.add_assistant_turn("Hi")
        d = session.to_dict()
        assert d["session_id"] == "test1234"
        assert d["objective"] == "Reserve a table for 2 at 8pm"
        assert len(d["conversation"]) == 1
        assert "metrics" in d


# -- Pending Calls Registry Tests --------------------------------------------


class TestPendingCallsRegistry:
    def setup_method(self):
        """Clear pending calls before each test."""
        _PENDING_CALLS.clear()

    def test_register_and_get(self):
        session_id = register_pending_call(
            objective="Book table",
            user_name="Henrique",
            language="pt",
            phone_number="+353894434456",
            telegram_chat_id=123456,
            telegram_user_id=789,
        )
        assert len(session_id) == 16
        pending = get_pending_call(session_id)
        assert pending is not None
        assert pending.objective == "Book table"
        assert pending.user_name == "Henrique"

    def test_get_removes_from_registry(self):
        session_id = register_pending_call(
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1234",
            telegram_chat_id=1,
            telegram_user_id=1,
        )
        get_pending_call(session_id)
        # Second get should return None
        assert get_pending_call(session_id) is None

    def test_get_nonexistent(self):
        assert get_pending_call("doesnotexist") is None

    def test_expired_call_returns_none(self):
        session_id = register_pending_call(
            objective="Test",
            user_name="Test",
            language="en",
            phone_number="+1234",
            telegram_chat_id=1,
            telegram_user_id=1,
        )
        # Manually expire it
        _PENDING_CALLS[session_id].created_at = time.time() - 60
        assert get_pending_call(session_id) is None

    def test_count(self):
        register_pending_call(
            objective="A",
            user_name="A",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )
        register_pending_call(
            objective="B",
            user_name="B",
            language="en",
            phone_number="+2",
            telegram_chat_id=2,
            telegram_user_id=2,
        )
        assert get_pending_calls_count() == 2


class TestPendingCallExpiry:
    def test_is_expired(self):
        p = _make_pending()
        assert p.is_expired is False
        p.created_at = time.time() - 60
        assert p.is_expired is True

    def test_cleanup_removes_expired_entries(self):
        """register_pending_call triggers cleanup of expired entries."""
        _PENDING_CALLS.clear()

        # Manually inject an expired pending call
        expired = _make_pending()
        expired.created_at = time.time() - 120  # well past TTL
        _PENDING_CALLS["expired_id"] = expired

        assert "expired_id" in _PENDING_CALLS

        # Registering a new call triggers _cleanup_expired
        register_pending_call(
            objective="New",
            user_name="U",
            language="en",
            phone_number="+1",
            telegram_chat_id=1,
            telegram_user_id=1,
        )

        assert "expired_id" not in _PENDING_CALLS
