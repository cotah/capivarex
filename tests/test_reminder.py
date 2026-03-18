# -*- coding: utf-8 -*-
"""
tests/test_reminder_agent.py
=============================
Testes unitários para ReminderAgent e helpers de parsing de data/hora.

Cobertura:
- _parse_remind_datetime: amanhã, hoje, dias da semana, em X dias/semanas,
  recorrência (daily/weekly/monthly), hora com minutos
- _extract_message: extracção do texto do lembrete
- _extract_id: detecção de IDs parciais (8 chars hex)
- ReminderAgent.execute: criar, listar, cancelar, cancelar todos
- Cenários de erro: sem data, sem ID, sem user_id, serviço indisponível
- Conteúdo das respostas (ícones, dados retornados)
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _utcnow():
    return datetime.now(timezone.utc)


def _make_reminder(
    rid="abc12345-0000-0000-0000-000000000000",
    user_id="user1",
    message="Ligar ao médico",
    recurrence=None,
    fired=False,
    cancelled=False,
    remind_at=None,
):
    if remind_at is None:
        remind_at = (_utcnow() + timedelta(hours=2)).isoformat()
    return {
        "id": rid,
        "user_id": user_id,
        "chat_id": user_id,
        "message": message,
        "remind_at": remind_at,
        "recurrence": recurrence,
        "fired": fired,
        "cancelled": cancelled,
    }


def _agent():
    from agents.specialized.reminder_agent import ReminderAgent

    a = ReminderAgent.__new__(ReminderAgent)
    a.name = "reminder"
    a.logger = MagicMock()
    return a


def _svc():
    svc = MagicMock()
    svc.is_initialized.return_value = True
    svc.format_remind_at = lambda dt, tz=0: "22/02/2026 às 10:00"
    svc.format_recurrence = lambda r: {
        "daily": "todo dia",
        "weekly": "toda semana",
        "monthly": "todo mês",
    }.get(r or "", "uma vez")
    return svc


def _ctx(user_id="user1"):
    return {"user_id": user_id, "chat_id": user_id}


# ─── _parse_remind_datetime ───────────────────────────────────────────────────


class TestParseRemindDatetime:
    def test_amanha_hora(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        base = _utcnow()
        dt, rec = _parse_remind_datetime("Me lembra amanhã às 9h", base)
        assert dt is not None
        assert dt.date() == (base + timedelta(days=1)).date()
        assert dt.hour == 9
        assert rec is None

    def test_hoje_hora(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        base = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        dt, _ = _parse_remind_datetime("Me lembra hoje às 10h", base)
        assert dt is not None
        assert dt.hour == 10

    def test_dia_semana_sexta(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, _ = _parse_remind_datetime("Sexta às 14h para reunião")
        assert dt is not None
        assert dt.weekday() == 4
        assert dt.hour == 14

    def test_dia_semana_segunda(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, _ = _parse_remind_datetime("Segunda às 8h")
        assert dt is not None
        assert dt.weekday() == 0

    def test_dia_semana_sabado(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, _ = _parse_remind_datetime("Sábado às 11h")
        assert dt is not None
        assert dt.weekday() == 5

    def test_em_x_dias(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        base = _utcnow()
        dt, _ = _parse_remind_datetime("em 3 dias para pagar o aluguel", base)
        assert dt is not None
        assert dt.date() == (base + timedelta(days=3)).date()

    def test_em_x_semanas(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        base = _utcnow()
        dt, _ = _parse_remind_datetime("em 2 semanas às 10h", base)
        assert dt is not None
        assert dt.date() == (base + timedelta(weeks=2)).date()

    def test_recorrencia_daily(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, rec = _parse_remind_datetime("Todo dia às 8h me lembra de tomar o remédio")
        assert rec == "daily"
        assert dt is not None

    def test_recorrencia_weekly(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        _, rec = _parse_remind_datetime("Toda semana às 10h")
        assert rec == "weekly"

    def test_recorrencia_monthly(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        _, rec = _parse_remind_datetime("Todo mês às 9h")
        assert rec == "monthly"

    def test_hora_com_minutos(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, _ = _parse_remind_datetime("amanhã às 14:30")
        assert dt is not None
        assert dt.hour == 14
        assert dt.minute == 30

    def test_hora_formato_simples(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, _ = _parse_remind_datetime("amanhã às 7h")
        assert dt is not None
        assert dt.hour == 7
        assert dt.minute == 0

    def test_sem_data_retorna_none(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, rec = _parse_remind_datetime("Me lembra de comprar leite")
        assert dt is None

    def test_hora_clamped(self):
        from agents.specialized.reminder_agent import _parse_remind_datetime

        dt, _ = _parse_remind_datetime("amanhã às 25h")
        assert dt is not None
        assert dt.hour <= 23


# ─── _extract_message ─────────────────────────────────────────────────────────


class TestExtractMessage:
    def test_apos_para(self):
        from agents.specialized.reminder_agent import _extract_message

        msg = _extract_message("Me lembra sexta às 10h para ligar pro médico")
        assert "médico" in msg.lower() or "ligar" in msg.lower()

    def test_strips_command(self):
        from agents.specialized.reminder_agent import _extract_message

        msg = _extract_message("Me lembra de tomar o remédio")
        assert "remédio" in msg.lower()
        assert "me lembra" not in msg.lower()

    def test_apos_dois_pontos(self):
        from agents.specialized.reminder_agent import _extract_message

        msg = _extract_message("Lembrete: reunião com o João")
        assert "reunião" in msg.lower() or "joão" in msg.lower()

    def test_fallback(self):
        from agents.specialized.reminder_agent import _extract_message

        msg = _extract_message("pagar o aluguel")
        assert len(msg) >= 3


# ─── _extract_id ─────────────────────────────────────────────────────────────


class TestExtractId:
    def test_extrai_id(self):
        assert _agent()._extract_id("Cancela o lembrete abc12345") == "abc12345"

    def test_extrai_id_maiusculo(self):
        assert _agent()._extract_id("Cancela ABC12345") == "abc12345"

    def test_sem_id(self):
        assert _agent()._extract_id("Cancela todos os lembretes") is None


# ─── ReminderAgent.execute ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestReminderAgentCreate:
    async def test_create_success(self):
        a = _agent()
        s = _svc()
        s.create_reminder = AsyncMock(return_value=_make_reminder())
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Me lembra amanhã às 9h para ligar ao médico", _ctx())
        assert r.status.value == "success"
        assert "criado" in r.response.lower()
        s.create_reminder.assert_called_once()

    async def test_create_has_short_id_in_response(self):
        a = _agent()
        s = _svc()
        s.create_reminder = AsyncMock(return_value=_make_reminder())
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Me lembra amanhã às 9h para reunião", _ctx())
        assert "abc12345" in r.response

    async def test_create_recurrence_daily(self):
        a = _agent()
        s = _svc()
        s.create_reminder = AsyncMock(return_value=_make_reminder(recurrence="daily"))
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Todo dia às 8h me lembra de tomar o remédio", _ctx())
        assert r.status.value == "success"
        assert "todo dia" in r.response.lower() or "🔁" in r.response

    async def test_create_no_date_error(self):
        a = _agent()
        s = _svc()
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Me lembra de comprar leite", _ctx())
        assert r.status.value == "error"

    async def test_create_context_override(self):
        a = _agent()
        s = _svc()
        s.create_reminder = AsyncMock(return_value=_make_reminder())
        ctx = _ctx()
        ctx["action"] = "create"
        ctx["remind_at"] = _utcnow() + timedelta(hours=3)
        ctx["message"] = "Reunião importante"
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("", ctx)
        assert r.status.value == "success"

    async def test_create_returns_data(self):
        a = _agent()
        s = _svc()
        reminder = _make_reminder()
        s.create_reminder = AsyncMock(return_value=reminder)
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Me lembra amanhã às 9h para reunião", _ctx())
        assert r.data is not None
        assert r.data["id"] == reminder["id"]

    async def test_fallback_with_date_creates(self):
        """Prompt sem palavras-chave mas com data → tenta criar."""
        a = _agent()
        s = _svc()
        s.create_reminder = AsyncMock(return_value=_make_reminder())
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("amanhã às 9h dentista", _ctx())
        assert r.status.value == "success"

    async def test_fallback_no_date_error(self):
        a = _agent()
        s = _svc()
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("olá tudo bem?", _ctx())
        assert r.status.value == "error"


@pytest.mark.asyncio
class TestReminderAgentList:
    async def test_list_with_reminders(self):
        a = _agent()
        s = _svc()
        s.list_reminders = AsyncMock(
            return_value=[
                _make_reminder(),
                _make_reminder("def67890-0000-0000-0000-000000000000"),
            ]
        )
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Meus lembretes", _ctx())
        assert r.status.value == "success"
        assert r.data["reminders"] is not None
        assert len(r.data["reminders"]) == 2

    async def test_list_empty(self):
        a = _agent()
        s = _svc()
        s.list_reminders = AsyncMock(return_value=[])
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Meus lembretes", _ctx())
        assert r.status.value == "success"
        assert "não" in r.response.lower() or "sem" in r.response.lower()

    async def test_list_recurrence_shows_icon(self):
        a = _agent()
        s = _svc()
        s.list_reminders = AsyncMock(return_value=[_make_reminder(recurrence="daily")])
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Listar lembretes", _ctx())
        assert "🔁" in r.response


@pytest.mark.asyncio
class TestReminderAgentCancel:
    async def test_cancel_by_id_success(self):
        a = _agent()
        s = _svc()
        s.cancel_reminder = AsyncMock(return_value=True)
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Cancela o lembrete abc12345", _ctx())
        assert r.status.value == "success"
        assert "cancelado" in r.response.lower()
        assert r.data["cancelled"] is True

    async def test_cancel_by_id_not_found(self):
        a = _agent()
        s = _svc()
        s.cancel_reminder = AsyncMock(return_value=False)
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Cancela o lembrete abc12345", _ctx())
        assert r.status.value == "error"
        assert "não encontrado" in r.response.lower()

    async def test_cancel_without_id_asks(self):
        a = _agent()
        s = _svc()
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Cancela o lembrete", _ctx())
        assert r.status.value == "error"

    async def test_cancel_all_success(self):
        a = _agent()
        s = _svc()
        s.list_reminders = AsyncMock(
            return_value=[
                _make_reminder(),
                _make_reminder("def67890-0000-0000-0000-000000000000"),
            ]
        )
        s.cancel_reminder = AsyncMock(return_value=True)
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Cancela todos os lembretes", _ctx())
        assert r.status.value == "success"
        assert r.data["cancelled_count"] == 2

    async def test_cancel_all_empty(self):
        a = _agent()
        s = _svc()
        s.list_reminders = AsyncMock(return_value=[])
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Cancela todos os lembretes", _ctx())
        assert r.status.value == "success"
        assert r.data["cancelled_count"] == 0


@pytest.mark.asyncio
class TestReminderAgentErrors:
    async def test_no_user_id(self):
        a = _agent()
        s = _svc()
        with patch("agents.specialized.reminder_agent.get_service", return_value=s):
            r = await a.execute("Meus lembretes", {"user_id": "", "chat_id": ""})
        assert r.status.value == "error"

    async def test_service_unavailable(self):
        a = _agent()
        with patch("agents.specialized.reminder_agent.get_service", return_value=None):
            r = await a.execute("Meus lembretes", _ctx())
        assert r.status.value == "error"
        assert "disponível" in r.response.lower()


# ─── ReminderService._fetch_due retry ────────────────────────────────────────


class TestFetchDueRetry:
    """Tests for Supabase retry logic in check_and_fire_due."""

    def _make_svc(self):
        import logging

        from services.business.reminder_service import ReminderService

        svc = ReminderService.__new__(ReminderService)
        svc.name = "reminder"
        svc.logger = logging.getLogger("test.reminder")
        svc._initialized = True
        svc._db = MagicMock()
        svc._redis = None
        return svc

    @pytest.mark.asyncio
    async def test_fetch_due_success_first_try(self):
        """Normal path — Supabase responds on first call."""
        svc = self._make_svc()
        mock_response = MagicMock()
        mock_response.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.lte.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = mock_response

        svc._db.get_client.return_value.table.return_value = mock_query

        result = await svc.check_and_fire_due()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_due_retry_succeeds(self):
        """First call fails, retry succeeds."""
        svc = self._make_svc()
        mock_response = MagicMock()
        mock_response.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.lte.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.side_effect = [
            Exception("502 Bad Gateway"),
            mock_response,
        ]

        svc._db.get_client.return_value.table.return_value = mock_query

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await svc.check_and_fire_due()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_due_both_fail_returns_empty(self):
        """Both attempts fail — returns [] gracefully."""
        svc = self._make_svc()

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.lte.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.side_effect = Exception("503")

        svc._db.get_client.return_value.table.return_value = mock_query

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await svc.check_and_fire_due()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_due_retry_logs_warning_then_error(self):
        """Logs warning on first fail, error on second."""
        import logging

        svc = self._make_svc()
        svc.logger = MagicMock(spec=logging.Logger)

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.lte.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.side_effect = Exception("503")

        svc._db.get_client.return_value.table.return_value = mock_query

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.check_and_fire_due()

        svc.logger.warning.assert_called_once()
        assert "retrying" in str(svc.logger.warning.call_args).lower()
        svc.logger.error.assert_called_once()
        assert "retry failed" in str(svc.logger.error.call_args).lower()


class TestReminderAgentCapabilities:
    def test_get_capabilities(self):
        from agents.specialized.reminder_agent import ReminderAgent

        a = ReminderAgent.__new__(ReminderAgent)
        caps = a.get_capabilities()
        assert "create_reminder" in caps
        assert "cancel_reminder" in caps
        assert "list_reminders" in caps
        assert "recurring_reminders" in caps
