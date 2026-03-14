# -*- coding: utf-8 -*-
"""
Auth Routes — Google OAuth2
===========================
Endpoints para conectar/desconectar contas Google (Calendar + Gmail).

Fluxo:
1. Frontend/bot chama GET /api/auth/google/connect?user_id=xxx
2. Redireciona user para Google consent screen
3. Google redireciona para GET /api/auth/google/callback?code=xxx&state=xxx
4. Backend troca code por tokens, guarda no Supabase
5. User vê página de sucesso

Endpoints:
- GET  /api/auth/google/connect     → gera URL e redireciona
- GET  /api/auth/google/callback    → processa callback do Google
- GET  /api/auth/google/status      → verifica se user está conectado
- POST /api/auth/google/disconnect  → desconecta conta
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from services.auth.google_oauth_service import get_google_oauth
from services.i18n import t
from utils.identity import resolve_user_uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/google", tags=["auth"])


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/connect")
async def google_connect(
    user_id: str = Query(..., description="User ID"),
):
    """
    Inicia fluxo OAuth2 Google.
    Redireciona o user para o Google consent screen.

    Args:
        user_id: ID do utilizador (obrigatório)

    Returns:
        Redirect para Google consent screen
    """
    user_id = await resolve_user_uuid(user_id, context="google")

    oauth = get_google_oauth()
    if not oauth.is_configured:
        raise HTTPException(
            status_code=503,
            detail=t("oauth_not_configured"),
        )

    auth_url = oauth.get_auth_url(user_id)
    logger.info("OAuth2 flow started: user=%s", user_id)
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def google_callback(
    code: str = Query(None, description="Authorization code from Google"),
    state: str = Query(None, description="State parameter (base64 JSON)"),
    error: str = Query(None, description="Error from Google"),
):
    """
    Callback do Google OAuth2.
    Recebe authorization code, troca por tokens, guarda no Supabase.

    Returns:
        HTML page com resultado (sucesso ou erro)
    """
    # Google pode enviar erro em vez de code
    if error:
        logger.warning("Google OAuth error: %s", error)
        return HTMLResponse(
            content=_error_page(t("oauth_google_error", error=error)),
            status_code=400,
        )

    if not code or not state:
        return HTMLResponse(
            content=_error_page(t("oauth_missing_params")),
            status_code=400,
        )

    try:
        oauth = get_google_oauth()
        result = await oauth.handle_callback(code=code, state_b64=state)

        # handle_callback may return an error dict instead of raising
        if isinstance(result, dict) and result.get("error"):
            reason = result["error"]
            message = result.get("message", t("oauth_connect_error", error=reason))
            logger.warning("Google OAuth error: %s — %s", reason, message)
            return HTMLResponse(
                content=_error_page(message),
                status_code=400,
            )

        email = result.get("email", "")
        name = result.get("name", "")

        logger.info("Google OAuth success: email=%s", email)

        return HTMLResponse(content=_success_page(email, name))

    except ValueError as e:
        logger.error("OAuth callback ValueError: %s", e)
        return HTMLResponse(
            content=_error_page(t("oauth_invalid_state", error=str(e))),
            status_code=400,
        )
    except Exception as e:
        logger.error("OAuth callback failed: %s", e, exc_info=True)
        return HTMLResponse(
            content=_error_page(t("oauth_connect_error", error=str(e))),
            status_code=500,
        )


@router.get("/status")
async def google_status(
    user_id: str = Query(..., description="User ID"),
):
    """
    Verifica se user tem conta Google conectada.

    Returns:
        Dict com connected, email, accounts
    """
    user_id = await resolve_user_uuid(user_id, context="google")
    oauth = get_google_oauth()
    connected = await oauth.is_connected(user_id)
    email = await oauth.get_user_email(user_id) if connected else None
    accounts = await oauth.get_connected_accounts(user_id)

    return {
        "connected": connected,
        "email": email,
        "accounts": accounts,
        "services": ["calendar", "gmail"] if connected else [],
    }


@router.post("/disconnect")
async def google_disconnect(
    user_id: str = Query(..., description="User ID"),
):
    """
    Desconecta conta Google do user.
    Remove tokens do Supabase (soft delete — active=false).

    Returns:
        Dict com success
    """
    user_id = await resolve_user_uuid(user_id, context="google")
    oauth = get_google_oauth()
    success = await oauth.disconnect(user_id)

    if success:
        logger.info("Google disconnected: user=%s", user_id)
        return {"success": True, "message": t("oauth_disconnected")}
    else:
        raise HTTPException(
            status_code=500, detail=t("oauth_disconnect_failed")
        )


# -- HTML Pages ----------------------------------------------------------------


def _success_page(email: str, name: str) -> str:
    """Página HTML de sucesso após conectar Google."""
    display = name or email
    title = t("oauth_success_title")
    heading = t("oauth_success_heading")
    message = t("oauth_success_message", name=display)
    close_msg = t("oauth_success_close")
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
        }}
        .card {{
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 3rem;
            text-align: center;
            max-width: 400px;
        }}
        .icon {{ font-size: 4rem; margin-bottom: 1rem; }}
        h1 {{ margin: 0.5rem 0; font-size: 1.5rem; }}
        p {{ opacity: 0.9; margin: 0.5rem 0; }}
        .email {{ font-weight: bold; font-size: 1.1rem; }}
        .close {{ margin-top: 1.5rem; opacity: 0.7; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#10004;</div>
        <h1>{heading}</h1>
        <p class="email">{email}</p>
        <p>{message}</p>
        <p class="close">{close_msg}</p>
    </div>
    <script>setTimeout(function(){{ window.close(); }}, 2000);</script>
</body>
</html>"""


def _error_page(error: str) -> str:
    """Página HTML de erro."""
    title = t("oauth_error_page_title")
    heading = t("oauth_error_heading")
    retry = t("oauth_error_retry")
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: #fff;
        }}
        .card {{
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 3rem;
            text-align: center;
            max-width: 400px;
        }}
        .icon {{ font-size: 4rem; margin-bottom: 1rem; }}
        h1 {{ margin: 0.5rem 0; font-size: 1.5rem; }}
        p {{ opacity: 0.9; }}
        .error {{ font-family: monospace; font-size: 0.85rem; opacity: 0.8; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#10060;</div>
        <h1>{heading}</h1>
        <p>{error}</p>
        <p>{retry}</p>
    </div>
</body>
</html>"""
