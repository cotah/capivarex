"""
Finance Routes - Refactored to use services.

Endpoints for fetching stock quotes, prices, and historical data via
the registered ``finance`` service from the refactored service registry.
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies.auth import get_current_user
from services.core import get_service

logger = logging.getLogger("capivarax.api.routes.finance")

router = APIRouter()


async def _get_finance_service():
    """Resolve and lazily initialise the finance service."""
    service = get_service("finance")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Finance service is not available",
        )
    if not service.is_initialized():
        await service.initialize()
    return service


@router.get("/quote/{symbol}")
async def get_stock_quote(symbol: str, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Busca a cotação completa de uma ação.

    Args:
        symbol: Símbolo da ação (ex: "AAPL", "GOOGL", "TSLA")

    Returns:
        Cotação completa com preço, volume, variação, etc.

    Raises:
        HTTPException 500: Se houver erro ao buscar cotação
    """
    try:
        service = await _get_finance_service()
        quote_data = await service.get_quote(symbol.upper())

        return {
            "success": True,
            "data": quote_data,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price/{symbol}")
async def get_stock_price(symbol: str, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Busca apenas o preço atual de uma ação (endpoint mais leve).

    Args:
        symbol: Símbolo da ação (ex: "AAPL", "GOOGL", "TSLA")

    Returns:
        Preço atual da ação

    Raises:
        HTTPException 500: Se houver erro ao buscar preço
    """
    try:
        service = await _get_finance_service()
        price_data = await service.get_price(symbol.upper())

        return {
            "success": True,
            "data": price_data,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{symbol}")
async def get_stock_history(
    symbol: str,
    interval: str = Query(
        default="1day",
        pattern="^(1min|5min|15min|30min|45min|1h|2h|4h|1day|1week|1month)$",
    ),
    outputsize: int = Query(default=30, ge=1, le=5000),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Busca o histórico de preços de uma ação.

    Args:
        symbol: Símbolo da ação (ex: "AAPL", "GOOGL", "TSLA")
        interval: Intervalo de tempo (1min, 5min, 15min, 30min, 45min,
                  1h, 2h, 4h, 1day, 1week, 1month)
        outputsize: Número de pontos de dados (1-5000, padrão: 30)

    Returns:
        Histórico de preços

    Raises:
        HTTPException 400: Se interval for inválido
        HTTPException 500: Se houver erro ao buscar histórico
    """
    try:
        service = await _get_finance_service()
        history_data = await service.get_time_series(
            symbol.upper(),
            interval,
            outputsize,
        )

        return {
            "success": True,
            "data": history_data,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
