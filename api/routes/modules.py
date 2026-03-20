# api/routes/modules.py
"""
Modules API Routes
Provides endpoints for the frontend to display capivara module status.
"""
from fastapi import APIRouter, Depends

from api.middleware.webapp_auth import verify_webapp_user
from capivarex_modules.access_service import get_module_access_service
from capivarex_modules.config import CAPIVARA_MODULES

router = APIRouter(prefix="/api/modules", tags=["Modules"])


@router.get("/")
async def list_modules(user_id: str = Depends(verify_webapp_user)):
    """List all capivara modules with user's access status."""
    access_svc = get_module_access_service()
    modules = await access_svc.get_user_modules(user_id)
    return {"modules": modules}


@router.get("/config")
async def get_modules_config():
    """Public endpoint — returns module metadata without user-specific access status."""
    return {
        "modules": [
            {
                "module_name": name,
                "name": config["name"],
                "full_name": config["full_name"],
                "description": config["description"],
                "color": config["color"],
                "emoji": config["emoji"],
                "price_eur": config.get("price_eur"),
                "status": config["status"],
            }
            for name, config in CAPIVARA_MODULES.items()
        ]
    }
