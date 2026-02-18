"""
Weather Routes - Refactored to use services.

Endpoints for fetching current weather and forecasts via the
registered ``weather`` service from the refactored service registry.
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from api.dependencies.auth import get_current_user
from services.core import get_service

logger = logging.getLogger("capivarax.api.routes.weather")

router = APIRouter()


async def _get_weather_service():
    """Resolve and lazily initialise the weather service."""
    service = get_service("weather")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Weather service is not available",
        )
    if not service.is_initialized():
        await service.initialize()
    return service


@router.get("/auto")
async def get_weather_auto(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Busca o clima atual baseado no IP do cliente (detecção automática).

    Args:
        request: Request object do FastAPI (para obter IP do cliente)

    Returns:
        Informações do clima atual

    Raises:
        HTTPException 500: Se houver erro ao buscar clima
    """
    try:
        service = await _get_weather_service()
        client_ip: str = request.client.host
        weather_data = await service.get_current_weather(client_ip)

        return {
            "success": True,
            "data": weather_data,
            "detected_ip": client_ip,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auto/forecast")
async def get_forecast_auto(
    request: Request,
    days: int = 3,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Busca a previsão do tempo baseado no IP do cliente (detecção automática).

    Args:
        request: Request object do FastAPI (para obter IP do cliente)
        days: Número de dias de previsão (1-14, padrão: 3)

    Returns:
        Previsão do tempo para os próximos dias

    Raises:
        HTTPException 400: Se days estiver fora do range 1-14
        HTTPException 500: Se houver erro ao buscar previsão
    """
    if days < 1 or days > 14:
        raise HTTPException(
            status_code=400,
            detail="Parameter 'days' must be between 1 and 14",
        )

    try:
        service = await _get_weather_service()
        client_ip: str = request.client.host
        forecast_data = await service.get_forecast(client_ip, days)

        return {
            "success": True,
            "data": forecast_data,
            "detected_ip": client_ip,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{city}")
async def get_weather_by_city(city: str, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Busca o clima atual para uma cidade específica.

    Args:
        city: Nome da cidade (ex: "London", "São Paulo", "New York")

    Returns:
        Informações do clima atual

    Raises:
        HTTPException 500: Se houver erro ao buscar clima
    """
    try:
        service = await _get_weather_service()
        weather_data = await service.get_current_weather(city)

        return {
            "success": True,
            "data": weather_data,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{city}/forecast")
async def get_forecast_by_city(
    city: str,
    days: int = 3,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Busca a previsão do tempo para uma cidade específica.

    Args:
        city: Nome da cidade (ex: "London", "São Paulo", "New York")
        days: Número de dias de previsão (1-14, padrão: 3)

    Returns:
        Previsão do tempo para os próximos dias

    Raises:
        HTTPException 400: Se days estiver fora do range 1-14
        HTTPException 500: Se houver erro ao buscar previsão
    """
    if days < 1 or days > 14:
        raise HTTPException(
            status_code=400,
            detail="Parameter 'days' must be between 1 and 14",
        )

    try:
        service = await _get_weather_service()
        forecast_data = await service.get_forecast(city, days)

        return {
            "success": True,
            "data": forecast_data,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
