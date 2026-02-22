# -*- coding: utf-8 -*-
"""
services/integrations/n8n_service.py
======================================
Serviço de comunicação com N8N para automação de workflows.

Responsabilidades:
    - Receber webhooks do N8N (emails, eventos)
    - Disparar workflows do N8N (enviar email, executar acção)
    - Gerir autenticação com N8N API

Variáveis de ambiente necessárias:
    N8N_BASE_URL=https://teu-n8n.app.n8n.cloud
    N8N_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
    N8N_WEBHOOK_SECRET=xxxxxx   (opcional, para validar webhooks recebidos)

Workflows N8N necessários:
    - Gmail Monitor     → webhook para Jarvis quando email recebido
    - Hotmail Monitor   → webhook para Jarvis quando email recebido
    - Send Email        → recebe payload do Jarvis e envia email
"""

import hashlib
import hmac
import os
from typing import Any, Dict, Optional

import aiohttp
from dotenv import load_dotenv

from services.core import BaseService, ServiceUnavailableError, register_service

load_dotenv()

# IDs dos workflows N8N (preencher após criar no N8N)
# Encontras em: N8N → Workflow → Settings → ID
WORKFLOW_IDS = {
    "send_email":       os.getenv("N8N_WORKFLOW_SEND_EMAIL", ""),
    "gmail_monitor":    os.getenv("N8N_WORKFLOW_GMAIL_MONITOR", ""),
    "hotmail_monitor":  os.getenv("N8N_WORKFLOW_HOTMAIL_MONITOR", ""),
}

# URLs dos webhooks de envio (preencher após criar no N8N)
# Encontras em: N8N → Webhook node → URL
WEBHOOK_URLS = {
    "send_email":   os.getenv("N8N_WEBHOOK_SEND_EMAIL", ""),
    "send_reply":   os.getenv("N8N_WEBHOOK_SEND_REPLY", ""),
}

ACCOUNT_LABELS = {
    "gmail":   "Gmail",
    "hotmail": "Hotmail",
    "outlook": "Outlook",
    "yahoo":   "Yahoo",
}


@register_service("n8n")
class N8NService(BaseService):
    """
    Serviço de integração com N8N.

    Interface pública:
        trigger_send_email(account, to, subject, body, reply_to_id?)
            → Dict com status

        trigger_send_reply(account, thread_id, message_id, body)
            → Dict com status

        validate_webhook_signature(payload_bytes, signature)
            → bool

        get_account_label(account)
            → str ("Gmail", "Hotmail", etc.)

        is_workflow_configured(workflow_name)
            → bool
    """

    def __init__(self):
        super().__init__(name="n8n")
        self._base_url: Optional[str] = None
        self._api_key: Optional[str] = None
        self._webhook_secret: Optional[str] = None

    async def _initialize(self) -> None:
        self._base_url = os.getenv("N8N_BASE_URL", "").rstrip("/")
        self._api_key = os.getenv("N8N_API_KEY", "")
        self._webhook_secret = os.getenv("N8N_WEBHOOK_SECRET", "")

        if not self._base_url:
            raise ServiceUnavailableError(
                "N8N_BASE_URL não configurado no .env"
            )

        configured = [k for k, v in WEBHOOK_URLS.items() if v]
        self.logger.info(
            "N8NService initialized. Base: %s | Webhooks configurados: %s",
            self._base_url, configured or "nenhum ainda"
        )

    async def _health_check(self) -> bool:
        return bool(self._base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-N8N-API-KEY"] = self._api_key
        return headers

    # ──────────────────────────────────────────────────────────────────────────
    # ENVIO DE EMAIL (Jarvis → N8N → Gmail/Hotmail)
    # ──────────────────────────────────────────────────────────────────────────

    async def trigger_send_email(
        self,
        account: str,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dispara o workflow N8N para enviar um email.

        Args:
            account:              "gmail" ou "hotmail"
            to:                   Destinatário
            subject:              Assunto
            body:                 Corpo do email (texto ou HTML)
            reply_to_message_id:  Message-ID para responder a thread existente
            thread_id:            Thread ID (Gmail) para agrupar na mesma conversa

        Returns:
            Dict com success, message_id (se disponível)
        """
        if not self.is_initialized():
            await self.initialize()

        webhook_url = WEBHOOK_URLS.get("send_reply" if reply_to_message_id else "send_email")
        if not webhook_url:
            raise ServiceUnavailableError(
                "Webhook de envio não configurado. "
                "Define N8N_WEBHOOK_SEND_EMAIL no .env"
            )

        payload = {
            "action": "send_email",
            "account": account,
            "to": to,
            "subject": subject,
            "body": body,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if thread_id:
            payload["thread_id"] = thread_id

        return await self._post_webhook(webhook_url, payload)

    async def trigger_send_reply(
        self,
        account: str,
        thread_id: str,
        message_id: str,
        to: str,
        subject: str,
        body: str,
    ) -> Dict[str, Any]:
        """
        Dispara workflow N8N para responder a um email existente.
        Mantém o thread correcto na caixa de email.
        """
        if not self.is_initialized():
            await self.initialize()

        webhook_url = WEBHOOK_URLS.get("send_reply") or WEBHOOK_URLS.get("send_email")
        if not webhook_url:
            raise ServiceUnavailableError("Webhook de resposta não configurado.")

        payload = {
            "action": "send_reply",
            "account": account,
            "thread_id": thread_id,
            "reply_to_message_id": message_id,
            "to": to,
            "subject": f"Re: {subject}" if not subject.startswith("Re:") else subject,
            "body": body,
        }

        return await self._post_webhook(webhook_url, payload)

    # ──────────────────────────────────────────────────────────────────────────
    # VALIDAÇÃO DE WEBHOOK (N8N → Jarvis)
    # ──────────────────────────────────────────────────────────────────────────

    def validate_webhook_signature(
        self, payload_bytes: bytes, signature: str
    ) -> bool:
        """
        Valida a assinatura HMAC do webhook recebido do N8N.
        Configura N8N_WEBHOOK_SECRET no .env e no workflow N8N.

        Returns:
            True se válido (ou se secret não configurado — modo dev)
        """
        if not self._webhook_secret:
            self.logger.warning(
                "N8N_WEBHOOK_SECRET não configurado — validação desactivada"
            )
            return True

        expected = hmac.new(
            self._webhook_secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _post_webhook(
        self, url: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Faz POST para um webhook N8N."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    if resp.status not in (200, 201):
                        raise RuntimeError(
                            f"N8N webhook erro {resp.status}: {data}"
                        )
                    self.logger.info(
                        "N8N webhook OK: %s → status %d", url, resp.status
                    )
                    return {"success": True, "data": data}
        except aiohttp.ClientError as e:
            self.logger.error("N8N connection error: %s", e)
            raise ServiceUnavailableError(f"N8N indisponível: {e}")

    @staticmethod
    def get_account_label(account: str) -> str:
        """Retorna label legível da conta. Ex: 'gmail' → 'Gmail'"""
        return ACCOUNT_LABELS.get(account.lower(), account.capitalize())

    @staticmethod
    def is_workflow_configured(workflow_name: str) -> bool:
        """Verifica se um workflow tem URL configurado."""
        return bool(WEBHOOK_URLS.get(workflow_name))

    @staticmethod
    def parse_webhook_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normaliza o payload recebido do N8N para formato padrão.

        N8N pode enviar em formatos ligeiramente diferentes
        dependendo do node (Gmail vs Outlook). Este método
        normaliza tudo para o mesmo formato que o EmailAgent espera.

        Formato de saída:
            {
                "account":    "gmail",
                "email_id":   "...",
                "thread_id":  "...",
                "message_id": "...",     # Message-ID do header
                "from_email": "...",
                "from_name":  "...",
                "to":         "...",
                "subject":    "...",
                "body_text":  "...",
                "body_html":  "...",
                "received_at":"...",
                "is_reply":   bool,
            }
        """
        # Gmail node do N8N
        if "labelIds" in data or data.get("account") == "gmail":
            payload = data.get("payload", {})
            headers = {
                h["name"].lower(): h["value"]
                for h in payload.get("headers", [])
            }
            return {
                "account":    "gmail",
                "email_id":   data.get("id", ""),
                "thread_id":  data.get("threadId", ""),
                "message_id": headers.get("message-id", ""),
                "from_email": _extract_email(headers.get("from", "")),
                "from_name":  _extract_name(headers.get("from", "")),
                "to":         headers.get("to", ""),
                "subject":    headers.get("subject", "(sem assunto)"),
                "body_text":  data.get("body_text", ""),
                "body_html":  data.get("body_html", ""),
                "received_at": headers.get("date", ""),
                "is_reply":   headers.get("subject", "").lower().startswith("re:"),
            }

        # Outlook/Hotmail node do N8N
        if data.get("account") in ("hotmail", "outlook") or "internetMessageId" in data:
            from_obj = data.get("from", {}).get("emailAddress", {})
            return {
                "account":    data.get("account", "hotmail"),
                "email_id":   data.get("id", ""),
                "thread_id":  data.get("conversationId", ""),
                "message_id": data.get("internetMessageId", ""),
                "from_email": from_obj.get("address", ""),
                "from_name":  from_obj.get("name", ""),
                "to":         data.get("toRecipients", [{}])[0]
                              .get("emailAddress", {}).get("address", ""),
                "subject":    data.get("subject", "(sem assunto)"),
                "body_text":  data.get("body", {}).get("content", ""),
                "body_html":  "",
                "received_at": data.get("receivedDateTime", ""),
                "is_reply":   data.get("subject", "").lower().startswith("re:"),
            }

        # Formato genérico (Jarvis já normalizou)
        return {
            "account":    data.get("account", "unknown"),
            "email_id":   data.get("email_id", ""),
            "thread_id":  data.get("thread_id", ""),
            "message_id": data.get("message_id", ""),
            "from_email": data.get("from_email", ""),
            "from_name":  data.get("from_name", ""),
            "to":         data.get("to", ""),
            "subject":    data.get("subject", "(sem assunto)"),
            "body_text":  data.get("body_text", ""),
            "body_html":  data.get("body_html", ""),
            "received_at": data.get("received_at", ""),
            "is_reply":   data.get("is_reply", False),
        }


# ─── Helpers privados ─────────────────────────────────────────────────────────

def _extract_email(from_header: str) -> str:
    """'João Silva <joao@exemplo.com>' → 'joao@exemplo.com'"""
    import re
    match = re.search(r"<([^>]+)>", from_header)
    return match.group(1) if match else from_header.strip()


def _extract_name(from_header: str) -> str:
    """'João Silva <joao@exemplo.com>' → 'João Silva'"""
    import re
    match = re.match(r"^([^<]+)<", from_header)
    if match:
        return match.group(1).strip().strip('"')
    return _extract_email(from_header)
