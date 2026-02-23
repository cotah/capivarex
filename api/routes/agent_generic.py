"""
Generic Agent Route

Provides a single endpoint that can route requests to any registered agent.
This covers agents that don't have dedicated route files:
email, restaurant, crypto, youtube, timer, reminder, meeting,
search, tracking, translate, mercado, leaving_now, time.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from agents import get_agent
from api.dependencies import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

# Agents that already have dedicated routes — block them here to avoid conflicts
_DEDICATED_ROUTE_AGENTS = {
    "orchestrator", "chat", "dev", "research", "image", "video",
    "voice", "calendar", "weather", "traffic", "car", "finance",
    "smarthome", "github", "notes",
}


@router.post("/{agent_name}")
async def process_agent_request(
    agent_name: str,
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
):
    """
    Generic endpoint to send a message to any registered agent.

    - **agent_name**: Name of the agent (e.g., "email", "crypto", "timer")
    - **payload**: Must contain at least {"message": "..."}, optionally {"context": {...}}
    """
    if agent_name in _DEDICATED_ROUTE_AGENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Agent '{agent_name}' has a dedicated route. Use /api/v1/{agent_name} instead.",
        )

    agent = get_agent(agent_name)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_name}' not found in registry.",
        )

    message = payload.get("message", "")
    context = payload.get("context", {})
    context["user_id"] = current_user.get("id", "")

    try:
        response = await agent.process(message, context)
        return {
            "agent": agent_name,
            "status": response.status.value if hasattr(response.status, "value") else str(response.status),
            "response": response.response,
            "data": response.data,
        }
    except Exception as e:
        logger.exception("Error processing request for agent '%s'", agent_name)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_available_agents(current_user: dict = Depends(get_current_user)):
    """List all available agents that can be used via this generic endpoint."""
    from agents.core.agent_registry import registry

    all_agents = registry.list_agents() if registry else []
    generic_agents = [a for a in all_agents if a not in _DEDICATED_ROUTE_AGENTS]
    return {
        "dedicated_route_agents": sorted(_DEDICATED_ROUTE_AGENTS),
        "generic_agents": sorted(generic_agents),
        "total": len(all_agents),
    }
