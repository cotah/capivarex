# -*- coding: utf-8 -*-
"""
Google OAuth2 Service
=====================
Serviço centralizado de OAuth2 Google para Calendar + Gmail.

Responsabilidades:
- Gerar URL de autorização (com scopes combinados)
- Trocar authorization code por tokens
- Guardar/carregar tokens do Supabase (tabela user_oauth_tokens)
- Renovar tokens expirados automaticamente
- Verificar se user tem conta Google conectada

Usado por:
- GmailService (ler/enviar emails)
- CalendarService (modo OAuth2 per-user)
- Auth routes (/api/auth/google/*)
"""

import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Scopes combinados: Calendar + Gmail
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


class GoogleOAuthService:
    """
    Serviço centralizado de OAuth2 Google.

    Não é um BaseService registado — é usado directamente pelo
    GmailService, CalendarService e pelas auth routes.
    """

    def __init__(self):
        self.client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
        self.client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv(
            "GOOGLE_OAUTH_REDIRECT_URI",
            "http://localhost:8000/api/auth/google/callback",
        )

    @property
    def is_configured(self) -> bool:
        """Verifica se OAuth2 está configurado."""
        return bool(self.client_id and self.client_secret)

    # ── OAuth2 Flow ─────────────────────────────────────────────────────────

    def get_auth_url(self, user_id: str, extra_state: str = "") -> str:
        """
        Gera URL de autorização Google OAuth2.
        O user clica neste link → Google consent screen → callback.

        Args:
            user_id: ID do utilizador (incluído no state para o callback)
            extra_state: Info extra para o callback (ex: redirect URL)

        Returns:
            URL completa para redirecionar o user
        """
        state_data = json.dumps({
            "user_id": user_id,
            "extra": extra_state,
        })
        state_b64 = base64.urlsafe_b64encode(state_data.encode()).decode()

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",    # Essencial para refresh_token
            "prompt": "consent",         # Forçar para garantir refresh_token
            "state": state_b64,
            "include_granted_scopes": "true",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def handle_callback(
        self, code: str, state_b64: str
    ) -> Dict[str, Any]:
        """
        Processa callback do Google OAuth2.
        Troca code por tokens, obtém perfil, guarda no Supabase.

        Args:
            code: Authorization code do Google
            state_b64: State (base64 JSON com user_id)

        Returns:
            Dict com success, user_id, email, name
        """
        # 1. Decodificar state
        try:
            state_data = json.loads(
                base64.urlsafe_b64decode(state_b64.encode()).decode()
            )
            user_id = state_data["user_id"]
        except Exception as e:
            raise ValueError(f"State inválido no callback: {e}")

        # 2. Trocar code por tokens
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Google token exchange failed "
                    f"({resp.status_code}): {resp.text}"
                )
            tokens = resp.json()

        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", "")
        expires_in = tokens.get("expires_in", 3600)

        # 3. Obter perfil do user
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Failed to get Google profile: {resp.text}"
                )
            profile = resp.json()

        email = profile.get("email", "")
        name = profile.get("name", "")

        # 4. Guardar tokens no Supabase
        await self.save_tokens(
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

        logger.info(
            "Google OAuth connected: user=%s email=%s", user_id, email
        )

        return {
            "success": True,
            "user_id": user_id,
            "email": email,
            "name": name,
        }

    # ── Token Management ────────────────────────────────────────────────────

    async def save_tokens(
        self,
        user_id: str,
        email: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
    ) -> None:
        """Guarda/actualiza tokens OAuth2 no Supabase."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            raise RuntimeError(
                "Supabase not available for token storage"
            )

        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        sb.table("user_oauth_tokens").upsert(
            {
                "user_id": user_id,
                "provider": "google",
                "email": email,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "scopes": GOOGLE_SCOPES,
                "active": True,
            },
            on_conflict="user_id,provider,email",
        ).execute()

    async def get_valid_access_token(
        self, user_id: str
    ) -> Optional[str]:
        """
        Obtém access_token válido para o user.
        Se expirado, renova automaticamente com refresh_token.

        Args:
            user_id: ID do utilizador

        Returns:
            access_token válido ou None se não conectado
        """
        token_row = await self._get_token_row(user_id)
        if not token_row:
            return None

        access_token = token_row["access_token"]
        refresh_token = token_row.get("refresh_token", "")
        expires_at_str = token_row.get("expires_at", "")

        # Verificar expiração (com 5 min de margem)
        try:
            expires_at = datetime.fromisoformat(
                expires_at_str.replace("Z", "+00:00")
            )
            margin = datetime.now(timezone.utc) + timedelta(minutes=5)
            if margin >= expires_at:
                if not refresh_token:
                    logger.warning(
                        "Token expired, no refresh_token: user=%s",
                        user_id,
                    )
                    return None
                access_token = await self._refresh_token(
                    user_id, token_row["email"], refresh_token
                )
        except Exception as e:
            logger.warning("Error checking token expiry: %s", e)

        return access_token

    async def get_user_email(self, user_id: str) -> Optional[str]:
        """Retorna o email Google conectado do user, ou None."""
        token_row = await self._get_token_row(user_id)
        return token_row["email"] if token_row else None

    async def is_connected(self, user_id: str) -> bool:
        """Verifica se o user tem conta Google conectada e activa."""
        token_row = await self._get_token_row(user_id)
        return token_row is not None

    async def disconnect(self, user_id: str) -> bool:
        """Desconecta conta Google do user (desactiva tokens)."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            return False
        try:
            sb.table("user_oauth_tokens").update(
                {"active": False}
            ).eq("user_id", user_id).eq(
                "provider", "google"
            ).execute()
            logger.info("Google disconnected: user=%s", user_id)
            return True
        except Exception as e:
            logger.error("Failed to disconnect Google: %s", e)
            return False

    async def get_connected_accounts(
        self, user_id: str
    ) -> List[Dict[str, Any]]:
        """Lista todas as contas Google conectadas do user."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            return []
        try:
            res = (
                sb.table("user_oauth_tokens")
                .select("email, scopes, created_at, active")
                .eq("user_id", user_id)
                .eq("provider", "google")
                .eq("active", True)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error("Failed to get connected accounts: %s", e)
            return []

    # ── Private Helpers ─────────────────────────────────────────────────────

    async def _get_token_row(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Busca token row do Supabase."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            return None
        try:
            res = (
                sb.table("user_oauth_tokens")
                .select("*")
                .eq("user_id", user_id)
                .eq("provider", "google")
                .eq("active", True)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error("Failed to get OAuth tokens: %s", e)
            return None

    async def _refresh_token(
        self, user_id: str, email: str, refresh_token: str
    ) -> str:
        """Renova access_token usando refresh_token."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Token refresh failed: {resp.text}"
                )
            tokens = resp.json()

        new_access_token = tokens["access_token"]
        expires_in = tokens.get("expires_in", 3600)

        # Google não retorna novo refresh_token no refresh —
        # manter o original
        await self.save_tokens(
            user_id=user_id,
            email=email,
            access_token=new_access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

        logger.info("Google token refreshed: user=%s", user_id)
        return new_access_token


# ── Singleton ───────────────────────────────────────────────────────────────

_google_oauth: Optional[GoogleOAuthService] = None


def get_google_oauth() -> GoogleOAuthService:
    """Retorna instância singleton do GoogleOAuthService."""
    global _google_oauth
    if _google_oauth is None:
        _google_oauth = GoogleOAuthService()
    return _google_oauth
