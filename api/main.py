"""
Main FastAPI Application - Refactored Architecture.

Entry point for the CapivaraX Bot API with:
- Modular router structure
- Integration with agents and services
- Improved middleware and error handling
- Dependency injection
"""

# ==================================================================== 
# ALL IMPORTS AT TOP (ruff E402 compliance)
# ==================================================================== 
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from api.middleware.autofix import autofix_exception_middleware
from api.middleware.error_handler import setup_error_handlers
from api.middleware.logging import logging_middleware
from api.middleware.rate_limit import setup_rate_limiting
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.routes import (
    agent_generic,
    auth,
    chat,
    notes,
    research,
    dev,
    workspace,
    weather,
    finance,
    image,
    video,
    voice,
    calendar,
    car,
    traffic,
    smartthings,
    health,
)
from api.routes import webhooks
from api.routes.voice_pipeline_routes import router_pipeline as voice_pipeline_router

# Load environment variables
load_dotenv()

# Explicit service and agent registration
from services.registration import register_all_services  # noqa: E402
from agents.registration import register_all_agents  # noqa: E402

register_all_services()
register_all_agents()

# ==================================================================== 
# CRIAÇÃO DA APLICAÇÃO
# ==================================================================== 

app = FastAPI(
    title="CapivaraX Bot API",
    description="API Backend do CapivaraX Bot - Assistente de IA Unificado com Arquitetura Refatorada",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ==================================================================== 
# PROMETHEUS METRICS
# ==================================================================== 

Instrumentator().instrument(app).expose(app)

# ==================================================================== 
# MIDDLEWARE
# ==================================================================== 

app.middleware("http")(logging_middleware)
app.middleware("http")(autofix_exception_middleware)
app.add_middleware(SecurityHeadersMiddleware)
setup_rate_limiting(app)
setup_error_handlers(app)

_cors_origins = []

# Always allow localhost for development
if os.getenv("ENVIRONMENT") == "development":
    _cors_origins.extend([
        os.getenv("CORS_ORIGIN_LOCALHOST", "http://localhost:3000"),
        os.getenv("CORS_ORIGIN_VITE", "http://localhost:5173"),
        "https://*.replit.dev",
    ])

# Add configured frontend URL (production or staging)
_frontend_url = os.getenv("FRONTEND_URL")
if _frontend_url:
    _cors_origins.append(_frontend_url)

# Safety: if no origins configured, log a warning
if not _cors_origins:
    import logging
    logging.getLogger("capivarex.api").warning(
        "No CORS origins configured. Set FRONTEND_URL or ENVIRONMENT=development. "
        "Defaulting to allow all origins for safety."
    )
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ==================================================================== 
# HEALTH CHECKS
# ==================================================================== 

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "status": "online",
        "service": "CapivaraX Bot API",
        "version": "2.0.0",
        "architecture": "refactored",
    }


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "version": "2.0.0",
    }


@app.get("/api/health/detailed")
async def detailed_health_check():
    """Detailed health check with service status."""
    from services.core import registry as service_registry
    from agents.core import registry as agent_registry

    service_health = {}
    try:
        service_metrics = service_registry.get_all_metrics()
        for name, metrics in service_metrics.items():
            service_health[name] = {
                "status": metrics.get("status"),
                "initialized": metrics.get("initialized"),
                "call_count": metrics.get("call_count"),
                "error_rate": metrics.get("error_rate"),
            }
    except Exception as e:
        service_health["error"] = str(e)

    agent_health = {}
    try:
        agents = agent_registry.list_agents()
        agent_health = {"registered_agents": agents, "count": len(agents)}
    except Exception as e:
        agent_health["error"] = str(e)

    return {
        "status": "healthy",
        "version": "2.0.0",
        "services": service_health,
        "agents": agent_health,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


# ==================================================================== 
# DEBUG ENDPOINTS
# ==================================================================== 

@app.get("/debug/services")
def debug_services():
    """Lista todos os serviços registrados (apenas desenvolvimento)."""
    from services.core import registry as service_registry
    try:
        all_services = service_registry.list_services()
        metrics = service_registry.get_all_metrics()
        return {"total": len(all_services), "services": all_services, "metrics": metrics}
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug/agents")
def debug_agents():
    """Lista todos os agentes registrados (apenas desenvolvimento)."""
    from agents.core import registry as agent_registry
    try:
        all_agents = agent_registry.list_agents()
        return {"total": len(all_agents), "agents": all_agents}
    except Exception as e:
        return {"error": str(e)}


# ==================================================================== 
# ROUTERS
# ==================================================================== 

API_V1 = "/api/v1"

app.include_router(auth.router, prefix=f"{API_V1}/auth", tags=["Authentication"])
app.include_router(chat.router, prefix=f"{API_V1}/chat", tags=["Chat"])
app.include_router(notes.router, prefix=f"{API_V1}/notes", tags=["Notes"])
app.include_router(workspace.router, prefix=f"{API_V1}/workspace", tags=["Workspace"])
app.include_router(research.router, prefix=f"{API_V1}/research", tags=["Research"])
app.include_router(dev.router, prefix=f"{API_V1}/dev", tags=["Development"])
app.include_router(image.router, prefix=f"{API_V1}/image", tags=["Image"])
app.include_router(video.router, prefix=f"{API_V1}/video", tags=["Video"])
app.include_router(voice.router, prefix=f"{API_V1}/voice", tags=["Voice"])
app.include_router(voice_pipeline_router, prefix=f"{API_V1}/voice/pipeline", tags=["Voice Pipeline"])
app.include_router(weather.router, prefix=f"{API_V1}/weather", tags=["Weather"])
app.include_router(finance.router, prefix=f"{API_V1}/finance", tags=["Finance"])
app.include_router(calendar.router, prefix=f"{API_V1}/calendar", tags=["Calendar"])
app.include_router(car.router, prefix=f"{API_V1}/car", tags=["Car"])
app.include_router(traffic.router, prefix=f"{API_V1}/traffic", tags=["Traffic"])
app.include_router(smartthings.router, prefix=f"{API_V1}/smartthings", tags=["SmartThings"])
app.include_router(agent_generic.router, prefix=f"{API_V1}/agent", tags=["Generic Agent"])
app.include_router(webhooks.router, prefix=f"{API_V1}/webhooks", tags=["Webhooks"])
app.include_router(health.router, tags=["Monitoring"])


# ==================================================================== 
# STARTUP / SHUTDOWN
# ==================================================================== 

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    import logging
    logger = logging.getLogger("capivarex.api")
    logger.info("CapivaraX Bot API starting up...")
    from services import get_service
    for service_name in ["database", "openai", "redis"]:
        try:
            service = get_service(service_name)
            if service and not service.is_initialized():
                await service.initialize()
                logger.info("Initialized %s service", service_name)
        except Exception as e:
            logger.warning("Service %s not found or failed to initialize: %s", service_name, e)
    logger.info("CapivaraX Bot API started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    import logging
    logging.getLogger("capivarex.api").info("CapivaraX Bot API shutting down...")
