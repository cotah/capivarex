"""Unit tests for the standalone rate limiter."""

import time
import pytest
from unittest.mock import patch

import utils.rate_limiter as rl


@pytest.fixture(autouse=True)
def _clear_state():
    """Ensure a clean rate-limit dict for every test."""
    rl._user_last_message_time.clear()
    yield
    rl._user_last_message_time.clear()


class TestIsRateLimited:
    def test_first_call_not_limited(self):
        assert rl.is_rate_limited(1) is False

    def test_rapid_second_call_limited(self):
        rl.is_rate_limited(2)
        assert rl.is_rate_limited(2) is True

    def test_different_users_independent(self):
        rl.is_rate_limited(10)
        assert rl.is_rate_limited(20) is False

    def test_after_cooldown_not_limited(self):
        rl.is_rate_limited(30)
        # Push timestamp into the past
        rl._user_last_message_time[30] = time.time() - rl.RATE_LIMIT_SECONDS - 1
        assert rl.is_rate_limited(30) is False

    def test_rate_limit_seconds_value(self):
        assert rl.RATE_LIMIT_SECONDS == 2
