# -*- coding: utf-8 -*-
"""
agents/specialized/email_agent.py
====================================
EmailAgent — gestão de emails (Gmail + Hotmail/Outlook).

Fluxo completo:
    1. Webhook recebe notificação de email novo em /api/webhooks/email
    2. EmailAgent recebe, resume e notifica no Telegram
    3. Utilizador responde: "sim responde" / "ignora" / "responde dizendo X"
    4. EmailAgent gera resposta com GPT e pede confirmação
    5. Com confirmação, envia via Gmail API / Microsoft Graph (TODO)

Comandos suportados (no Telegram):
    "Mostra os meus emails"
    "Últimos emails do Gmail"
    "Emails não lidos"
    "Responde ao último email dizendo que confirmo"
    "Ignora o email do João"
    "Quantos emails tenho?"
    "Resume o email da Maria"
"""

import re
from datetime import timezone
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services.core import get_service
from services.business import email_account_service as edb
from services.i18n import t, get_user_lang


# ─── Padrões de intenção ─────────────────────────────────────────────────────

_RE_SHOW = re.compile(
    r"\b(mostra?|ver?|lista?|últimos?|recentes?|inbox|caixa)\b.*\b(emails?|mails?|mensage[nm]s?|correio)\b",
    re.IGNORECASE,
)
_RE_UNREAD = re.compile(
    r"não\s*lid|nao\s*lid|\bunread\b|\bpor\s*ler\b|\bnovos?\b",
    re.IGNORECASE,
)
_RE_COUNT = re.compile(
    r"\b(quantos?|número|numero|total)\b.*\b(emails?|mails?)\b",
    re.IGNORECASE,
)
_RE_REPLY = re.compile(
    r"\b(responde?|reply|responder|resposta)\b",
    re.IGNORECASE,
)
_RE_IGNORE = re.compile(
    r"\b(ignora?|ignorar|apaga?|arquiva?|descarta?)\b",
    re.IGNORECASE,
)
_RE_SUMMARY = re.compile(
    r"\b(resum[eo]|resume?|summarize?|o\s*que\s*diz)\b",
    re.IGNORECASE,
)
_RE_CONFIRM = re.compile(
    r"\b(sim|yes|confirmo|confirma|envia|send|ok|pode)\b",
    re.IGNORECASE,
)
_RE_CANCEL = re.compile(
    r"\b(não|nao|cancela|cancel|não\s*envia|nao\s*envia)\b",
    re.IGNORECASE,
)
_RE_ACCOUNT_GMAIL = re.compile(r"\bgmail\b", re.IGNORECASE)
_RE_ACCOUNT_HOTMAIL = re.compile(r"\b(hotmail|outlook|microsoft)\b", re.IGNORECASE)
_RE_SENT = re.compile(
    r"\b(respondeu|respondid[oa]s?|enviad[oa]s?|sent|replies)\b.*\b(email|bot|mail)\b"
    r"|\b(email|bot|mail)\b.*\b(respondeu|respondid[oa]s?|enviad[oa]s?|sent|replies)\b",
    re.IGNORECASE,
)
_RE_CONNECT = re.compile(
    r"\b(conectar?|connect|ligar|autorizar?|authorize?)\b"
    r".*\b(gmail|email|google|conta)\b",
    re.IGNORECASE,
)
_RE_SUMMARY_ALL = re.compile(
    r"\b(resum[eo]|resume?|summarize?)\b.*\b(emails?|todos?|últimos?)\b"
    r"|\b(todos?|últimos?)\b.*\b(resum[eo]|resume?|summarize?)\b",
    re.IGNORECASE,
)
_RE_POLL_ENABLE = re.compile(
    r"\b(ativ|activ|enabl|ligar|habilitar)\w*\b.*\b(notific|poll|alert)",
    re.IGNORECASE,
)
_RE_POLL_DISABLE = re.compile(
    r"\b(desativ|desactiv|deactiv|disabl|desligar|parar|stop)\w*\b"
    r".*\b(notific|poll|alert)",
    re.IGNORECASE,
)


@register_agent("email")
class EmailAgent(BaseAgent):
    """
    Agente de email — gere emails de Gmail e Hotmail/Outlook
    através do Telegram.
    """

    def __init__(self):
        super().__init__(name="email", description="Gestão de emails Gmail e Hotmail")
        self._db = None
        self._ai = None
        self._initialized = False

    def is_initialized(self) -> bool:
        """Check if services have been resolved."""
        return self._initialized

    async def initialize(self) -> None:
        """Resolve service dependencies."""
        await self._initialize()
        self._initialized = True

    async def _initialize(self) -> None:
        self._db = get_service("database")
        self._ai = get_service("openai")

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS INTERNOS (substituem N8NService)
    # ──────────────────────────────────────────────────────────────────────────

    _ACCOUNT_LABELS = {
        "gmail": "Gmail",
        "hotmail": "Hotmail",
        "outlook": "Outlook",
        "yahoo": "Yahoo",
    }

    @staticmethod
    def _get_account_label(account: str) -> str:
        """Retorna label legível da conta. Ex: 'gmail' → 'Gmail'"""
        return EmailAgent._ACCOUNT_LABELS.get(account.lower(), account.capitalize())

    @staticmethod
    async def _resolve_email_service(user_id: str, prompt: str = ""):
        """Resolve which email service to use: Gmail, Outlook, or both.

        Returns (service, provider_name) or (None, None) if nothing connected.
        Priority:
        1. User explicitly asks for "outlook"/"hotmail" → use outlook
        2. User explicitly asks for "gmail" → use gmail
        3. Check which providers are connected → use the connected one
        4. If both connected → prefer gmail (legacy default)
        """
        gmail = get_service("gmail")
        outlook = get_service("outlook")

        # Explicit mention in prompt
        if _RE_ACCOUNT_HOTMAIL.search(prompt):
            if outlook:
                if not outlook.is_initialized():
                    await outlook.initialize()
                return outlook, "outlook"
        if _RE_ACCOUNT_GMAIL.search(prompt):
            if gmail:
                if not gmail.is_initialized():
                    await gmail.initialize()
                return gmail, "gmail"

        # Check connections
        gmail_connected = False
        outlook_connected = False

        if gmail and gmail.is_initialized():
            try:
                gmail_connected = await gmail.is_connected(user_id)
            except Exception:
                pass

        if outlook and outlook.is_initialized():
            try:
                from services.auth.microsoft_oauth_service import get_microsoft_oauth

                outlook_connected = await get_microsoft_oauth().is_connected(user_id)
            except Exception:
                pass

        if gmail_connected and not outlook_connected:
            return gmail, "gmail"
        if outlook_connected and not gmail_connected:
            return outlook, "outlook"
        if gmail_connected and outlook_connected:
            return gmail, "gmail"  # Default to gmail when both connected

        # Nothing connected — return gmail for auth URL generation
        if gmail:
            if not gmail.is_initialized():
                await gmail.initialize()
            return gmail, "gmail"

        return None, None

    @staticmethod
    def _parse_webhook_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normaliza payload recebido do webhook para formato padrão.
        Suporta payloads já normalizados (do N8N antigo ou de qualquer fonte).
        """
        return {
            "account": data.get("account", "unknown"),
            "email_id": data.get("email_id", ""),
            "thread_id": data.get("thread_id", ""),
            "message_id": data.get("message_id", ""),
            "from_email": data.get("from_email", data.get("from", "")),
            "from_name": data.get("from_name", ""),
            "to": data.get("to", ""),
            "subject": data.get("subject", t("email_no_subject")),
            "body_text": data.get("body_text", data.get("body", "")),
            "body_html": data.get("body_html", ""),
            "received_at": data.get("received_at", ""),
            "is_reply": data.get("is_reply", False),
        }

    async def _send_email(
        self,
        to: str,
        subject: str,
        body: str,
        user_id: str = "",
        reply_to_message_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envia email via Gmail API (OAuth2 per-user).

        Args:
            to: Email do destinatário
            subject: Assunto do email
            body: Corpo do email (texto plano)
            user_id: ID do utilizador (obrigatório para OAuth2)
            reply_to_message_id: Message-ID para reply
            thread_id: Thread ID para manter na conversa

        Returns:
            Dict com resultado do envio

        Raises:
            RuntimeError: Se Gmail não conectado ou envio falhar
        """
        if not user_id:
            return {
                "success": False,
                "error": t("email_user_id_required"),
            }

        try:
            gmail = get_service("gmail")
            if not gmail or not gmail.is_initialized():
                if gmail:
                    await gmail.initialize()
                else:
                    return {
                        "success": False,
                        "error": t("email_gmail_unavailable"),
                    }

            # Verificar se user tem Gmail conectado
            connected = await gmail.is_connected(user_id)
            if not connected:
                auth_url = gmail.get_auth_url(user_id)
                return {
                    "success": False,
                    "error": t("email_gmail_not_connected"),
                    "auth_url": auth_url,
                    "message": t("email_need_connect_first"),
                }

            result = await gmail.send_email(
                user_id=user_id,
                to=to,
                subject=subject,
                body=body,
                reply_to_message_id=reply_to_message_id,
                thread_id=thread_id,
            )

            return {
                "success": True,
                "message_id": result.get("id", ""),
                "thread_id": result.get("threadId", ""),
            }

        except Exception as e:
            self.logger.error("Failed to send email: %s", e, exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    async def _list_emails(
        self,
        user_id: str,
        max_results: int = 5,
        unread_only: bool = False,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Lista emails do utilizador via Gmail API.

        Returns:
            Dict com success, emails, count
        """
        if not user_id:
            return {"success": False, "error": t("email_user_id_required")}

        try:
            gmail = get_service("gmail")
            if not gmail:
                return {"success": False, "error": t("email_gmail_unavailable")}

            if not await gmail.is_connected(user_id):
                auth_url = gmail.get_auth_url(user_id)
                return {
                    "success": False,
                    "error": t("email_gmail_not_connected"),
                    "auth_url": auth_url,
                }

            emails = await gmail.list_emails(
                user_id=user_id,
                max_results=max_results,
                unread_only=unread_only,
                query=query,
            )

            return {
                "success": True,
                "emails": emails,
                "count": len(emails),
            }

        except Exception as e:
            self.logger.error("Failed to list emails: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    async def _get_connect_url(self, user_id: str) -> Dict[str, Any]:
        """
        Retorna URL para o user conectar o Gmail.

        Returns:
            Dict com auth_url
        """
        try:
            gmail = get_service("gmail")
            if not gmail:
                return {"success": False, "error": t("email_gmail_unavailable")}

            already_connected = await gmail.is_connected(user_id)
            if already_connected:
                return {
                    "success": True,
                    "already_connected": True,
                    "message": t("email_connect_url_already"),
                }

            auth_url = gmail.get_auth_url(user_id)
            return {
                "success": True,
                "auth_url": auth_url,
                "message": t("email_connect_url_click"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # ENTRADA PRINCIPAL
    # ──────────────────────────────────────────────────────────────────────────

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """
        Processa mensagem do utilizador relacionada com emails.
        Também é chamado internamente quando chega webhook.
        """
        if not self.is_initialized():
            await self.initialize()

        user_id = str(context.get("user_id", context.get("chat_id", "")))
        lang = get_user_lang(context)

        # Fetch linked accounts so the agent knows what's available
        try:
            accounts = await edb.get_email_accounts(user_id)
            context["email_accounts"] = accounts
        except Exception:
            pass

        msg = prompt.strip()

        # Verificar se é resposta a confirmação pendente
        pending = context.get("email_pending_reply")
        if pending:
            return await self._handle_confirmation(msg, user_id, context, pending, lang)

        # Detectar intenção — poll toggle first (before _RE_CONNECT to avoid
        # conflicts with "ligar/desligar" stems)
        if _RE_POLL_ENABLE.search(msg):
            return await self._handle_poll_toggle(user_id, enable=True, lang=lang)

        if _RE_POLL_DISABLE.search(msg):
            return await self._handle_poll_toggle(user_id, enable=False, lang=lang)

        if _RE_CONNECT.search(msg):
            return await self._handle_connect(user_id, lang)

        if _RE_SENT.search(msg):
            return await self._handle_sent_replies(user_id, context, lang)

        if _RE_REPLY.search(msg):
            return await self._handle_reply_intent(msg, user_id, context, lang)

        if _RE_IGNORE.search(msg):
            return await self._handle_ignore(msg, user_id, context, lang)

        if _RE_SUMMARY_ALL.search(msg):
            return await self._handle_summary_all(user_id, context, lang)

        if _RE_SUMMARY.search(msg):
            return await self._handle_summary(msg, user_id, context, lang)

        if _RE_COUNT.search(msg):
            return await self._handle_count(user_id, context, lang)

        if _RE_UNREAD.search(msg):
            return await self._handle_list(
                user_id, context, unread_only=True, lang=lang
            )

        if _RE_SHOW.search(msg):
            account = self._extract_account(msg)
            return await self._handle_list(user_id, context, account=account, lang=lang)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=t("email_help", lang=lang),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # EMAIL NOTIFICATION TOGGLE
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_poll_toggle(
        self, user_id: str, *, enable: bool, lang: str
    ) -> AgentResponse:
        """Enable or disable email polling notifications."""
        eps = get_service("email_polling")
        if not eps:
            return AgentResponse(
                status=AgentStatus.ERROR,
                message=t("email_poll_error", lang=lang),
            )

        if not eps.is_initialized():
            try:
                await eps.initialize()
            except Exception:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    message=t("email_poll_error", lang=lang),
                )

        if enable:
            # Verify Gmail is connected first
            gmail = get_service("gmail")
            if gmail:
                try:
                    if not await gmail.is_connected(user_id):
                        return AgentResponse(
                            status=AgentStatus.ERROR,
                            message=t("email_poll_not_connected", lang=lang),
                        )
                except Exception:
                    pass

            if await eps.is_polling_enabled(user_id):
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    message=t("email_poll_already_enabled", lang=lang),
                )

            ok = await eps.enable_polling(user_id)
            if ok:
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    message=t("email_poll_enabled", lang=lang),
                )
            return AgentResponse(
                status=AgentStatus.ERROR,
                message=t("email_poll_error", lang=lang),
            )

        # Disable
        if not await eps.is_polling_enabled(user_id):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_poll_already_disabled", lang=lang),
            )

        ok = await eps.disable_polling(user_id)
        if ok:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_poll_disabled", lang=lang),
            )
        return AgentResponse(
            status=AgentStatus.ERROR,
            message=t("email_poll_error", lang=lang),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # WEBHOOK RECEBIDO (chamado pela route /api/webhooks/email)
    # ──────────────────────────────────────────────────────────────────────────

    async def handle_incoming_email(
        self,
        user_id: str,
        email_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> AgentResponse:
        """
        Processa email recebido via webhook.
        Guarda no Supabase, analisa com GPT e notifica no Telegram.

        Args:
            user_id:    ID do utilizador dono da conta
            email_data: Payload do webhook (será normalizado internamente)
            context:    Contexto do utilizador
        """
        if not self.is_initialized():
            await self.initialize()

        lang = get_user_lang(context)

        # 1. Normalizar payload
        email = self._parse_webhook_payload(email_data)

        # 2. Guardar no Supabase
        email_id = await self._save_email(user_id, email)

        # 3. Resumir com GPT
        summary = await self._summarize_email(email, lang=lang)

        # 4. Classificar urgência
        urgency = await self._classify_urgency(email)

        # 5. Formatar notificação Telegram
        account_label = self._get_account_label(email["account"])
        urgency_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(urgency, "📧")

        notification = t(
            "email_incoming_notification",
            lang=lang,
            urgency_icon=urgency_icon,
            account=account_label,
            sender=email["from_name"] or email["from_email"],
            subject=email["subject"],
            summary=summary,
        )

        # 6. Guardar contexto para resposta futura
        context["email_pending_reply"] = {
            "email_id": email_id,
            "account": email["account"],
            "thread_id": email["thread_id"],
            "message_id": email["message_id"],
            "from_email": email["from_email"],
            "subject": email["subject"],
            "body_text": email["body_text"],
        }

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=notification,
            data={"email_id": email_id, "urgency": urgency},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # LISTAR EMAILS
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_list(
        self,
        user_id: str,
        context: Dict[str, Any],
        unread_only: bool = False,
        account: Optional[str] = None,
        limit: int = 5,
        lang: str = "en",
    ) -> AgentResponse:
        emails = await self._fetch_emails(
            user_id, unread_only=unread_only, account=account, limit=limit
        )

        if not emails:
            filter_desc = ""
            if account:
                filter_desc += t(
                    "email_filter_from_account", lang=lang, account=account.capitalize()
                )
            if unread_only:
                filter_desc += t("email_filter_unread", lang=lang)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_no_emails", lang=lang, filter=filter_desc),
            )

        account_label = (
            account.capitalize() if account else t("email_all_accounts", lang=lang)
        )
        filter_str = t("email_filter_unread", lang=lang) if unread_only else ""
        title = t(
            "email_list_title", lang=lang, filter=filter_str, account=account_label
        )
        lines = [title]

        for i, email in enumerate(emails, 1):
            acc_icon = "📮" if email.get("account") == "gmail" else "📬"
            read_icon = "🔵" if not email.get("read") else ""
            lines.append(
                f"{i}. {acc_icon}{read_icon} **{email.get('from_name') or email.get('from_email', '?')}**\n"
                f"   _{email.get('subject', t('email_no_subject', lang=lang))}_\n"
                f"   {self._format_time(email.get('received_at', ''), lang=lang)}\n"
            )

        lines.append(t("email_list_interact", lang=lang))

        # Guardar lista no contexto para referenciar por número
        context["email_last_list"] = emails

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message="\n".join(lines),
            data={"emails": emails},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # CONECTAR GMAIL
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_connect(self, user_id: str, lang: str = "en") -> AgentResponse:
        """Handle Gmail connect intent."""
        result = await self._get_connect_url(user_id)

        if not result.get("success"):
            return AgentResponse(
                status=AgentStatus.ERROR,
                message=t(
                    "email_connect_error", lang=lang, error=result.get("error", "")
                ),
            )

        if result.get("already_connected"):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_already_connected", lang=lang),
            )

        auth_url = result.get("auth_url", "")
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=t("email_connect_link", lang=lang, auth_url=auth_url),
            data={"auth_url": auth_url},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # CONTAR EMAILS
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_count(
        self, user_id: str, context: Dict[str, Any], lang: str = "en"
    ) -> AgentResponse:
        counts = await self._get_counts(user_id)

        lines = [t("email_count_header", lang=lang)]
        total_unread = 0

        for account, data in counts.items():
            icon = "📮" if account == "gmail" else "📬"
            unread = data.get("unread", 0)
            total = data.get("total", 0)
            total_unread += unread
            label = self._get_account_label(account)
            lines.append(
                t(
                    "email_count_line",
                    lang=lang,
                    icon=icon,
                    label=label,
                    unread=unread,
                    total=total,
                )
            )

        if total_unread > 0:
            lines.append(t("email_count_total_unread", lang=lang, count=total_unread))
        else:
            lines.append(t("email_count_all_read", lang=lang))

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message="\n".join(lines),
            data=counts,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # RESUMIR EMAIL
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_summary(
        self, msg: str, user_id: str, context: Dict[str, Any], lang: str = "en"
    ) -> AgentResponse:
        email = await self._resolve_email_reference(msg, user_id, context)
        if not email:
            return AgentResponse(
                status=AgentStatus.ERROR,
                message=t("email_not_found", lang=lang),
            )

        # PART B: Fetch email body from Gmail API if available
        body_text = email.get("body_text", "")
        gmail_id = email.get("id") or email.get("email_id", "")
        if not body_text and gmail_id:
            try:
                gmail = get_service("gmail")
                if gmail and await gmail.is_connected(user_id):
                    body_text = await gmail.get_email_body(user_id, gmail_id)
            except Exception:
                pass

        # Summarize with LLM using structured prompt
        summary = await self._summarize_email(
            {**email, "body_text": body_text}, detailed=True, lang=lang
        )

        # Classify urgency
        urgency = await self._classify_urgency({**email, "body_text": body_text})
        urgency_label = t(f"email_urgency_{urgency}", lang=lang)

        sender = email.get("from_name") or email.get("from_email", "")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=t(
                "email_summary_formatted",
                lang=lang,
                sender=sender,
                subject=email.get("subject", ""),
                summary=summary,
                urgency=urgency_label,
            ),
        )

    async def _handle_summary_all(
        self, user_id: str, context: Dict[str, Any], lang: str = "en"
    ) -> AgentResponse:
        """Summarize the last N emails with short summaries."""
        emails = await self._fetch_emails(user_id, limit=5)
        if not emails:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_summary_all_empty", lang=lang),
            )

        lines = [t("email_summary_all_header", lang=lang)]
        for i, email in enumerate(emails, 1):
            # Try to get body from Gmail API
            body_text = email.get("body_text", "")
            gmail_id = email.get("id") or email.get("email_id", "")
            if not body_text and gmail_id:
                try:
                    gmail = get_service("gmail")
                    if gmail and await gmail.is_connected(user_id):
                        body_text = await gmail.get_email_body(user_id, gmail_id)
                except Exception:
                    pass

            summary = await self._summarize_email(
                {**email, "body_text": body_text}, lang=lang
            )
            urgency = await self._classify_urgency({**email, "body_text": body_text})
            urgency_label = t(f"email_urgency_{urgency}", lang=lang)
            sender = email.get("from_name") or email.get("from_email", "?")
            lines.append(
                f"{i}. "
                + t(
                    "email_summary_formatted",
                    lang=lang,
                    sender=sender,
                    subject=email.get("subject", ""),
                    summary=summary,
                    urgency=urgency_label,
                )
                + "\n"
            )

        context["email_last_list"] = emails

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message="\n".join(lines),
            data={"emails": emails},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # INTENÇÃO DE RESPONDER
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_reply_intent(
        self, msg: str, user_id: str, context: Dict[str, Any], lang: str = "en"
    ) -> AgentResponse:
        email = await self._resolve_email_reference(msg, user_id, context)
        if not email:
            # Se não especificou qual, pegar o mais recente não lido
            emails = await self._fetch_emails(user_id, unread_only=True, limit=1)
            if emails:
                email = emails[0]
            else:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    message=t("email_no_email_to_reply", lang=lang),
                )

        # Extrair instrução de resposta da mensagem
        instruction = self._extract_reply_instruction(msg)

        # Gerar rascunho com GPT
        draft = await self._generate_reply_draft(email, instruction, lang=lang)

        account_label = self._get_account_label(email.get("account", ""))

        # Guardar rascunho no contexto
        context["email_pending_reply"] = {
            "email_id": email.get("id") or email.get("email_id", ""),
            "account": email.get("account", ""),
            "thread_id": email.get("thread_id", ""),
            "message_id": email.get("message_id", ""),
            "from_email": email.get("from_email", ""),
            "subject": email.get("subject", ""),
            "draft": draft,
        }

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=t(
                "email_draft_header",
                lang=lang,
                account=account_label,
                to=email.get("from_email"),
                subject=email.get("subject"),
                draft=draft,
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # CONFIRMAÇÃO DE ENVIO
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_confirmation(
        self,
        msg: str,
        user_id: str,
        context: Dict[str, Any],
        pending: Dict[str, Any],
        lang: str = "en",
    ) -> AgentResponse:
        if _RE_CANCEL.search(msg) and not _RE_CONFIRM.search(msg):
            context.pop("email_pending_reply", None)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_reply_cancelled", lang=lang),
            )

        if _RE_CONFIRM.search(msg):
            # Enviar resposta
            draft = pending.get("draft", "")
            if not draft:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    message=t("email_no_draft", lang=lang),
                )

            try:
                send_result = await self._send_email(
                    to=pending["from_email"],
                    subject=pending.get("subject", ""),
                    body=draft,
                    user_id=user_id,
                    reply_to_message_id=pending.get("message_id", ""),
                    thread_id=pending.get("thread_id", ""),
                )

                if not send_result.get("success"):
                    error_msg = send_result.get("error", "Erro desconhecido")
                    auth_url = send_result.get("auth_url")
                    if auth_url:
                        msg_text = t(
                            "email_send_error_with_auth",
                            lang=lang,
                            error=error_msg,
                            auth_url=auth_url,
                        )
                    else:
                        msg_text = f"❌ {error_msg}"
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        message=msg_text,
                        data=send_result,
                    )

                # Marcar como respondido no Supabase
                await self._mark_replied(pending.get("email_id"), user_id)

                # Log reply in email_replies table
                try:
                    await edb.save_reply(
                        user_id=user_id,
                        account=pending["account"],
                        to_email=pending["from_email"],
                        subject=pending.get("subject", ""),
                        body=draft,
                        inbox_id=pending.get("email_id"),
                        status="sent",
                    )
                except Exception:
                    pass

                context.pop("email_pending_reply", None)

                account_label = self._get_account_label(pending["account"])

                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    message=t("email_reply_sent", lang=lang, account=account_label),
                )

            except Exception as e:
                self.logger.error("Erro ao enviar reply: %s", e)
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    message=t("email_send_error", lang=lang, error=str(e)),
                )

        # Check for ignore intent within confirmation flow
        if _RE_IGNORE.search(msg):
            context.pop("email_pending_reply", None)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_ignored", lang=lang),
            )

        # Não foi sim nem não — pode ser uma alteração ao rascunho
        new_instruction = msg
        email_ctx = {
            "from_email": pending.get("from_email", ""),
            "subject": pending.get("subject", ""),
            "body_text": pending.get("body_text", ""),
        }
        new_draft = await self._generate_reply_draft(
            email_ctx, new_instruction, lang=lang
        )
        pending["draft"] = new_draft
        context["email_pending_reply"] = pending

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=t("email_draft_updated", lang=lang, draft=new_draft),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # EMAILS RESPONDIDOS PELO BOT
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_sent_replies(
        self, user_id: str, context: Dict[str, Any], lang: str = "en"
    ) -> AgentResponse:
        try:
            replies = await edb.get_sent_replies(user_id)
        except Exception:
            replies = []

        if not replies:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=t("email_no_sent_replies", lang=lang),
            )

        lines = [t("email_sent_replies_header", lang=lang)]
        for i, r in enumerate(replies[:10], 1):
            lines.append(
                f"{i}. **Para:** {r.get('to_email', '?')}\n"
                f"   _{r.get('subject', t('email_no_subject', lang=lang))}_\n"
                f"   📅 {self._format_time(r.get('sent_at', ''), lang=lang)}\n"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message="\n".join(lines),
            data={"replies": replies[:10]},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # IGNORAR EMAIL
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_ignore(
        self, msg: str, user_id: str, context: Dict[str, Any], lang: str = "en"
    ) -> AgentResponse:
        context.pop("email_pending_reply", None)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=t("email_ignored", lang=lang),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # GPT HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _summarize_email(
        self, email: Dict[str, Any], detailed: bool = False, lang: str = "en"
    ) -> str:
        body = (email.get("body_text") or "")[:2000]
        if not body:
            return t("email_no_body", lang=lang)

        if not self._ai:
            return body[:300] + ("..." if len(body) > 300 else "")

        sender = email.get("from_name") or email.get("from_email", "")
        subject = email.get("subject", "")
        if detailed:
            prompt = t(
                "email_summary_prompt_detailed",
                lang=lang,
                sender=sender,
                subject=subject,
                body=body,
            )
        else:
            prompt = t(
                "email_summary_prompt",
                lang=lang,
                sender=sender,
                subject=subject,
                body=body,
            )
        try:
            response = await self._ai.complete(prompt, max_tokens=300)
            return response.strip()
        except Exception as e:
            self.logger.warning("Erro ao resumir email: %s", e)
            return body[:300] + "..."

    async def _classify_urgency(self, email: Dict[str, Any]) -> str:
        subject = email.get("subject", "").lower()
        body = (email.get("body_text") or "").lower()[:500]

        urgent_keywords = [
            "urgente",
            "urgent",
            "asap",
            "imediato",
            "hoje",
            "agora",
            "prazo",
            "deadline",
            "importante",
            "critical",
            "emergency",
        ]
        for kw in urgent_keywords:
            if kw in subject or kw in body:
                return "high"

        low_keywords = [
            "newsletter",
            "unsubscribe",
            "promoção",
            "oferta",
            "desconto",
            "sale",
            "marketing",
            "noreply",
        ]
        for kw in low_keywords:
            if kw in subject or kw in body:
                return "low"

        return "medium"

    async def _generate_reply_draft(
        self, email: Dict[str, Any], instruction: Optional[str] = None, lang: str = "en"
    ) -> str:
        if not self._ai:
            return t(
                "email_reply_fallback", lang=lang, subject=email.get("subject", "")
            )

        instr = (
            t("email_reply_instruction", lang=lang, instruction=instruction)
            if instruction
            else t("email_reply_default_instruction", lang=lang)
        )
        sender = email.get("from_name") or email.get("from_email", "")
        prompt = t(
            "email_reply_prompt",
            lang=lang,
            instruction=instr,
            sender=sender,
            subject=email.get("subject", ""),
            body=(email.get("body_text") or "")[:1000],
        )
        try:
            response = await self._ai.complete(prompt, max_tokens=400)
            return response.strip()
        except Exception as e:
            self.logger.warning("Erro ao gerar rascunho: %s", e)
            return t("email_reply_fallback_generic", lang=lang)

    # ──────────────────────────────────────────────────────────────────────────
    # DATABASE HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _save_email(self, user_id: str, email: Dict[str, Any]) -> Optional[str]:
        if not self._db:
            return None
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: (
                    self._db.get_client()
                    .table("email_inbox")
                    .upsert(
                        {
                            "user_id": user_id,
                            "account": email.get("account"),
                            "email_id": email.get("email_id"),
                            "thread_id": email.get("thread_id"),
                            "message_id": email.get("message_id"),
                            "from_email": email.get("from_email"),
                            "from_name": email.get("from_name"),
                            "to_email": email.get("to"),
                            "subject": email.get("subject"),
                            "body_text": (email.get("body_text") or "")[:5000],
                            "received_at": email.get("received_at"),
                            "read": False,
                            "replied": False,
                            "urgency": "medium",
                        },
                        on_conflict="user_id,email_id",
                    )
                    .execute()
                ),
            )
            if result.data:
                return result.data[0].get("id")
        except Exception as e:
            self.logger.warning("Erro ao guardar email: %s", e)
        return None

    async def _get_emails(
        self,
        user_id: str,
        unread_only: bool = False,
        account: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            q = (
                self._db.get_client()
                .table("email_inbox")
                .select("*")
                .eq("user_id", user_id)
                .order("received_at", desc=True)
                .limit(min(limit, 20))
            )
            if unread_only:
                q = q.eq("read", False)
            if account:
                q = q.eq("account", account.lower())

            result = await loop.run_in_executor(None, lambda: q.execute())
            return result.data or []
        except Exception as e:
            self.logger.warning("Erro ao buscar emails: %s", e)
            return []

    async def _get_counts(self, user_id: str) -> Dict[str, Any]:
        emails = await self._fetch_emails(user_id, limit=100)
        counts: Dict[str, Any] = {}
        for email in emails:
            acc = email.get("account", "unknown")
            if acc not in counts:
                counts[acc] = {"total": 0, "unread": 0}
            counts[acc]["total"] += 1
            if not email.get("read"):
                counts[acc]["unread"] += 1
        return counts

    async def _mark_replied(self, email_id: Optional[str], user_id: str) -> None:
        if not self._db or not email_id:
            return
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: (
                    self._db.get_client()
                    .table("email_inbox")
                    .update({"replied": True, "read": True})
                    .eq("id", email_id)
                    .eq("user_id", user_id)
                    .execute()
                ),
            )
        except Exception as e:
            self.logger.warning("Erro ao marcar como respondido: %s", e)

    # ──────────────────────────────────────────────────────────────────────────
    # GMAIL-FIRST FETCHING
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_gmail_email(
        gmail_email: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Normalize Gmail API fields to Supabase-compatible names.

        Gmail → Supabase mappings:
          date       → received_at
          is_unread  → read (inverted)
          id         → email_id
        """
        n = dict(gmail_email)
        if "date" in n and "received_at" not in n:
            n["received_at"] = n["date"]
        if "is_unread" in n and "read" not in n:
            n["read"] = not n["is_unread"]
        if "id" in n and "email_id" not in n:
            n["email_id"] = n["id"]
        return n

    async def _fetch_emails(
        self,
        user_id: str,
        unread_only: bool = False,
        account: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch emails: Gmail API first, Supabase fallback.

        If *account* is explicitly non-Gmail (e.g. hotmail),
        skip the Gmail API and go straight to Supabase.
        """
        if account and account.lower() not in ("gmail",):
            return await self._get_emails(
                user_id,
                unread_only=unread_only,
                account=account,
                limit=limit,
            )

        # Try Gmail API first
        try:
            result = await self._list_emails(
                user_id=user_id,
                max_results=limit,
                unread_only=unread_only,
            )
            if result.get("success") and result.get("emails"):
                return [self._normalize_gmail_email(e) for e in result["emails"]]
            if result.get("success"):
                return []
        except Exception as e:
            self.logger.debug(
                "Gmail API unavailable, falling back to Supabase: %s",
                e,
            )

        # Supabase fallback (old N8N flow / Gmail not connected)
        return await self._get_emails(
            user_id,
            unread_only=unread_only,
            account=account,
            limit=limit,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _resolve_email_reference(
        self, msg: str, user_id: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Resolve referências como 'o 1', 'o primeiro', 'o do João'."""
        # Referência por número na lista
        num_match = re.search(
            r"\b([1-5]|primeiro|segundo|terceiro|último)\b", msg, re.IGNORECASE
        )
        if num_match:
            word = num_match.group(1).lower()
            idx = {"primeiro": 0, "segundo": 1, "terceiro": 2, "último": -1}.get(word)
            if idx is None:
                idx = int(word) - 1
            last_list = context.get("email_last_list", [])
            if last_list and 0 <= idx < len(last_list):
                return last_list[idx]
            if idx == -1 and last_list:
                return last_list[-1]

        # Referência por remetente
        name_match = re.search(
            r"\b(?:do|da|de|from)\s+([A-ZÀ-Ÿa-zà-ÿ]+(?:\s+[A-ZÀ-Ÿa-zà-ÿ]+)?)\b",
            msg,
            re.IGNORECASE,
        )
        if name_match:
            name = name_match.group(1).lower()
            emails = await self._fetch_emails(user_id, limit=20)
            for email in emails:
                if (
                    name in (email.get("from_name") or "").lower()
                    or name in (email.get("from_email") or "").lower()
                ):
                    return email

        # Último email pendente de resposta
        pending = context.get("email_pending_reply")
        if pending:
            return pending

        # Mais recente
        emails = await self._fetch_emails(user_id, limit=1)
        return emails[0] if emails else None

    @staticmethod
    def _extract_account(msg: str) -> Optional[str]:
        if _RE_ACCOUNT_GMAIL.search(msg):
            return "gmail"
        if _RE_ACCOUNT_HOTMAIL.search(msg):
            return "hotmail"
        return None

    @staticmethod
    def _extract_reply_instruction(msg: str) -> Optional[str]:
        """Extrai instrução de resposta da mensagem. Ex: 'responde dizendo que confirmo' → 'que confirmo'"""
        match = re.search(
            r"\b(?:dizendo?|diz|saying?|que|to say)\s+(.+)$", msg, re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _format_time(dt_str: str, lang: str = "en") -> str:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            diff = now - dt
            if diff.days == 0:
                return t("email_today_at", lang=lang, time=dt.strftime("%H:%M"))
            elif diff.days == 1:
                return t("email_yesterday", lang=lang)
            elif diff.days < 7:
                return t("email_days_ago", lang=lang, days=diff.days)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return dt_str[:10] if dt_str else ""

    def get_capabilities(self) -> List[str]:
        return [
            "listar emails Gmail e Hotmail",
            "resumir emails recebidos",
            "responder emails com confirmação",
            "contar emails não lidos",
            "notificar quando chega email novo",
            "listar emails respondidos pelo bot",
        ]
