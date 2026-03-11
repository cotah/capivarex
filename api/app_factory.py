# api/app_factory.py
"""
Application factory — explicit initialization entry point.

Usage:
    from api.app_factory import create_app
    app = create_app()
"""

from services.registration import register_all_services
from agents.registration import register_all_agents


def create_app():
    """
    Create and configure the FastAPI application.

    Steps:
      1. Explicitly register all services and agents.
      2. Import and return the configured app from api.main.
    """
    register_all_services()
    register_all_agents()

    # The app object in api.main is already fully configured
    # (routers, middleware, Prometheus, etc.)
    from api.main import app
    return app
