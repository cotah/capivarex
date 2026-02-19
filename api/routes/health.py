# api/routes/health.py
"""Health check route for external monitoring."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from services.core import registry as service_registry, ServiceStatus

router = APIRouter()


@router.get("/health", tags=["Monitoring"])
async def health_check():
    """
    Verifica o status de todos os servicos inicializados.

    Retorna 200 se todos estiverem saudaveis, 503 caso contrario.
    """
    service_statuses = {}
    overall_healthy = True

    for name, service in service_registry._services.items():
        if service.is_initialized():
            try:
                svc_status = await service.health_check()
                is_ok = svc_status == ServiceStatus.HEALTHY
                service_statuses[name] = "ok" if is_ok else "error"
                if not is_ok:
                    overall_healthy = False
            except Exception:
                service_statuses[name] = "error"
                overall_healthy = False
        else:
            service_statuses[name] = "not_initialized"

    if overall_healthy:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ok", "services": service_statuses},
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "services": service_statuses},
        )
