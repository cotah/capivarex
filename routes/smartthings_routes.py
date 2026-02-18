"""
Compatibility wrapper for SmartThings routes.

Re-exports the router implemented in api.routes.smartthings_routes.
"""

from api.routes.smartthings_routes import router

__all__ = ["router"]
