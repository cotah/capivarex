# -*- coding: utf-8 -*-
"""
Auth Routes — Spotify OAuth2
==============================
Endpoints para conectar/desconectar contas Spotify.

Fluxo:
1. Frontend/bot chama GET /api/auth/spotify/connect?user_id=xxx
2. Redireciona user para Spotify consent screen
3. Spotify redireciona para GET /api/auth/spotify/callback?code=xxx&state=xxx
4. Backend troca code por tokens, guarda no Supabase
5. User vê página de sucesso

Endpoints:
- GET  /api/auth/spotify/connect     → gera URL e redireciona
- GET  /api/auth/spotify/callback    → processa callback do Spotify
- GET  /api/auth/spotify/status      → verifica se user está conectado
- POST /api/auth/spotify/disconnect  → desconecta conta
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

from services.auth.spotify_oauth_service import get_spotify_oauth
from services.i18n import t
from utils.identity import resolve_user_uuid

router = APIRouter(prefix="/api/auth/spotify", tags=["auth"])


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/connect")
async def spotify_connect(
    user_id: str = Query(..., description="User ID"),
):
    """
    Inicia fluxo OAuth2 Spotify.
    Redireciona o user para o Spotify consent screen.
    """
    user_id = await resolve_user_uuid(user_id, context="spotify")

    oauth = get_spotify_oauth()
    if not oauth.is_configured:
        raise HTTPException(
            status_code=503,
            detail=t("oauth_not_configured"),
        )

    auth_url = oauth.get_auth_url(user_id)
    logger.info("Spotify OAuth2 flow started: user=%s", user_id)
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def spotify_callback(
    code: str = Query(None, description="Authorization code from Spotify"),
    state: str = Query(None, description="State parameter (base64 JSON)"),
    error: str = Query(None, description="Error from Spotify"),
):
    """
    Callback do Spotify OAuth2.
    Recebe authorization code, troca por tokens, guarda no Supabase.
    """
    if error:
        logger.warning("Spotify OAuth error: %s", error)
        return HTMLResponse(
            content=_error_page(f"Spotify error: {error}"),
            status_code=400,
        )

    if not code or not state:
        return HTMLResponse(
            content=_error_page(t("oauth_missing_params")),
            status_code=400,
        )

    try:
        oauth = get_spotify_oauth()
        result = await oauth.handle_callback(code=code, state_b64=state)

        display_name = result.get("display_name", "")
        email = result.get("email", "")

        logger.info(
            "Spotify OAuth success: name=%s email=%s",
            display_name,
            email,
        )

        return HTMLResponse(
            content=_success_page(display_name or email, email)
        )

    except ValueError as e:
        logger.error("Spotify OAuth callback ValueError: {}", e)
        return HTMLResponse(
            content=_error_page(str(e)),
            status_code=400,
        )
    except Exception as e:
        logger.error(
            "Spotify OAuth callback failed: %s", e, exc_info=True
        )
        return HTMLResponse(
            content=_error_page(str(e)),
            status_code=500,
        )


@router.get("/status")
async def spotify_status(
    user_id: str = Query(..., description="User ID"),
):
    """Verifica se user tem conta Spotify conectada."""
    user_id = await resolve_user_uuid(user_id, context="spotify")
    oauth = get_spotify_oauth()
    connected = await oauth.is_connected(user_id)

    return {
        "connected": connected,
        "services": ["spotify_playback", "spotify_playlists"]
        if connected
        else [],
    }


@router.post("/disconnect")
async def spotify_disconnect(
    user_id: str = Query(..., description="User ID"),
):
    """Desconecta conta Spotify do user."""
    user_id = await resolve_user_uuid(user_id, context="spotify")
    oauth = get_spotify_oauth()
    success = await oauth.disconnect(user_id)

    if success:
        logger.info("Spotify disconnected: user=%s", user_id)
        return {"success": True, "message": t("oauth_disconnected")}
    else:
        raise HTTPException(
            status_code=500, detail=t("oauth_disconnect_failed")
        )


# -- HTML Pages ----------------------------------------------------------------


def _success_page(name: str, email: str) -> str:
    """Spotify-themed success page (green gradient)."""
    display = name or email
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Spotify Connected!</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #1DB954 0%, #191414 100%);
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
        .name {{ font-weight: bold; font-size: 1.1rem; }}
        .close {{ margin-top: 1.5rem; opacity: 0.7; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#127925;</div>
        <h1>Spotify Connected!</h1>
        <p class="name">{display}</p>
        <p>You can now control Spotify from the bot!</p>
        <p>Try: "play Bohemian Rhapsody" or "pause"</p>
        <p class="close">You can close this window and return to Telegram.</p>
    </div>
</body>
</html>"""


def _error_page(error: str) -> str:
    """Spotify-themed error page (red gradient)."""
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Spotify Connection Error</title>
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
        <h1>Connection Failed</h1>
        <p>{error}</p>
        <p>Please try again from the bot.</p>
    </div>
</body>
</html>"""
