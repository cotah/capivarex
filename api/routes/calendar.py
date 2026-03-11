"""
Calendar API Routes - Refactored to use agents and services.

Handles calendar-related requests via the CalendarAgent from the agent registry.

Endpoints:
    POST /query         - Query calendar information
    GET  /today         - Get today's calendar events
    GET  /next-meeting  - Get the next upcoming meeting
    GET  /briefing      - Get calendar briefing for morning briefing
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents import get_agent
from api.dependencies import get_current_user

router = APIRouter()
logger = logging.getLogger("capivarex.api.routes.calendar")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CalendarQuery(BaseModel):
    """Calendar query request model."""
    query: str
    context: Optional[Dict[str, Any]] = None


class CalendarResponse(BaseModel):
    """Calendar response model."""
    success: bool
    response: str
    events: List[Any] = []
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_calendar_agent():
    """Retrieve the calendar agent from the registry, raising if absent."""
    agent = get_agent("calendar")
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Calendar agent is not available",
        )
    return agent


def _build_context(current_user: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a standard context dict from the authenticated user."""
    context = extra.copy() if extra else {}
    context.update({
        "user_id": current_user.get("id"),
        "tenant_id": current_user.get("tenant_id", "default"),
        "channel": "api",
    })
    return context


async def _calendar_request(
    prompt: str,
    current_user: Dict[str, Any],
    extra_context: Optional[Dict[str, Any]] = None,
    *,
    error_label: str = "calendar request",
) -> CalendarResponse:
    """Execute a calendar agent request and build a ``CalendarResponse``.

    Centralises the try/except/response-assembly pattern shared by all
    calendar endpoints.
    """
    try:
        agent = _get_calendar_agent()
        context = _build_context(current_user, extra_context)
        result = await agent.process(prompt, context)

        return CalendarResponse(
            success=result.get("success", False),
            response=result.get("response", ""),
            events=result.get("events", []),
            error=result.get("error"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error processing %s: %s", error_label, e)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing {error_label}: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/query", response_model=CalendarResponse)
async def query_calendar(
    request: CalendarQuery,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> CalendarResponse:
    """Query calendar information."""
    return await _calendar_request(
        request.query, current_user, request.context, error_label="calendar query",
    )


@router.get("/today", response_model=CalendarResponse)
async def get_today_events(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> CalendarResponse:
    """Get today's calendar events."""
    return await _calendar_request(
        "What's on my calendar today?", current_user, error_label="today's events",
    )


@router.get("/next-meeting", response_model=CalendarResponse)
async def get_next_meeting(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> CalendarResponse:
    """Get the next upcoming meeting."""
    return await _calendar_request(
        "What's my next meeting?", current_user, error_label="next meeting",
    )


@router.get("/briefing", response_model=CalendarResponse)
async def get_calendar_briefing(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> CalendarResponse:
    """Get calendar briefing for morning briefing."""
    return await _calendar_request(
        "Give me my calendar briefing", current_user, error_label="calendar briefing",
    )
