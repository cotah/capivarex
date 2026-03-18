"""
Microsoft OAuth2 routes — connect, callback, status, disconnect.

Follows the same pattern as google_auth.py.
Endpoints: /api/auth/microsoft/*
"""

import base64
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from services.auth.microsoft_oauth_service import get_microsoft_oauth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/microsoft", tags=["Microsoft Auth"])


# ---------------------------------------------------------------------------
# HTML templates (same pattern as google_auth.py)
# ---------------------------------------------------------------------------

_SUCCESS_HTML = """
<!DOCTYPE html><html><head><title>Connected</title>
<style>body{font-family:system-ui;display:flex;justify-content:center;align-items:center;
height:100vh;margin:0;background:#0a0a0f;color:#e8e6e3}
.card{text-align:center;padding:40px;border-radius:16px;background:rgba(255,255,255,0.05);
border:1px solid rgba(255,255,255,0.1);max-width:400px}
.ok{color:#4ade80;font-size:48px}h2{margin:16px 0 8px}
p{color:rgba(255,255,255,0.6);font-size:14px}</style></head>
<body><div class="card"><div class="ok">✓</div>
<h2>Microsoft Connected</h2>
<p>Your Outlook and Calendar are now linked.<br>You can close this window.</p>
</div></body></html>
"""

_ERROR_HTML = """
<!DOCTYPE html><html><head><title>Error</title>
<style>body{font-family:system-ui;display:flex;justify-content:center;align-items:center;
height:100vh;margin:0;background:#0a0a0f;color:#e8e6e3}
.card{text-align:center;padding:40px;border-radius:16px;background:rgba(255,255,255,0.05);
border:1px solid rgba(255,255,255,0.1);max-width:400px}
.err{color:#f87171;font-size:48px}h2{margin:16px 0 8px}
p{color:rgba(255,255,255,0.6);font-size:14px}</style></head>
<body><div class="card"><div class="err">✕</div>
<h2>Connection Failed</h2>
<p>%s</p></div></body></html>
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/connect")
async def microsoft_connect(user_id: str = Query(...)):
    """Initiate Microsoft OAuth2 flow."""
    oauth = get_microsoft_oauth()
    url = oauth.get_authorization_url(user_id)
    return RedirectResponse(url)


@router.get("/callback")
async def microsoft_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
):
    """Handle Microsoft OAuth2 callback."""
    if error:
        msg = error_description or error
        logger.warning("Microsoft OAuth error: %s", msg)
        return HTMLResponse(_ERROR_HTML % msg, status_code=400)

    if not code or not state:
        return HTMLResponse(
            _ERROR_HTML % "Missing authorization code or state parameter.",
            status_code=400,
        )

    # Decode state
    try:
        state_json = base64.urlsafe_b64decode(state).decode()
        state_data = json.loads(state_json)
        user_id = state_data.get("user_id", "")
    except Exception:
        return HTMLResponse(_ERROR_HTML % "Invalid state parameter.", status_code=400)

    if not user_id:
        return HTMLResponse(_ERROR_HTML % "No user_id in state.", status_code=400)

    oauth = get_microsoft_oauth()

    # Exchange code for tokens
    try:
        token_data = await oauth.exchange_code(code)
    except Exception as e:
        logger.error("Microsoft token exchange failed: %s", e)
        return HTMLResponse(
            _ERROR_HTML % "Failed to exchange authorization code. Please try again.",
            status_code=400,
        )

    # Get user email
    email = ""
    try:
        access_token = token_data["access_token"]
        user_info = await oauth.get_user_info(access_token)
        email = user_info.get("mail") or user_info.get("userPrincipalName", "")
    except Exception as e:
        logger.warning("Could not get Microsoft user info: %s", e)

    # Save tokens
    saved = await oauth.save_tokens(user_id, token_data, email=email)
    if not saved:
        return HTMLResponse(_ERROR_HTML % "Failed to save tokens.", status_code=500)

    logger.info("Microsoft connected for user %s (%s)", user_id[:8], email)
    return HTMLResponse(_SUCCESS_HTML)


@router.get("/status")
async def microsoft_status(user_id: str = Query(...)):
    """Check Microsoft connection status."""
    oauth = get_microsoft_oauth()
    accounts = await oauth.get_connected_accounts(user_id)
    connected = len(accounts) > 0

    return {
        "connected": connected,
        "provider": "microsoft",
        "accounts": [
            {"email": a.get("email", ""), "connected_at": a.get("created_at", "")}
            for a in accounts
        ],
    }


@router.post("/disconnect")
async def microsoft_disconnect(user_id: str = Query(...)):
    """Disconnect Microsoft account."""
    oauth = get_microsoft_oauth()
    success = await oauth.disconnect(user_id)
    return {"disconnected": success}
