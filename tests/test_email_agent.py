# -*- coding: utf-8 -*-
"""
tests/test_email_agent.py
===========================
Testes unitários para EmailAgent (sem N8N).

Cobertura EmailAgent:
- _parse_webhook_payload: normalização de payloads
- _get_account_label: labels de contas
- handle_incoming_email: notificação, urgência, contexto
- execute: list, count, reply intent, confirmation, ignore, summary
- _classify_urgency: high/medium/low
- _format_time
- _extract_account
- _extract_reply_instruction
- _resolve_email_reference: por número, por nome, fallback
- _send_email: Gmail API integration
- Fluxo completo: email chega → notifica → responde → confirma → envia
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Fixtures ────────────────────────────────────────────────────────────────

# Payloads normalizados (formato que _parse_webhook_payload espera/produz)
GMAIL_PAYLOAD = {
    "account": "gmail",
    "email_id": "gmail_msg_001",
    "thread_id": "thread_001",
    "message_id": "<abc123@mail.gmail.com>",
    "from_email": "joao@gmail.com",
    "from_name": "João Silva",
    "to": "eu@gmail.com",
    "subject": "Reunião amanhã",
    "body_text": "Olá, podemos ter reunião amanhã às 10h? Confirmas?",
    "received_at": "2026-02-22T10:00:00Z",
    "is_reply": False,
}

HOTMAIL_PAYLOAD = {
    "account": "hotmail",
    "email_id": "hotmail_msg_001",
    "thread_id": "conv_001",
    "message_id": "<xyz456@outlook.com>",
    "from_email": "maria@hotmail.com",
    "from_name": "Maria Costa",
    "to": "eu@hotmail.com",
    "subject": "Proposta urgente",
    "body_text": "Boa tarde, tenho uma proposta urgente para ti.",
    "received_at": "2026-02-22T14:00:00Z",
    "is_reply": False,
}


def _email_agent(ai_response="Resumo do email.", draft="Olá, confirmo a reunião."):
    from agents.specialized.email_agent import EmailAgent

    agent = EmailAgent.__new__(EmailAgent)
    agent.name = "email"
    agent.logger = MagicMock()
    agent._initialized = True
    agent._db = None

    ai_mock = AsyncMock()
    ai_mock.complete = AsyncMock(return_value=ai_response)
    agent._ai = ai_mock

    # Mock database methods
    agent._save_email = AsyncMock(return_value="email_uuid_001")
    agent._get_emails = AsyncMock(return_value=[])
    agent._get_counts = AsyncMock(return_value={})
    agent._mark_replied = AsyncMock()

    return agent


# ─── EmailAgent — _parse_webhook_payload ─────────────────────────────────────


class TestParseWebhookPayload:
    def test_parse_normalized_gmail(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._parse_webhook_payload(GMAIL_PAYLOAD)
        assert result["account"] == "gmail"
        assert result["email_id"] == "gmail_msg_001"
        assert result["thread_id"] == "thread_001"
        assert result["from_email"] == "joao@gmail.com"
        assert result["from_name"] == "João Silva"
        assert result["subject"] == "Reunião amanhã"
        assert (
            result["body_text"]
            == "Olá, podemos ter reunião amanhã às 10h? Confirmas?"
        )
        assert result["is_reply"] is False

    def test_parse_normalized_hotmail(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._parse_webhook_payload(HOTMAIL_PAYLOAD)
        assert result["account"] == "hotmail"
        assert result["email_id"] == "hotmail_msg_001"
        assert result["thread_id"] == "conv_001"
        assert result["from_email"] == "maria@hotmail.com"
        assert result["from_name"] == "Maria Costa"
        assert result["subject"] == "Proposta urgente"

    def test_parse_generic_payload(self):
        from agents.specialized.email_agent import EmailAgent

        generic = {
            "account": "yahoo",
            "email_id": "y001",
            "thread_id": "t001",
            "from_email": "test@yahoo.com",
            "from_name": "Test User",
            "subject": "Teste",
            "body_text": "Corpo do email",
        }
        result = EmailAgent._parse_webhook_payload(generic)
        assert result["account"] == "yahoo"
        assert result["from_email"] == "test@yahoo.com"

    def test_parse_empty_payload_defaults(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._parse_webhook_payload({})
        assert result["account"] == "unknown"
        assert result["email_id"] == ""
        assert result["from_email"] == ""
        assert result["subject"] == "(sem assunto)"
        assert result["is_reply"] is False

    def test_parse_from_fallback_to_from_key(self):
        """Quando não há from_email, usa chave 'from'."""
        from agents.specialized.email_agent import EmailAgent

        data = {"from": "fallback@test.com", "account": "gmail"}
        result = EmailAgent._parse_webhook_payload(data)
        assert result["from_email"] == "fallback@test.com"

    def test_parse_body_fallback_to_body_key(self):
        """Quando não há body_text, usa chave 'body'."""
        from agents.specialized.email_agent import EmailAgent

        data = {"body": "Corpo via body key", "account": "gmail"}
        result = EmailAgent._parse_webhook_payload(data)
        assert result["body_text"] == "Corpo via body key"

    def test_parse_is_reply_true(self):
        from agents.specialized.email_agent import EmailAgent

        data = {**GMAIL_PAYLOAD, "is_reply": True}
        result = EmailAgent._parse_webhook_payload(data)
        assert result["is_reply"] is True


# ─── EmailAgent — _get_account_label ─────────────────────────────────────────


class TestGetAccountLabel:
    def test_gmail(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._get_account_label("gmail") == "Gmail"

    def test_hotmail(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._get_account_label("hotmail") == "Hotmail"

    def test_outlook(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._get_account_label("outlook") == "Outlook"

    def test_yahoo(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._get_account_label("yahoo") == "Yahoo"

    def test_unknown_capitalizes(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._get_account_label("protonmail") == "Protonmail"

    def test_case_insensitive(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._get_account_label("GMAIL") == "Gmail"
        assert EmailAgent._get_account_label("Gmail") == "Gmail"


# ─── EmailAgent — _send_email (Gmail API) ──────────────────────────────────


@pytest.mark.asyncio
class TestSendEmail:
    async def test_send_email_no_user_id(self):
        """Send without user_id returns error dict."""
        agent = _email_agent()
        result = await agent._send_email(
            to="test@test.com",
            subject="Test",
            body="Body",
        )
        assert result["success"] is False
        assert "user_id" in result["error"]

    async def test_send_email_no_gmail_service(self):
        """Send when GmailService not available returns error."""
        agent = _email_agent()
        with patch("agents.specialized.email_agent.get_service", return_value=None):
            result = await agent._send_email(
                to="test@test.com",
                subject="Test",
                body="Body",
                user_id="u1",
            )
        assert result["success"] is False
        assert "GmailService" in result["error"]


# ─── EmailAgent — classify urgency ───────────────────────────────────────────


@pytest.mark.asyncio
class TestEmailUrgency:
    async def test_high_urgency_from_subject(self):
        agent = _email_agent()
        email = {"subject": "URGENTE: Reunião agora", "body_text": ""}
        urgency = await agent._classify_urgency(email)
        assert urgency == "high"

    async def test_high_urgency_deadline_in_body(self):
        agent = _email_agent()
        email = {"subject": "Proposta", "body_text": "Tens um deadline hoje!"}
        urgency = await agent._classify_urgency(email)
        assert urgency == "high"

    async def test_low_urgency_newsletter(self):
        agent = _email_agent()
        email = {
            "subject": "Newsletter de Fevereiro",
            "body_text": "unsubscribe here",
        }
        urgency = await agent._classify_urgency(email)
        assert urgency == "low"

    async def test_medium_urgency_normal(self):
        agent = _email_agent()
        email = {"subject": "Olá, como estás?", "body_text": "Tudo bem por aí?"}
        urgency = await agent._classify_urgency(email)
        assert urgency == "medium"


# ─── EmailAgent — format_time ────────────────────────────────────────────────


class TestFormatTime:
    def test_format_today(self):
        from agents.specialized.email_agent import EmailAgent
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        result = EmailAgent._format_time(now)
        assert "hoje" in result

    def test_format_invalid(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._format_time("invalid")
        assert result == "invalid"[:10] or result == ""

    def test_format_empty(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._format_time("")
        assert result == ""


# ─── EmailAgent — extract helpers ────────────────────────────────────────────


class TestEmailExtractHelpers:
    def test_extract_account_gmail(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._extract_account("mostra emails do gmail") == "gmail"

    def test_extract_account_hotmail(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._extract_account("emails do hotmail") == "hotmail"

    def test_extract_account_outlook(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._extract_account("meus emails do outlook") == "hotmail"

    def test_extract_account_none(self):
        from agents.specialized.email_agent import EmailAgent

        assert EmailAgent._extract_account("mostra os meus emails") is None

    def test_extract_reply_instruction_dizendo(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._extract_reply_instruction(
            "responde dizendo que confirmo a reunião"
        )
        assert "confirmo" in result.lower()

    def test_extract_reply_instruction_diz(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._extract_reply_instruction(
            "responde diz que não posso"
        )
        assert "não posso" in result.lower()

    def test_extract_reply_instruction_none(self):
        from agents.specialized.email_agent import EmailAgent

        result = EmailAgent._extract_reply_instruction("responde ao email")
        assert result is None


# ─── EmailAgent — handle_incoming_email ──────────────────────────────────────


@pytest.mark.asyncio
class TestEmailIncoming:
    async def test_handle_incoming_gmail(self):
        agent = _email_agent()
        context = {}
        result = await agent.handle_incoming_email(
            "user_001", GMAIL_PAYLOAD, context
        )
        assert (
            result.status.value == "success"
            or result.status == "success"
            or "success" in str(result.status).lower()
        )
        assert "Gmail" in result.message or "email" in result.message.lower()
        assert (
            "Queres" in result.message
            or "responder" in result.message.lower()
            or "respond" in result.message.lower()
        )

    async def test_handle_incoming_sets_context(self):
        agent = _email_agent()
        context = {}
        await agent.handle_incoming_email("user_001", GMAIL_PAYLOAD, context)
        assert "email_pending_reply" in context
        assert context["email_pending_reply"]["account"] == "gmail"

    async def test_handle_incoming_hotmail(self):
        agent = _email_agent()
        context = {}
        await agent.handle_incoming_email(
            "user_001", HOTMAIL_PAYLOAD, context
        )
        assert context["email_pending_reply"]["account"] == "hotmail"

    async def test_high_urgency_email_shows_red(self):
        agent = _email_agent()
        context = {}
        urgent_payload = {
            **GMAIL_PAYLOAD,
            "subject": "URGENTE: Reunião agora!",
            "body_text": "Urgente mesmo!",
        }
        result = await agent.handle_incoming_email(
            "user_001", urgent_payload, context
        )
        assert (
            "🔴" in result.message
            or "urgente" in result.message.lower()
            or "high" in str(result.data)
        )


# ─── EmailAgent — execute list ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmailExecuteList:
    async def test_list_empty(self):
        agent = _email_agent()
        agent._get_emails = AsyncMock(return_value=[])
        result = await agent.execute("mostra os meus emails", {"user_id": "u1"})
        assert "Nenhum email" in result.message or "📭" in result.message

    async def test_list_with_emails(self):
        agent = _email_agent()
        agent._get_emails = AsyncMock(
            return_value=[
                {
                    "account": "gmail",
                    "from_name": "João",
                    "from_email": "j@gmail.com",
                    "subject": "Olá",
                    "received_at": "2026-02-22T10:00:00Z",
                    "read": False,
                }
            ]
        )
        result = await agent.execute("mostra os meus emails", {"user_id": "u1"})
        assert "João" in result.message or "Olá" in result.message

    async def test_list_unread_only(self):
        agent = _email_agent()
        agent._get_emails = AsyncMock(return_value=[])
        await agent.execute("emails não lidos", {"user_id": "u1"})
        agent._get_emails.assert_called_once()
        call_kwargs = agent._get_emails.call_args
        assert call_kwargs[1].get("unread_only") is True or (
            call_kwargs[0] and True in call_kwargs[0]
        )

    async def test_list_gmail_filter(self):
        agent = _email_agent()
        agent._get_emails = AsyncMock(return_value=[])
        await agent.execute("mostra emails do gmail", {"user_id": "u1"})
        call_kwargs = agent._get_emails.call_args
        # account deve ser gmail
        account_arg = call_kwargs[1].get("account") or (
            call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None
        )
        assert account_arg == "gmail"


# ─── EmailAgent — execute count ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmailExecuteCount:
    async def test_count_empty(self):
        agent = _email_agent()
        agent._get_counts = AsyncMock(return_value={})
        result = await agent.execute("quantos emails tenho?", {"user_id": "u1"})
        assert "email" in result.message.lower() or "📊" in result.message

    async def test_count_with_data(self):
        agent = _email_agent()
        agent._get_counts = AsyncMock(
            return_value={
                "gmail": {"total": 10, "unread": 3},
                "hotmail": {"total": 5, "unread": 0},
            }
        )
        result = await agent.execute("quantos emails tenho?", {"user_id": "u1"})
        assert "Gmail" in result.message
        assert "3" in result.message


# ─── EmailAgent — reply flow ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmailReplyFlow:
    async def test_reply_intent_generates_draft(self):
        agent = _email_agent(draft="Olá, confirmo a reunião para amanhã.")
        agent._get_emails = AsyncMock(
            return_value=[
                {
                    "id": "e001",
                    "account": "gmail",
                    "thread_id": "t001",
                    "message_id": "<m001>",
                    "from_email": "joao@gmail.com",
                    "from_name": "João",
                    "subject": "Reunião amanhã",
                    "body_text": "Confirmas?",
                }
            ]
        )
        context = {"user_id": "u1"}
        result = await agent.execute(
            "responde ao último email", context
        )
        assert (
            "Rascunho" in result.message
            or "rascunho" in result.message.lower()
        )
        assert "email_pending_reply" in context
        assert "draft" in context["email_pending_reply"]

    async def test_confirm_sends_email(self):
        """Confirmar envia via _send_email (que levanta NotImplementedError)."""
        agent = _email_agent()
        # Mock _send_email to simulate success (future implementation)
        agent._send_email = AsyncMock(return_value={"success": True})

        context = {
            "user_id": "u1",
            "email_pending_reply": {
                "email_id": "e001",
                "account": "gmail",
                "thread_id": "t001",
                "message_id": "<m001>",
                "from_email": "joao@gmail.com",
                "subject": "Reunião",
                "draft": "Confirmo a reunião!",
            },
        }
        result = await agent.execute("sim", context)
        agent._send_email.assert_called_once()
        assert "enviada" in result.message.lower() or "✅" in result.message
        assert "email_pending_reply" not in context

    async def test_cancel_clears_context(self):
        agent = _email_agent()
        context = {
            "user_id": "u1",
            "email_pending_reply": {
                "email_id": "e001",
                "account": "gmail",
                "from_email": "j@g.com",
                "subject": "test",
                "draft": "rascunho",
            },
        }
        result = await agent.execute("não", context)
        assert "email_pending_reply" not in context
        assert (
            "cancelada" in result.message.lower()
            or "não enviado" in result.message.lower()
        )

    async def test_modify_draft(self):
        agent = _email_agent(draft="Novo rascunho modificado.")
        context = {
            "user_id": "u1",
            "email_pending_reply": {
                "email_id": "e001",
                "account": "gmail",
                "from_email": "j@g.com",
                "subject": "test",
                "body_text": "corpo original",
                "draft": "rascunho antigo",
            },
        }
        result = await agent.execute(
            "muda para um tom mais formal", context
        )
        assert (
            "Rascunho actualizado" in result.message
            or "actualizado" in result.message.lower()
        )

    async def test_ignore_clears_pending(self):
        agent = _email_agent()
        context = {"user_id": "u1", "email_pending_reply": {"email_id": "e001"}}
        result = await agent.execute("ignora este email", context)
        assert "email_pending_reply" not in context
        assert "ignorado" in result.message.lower()


# ─── EmailAgent — reply with instruction ─────────────────────────────────────


@pytest.mark.asyncio
class TestEmailReplyInstruction:
    async def test_reply_with_instruction(self):
        agent = _email_agent(
            draft="Olá, confirmo que posso estar presente."
        )
        agent._get_emails = AsyncMock(
            return_value=[
                {
                    "id": "e001",
                    "account": "gmail",
                    "thread_id": "t001",
                    "message_id": "<m001>",
                    "from_email": "j@g.com",
                    "from_name": "João",
                    "subject": "Evento",
                    "body_text": "Vais estar presente?",
                }
            ]
        )
        context = {"user_id": "u1"}
        await agent.execute(
            "responde dizendo que confirmo presença", context
        )
        # GPT foi chamado com a instrução
        agent._ai.complete.assert_called_once()
        prompt_used = agent._ai.complete.call_args[0][0]
        assert (
            "confirmo presença" in prompt_used.lower()
            or "instrução" in prompt_used.lower()
        )


# ─── EmailAgent — help message ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmailHelp:
    async def test_unknown_intent_shows_help(self):
        agent = _email_agent()
        result = await agent.execute("ajuda com email", {"user_id": "u1"})
        assert (
            "Podes dizer" in result.message
            or "email" in result.message.lower()
        )

    async def test_capabilities(self):
        agent = _email_agent()
        caps = agent.get_capabilities()
        assert isinstance(caps, list)
        assert len(caps) > 0
        assert any(
            "gmail" in c.lower() or "hotmail" in c.lower() for c in caps
        )


# ─── Supplementary tests — cover init, fallback branches, DB helpers ────────


@pytest.mark.asyncio
class TestEmailInit:
    async def test_real_constructor(self):
        """Cover __init__ and is_initialized/initialize."""
        with patch(
            "agents.specialized.email_agent.get_service",
            return_value=None,
        ):
            from agents.specialized.email_agent import EmailAgent

            agent = EmailAgent()
            assert agent.name == "email"
            assert agent.is_initialized() is False
            await agent.initialize()
            assert agent.is_initialized() is True

    async def test_execute_triggers_init(self):
        """execute() calls initialize() when not yet initialized."""
        with patch(
            "agents.specialized.email_agent.get_service",
            return_value=None,
        ):
            from agents.specialized.email_agent import EmailAgent

            agent = EmailAgent()
            result = await agent.execute("olá email", {"user_id": "u1"})
            assert agent.is_initialized() is True
            # Falls through to help message (no intent matched)
            assert "email" in result.message.lower()


@pytest.mark.asyncio
class TestSummarizeEmail:
    async def test_summarize_no_body(self):
        agent = _email_agent()
        result = await agent._summarize_email({"body_text": ""})
        assert "Sem corpo" in result

    async def test_summarize_no_ai(self):
        agent = _email_agent()
        agent._ai = None
        result = await agent._summarize_email({"body_text": "Test body"})
        assert result == "Test body"

    async def test_summarize_ai_error(self):
        agent = _email_agent()
        agent._ai.complete = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await agent._summarize_email({"body_text": "Short body"})
        assert "Short body" in result

    async def test_summarize_detailed(self):
        agent = _email_agent(ai_response="Resumo detalhado.")
        result = await agent._summarize_email(
            {
                "body_text": "Corpo do email",
                "from_name": "João",
                "subject": "Teste",
            },
            detailed=True,
        )
        assert result == "Resumo detalhado."


@pytest.mark.asyncio
class TestGenerateReplyDraft:
    async def test_draft_no_ai(self):
        agent = _email_agent()
        agent._ai = None
        result = await agent._generate_reply_draft({"subject": "Reunião"})
        assert "Obrigado" in result
        assert "Reunião" in result

    async def test_draft_ai_error(self):
        agent = _email_agent()
        agent._ai.complete = AsyncMock(
            side_effect=Exception("GPT fail")
        )
        result = await agent._generate_reply_draft({"subject": "X"})
        assert "Obrigado" in result


@pytest.mark.asyncio
class TestHandleSummary:
    async def test_summary_no_email_found(self):
        agent = _email_agent()
        agent._get_emails = AsyncMock(return_value=[])
        result = await agent.execute("resume o email do Pedro", {"user_id": "u1"})
        assert "Não encontrei" in result.message or "❌" in result.message

    async def test_summary_with_email(self):
        agent = _email_agent(
            ai_response="Este email fala sobre reunião."
        )
        agent._get_emails = AsyncMock(
            return_value=[
                {
                    "id": "e1",
                    "account": "gmail",
                    "from_name": "Ana",
                    "from_email": "ana@test.com",
                    "subject": "Projecto",
                    "body_text": "Vamos reunir amanhã.",
                }
            ]
        )
        result = await agent.execute("resume o email da Ana", {"user_id": "u1"})
        assert (
            "Resumo" in result.message
            or "resumo" in result.message.lower()
        )


@pytest.mark.asyncio
class TestHandleIgnoreWithoutPending:
    async def test_ignore_without_pending(self):
        agent = _email_agent()
        result = await agent.execute("ignora o email", {"user_id": "u1"})
        assert "ignorado" in result.message.lower()


@pytest.mark.asyncio
class TestConfirmationEdgeCases:
    async def test_confirm_no_draft_error(self):
        agent = _email_agent()
        context = {
            "user_id": "u1",
            "email_pending_reply": {
                "email_id": "e1",
                "account": "gmail",
                "from_email": "j@g.com",
                "subject": "test",
                "draft": "",  # empty draft
            },
        }
        result = await agent.execute("sim", context)
        assert "❌" in result.message or "rascunho" in result.message.lower()

    async def test_confirm_send_error(self):
        agent = _email_agent()
        agent._send_email = AsyncMock(
            side_effect=Exception("Network fail")
        )
        context = {
            "user_id": "u1",
            "email_pending_reply": {
                "email_id": "e1",
                "account": "gmail",
                "thread_id": "t1",
                "message_id": "<m1>",
                "from_email": "j@g.com",
                "subject": "test",
                "draft": "Rascunho ok",
            },
        }
        result = await agent.execute("sim envia", context)
        assert "❌" in result.message or "Erro" in result.message


@pytest.mark.asyncio
class TestResolveEmailReference:
    async def test_resolve_by_number_in_list(self):
        agent = _email_agent()
        context = {
            "email_last_list": [
                {"id": "e1", "from_name": "A"},
                {"id": "e2", "from_name": "B"},
            ]
        }
        email = await agent._resolve_email_reference(
            "resume o 1", "u1", context
        )
        assert email["id"] == "e1"

    async def test_resolve_ultimo(self):
        agent = _email_agent()
        context = {
            "email_last_list": [
                {"id": "e1", "from_name": "A"},
                {"id": "e2", "from_name": "B"},
            ]
        }
        email = await agent._resolve_email_reference(
            "resume o último", "u1", context
        )
        assert email["id"] == "e2"

    async def test_resolve_by_name(self):
        agent = _email_agent()
        agent._get_emails = AsyncMock(
            return_value=[
                {"from_name": "Carlos", "from_email": "carlos@x.com"},
            ]
        )
        email = await agent._resolve_email_reference(
            "resume do Carlos", "u1", {}
        )
        assert email["from_name"] == "Carlos"

    async def test_resolve_fallback_to_pending(self):
        agent = _email_agent()
        agent._get_emails = AsyncMock(return_value=[])
        context = {
            "email_pending_reply": {
                "email_id": "pending_e1",
                "account": "gmail",
            }
        }
        email = await agent._resolve_email_reference(
            "resume email", "u1", context
        )
        assert email["email_id"] == "pending_e1"
