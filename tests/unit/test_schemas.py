"""Unit tests for Pydantic schemas."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from schemas.context import UserContext, Device
from schemas.calendar import CalendarEventInput
from schemas.orchestrator import OrchestratorDecision


# -------------------------------------------------------------------
# Device
# -------------------------------------------------------------------

class TestDevice:
    def test_create_device(self):
        d = Device(type="mobile", id="phone-1")
        assert d.type == "mobile"
        assert d.id == "phone-1"
        assert d.permissions == []

    def test_device_with_permissions(self):
        d = Device(type="car", id="car-1", permissions=["lock", "unlock"])
        assert len(d.permissions) == 2


# -------------------------------------------------------------------
# UserContext
# -------------------------------------------------------------------

class TestUserContext:
    def test_minimal_creation(self):
        ctx = UserContext(
            user_id="u1",
            telegram_chat_id=123,
            full_name="Test User",
        )
        assert ctx.user_id == "u1"
        assert ctx.locale == "en_US"
        assert ctx.timezone == "UTC"
        assert ctx.devices == []
        assert ctx.permissions == []
        assert ctx.extra_data == {}

    def test_full_creation(self):
        ctx = UserContext(
            user_id="u2",
            telegram_chat_id=456,
            full_name="Full User",
            locale="pt_BR",
            timezone="America/Sao_Paulo",
            devices=[Device(type="pc", id="pc-1")],
            permissions=["admin"],
            extra_data={"pref": "dark"},
        )
        assert ctx.locale == "pt_BR"
        assert len(ctx.devices) == 1

    def test_extra_fields_ignored(self):
        """Fields not in the model should be silently ignored."""
        ctx = UserContext(
            user_id="u1",
            telegram_chat_id=1,
            full_name="Test",
            unknown_field="value",
        )
        assert not hasattr(ctx, "unknown_field")

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            UserContext(user_id="u1")  # missing telegram_chat_id, full_name

    def test_from_dict(self):
        data = {
            "user_id": "u1",
            "telegram_chat_id": 789,
            "full_name": "Dict User",
            "extra_ignored_field": True,
        }
        ctx = UserContext.model_validate(data)
        assert ctx.full_name == "Dict User"


# -------------------------------------------------------------------
# CalendarEventInput
# -------------------------------------------------------------------

class TestCalendarEventInput:
    def test_basic_creation(self):
        ev = CalendarEventInput(
            title="Meeting",
            start_datetime=datetime(2026, 3, 1, 10, 0),
        )
        assert ev.title == "Meeting"
        assert ev.end_datetime is None
        assert ev.location == ""

    def test_resolved_end_default(self):
        ev = CalendarEventInput(
            title="Meeting",
            start_datetime=datetime(2026, 3, 1, 10, 0),
        )
        assert ev.resolved_end() == datetime(2026, 3, 1, 11, 0)

    def test_resolved_end_explicit(self):
        ev = CalendarEventInput(
            title="Meeting",
            start_datetime=datetime(2026, 3, 1, 10, 0),
            end_datetime=datetime(2026, 3, 1, 12, 0),
        )
        assert ev.resolved_end() == datetime(2026, 3, 1, 12, 0)

    def test_iso_string_parsing(self):
        ev = CalendarEventInput(
            title="Test",
            start_datetime="2026-03-01T10:00:00",
        )
        assert ev.start_datetime == datetime(2026, 3, 1, 10, 0)

    def test_z_suffix_parsing(self):
        ev = CalendarEventInput(
            title="Test",
            start_datetime="2026-03-01T10:00:00Z",
        )
        # Z should be normalised and tzinfo stripped
        assert ev.start_datetime == datetime(2026, 3, 1, 10, 0)
        assert ev.start_datetime.tzinfo is None

    def test_invalid_datetime_raises(self):
        with pytest.raises(ValidationError):
            CalendarEventInput(title="Bad", start_datetime="not-a-date")

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            CalendarEventInput(start_datetime=datetime(2026, 1, 1))

    def test_missing_start_raises(self):
        with pytest.raises(ValidationError):
            CalendarEventInput(title="No Date")

    def test_none_end_datetime_passes_validator(self):
        ev = CalendarEventInput(
            title="T", start_datetime=datetime(2026, 1, 1, 9, 0)
        )
        assert ev.end_datetime is None


# -------------------------------------------------------------------
# OrchestratorDecision
# -------------------------------------------------------------------

class TestOrchestratorDecision:
    def test_valid_decision(self):
        d = OrchestratorDecision(agent="weather", reason="User asked about weather")
        assert d.agent == "weather"
        assert d.reason == "User asked about weather"

    def test_all_valid_agents(self):
        valid_agents = [
            "chat", "research", "dev", "weather", "finance",
            "image", "video", "voice", "calendar", "traffic",
            "car", "smarthome", "github", "time", "translate",
            "crypto", "timer", "reminder", "youtube", "tracking",
            "meeting", "search", "leaving_now", "mercado", "notes",
        ]
        for agent in valid_agents:
            d = OrchestratorDecision(agent=agent, reason="test")
            assert d.agent == agent

    def test_invalid_agent_raises(self):
        with pytest.raises(ValidationError):
            OrchestratorDecision(agent="invalid_agent", reason="test")

    def test_missing_reason_raises(self):
        with pytest.raises(ValidationError):
            OrchestratorDecision(agent="chat")
