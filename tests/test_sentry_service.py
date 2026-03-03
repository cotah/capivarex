# -*- coding: utf-8 -*-
"""Tests for the Sentry integration module."""

from unittest.mock import patch

from services.infrastructure.sentry_service import (
    _before_send,
    init_sentry,
)


class TestBeforeSend:
    """Tests for the _before_send event filter."""

    def test_health_check_filtered(self):
        event = {"request": {"url": "https://app.example.com/health"}}
        assert _before_send(event, {}) is None

    def test_healthz_filtered(self):
        event = {"request": {"url": "https://app.example.com/healthz"}}
        assert _before_send(event, {}) is None

    def test_ready_filtered(self):
        event = {"request": {"url": "https://app.example.com/ready"}}
        assert _before_send(event, {}) is None

    def test_normal_event_passes(self):
        event = {"request": {"url": "https://app.example.com/api/chat"}}
        assert _before_send(event, {}) is event

    def test_keyboard_interrupt_filtered(self):
        event = {"level": "error"}
        hint = {"exc_info": (KeyboardInterrupt, None, None)}
        assert _before_send(event, hint) is None

    def test_system_exit_filtered(self):
        event = {"level": "error"}
        hint = {"exc_info": (SystemExit, None, None)}
        assert _before_send(event, hint) is None

    def test_value_error_passes(self):
        event = {"level": "error"}
        hint = {"exc_info": (ValueError, None, None)}
        assert _before_send(event, hint) is event

    def test_no_request_passes(self):
        """Events without request info should pass through."""
        event = {"level": "info"}
        assert _before_send(event, {}) is event


class TestInitSentry:
    """Tests for init_sentry() bootstrapping."""

    @patch("services.infrastructure.sentry_service.sentry_sdk")
    def test_init_with_dsn(self, mock_sdk):
        with patch.dict(
            "os.environ",
            {
                "SENTRY_DSN": "https://test@sentry.io/123",
                "SENTRY_ENVIRONMENT": "testing",
                "SENTRY_TRACES_SAMPLE_RATE": "0.5",
                "RELEASE": "v1.0.0",
            },
        ):
            init_sentry()

        mock_sdk.init.assert_called_once()
        kwargs = mock_sdk.init.call_args[1]
        assert kwargs["dsn"] == "https://test@sentry.io/123"
        assert kwargs["environment"] == "testing"
        assert kwargs["traces_sample_rate"] == 0.5
        assert kwargs["release"] == "v1.0.0"
        assert kwargs["send_default_pii"] is True

    @patch("services.infrastructure.sentry_service.sentry_sdk")
    def test_skip_when_no_dsn(self, mock_sdk):
        with patch.dict("os.environ", {}, clear=True):
            init_sentry()

        mock_sdk.init.assert_not_called()

    @patch("services.infrastructure.sentry_service.sentry_sdk")
    def test_skip_when_empty_dsn(self, mock_sdk):
        with patch.dict("os.environ", {"SENTRY_DSN": ""}):
            init_sentry()

        mock_sdk.init.assert_not_called()

    @patch("services.infrastructure.sentry_service.sentry_sdk")
    def test_defaults_when_env_missing(self, mock_sdk):
        with patch.dict(
            "os.environ",
            {"SENTRY_DSN": "https://test@sentry.io/1"},
            clear=True,
        ):
            init_sentry()

        kwargs = mock_sdk.init.call_args[1]
        assert kwargs["environment"] == "development"
        assert kwargs["traces_sample_rate"] == 0.3
        assert kwargs["release"] is None

    @patch("services.infrastructure.sentry_service.sentry_sdk")
    def test_invalid_traces_rate_defaults(self, mock_sdk):
        with patch.dict(
            "os.environ",
            {
                "SENTRY_DSN": "https://test@sentry.io/1",
                "SENTRY_TRACES_SAMPLE_RATE": "not-a-number",
            },
            clear=True,
        ):
            init_sentry()

        kwargs = mock_sdk.init.call_args[1]
        assert kwargs["traces_sample_rate"] == 0.3

    @patch("services.infrastructure.sentry_service.sentry_sdk")
    def test_falls_back_to_environment_var(self, mock_sdk):
        """Falls back to ENVIRONMENT if SENTRY_ENVIRONMENT not set."""
        with patch.dict(
            "os.environ",
            {
                "SENTRY_DSN": "https://test@sentry.io/1",
                "ENVIRONMENT": "staging",
            },
            clear=True,
        ):
            init_sentry()

        kwargs = mock_sdk.init.call_args[1]
        assert kwargs["environment"] == "staging"
