"""
Notion OAuth2 routes — connect, callback, status, disconnect.

Follows the same pattern as google_auth.py / microsoft_auth.py.
Endpoints: /api/auth/notion/*
"""

import base64
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from services.auth.notion_oauth_service import get_notion_oauth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/notion", tags=["Notion Auth"])


# ---------------------------------------------------------------------------
# HTML templates
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
<h2>Notion Connected</h2>
<p>Your notes will now sync to Notion.<br>You can close this window.</p>
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


@router.get("/login")
async def notion_login(user_id: str = Query(...)):
    """Initiate Notion OAuth2 flow."""
    oauth = get_notion_oauth()
    url = oauth.get_authorization_url(user_id)
    return RedirectResponse(url)


@router.get("/callback")
async def notion_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    """Handle Notion OAuth2 callback."""
    if error:
        logger.warning("Notion OAuth error: %s", error)
        return HTMLResponse(_ERROR_HTML % error, status_code=400)

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

    oauth = get_notion_oauth()

    # Exchange code for tokens
    try:
        token_data = await oauth.exchange_code(code)
    except Exception as e:
        logger.error("Notion token exchange failed: %s", e)
        return HTMLResponse(
            _ERROR_HTML % "Failed to exchange authorization code. Please try again.",
            status_code=400,
        )

    # Save tokens
    saved = await oauth.save_tokens(user_id, token_data)
    if not saved:
        return HTMLResponse(_ERROR_HTML % "Failed to save tokens.", status_code=500)

    workspace = token_data.get("workspace_name", "")
    logger.info("Notion connected for user %s (workspace: %s)", user_id[:8], workspace)
    return HTMLResponse(_SUCCESS_HTML)


@router.get("/status")
async def notion_status(user_id: str = Query(...)):
    """Check Notion connection status."""
    oauth = get_notion_oauth()
    accounts = await oauth.get_connected_accounts(user_id)
    connected = len(accounts) > 0

    return {
        "connected": connected,
        "provider": "notion",
        "accounts": [
            {"workspace": a.get("email", ""), "connected_at": a.get("created_at", "")}
            for a in accounts
        ],
    }


@router.post("/disconnect")
async def notion_disconnect(user_id: str = Query(...)):
    """Disconnect Notion account."""
    oauth = get_notion_oauth()
    success = await oauth.disconnect(user_id)
    return {"disconnected": success}
