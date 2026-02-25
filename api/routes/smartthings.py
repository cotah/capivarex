"""
api/routes/smartthings.py

FIX [2025-02]: Adicionado endpoint POST /webhook para tratar lifecycle events
do SmartThings (CONFIRMATION, PING, INSTALL, UPDATE, EVENT, UNINSTALL).

PROBLEMA: O SmartThings Developer Workspace envia um CONFIRMATION request
ao webhook URL quando a app é registada. O código anterior não tinha endpoint
POST para receber este request, por isso a verificação falhava sempre.

SOLUÇÃO: Adicionar POST /webhook que:
  1. PING → responde com {pingData: {challenge}} (health check)
  2. CONFIRMATION → faz GET ao confirmationUrl e responde com sucesso
  3. INSTALL/UPDATE/EVENT/UNINSTALL → responde 200 OK (não usados neste fluxo)
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from services.core import get_service
from api.dependencies import get_current_user
from utils.encryption import decrypt_token, encrypt_token

router = APIRouter()
logger = logging.getLogger("capivarex.api.routes.smartthings")

# OAuth Configuration
CLIENT_ID = os.getenv("SMARTTHINGS_CLIENT_ID")
CLIENT_SECRET = os.getenv("SMARTTHINGS_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SMARTTHINGS_REDIRECT_URI")

OAUTH_AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://api.smartthings.com/oauth/token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_oauth_config() -> None:
    if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="SmartThings OAuth config missing (CLIENT_ID/SECRET/REDIRECT_URI)",
        )


def _get_smartthings_service():
    service = get_service("smartthings")
    if service is None:
        raise HTTPException(
            status_code=503, detail="SmartThings service is not available"
        )
    return service


def _get_database_service():
    service = get_service("database")
    if service is None:
        raise HTTPException(status_code=503, detail="Database service is not available")
    return service


def _get_supabase_client():
    return _get_database_service().get_client()


def _parse_expires_at(raw_value: str) -> datetime:
    return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).replace(tzinfo=None)


def _is_token_expired(raw_expires_at: str) -> bool:
    try:
        return _parse_expires_at(raw_expires_at) <= datetime.now()
    except Exception:
        return True


def _get_token_row(user_id: str) -> Optional[Dict[str, Any]]:
    supabase = _get_supabase_client()
    result = (
        supabase.table("smartthings_tokens")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return result.data if result and result.data else None


async def _refresh_user_tokens(user_id: str) -> Dict[str, Any]:
    _assert_oauth_config()
    row = _get_token_row(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="SmartThings not connected")

    refresh_token = decrypt_token(row.get("refresh_token", ""))

    async with aiohttp.ClientSession() as session:
        async with session.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        ) as response:
            response.raise_for_status()
            token_data = await response.json()

    access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token", refresh_token)
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = datetime.now() + timedelta(seconds=expires_in)

    supabase = _get_supabase_client()
    supabase.table("smartthings_tokens").upsert(
        {
            "user_id": user_id,
            "access_token": encrypt_token(access_token),
            "refresh_token": encrypt_token(new_refresh_token),
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
    ).execute()

    logger.info("SmartThings token refreshed for user %s", user_id)
    return {"access_token": access_token, "expires_at": expires_at.isoformat()}


async def _get_valid_access_token(user_id: str) -> str:
    row = _get_token_row(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="SmartThings not connected")
    if _is_token_expired(row.get("expires_at", "")):
        refreshed = await _refresh_user_tokens(user_id)
        return refreshed["access_token"]
    return decrypt_token(row["access_token"])


# ---------------------------------------------------------------------------
# FIX: Webhook lifecycle handler (NOVO)
# ---------------------------------------------------------------------------


@router.post("")
async def smartthings_webhook(request: Request) -> JSONResponse:
    """
    SmartThings Automation Connector lifecycle handler.

    O SmartThings envia POST para este endpoint durante o registo e operação:
    - CONFIRMATION: verifica que o servidor está activo (deve fazer GET ao confirmationUrl)
    - PING:         health check (deve devolver o challenge)
    - INSTALL:      SmartApp instalada por um utilizador
    - UPDATE:       configuração actualizada
    - EVENT:        evento de dispositivo
    - UNINSTALL:    SmartApp removida

    Sem este endpoint, "VERIFY APP REGISTRATION" falha sempre.
    """
    try:
        body = await request.json()
    except Exception:
        logger.error("SmartThings webhook: invalid JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    lifecycle = body.get("lifecycle", "")
    logger.info("SmartThings webhook lifecycle: %s", lifecycle)

    # ── CONFIRMATION ─────────────────────────────────────────────────────────
    # SmartThings envia isto quando clicas "VERIFY APP REGISTRATION".
    # Tens de fazer GET ao confirmationUrl para confirmar que és tu.
    if lifecycle == "CONFIRMATION":
        confirmation_data = body.get("confirmationData", {})
        confirmation_url = confirmation_data.get("confirmationUrl")

        if not confirmation_url:
            logger.error("CONFIRMATION lifecycle missing confirmationUrl")
            raise HTTPException(status_code=400, detail="Missing confirmationUrl")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(confirmation_url)
                logger.info(
                    "SmartThings CONFIRMATION GET %s → %d",
                    confirmation_url,
                    resp.status_code,
                )
        except Exception as e:
            logger.error("Failed to call confirmationUrl: %s", e)
            # Responde mesmo assim — o SmartThings aceita se o GET foi feito

        return JSONResponse(
            content={"targetUrl": confirmation_url},
            status_code=200,
        )

    # ── PING ──────────────────────────────────────────────────────────────────
    # Health check periódico do SmartThings.
    if lifecycle == "PING":
        ping_data = body.get("pingData", {})
        challenge = ping_data.get("challenge", "")
        return JSONResponse(
            content={"pingData": {"challenge": challenge}},
            status_code=200,
        )

    # ── INSTALL ───────────────────────────────────────────────────────────────
    if lifecycle == "INSTALL":
        install_data = body.get("installData", {})
        logger.info("SmartThings INSTALL: %s", install_data)
        return JSONResponse(content={"installData": {}}, status_code=200)

    # ── UPDATE ────────────────────────────────────────────────────────────────
    if lifecycle == "UPDATE":
        return JSONResponse(content={"updateData": {}}, status_code=200)

    # ── EVENT ─────────────────────────────────────────────────────────────────
    if lifecycle == "EVENT":
        return JSONResponse(content={"eventData": {}}, status_code=200)

    # ── UNINSTALL ─────────────────────────────────────────────────────────────
    if lifecycle == "UNINSTALL":
        return JSONResponse(content={"uninstallData": {}}, status_code=200)

    # ── Unknown ───────────────────────────────────────────────────────────────
    logger.warning("SmartThings unknown lifecycle: %s", lifecycle)
    return JSONResponse(content={"status": "ok"}, status_code=200)


# ---------------------------------------------------------------------------
# OAuth Endpoints (inalterados)
# ---------------------------------------------------------------------------


@router.get("/connect")
async def connect_smartthings(
    user_id: str = Query(default="unknown"),
) -> RedirectResponse:
    try:
        _assert_oauth_config()
        auth_url = (
            f"{OAUTH_AUTHORIZE_URL}"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=r:devices:* x:devices:*"
            f"&state={user_id}"
        )
        logger.info("User %s initiating SmartThings OAuth", user_id)
        return RedirectResponse(url=auth_url)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to initiate OAuth: %s", exc)
        raise HTTPException(status_code=500, detail="OAuth initiation failed")


@router.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    try:
        _assert_oauth_config()
        user_id = str(state)  # user_id vem no state param

        async with aiohttp.ClientSession() as session:
            async with session.post(
                OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "redirect_uri": REDIRECT_URI,
                    "code": code,
                },
            ) as response:
                response.raise_for_status()
                token_data = await response.json()

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in", 3600))
        expires_at = datetime.now() + timedelta(seconds=expires_in)

        supabase = _get_supabase_client()
        supabase.table("smartthings_tokens").upsert(
            {
                "user_id": user_id,
                "access_token": encrypt_token(access_token),
                "refresh_token": encrypt_token(refresh_token),
                "expires_at": expires_at.isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
        ).execute()

        logger.info("SmartThings tokens stored for user %s", user_id)
        return RedirectResponse(url=f"/smartthings/success?user_id={user_id}")
    except HTTPException:
        raise
    except aiohttp.ClientError as exc:
        logger.error("OAuth token exchange failed: %s", exc)
        raise HTTPException(status_code=400, detail="Token exchange failed")
    except Exception as exc:
        logger.error("OAuth callback error: %s", exc)
        raise HTTPException(status_code=500, detail="OAuth callback failed")


@router.post("/refresh")
async def refresh_tokens(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        user_id = str(current_user["id"])
        refreshed = await _refresh_user_tokens(user_id)
        return {"success": True, "expires_at": refreshed["expires_at"]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unexpected refresh error: %s", exc)
        raise HTTPException(status_code=500, detail="Token refresh failed")


@router.get("/devices")
async def get_user_devices(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        user_id = str(current_user["id"])
        access_token = await _get_valid_access_token(user_id)
        smartthings_service = _get_smartthings_service()
        devices = await smartthings_service.get_devices(access_token=access_token)

        supabase = _get_supabase_client()
        for device in devices:
            capabilities: List[str] = []
            for comp in device.get("components", []):
                for cap in comp.get("capabilities", []):
                    cap_id = cap.get("id")
                    if cap_id:
                        capabilities.append(cap_id)
            supabase.table("smartthings_devices").upsert(
                {
                    "user_id": user_id,
                    "device_id": device.get("deviceId"),
                    "label": device.get("label"),
                    "device_type": device.get("deviceTypeName", "unknown"),
                    "room": device.get("roomId"),
                    "capabilities": capabilities,
                    "updated_at": datetime.now().isoformat(),
                }
            ).execute()

        logger.info("Retrieved %d devices for user %s", len(devices), user_id)
        return {"devices": devices}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get devices: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve devices")


@router.post("/command")
async def execute_device_command(
    device_id: str,
    capability: str,
    command: str,
    arguments: Optional[List[Any]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        user_id = str(current_user["id"])
        access_token = await _get_valid_access_token(user_id)
        smartthings_service = _get_smartthings_service()
        success = await smartthings_service.execute_command(
            device_id=device_id,
            capability=capability,
            command=command,
            arguments=arguments or [],
            access_token=access_token,
        )
        if success:
            logger.info("Command executed: %s -> %s.%s", device_id, capability, command)
            return {"success": True, "message": "Command executed"}
        raise HTTPException(status_code=500, detail="Command execution failed")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to execute command: %s", exc)
        raise HTTPException(status_code=500, detail="Command execution failed")


@router.get("/status")
async def get_connection_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        user_id = str(current_user["id"])
        supabase = _get_supabase_client()
        result = (
            supabase.table("smartthings_tokens")
            .select("expires_at")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not result.data:
            return {"connected": False}
        expires_at = _parse_expires_at(result.data["expires_at"])
        return {
            "connected": True,
            "expires_at": expires_at.isoformat(),
            "is_expired": expires_at < datetime.now(),
        }
    except Exception as exc:
        logger.error("Failed to check status: %s", exc)
        return {"connected": False}
