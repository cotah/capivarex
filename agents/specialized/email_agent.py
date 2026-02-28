# -*- coding: utf-8 -*-
"""
agents/specialized/email_agent.py
====================================
EmailAgent — gestão de emails via N8N (Gmail + Hotmail/Outlook).

Fluxo completo:
    1. N8N detecta email novo (Gmail ou Hotmail)
    2. N8N envia webhook para /api/webhooks/email
    3. EmailAgent recebe, resume e notifica no Telegram
    4. Utilizador responde: "sim responde" / "ignora" / "responde dizendo X"
    5. EmailAgent gera resposta com GPT e pede confirmação
    6. Com confirmação, envia via N8N para a conta correcta

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


@register_agent("email")
class EmailAgent(BaseAgent):
    """
    Agente de email — recebe notificações do N8N e gere
    emails de Gmail e Hotmail/Outlook através do Telegram.
    """

    def __init__(self):
        super().__init__(name="email", description="Gestão de emails via N8N")
        self._db = None
        self._ai = None
        self._n8n = None
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
        self._n8n = get_service("n8n")

    # ──────────────────────────────────────────────────────────────────────────
    # ENTRADA PRINCIPAL
    # ──────────────────────────────────────────────────────────────────────────

    async def execute(
        self, message: str, user_id: str, context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Processa mensagem do utilizador relacionada com emails.
        Também é chamado internamente quando chega webhook do N8N.
        """
        if not self.is_initialized():
            await self.initialize()

        # Fetch linked accounts so the agent knows what's available
        try:
            accounts = await edb.get_email_accounts(user_id)
            context["email_accounts"] = accounts
        except Exception:
            pass

        msg = message.strip()

        # Verificar se é resposta a confirmação pendente
        pending = context.get("email_pending_reply")
        if pending:
            return await self._handle_confirmation(msg, user_id, context, pending)

        # Detectar intenção
        if _RE_SENT.search(msg):
            return await self._handle_sent_replies(user_id, context)

        if _RE_REPLY.search(msg):
            return await self._handle_reply_intent(msg, user_id, context)

        if _RE_IGNORE.search(msg):
            return await self._handle_ignore(msg, user_id, context)

        if _RE_SUMMARY.search(msg):
            return await self._handle_summary(msg, user_id, context)

        if _RE_COUNT.search(msg):
            return await self._handle_count(user_id, context)

        if _RE_UNREAD.search(msg):
            return await self._handle_list(user_id, context, unread_only=True)

        if _RE_SHOW.search(msg):
            account = self._extract_account(msg)
            return await self._handle_list(user_id, context, account=account)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=(
                "📧 *Gestão de Email*\n\n"
                "Podes dizer-me:\n"
                "• _'Mostra os meus emails'_\n"
                "• _'Emails não lidos do Gmail'_\n"
                "• _'Responde ao último email'_\n"
                "• _'Resume o email do João'_\n"
                "• _'Quantos emails tenho?'_"
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # WEBHOOK RECEBIDO DO N8N (chamado pela route /api/webhooks/email)
    # ──────────────────────────────────────────────────────────────────────────

    async def handle_incoming_email(
        self,
        user_id: str,
        email_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> AgentResponse:
        """
        Processa email recebido via webhook do N8N.
        Guarda no Supabase, analisa com GPT e notifica no Telegram.

        Args:
            user_id:    ID do utilizador dono da conta
            email_data: Payload já normalizado pelo N8NService.parse_webhook_payload
            context:    Contexto do utilizador
        """
        if not self.is_initialized():
            await self.initialize()

        # 1. Normalizar (caso não tenha sido feito antes)
        if self._n8n:
            email = self._n8n.parse_webhook_payload(email_data)
        else:
            email = email_data

        # 2. Guardar no Supabase
        email_id = await self._save_email(user_id, email)

        # 3. Resumir com GPT
        summary = await self._summarize_email(email)

        # 4. Classificar urgência
        urgency = await self._classify_urgency(email)

        # 5. Formatar notificação Telegram
        account_label = (
            self._n8n.get_account_label(email["account"])
            if self._n8n
            else email["account"].capitalize()
        )
        urgency_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(urgency, "📧")

        notification = (
            f"{urgency_icon} *{account_label}* — Email recebido\n\n"
            f"👤 **De:** {email['from_name'] or email['from_email']}\n"
            f"📌 **Assunto:** {email['subject']}\n\n"
            f"📝 **Resumo:**\n{summary}\n\n"
            f"💬 Queres que eu responda?"
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
    ) -> AgentResponse:
        emails = await self._get_emails(
            user_id, unread_only=unread_only, account=account, limit=limit
        )

        if not emails:
            filter_desc = ""
            if account:
                filter_desc = f" do {account.capitalize()}"
            if unread_only:
                filter_desc += " não lidos"
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message=f"📭 Nenhum email{filter_desc} encontrado.",
            )

        account_label = account.capitalize() if account else "todas as contas"
        title = (
            f"📧 *Emails{' não lidos' if unread_only else ''} — {account_label}*\n\n"
        )
        lines = [title]

        for i, email in enumerate(emails, 1):
            acc_icon = "📮" if email.get("account") == "gmail" else "📬"
            read_icon = "🔵" if not email.get("read") else ""
            lines.append(
                f"{i}. {acc_icon}{read_icon} **{email.get('from_name') or email.get('from_email', '?')}**\n"
                f"   _{email.get('subject', '(sem assunto)')}_\n"
                f"   {self._format_time(email.get('received_at', ''))}\n"
            )

        lines.append("\n_Diz 'responde ao 1' ou 'resume o 2' para interagir._")

        # Guardar lista no contexto para referenciar por número
        context["email_last_list"] = emails

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message="\n".join(lines),
            data={"emails": emails},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # CONTAR EMAILS
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_count(
        self, user_id: str, context: Dict[str, Any]
    ) -> AgentResponse:
        counts = await self._get_counts(user_id)

        lines = ["📊 *Seus emails*\n"]
        total_unread = 0

        for account, data in counts.items():
            icon = "📮" if account == "gmail" else "📬"
            unread = data.get("unread", 0)
            total = data.get("total", 0)
            total_unread += unread
            label = (
                self._n8n.get_account_label(account)
                if self._n8n
                else account.capitalize()
            )
            lines.append(f"{icon} **{label}:** {unread} não lidos / {total} total")

        if total_unread > 0:
            lines.append(f"\n🔵 **Total não lidos: {total_unread}**")
        else:
            lines.append("\n✅ Sem emails por ler!")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message="\n".join(lines),
            data=counts,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # RESUMIR EMAIL
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_summary(
        self, msg: str, user_id: str, context: Dict[str, Any]
    ) -> AgentResponse:
        email = await self._resolve_email_reference(msg, user_id, context)
        if not email:
            return AgentResponse(
                status=AgentStatus.ERROR,
                message="❌ Não encontrei o email. Podes mostrar a lista primeiro com 'mostra os meus emails'?",
            )

        summary = await self._summarize_email(email, detailed=True)
        account_label = (
            self._n8n.get_account_label(email.get("account", "")) if self._n8n else ""
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=(
                f"📧 **{account_label}** — Resumo\n\n"
                f"👤 **De:** {email.get('from_name') or email.get('from_email')}\n"
                f"📌 **Assunto:** {email.get('subject')}\n\n"
                f"{summary}"
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # INTENÇÃO DE RESPONDER
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_reply_intent(
        self, msg: str, user_id: str, context: Dict[str, Any]
    ) -> AgentResponse:
        email = await self._resolve_email_reference(msg, user_id, context)
        if not email:
            # Se não especificou qual, pegar o mais recente não lido
            emails = await self._get_emails(user_id, unread_only=True, limit=1)
            if emails:
                email = emails[0]
            else:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    message="❌ Não encontrei nenhum email para responder. Diz 'mostra os meus emails' primeiro.",
                )

        # Extrair instrução de resposta da mensagem
        instruction = self._extract_reply_instruction(msg)

        # Gerar rascunho com GPT
        draft = await self._generate_reply_draft(email, instruction)

        account_label = (
            self._n8n.get_account_label(email.get("account", "")) if self._n8n else ""
        )

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
            message=(
                f"📝 *Rascunho de resposta — {account_label}*\n\n"
                f"**Para:** {email.get('from_email')}\n"
                f"**Assunto:** Re: {email.get('subject')}\n\n"
                f"---\n{draft}\n---\n\n"
                f"✅ Diz **'sim'** para enviar ou **'não'** para cancelar.\n"
                f"Ou diz o que queres alterar."
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
    ) -> AgentResponse:
        if _RE_CANCEL.search(msg) and not _RE_CONFIRM.search(msg):
            context.pop("email_pending_reply", None)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message="✅ Resposta cancelada. Email não enviado.",
            )

        if _RE_CONFIRM.search(msg):
            # Enviar via N8N
            draft = pending.get("draft", "")
            if not draft:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    message="❌ Sem rascunho para enviar. Pede uma resposta primeiro.",
                )

            try:
                if self._n8n:
                    await self._n8n.trigger_send_reply(
                        account=pending["account"],
                        thread_id=pending.get("thread_id", ""),
                        message_id=pending.get("message_id", ""),
                        to=pending["from_email"],
                        subject=pending.get("subject", ""),
                        body=draft,
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

                account_label = (
                    self._n8n.get_account_label(pending["account"])
                    if self._n8n
                    else pending.get("account", "").capitalize()
                )

                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    message=f"✅ Resposta enviada pelo {account_label}!",
                )

            except Exception as e:
                self.logger.error("Erro ao enviar reply: %s", e)
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    message=f"❌ Erro ao enviar: {e}\nTente novamente.",
                )

        # Check for ignore intent within confirmation flow
        if _RE_IGNORE.search(msg):
            context.pop("email_pending_reply", None)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message="✅ Email ignorado. Não vou notificar-te sobre este.",
            )

        # Não foi sim nem não — pode ser uma alteração ao rascunho
        new_instruction = msg
        email_ctx = {
            "from_email": pending.get("from_email", ""),
            "subject": pending.get("subject", ""),
            "body_text": pending.get("body_text", ""),
        }
        new_draft = await self._generate_reply_draft(email_ctx, new_instruction)
        pending["draft"] = new_draft
        context["email_pending_reply"] = pending

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message=(
                f"📝 *Rascunho actualizado:*\n\n"
                f"---\n{new_draft}\n---\n\n"
                f"✅ **'sim'** para enviar ou **'não'** para cancelar."
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # EMAILS RESPONDIDOS PELO BOT
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_sent_replies(
        self, user_id: str, context: Dict[str, Any]
    ) -> AgentResponse:
        try:
            replies = await edb.get_sent_replies(user_id)
        except Exception:
            replies = []

        if not replies:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                message="📭 Ainda não respondi a nenhum email por ti.",
            )

        lines = ["📤 *Emails respondidos pelo bot*\n"]
        for i, r in enumerate(replies[:10], 1):
            lines.append(
                f"{i}. **Para:** {r.get('to_email', '?')}\n"
                f"   _{r.get('subject', '(sem assunto)')}_\n"
                f"   📅 {self._format_time(r.get('sent_at', ''))}\n"
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
        self, msg: str, user_id: str, context: Dict[str, Any]
    ) -> AgentResponse:
        context.pop("email_pending_reply", None)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            message="✅ Email ignorado. Não vou notificar-te sobre este.",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # GPT HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _summarize_email(
        self, email: Dict[str, Any], detailed: bool = False
    ) -> str:
        body = (email.get("body_text") or "")[:2000]
        if not body:
            return "_Sem corpo de email._"

        if not self._ai:
            return body[:300] + ("..." if len(body) > 300 else "")

        prompt = (
            f"Resume este email de forma clara e concisa em português.\n"
            f"{'Dá um resumo detalhado.' if detailed else 'Máximo 3 linhas.'}\n\n"
            f"De: {email.get('from_name') or email.get('from_email')}\n"
            f"Assunto: {email.get('subject')}\n\n"
            f"{body}"
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
        self, email: Dict[str, Any], instruction: Optional[str] = None
    ) -> str:
        if not self._ai:
            return f"Obrigado pelo seu email sobre '{email.get('subject', '')}'. Fico aguardando."

        prompt = (
            f"Gera uma resposta profissional e natural em português para este email.\n"
            f"{'Instrução: ' + instruction if instruction else 'Resposta educada e concisa.'}\n\n"
            f"Email original:\n"
            f"De: {email.get('from_name') or email.get('from_email', '')}\n"
            f"Assunto: {email.get('subject', '')}\n"
            f"Corpo: {(email.get('body_text') or '')[:1000]}\n\n"
            f"Escreve apenas o corpo da resposta, sem saudação de assunto."
        )
        try:
            response = await self._ai.complete(prompt, max_tokens=400)
            return response.strip()
        except Exception as e:
            self.logger.warning("Erro ao gerar rascunho: %s", e)
            return "Obrigado pela sua mensagem. Irei responder em breve."

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
        emails = await self._get_emails(user_id, limit=100)
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
            emails = await self._get_emails(user_id, limit=20)
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
        emails = await self._get_emails(user_id, limit=1)
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
    def _format_time(dt_str: str) -> str:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            diff = now - dt
            if diff.days == 0:
                return f"hoje às {dt.strftime('%H:%M')}"
            elif diff.days == 1:
                return "ontem"
            elif diff.days < 7:
                return f"há {diff.days} dias"
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
