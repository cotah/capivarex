# schemas/calendar.py
"""
Pydantic models for calendar event data.

Centralises validation and datetime parsing that was previously
inlined in CalendarAgent._create_event.
"""

from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CalendarEventInput(BaseModel):
    """Validated input for creating a calendar event."""

    title: str
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    location: str = ""
    description: str = ""

    @field_validator("start_datetime", "end_datetime", mode="before")
    @classmethod
    def _parse_datetime(cls, value):
        """Accept ISO strings (with trailing Z) and datetime objects."""
        if value is None:
            return value
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        raise ValueError(f"Cannot parse datetime from {type(value)}: {value}")

    def resolved_end(self) -> datetime:
        """Return end_datetime, defaulting to start + 1 hour."""
        if self.end_datetime is not None:
            return self.end_datetime
        return self.start_datetime + timedelta(hours=1)
