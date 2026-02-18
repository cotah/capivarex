"""
Traffic API Routes - Refactored to use agents.

Endpoints dedicated to traffic queries and route information.

Endpoints:
    GET /route       - Get route with traffic information
    GET /check-event - Check traffic for the next calendar event
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agents import get_agent
from api.dependencies import get_current_user

router = APIRouter()
logger = logging.getLogger("capivarax.api.routes.traffic")


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------

def _get_traffic_agent():
    """Retrieve the traffic agent from the registry."""
    agent = get_agent("traffic")
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Traffic agent is not available",
        )
    return agent


def _get_calendar_agent():
    """Retrieve the calendar agent from the registry (used for event-traffic checks)."""
    agent = get_agent("calendar")
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Calendar agent is not available",
        )
    return agent


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/route", summary="Get route with traffic information")
async def get_route(
    origin: str = Query(..., description="Endereço de origem"),
    destination: str = Query(..., description="Endereço de destino"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Obtém informações de rota e tráfego entre dois pontos.

    Args:
        origin: Origin address.
        destination: Destination address.
        current_user: Current authenticated user.

    Returns:
        Route and traffic information dict.
    """
    try:
        traffic_agent = _get_traffic_agent()
        context = {"origin": origin, "destination": destination}
        result = await traffic_agent.execute(prompt="", context=context)

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("response", "Erro ao buscar rota"),
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro em /traffic/route: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno do servidor: {str(e)}",
        )


@router.get("/check-event", summary="Check traffic for the next calendar event")
async def check_traffic_for_event(
    user_location: str = Query(..., description="Localização atual do usuário"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Verifica o tráfego para o próximo evento com localização no calendário do usuário.

    Args:
        user_location: Current user location string.
        current_user: Current authenticated user.

    Returns:
        Traffic check result for the next calendar event.
    """
    try:
        calendar_agent = _get_calendar_agent()
        result = await calendar_agent.check_traffic_for_next_event(user_location)

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get(
                    "response",
                    "Nenhum evento encontrado ou erro ao verificar tráfego",
                ),
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro em /traffic/check-event: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno do servidor: {str(e)}",
        )
