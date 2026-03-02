# -*- coding: utf-8 -*-
"""
Gmail Service
=============
Integração directa com Gmail API via OAuth2 per-user.

Usa GoogleOAuthService para gestão de tokens.
Cada utilizador acede à SUA conta Gmail.

Funcionalidades:
- Listar emails (inbox, não lidos, por label)
- Ler email completo
- Enviar email novo
- Responder a email (mantendo thread)
- Marcar como lido/não lido
- Arquivar / mover para lixo
- Obter perfil (email, total mensagens)
"""

import base64
import logging
import re
import time
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx

from services.auth.google_oauth_service import get_google_oauth
from services.core import BaseService, ServiceUnavailableError, register_service

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://www.googleapis.com/gmail/v1/users/me"


@register_service("gmail")
class GmailService(BaseService):
    """
    Gmail API via OAuth2 per-user.
    Usa GoogleOAuthService para tokens partilhados com Calendar.
    """

    def __init__(self):
        super().__init__(name="gmail")

    async def _initialize(self) -> None:
        oauth = get_google_oauth()
        if not oauth.is_configured:
            raise ServiceUnavailableError(
                "GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET "
                "não configurados. Gmail OAuth2 não disponível."
            )
        self.logger.info(
            "GmailService initialized (OAuth2 via GoogleOAuthService)"
        )

    async def _health_check(self) -> bool:
        return get_google_oauth().is_configured

    # ── Auth helpers ────────────────────────────────────────────────────────

    def get_auth_url(self, user_id: str) -> str:
        """Gera URL de autorização Google (Calendar + Gmail)."""
        return get_google_oauth().get_auth_url(user_id)

    async def is_connected(self, user_id: str) -> bool:
        """Verifica se user tem Gmail conectado."""
        return await get_google_oauth().is_connected(user_id)

    # ── Gmail API Request Helper ────────────────────────────────────────────

    async def _api(
        self,
        user_id: str,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Faz request autenticado à Gmail API."""
        oauth = get_google_oauth()
        access_token = await oauth.get_valid_access_token(user_id)
        if not access_token:
            raise ServiceUnavailableError(
                "Gmail não conectado. "
                "Usa 'conectar gmail' para autorizar."
            )

        url = f"{GMAIL_API_BASE}/{endpoint}"
        headers = {"Authorization": f"Bearer {access_token}"}

        start = time.time()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method,
                url,
                headers=headers,
                json=json_data,
                params=params,
            )

        latency = time.time() - start

        if resp.status_code == 401:
            self._track_call(latency, error=True)
            raise ServiceUnavailableError(
                "Token Gmail expirado ou revogado. "
                "Reconecta com 'conectar gmail'."
            )
        if resp.status_code == 204:
            self._track_call(latency, error=False)
            return {"success": True}
        if resp.status_code not in (200, 201):
            self._track_call(latency, error=True)
            raise RuntimeError(
                f"Gmail API {resp.status_code}: {resp.text[:200]}"
            )

        self._track_call(latency, error=False)
        return resp.json()

    # ── Listar Emails ───────────────────────────────────────────────────────

    async def list_emails(
        self,
        user_id: str,
        max_results: int = 10,
        label: str = "INBOX",
        unread_only: bool = False,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lista emails do utilizador.

        Args:
            user_id: ID do utilizador
            max_results: Máximo de emails (1-20)
            label: Label Gmail (INBOX, SENT, DRAFT, SPAM, TRASH)
            unread_only: Só emails não lidos
            query: Gmail search query (ex: "from:joao subject:reunião")

        Returns:
            Lista de emails com metadata
        """
        q_parts = []
        if label:
            q_parts.append(f"label:{label}")
        if unread_only:
            q_parts.append("is:unread")
        if query:
            q_parts.append(query)

        params: Dict[str, Any] = {
            "maxResults": min(max_results, 20),
        }
        if q_parts:
            params["q"] = " ".join(q_parts)

        data = await self._api(
            user_id, "GET", "messages", params=params
        )
        message_refs = data.get("messages", [])

        # Buscar detalhes de cada email
        emails = []
        for ref in message_refs[:max_results]:
            detail = await self._get_message_metadata(
                user_id, ref["id"]
            )
            if detail:
                emails.append(detail)

        return emails

    async def _get_message_metadata(
        self, user_id: str, message_id: str
    ) -> Optional[Dict[str, Any]]:
        """Obtém metadata de um email (sem corpo completo)."""
        try:
            data = await self._api(
                user_id,
                "GET",
                f"messages/{message_id}",
                params={
                    "format": "metadata",
                    "metadataHeaders": [
                        "From",
                        "To",
                        "Subject",
                        "Date",
                        "Message-ID",
                    ],
                },
            )

            headers = {
                h["name"].lower(): h["value"]
                for h in data.get("payload", {}).get("headers", [])
            }

            label_ids = data.get("labelIds", [])

            return {
                "id": data["id"],
                "thread_id": data.get("threadId", ""),
                "message_id": headers.get("message-id", ""),
                "from_email": _extract_email(
                    headers.get("from", "")
                ),
                "from_name": _extract_name(
                    headers.get("from", "")
                ),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", "(sem assunto)"),
                "date": headers.get("date", ""),
                "snippet": data.get("snippet", ""),
                "is_unread": "UNREAD" in label_ids,
                "labels": label_ids,
                "account": "gmail",
            }
        except Exception as e:
            logger.warning(
                "Error getting email %s: %s", message_id, e
            )
            return None

    # ── Ler Email Completo ──────────────────────────────────────────────────

    async def get_email_body(
        self, user_id: str, message_id: str
    ) -> str:
        """Obtém corpo completo de um email (text/plain preferido)."""
        data = await self._api(
            user_id,
            "GET",
            f"messages/{message_id}",
            params={"format": "full"},
        )
        return _extract_body(data.get("payload", {}))

    # ── Enviar Email ────────────────────────────────────────────────────────

    async def send_email(
        self,
        user_id: str,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envia email via Gmail API.

        Args:
            user_id: ID do utilizador
            to: Destinatário
            subject: Assunto
            body: Corpo (texto plano)
            reply_to_message_id: Message-ID header para reply
            thread_id: Thread ID para manter na conversa

        Returns:
            Dict com id, threadId, labelIds
        """
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject

        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
            msg["References"] = reply_to_message_id

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload: Dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id

        result = await self._api(
            user_id, "POST", "messages/send", json_data=payload
        )

        self.logger.info(
            "Email sent: user=%s to=%s subject=%s",
            user_id, to, subject,
        )
        return result

    # ── Acções sobre Emails ─────────────────────────────────────────────────

    async def mark_as_read(
        self, user_id: str, message_id: str
    ) -> None:
        """Marca email como lido."""
        await self._api(
            user_id,
            "POST",
            f"messages/{message_id}/modify",
            json_data={"removeLabelIds": ["UNREAD"]},
        )

    async def mark_as_unread(
        self, user_id: str, message_id: str
    ) -> None:
        """Marca email como não lido."""
        await self._api(
            user_id,
            "POST",
            f"messages/{message_id}/modify",
            json_data={"addLabelIds": ["UNREAD"]},
        )

    async def archive(
        self, user_id: str, message_id: str
    ) -> None:
        """Arquiva email (remove da inbox)."""
        await self._api(
            user_id,
            "POST",
            f"messages/{message_id}/modify",
            json_data={"removeLabelIds": ["INBOX"]},
        )

    async def trash(
        self, user_id: str, message_id: str
    ) -> None:
        """Move email para o lixo."""
        await self._api(
            user_id, "POST", f"messages/{message_id}/trash"
        )

    async def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Obtém perfil Gmail (email, total de mensagens)."""
        return await self._api(user_id, "GET", "profile")

    async def get_unread_count(self, user_id: str) -> int:
        """Conta emails não lidos na inbox."""
        data = await self._api(
            user_id,
            "GET",
            "messages",
            params={
                "q": "label:INBOX is:unread",
                "maxResults": 1,
            },
        )
        return data.get("resultSizeEstimate", 0)


# ── Helpers (module-level) ──────────────────────────────────────────────────


def _extract_email(from_header: str) -> str:
    """'João Silva <joao@email.com>' → 'joao@email.com'"""
    match = re.search(r"<([^>]+)>", from_header)
    return match.group(1) if match else from_header.strip()


def _extract_name(from_header: str) -> str:
    """'João Silva <joao@email.com>' → 'João Silva'"""
    match = re.match(r"^([^<]+)<", from_header)
    if match:
        return match.group(1).strip().strip('"')
    return _extract_email(from_header)


def _extract_body(payload: Dict[str, Any]) -> str:
    """Extrai corpo text/plain de um payload Gmail."""
    mime_type = payload.get("mimeType", "")

    # Corpo directo
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode(
                "utf-8", errors="replace"
            )

    # Multipart — procurar text/plain nas parts
    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result

    # Fallback: text/html
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode(
                "utf-8", errors="replace"
            )
            # Strip HTML tags básico
            return re.sub(r"<[^>]+>", "", html).strip()

    return ""
