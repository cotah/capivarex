"""
Weather Routes - Refactored to use services.

Endpoints for fetching current weather and forecasts via the
registered ``weather`` service from the refactored service registry.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.dependencies.auth import get_current_user
from services.core import get_service

logger = logging.getLogger("capivarex.api.routes.weather")

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
async def get_weather_auto(
    request: Request, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
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


@router.get("/auto/week")
async def get_week_forecast_auto(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Previsão semanal baseada no IP do cliente."""
    try:
        service = await _get_weather_service()
        client_ip: str = request.client.host
        data = await service.get_week_summary(client_ip)
        return {"success": True, "data": data, "detected_ip": client_ip}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{city}")
async def get_weather_by_city(
    city: str, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
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


@router.get("/{city}/week")
async def get_week_forecast(
    city: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Previsão da semana (7 dias) com resumo, melhor/pior dia e alertas de chuva.

    Args:
        city: Nome da cidade

    Returns:
        forecast (7 dias enriquecido), summary (best_day, worst_day,
        rainy_days_count, avg temps), alerts oficiais
    """
    try:
        service = await _get_weather_service()
        data = await service.get_week_summary(city)
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{city}/detailed")
async def get_detailed_forecast(
    city: str,
    days: int = Query(default=7, ge=1, le=14, description="Número de dias (1–14)"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Previsão detalhada: UV, vento, humidade, nascer/pôr do sol, alertas.

    Args:
        city: Nome da cidade
        days: Número de dias (1–14, padrão 7)

    Returns:
        current (enriquecido), forecast (enriquecido), alerts oficiais
    """
    try:
        service = await _get_weather_service()
        data = await service.get_detailed_forecast(city, days=days)
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{city}/alerts")
async def get_weather_alerts(
    city: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Alertas meteorológicos ativos para a cidade.

    Inclui alertas oficiais da WeatherAPI e alertas derivados
    (chuva >70%, vento >50 km/h, UV >6).

    Args:
        city: Nome da cidade

    Returns:
        Lista de alertas oficiais + alertas derivados dos próximos 3 dias
    """
    try:
        service = await _get_weather_service()
        # Usa o agente para formatar — aproveita a lógica de _handle_alerts
        from agents import get_agent

        agent = get_agent("weather")
        if agent:
            result = await agent.execute(
                f"alertas em {city}",
                {"location": city},
            )
            return {
                "success": result.is_success(),
                "data": result.data,
                "message": result.response if not result.is_success() else None,
            }
        # Fallback direto no serviço
        alerts = await service.get_alerts(city)
        return {"success": True, "data": {"alerts": alerts, "city": city}}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
