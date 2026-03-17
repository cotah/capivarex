"""
GitHub OAuth Routes.

Flow:
1. User clicks "Connect GitHub" → GET /api/auth/github/connect?user_id=xxx
2. Redirects to GitHub OAuth authorization page
3. User authorizes → GitHub redirects to /api/auth/github/callback?code=xxx&state=user_id
4. We exchange code for access_token → save to github_connections table

Env vars:
- GITHUB_CLIENT_ID: GitHub OAuth App client ID
- GITHUB_CLIENT_SECRET: GitHub OAuth App client secret
- GITHUB_ADMIN_TOKEN: Admin token for cybersecurity bot (optional, env-only)
"""

import logging
import os
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()
logger = logging.getLogger(__name__)

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

# Scopes: repo (full repo access), read:user (profile info)
GITHUB_SCOPES = "repo read:user"


def _get_client_id() -> str:
    return os.getenv("GITHUB_CLIENT_ID", "")


def _get_client_secret() -> str:
    return os.getenv("GITHUB_CLIENT_SECRET", "")


def _get_callback_url() -> str:
    base = os.getenv(
        "API_BASE_URL",
        "https://capivarex-production.up.railway.app",
    )
    return f"{base}/api/auth/github/callback"


# ---------------------------------------------------------------------------
# Step 1: Redirect user to GitHub authorization
# ---------------------------------------------------------------------------

@router.get("/github/connect")
async def github_connect(user_id: str = Query(...)):
    """Redirect user to GitHub OAuth authorization page."""
    client_id = _get_client_id()
    if not client_id:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")

    params = {
        "client_id": client_id,
        "redirect_uri": _get_callback_url(),
        "scope": GITHUB_SCOPES,
        "state": user_id,  # Pass user_id through OAuth state
    }

    auth_url = f"{GITHUB_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=auth_url)


# ---------------------------------------------------------------------------
# Step 2: GitHub redirects back with code
# ---------------------------------------------------------------------------

@router.get("/github/callback")
async def github_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    """Handle GitHub OAuth callback — exchange code for token."""
    if error:
        logger.warning("GitHub OAuth error: %s", error)
        return _close_window_response("GitHub connection failed. Please try again.")

    if not code or not state:
        return _close_window_response("Missing authorization code.")

    user_id = state
    client_id = _get_client_id()
    client_secret = _get_client_secret()

    if not client_id or not client_secret:
        return _close_window_response("GitHub OAuth not configured on server.")

    # Exchange code for access token
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GITHUB_TOKEN_URL,
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": _get_callback_url(),
                },
                headers={"Accept": "application/json"},
            )
            data = resp.json()

    except Exception as e:
        logger.error("GitHub token exchange failed: %s", e)
        return _close_window_response("Failed to connect to GitHub. Please try again.")

    access_token = data.get("access_token")
    if not access_token:
        error_desc = data.get("error_description", data.get("error", "Unknown error"))
        logger.warning("GitHub token exchange failed: %s", error_desc)
        return _close_window_response(f"GitHub error: {error_desc}")

    # Get GitHub username
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_resp = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            github_user = user_resp.json()

        github_username = github_user.get("login", "")

    except Exception:
        github_username = ""

    # Save to database
    try:
        from services.core import get_service

        db = get_service("database")
        if db and db.is_initialized():
            await db.save_github_connection(user_id, github_username, access_token)
            logger.info(
                "GitHub connected: user=%s github=%s",
                user_id[:8], github_username,
            )
        else:
            logger.error("Database not available for GitHub save")

    except Exception as e:
        logger.error("GitHub connection save failed: %s", e)
        return _close_window_response("Failed to save connection. Please try again.")

    return _close_window_response(
        f"✅ GitHub connected as @{github_username}!",
        success=True,
    )


# ---------------------------------------------------------------------------
# Admin token check (for cybersecurity bot)
# ---------------------------------------------------------------------------

@router.get("/github/admin-status")
async def github_admin_status():
    """Check if admin GitHub token is configured (for cybersecurity bot)."""
    admin_token = os.getenv("GITHUB_ADMIN_TOKEN", "")
    return {
        "configured": bool(admin_token),
        "note": "Admin token is for cybersecurity bot system operations only",
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _close_window_response(message: str, success: bool = False) -> HTMLResponse:
    """Return HTML that shows a message and closes the OAuth popup window."""
    color = "#22c55e" if success else "#ef4444"
    icon = "✅" if success else "❌"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>GitHub — Capivarex</title></head>
    <body style="
        display:flex; justify-content:center; align-items:center;
        min-height:100vh; margin:0;
        background:#0a0a0a; color:white;
        font-family:system-ui,-apple-system,sans-serif;
    ">
        <div style="text-align:center; max-width:400px; padding:20px;">
            <div style="font-size:48px; margin-bottom:16px;">{icon}</div>
            <p style="font-size:18px; color:{color}; margin-bottom:24px;">{message}</p>
            <p style="font-size:14px; color:#888;">This window will close automatically...</p>
        </div>
        <script>
            setTimeout(function() {{ window.close(); }}, 2500);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
