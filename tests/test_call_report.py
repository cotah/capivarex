"""
Tests for call report generation (generate_report / _send_telegram_report).

Covers:
- Report content for different CallResult outcomes
- Transcript truncation and long-turn trimming
- Telegram 4096-char limit → short report fallback
- Language flags
- Markdown escaping
- _send_telegram_report guards and fallbacks
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.business.call_session import (
    CallResult,
    CallSession,
    ConversationTurn,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_session(**overrides) -> CallSession:
    """Create a CallSession with sensible defaults, easily overridable."""
    defaults = {
        "session_id": "sess_abc123456789",
        "objective": "Reserve a table for 2 at 8pm",
        "user_name": "Henrique",
        "language": "pt",
        "phone_number": "+353894434456",
        "telegram_chat_id": 123456,
        "telegram_user_id": 789,
    }
    defaults.update(overrides)
    return CallSession(**defaults)


# ── Report content for different results ─────────────────────────────────────


class TestReportResults:
    """Reports display correct emoji and result text for each outcome."""

    def test_success_report(self):
        s = _make_session()
        s.result = CallResult.SUCCESS
        s.result_details = "Table confirmed for 20:00"
        s.conversation = [
            ConversationTurn(role="assistant", content="Boa noite!"),
            ConversationTurn(role="user", content="Boa noite, diga."),
        ]
        report = s.generate_report()

        assert "\u2705" in report  # ✅
        assert "SUCCESS" in report
        assert "Table confirmed" in report
        assert "Reserve a table" in report

    def test_failed_report(self):
        s = _make_session()
        s.result = CallResult.FAILED
        s.result_details = "Nobody answered"
        report = s.generate_report()

        assert "\u274c" in report  # ❌
        assert "FAILED" in report
        assert "Nobody answered" in report

    def test_hangup_report(self):
        s = _make_session()
        s.result = CallResult.HANGUP
        report = s.generate_report()

        assert "\U0001f4f5" in report  # 📵
        assert "HANGUP" in report

    def test_timeout_report(self):
        s = _make_session()
        s.result = CallResult.TIMEOUT
        report = s.generate_report()

        assert "\u23f0" in report  # ⏰
        assert "TIMEOUT" in report


# ── Transcript handling ──────────────────────────────────────────────────────


class TestTranscript:
    """Transcript truncation and content display."""

    def test_transcript_truncation_max_turns(self):
        """Only max_transcript_turns turns are included."""
        s = _make_session()
        s.result = CallResult.SUCCESS
        s.conversation = [
            ConversationTurn(role="assistant", content=f"Turn {i}")
            for i in range(15)
        ]

        report = s.generate_report(max_transcript_turns=5)

        assert "Turn 0" in report
        assert "Turn 4" in report
        assert "Turn 5" not in report
        assert "10 more turns" in report

    def test_long_turn_content_trimmed(self):
        """Single turn content longer than 200 chars is truncated."""
        s = _make_session()
        s.result = CallResult.SUCCESS
        long_text = "A" * 300
        s.conversation = [
            ConversationTurn(role="user", content=long_text),
        ]

        report = s.generate_report()

        # Should contain truncated version (197 chars + "...")
        assert "A" * 197 + "..." in report
        assert "A" * 200 not in report

    def test_no_conversation_no_transcript(self):
        """Report without conversation omits transcript section."""
        s = _make_session()
        s.result = CallResult.SUCCESS
        s.conversation = []

        report = s.generate_report()

        assert "Transcript" not in report


# ── Telegram message limit ───────────────────────────────────────────────────


class TestTelegramLimit:
    """Report respects Telegram's 4096 character limit."""

    def test_short_report_fallback_on_long_content(self):
        """When full report > 4000 chars, falls back to short report."""
        s = _make_session()
        s.result = CallResult.SUCCESS
        # Create many turns with long content to exceed 4000 chars
        s.conversation = [
            ConversationTurn(role="assistant", content="X" * 200)
            for _ in range(30)
        ]

        report = s.generate_report()

        # Short report doesn't have "Transcript:" section
        assert len(report) <= 4096
        # The short report still has essential info
        assert "+353894434456" in report
        assert "Call completed" in report

    def test_short_report_method(self):
        """_generate_short_report produces a compact report."""
        s = _make_session()
        s.result = CallResult.PARTIAL
        s.result_details = "Only partial info obtained"
        s._turn_count = 5

        report = s._generate_short_report()

        assert len(report) < 500
        assert "Call completed" in report
        assert "PARTIAL" in report
        assert "partial info" in report


# ── Language flags ───────────────────────────────────────────────────────────


class TestLanguageFlags:
    """Report includes correct language flag."""

    def test_portuguese_flag(self):
        s = _make_session(language="pt")
        s.result = CallResult.SUCCESS
        report = s.generate_report()
        assert "\U0001f1f5\U0001f1f9" in report  # 🇵🇹
        assert "PT" in report

    def test_english_flag(self):
        s = _make_session(language="en")
        s.result = CallResult.SUCCESS
        report = s.generate_report()
        assert "\U0001f1ec\U0001f1e7" in report  # 🇬🇧
        assert "EN" in report

    def test_spanish_flag(self):
        s = _make_session(language="es")
        s.result = CallResult.SUCCESS
        report = s.generate_report()
        assert "\U0001f1ea\U0001f1f8" in report  # 🇪🇸
        assert "ES" in report

    def test_unknown_language_uppercase(self):
        s = _make_session(language="fr")
        s.result = CallResult.SUCCESS
        report = s.generate_report()
        assert "FR" in report


# ── Markdown escaping ────────────────────────────────────────────────────────


class TestEscapeMarkdown:
    """_escape_markdown handles Telegram Markdown v1 special characters."""

    def test_escapes_underscores(self):
        assert CallSession._escape_markdown("hello_world") == r"hello\_world"

    def test_escapes_asterisks(self):
        assert CallSession._escape_markdown("*bold*") == r"\*bold\*"

    def test_escapes_backticks(self):
        assert CallSession._escape_markdown("`code`") == r"\`code\`"

    def test_escapes_brackets(self):
        assert CallSession._escape_markdown("[link]") == "\\[link]"

    def test_escapes_combined(self):
        result = CallSession._escape_markdown("_hello_ *world* `code` [x]")
        assert "\\_" in result
        assert "\\*" in result
        assert "\\`" in result
        assert "\\[" in result

    def test_plain_text_unchanged(self):
        assert CallSession._escape_markdown("hello world") == "hello world"


# ── Performance metrics ──────────────────────────────────────────────────────


class TestReportMetrics:
    """Report includes performance metrics when available."""

    def test_metrics_displayed(self):
        s = _make_session()
        s.result = CallResult.SUCCESS
        s._turn_count = 3
        s._stt_total_latency = 1.5
        s._llm_total_latency = 2.0
        s._tts_total_latency = 1.0

        report = s.generate_report()

        assert "Performance" in report
        assert "STT" in report
        assert "LLM" in report
        assert "TTS" in report

    def test_no_metrics_when_zero(self):
        s = _make_session()
        s.result = CallResult.SUCCESS
        s._turn_count = 0
        s._stt_total_latency = 0.0
        s._llm_total_latency = 0.0
        s._tts_total_latency = 0.0

        report = s.generate_report()

        assert "Performance" not in report


# ── _send_telegram_report guards and fallbacks ───────────────────────────────


class TestSendTelegramReport:
    """Tests for _send_telegram_report in twilio_stream."""

    @pytest.mark.asyncio
    async def test_none_session_returns_early(self):
        """None session should not crash — just log and return."""
        from api.routes.twilio_stream import _send_telegram_report

        # Should not raise
        await _send_telegram_report(None)

    @pytest.mark.asyncio
    async def test_no_chat_id_returns_early(self):
        """Session with chat_id=0 should log warning and return."""
        from api.routes.twilio_stream import _send_telegram_report

        session = _make_session(telegram_chat_id=0)
        session.result = CallResult.SUCCESS

        # Should not raise
        await _send_telegram_report(session)

    @pytest.mark.asyncio
    async def test_sends_with_markdown(self):
        """Successful send uses parse_mode=Markdown."""
        from api.routes.twilio_stream import _send_telegram_report

        session = _make_session()
        session.result = CallResult.SUCCESS

        mock_bot_instance = MagicMock()
        mock_bot_instance.send_message = AsyncMock()

        with (
            patch("os.getenv", return_value="tok"),
            patch(
                "telegram.Bot",
                return_value=mock_bot_instance,
            ),
        ):
            await _send_telegram_report(session)

        mock_bot_instance.send_message.assert_called_once()
        call_kwargs = mock_bot_instance.send_message.call_args
        assert call_kwargs.kwargs.get("parse_mode") == "Markdown"

    @pytest.mark.asyncio
    async def test_falls_back_to_plain_text(self):
        """If Markdown send fails, retries as plain text."""
        from api.routes.twilio_stream import _send_telegram_report

        session = _make_session()
        session.result = CallResult.SUCCESS

        mock_bot_instance = MagicMock()
        # First call (Markdown) fails, second call (plain) succeeds
        mock_bot_instance.send_message = AsyncMock(
            side_effect=[Exception("Bad markdown"), None]
        )

        with (
            patch("os.getenv", return_value="tok"),
            patch(
                "telegram.Bot",
                return_value=mock_bot_instance,
            ),
        ):
            await _send_telegram_report(session)

        assert mock_bot_instance.send_message.call_count == 2
        # Second call should NOT have parse_mode
        second_call = mock_bot_instance.send_message.call_args_list[1]
        assert "parse_mode" not in second_call.kwargs

    @pytest.mark.asyncio
    async def test_no_token_logs_report(self):
        """Missing TELEGRAM_BOT_TOKEN logs the report instead."""
        from api.routes.twilio_stream import _send_telegram_report

        session = _make_session()
        session.result = CallResult.SUCCESS

        with patch("os.getenv", return_value=""):
            # Should not raise
            await _send_telegram_report(session)
