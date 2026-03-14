"""
Tuya OAuth Routes — Connect, callback, status, disconnect.

Endpoints:
- GET  /api/auth/tuya/connect    → Redirect to Tuya authorization page
- GET  /api/auth/tuya/callback   → Handle Tuya OAuth callback
- GET  /api/auth/tuya/status     → Check if user has Tuya connected
- POST /api/auth/tuya/disconnect → Remove Tuya connection
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from pydantic import BaseModel

from api.middleware.webapp_auth import verify_webapp_user
from services.auth.tuya_oauth_service import get_tuya_oauth
from utils.identity import resolve_user_uuid

router = APIRouter(prefix="/api/auth/tuya", tags=["auth"])


class TuyaLoginRequest(BaseModel):
    username: str
    password: str
    country_code: str = "353"
    schema: str = "smartlife"


@router.post("/login")
async def tuya_login(
    body: TuyaLoginRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Login to Tuya with email/password — for Smart Life / Tuya Smart users."""
    try:
        oauth = get_tuya_oauth()
        await oauth.direct_login(
            user_id=user_id,
            username=body.username,
            password=body.password,
            country_code=body.country_code,
            schema=body.schema,
        )
        logger.info("Tuya login success: user={}", user_id[:8])
        return {"ok": True, "connected": True}
    except ValueError as e:
        logger.error("Tuya login failed: {}", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Tuya login error: {}", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Tuya login failed")


@router.get("/connect")
async def tuya_connect(
    user_id: str = Query(..., description="CAPIVAREX user ID"),
) -> RedirectResponse:
    """Redirect user to Tuya authorization page."""
    try:
        user_id = await resolve_user_uuid(user_id, context="tuya_connect")
        oauth = get_tuya_oauth()
        auth_url = oauth.get_authorization_url(user_id)
        logger.info("Tuya OAuth: user={} redirecting to consent screen", user_id[:8])
        return RedirectResponse(url=auth_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Tuya OAuth connect error: {}", e)
        return HTMLResponse(content=_error_page(str(e)), status_code=500)


@router.get("/callback")
async def tuya_callback(
    code: str = Query(..., description="Authorization code from Tuya"),
    state: str = Query(..., description="User ID passed as state"),
):
    """Handle Tuya OAuth callback — exchange code for tokens."""
    try:
        user_id = await resolve_user_uuid(state, context="tuya_callback")
        oauth = get_tuya_oauth()
        result = await oauth.handle_callback(code, user_id)

        tuya_uid = result.get("tuya_uid", "")
        logger.info("Tuya OAuth success: user={}, tuya_uid={}", user_id[:8], tuya_uid)

        return HTMLResponse(content=_success_page(tuya_uid))

    except ValueError as e:
        logger.error("Tuya OAuth callback ValueError: {}", e)
        return HTMLResponse(content=_error_page(str(e)), status_code=400)
    except Exception as e:
        logger.error("Tuya OAuth callback failed: {}", e, exc_info=True)
        return HTMLResponse(content=_error_page(str(e)), status_code=500)


@router.get("/status")
async def tuya_status(
    user_id: str = Query(..., description="User ID"),
):
    """Check if user has Tuya connected."""
    user_id = await resolve_user_uuid(user_id, context="tuya_status")
    oauth = get_tuya_oauth()
    connected = await oauth.is_connected(user_id)

    devices = []
    if connected:
        try:
            devices = await oauth.get_user_devices(user_id)
        except Exception:
            pass

    return {
        "connected": connected,
        "device_count": len(devices),
        "services": ["smart_home", "device_control"] if connected else [],
    }


@router.post("/disconnect")
async def tuya_disconnect(
    user_id: str = Query(..., description="User ID"),
):
    """Remove Tuya connection."""
    user_id = await resolve_user_uuid(user_id, context="tuya_disconnect")
    oauth = get_tuya_oauth()
    success = await oauth.disconnect(user_id)

    if success:
        return {"ok": True, "message": "Tuya disconnected"}
    raise HTTPException(status_code=500, detail="Failed to disconnect Tuya")


# ------------------------------------------------------------------
# HTML pages for popup flow
# ------------------------------------------------------------------


def _success_page(tuya_uid: str = "") -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Smart Home Connected!</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: linear-gradient(135deg, #FF6B2B 0%, #0a0a0f 100%);
            color: #fff;
        }
        .card {
            background: rgba(255,255,255,0.15); backdrop-filter: blur(10px);
            border-radius: 20px; padding: 3rem; text-align: center; max-width: 400px;
        }
        .icon { font-size: 4rem; margin-bottom: 1rem; }
        h1 { margin: 0.5rem 0; font-size: 1.5rem; }
        p { opacity: 0.9; margin: 0.5rem 0; }
        .close { margin-top: 1.5rem; opacity: 0.7; font-size: 0.9rem; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#127968;</div>
        <h1>Smart Home Connected!</h1>
        <p>Your Tuya / Smart Life devices are now linked.</p>
        <p>Try: "turn on living room lights" or "set AC to 22 degrees"</p>
        <p class="close">This window will close automatically...</p>
    </div>
    <script>setTimeout(function(){ window.close(); }, 2000);</script>
</body>
</html>"""


def _error_page(error: str) -> str:
    safe_error = error[:200].replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Connection Failed</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: linear-gradient(135deg, #e74c3c 0%, #0a0a0f 100%);
            color: #fff;
        }}
        .card {{
            background: rgba(255,255,255,0.15); backdrop-filter: blur(10px);
            border-radius: 20px; padding: 3rem; text-align: center; max-width: 400px;
        }}
        .icon {{ font-size: 4rem; margin-bottom: 1rem; }}
        h1 {{ margin: 0.5rem 0; font-size: 1.5rem; }}
        p {{ opacity: 0.9; margin: 0.5rem 0; }}
        .error {{ font-size: 0.85rem; opacity: 0.7; margin-top: 1rem; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#9888;</div>
        <h1>Connection Failed</h1>
        <p>Could not connect your Smart Home account.</p>
        <p class="error">{safe_error}</p>
        <p>Please close this window and try again.</p>
    </div>
</body>
</html>"""
