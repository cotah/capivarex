# -*- coding: utf-8 -*-
"""
Tests para ReminderService e ReminderAgent.

Cobre:
  - CRUD: create, cancel, list, check_and_fire_due
  - Recorrência: daily, weekly, monthly → próxima data calculada corretamente
  - Segurança: user_id isolamento
  - Validação: mensagem vazia, data no passado, recorrência inválida
  - Agent intents: create, list, cancel, cancel_all
  - Parser: data/hora de prompts em PT-BR
  - Edge cases: sem data, serviço indisponível, lembrete já disparado
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _future(hours: float = 2.0) -> datetime:
    return _utcnow() + timedelta(hours=hours)


def _make_reminder(
    rid: Optional[str] = None,
    user_id: str = "user-aaa",
    chat_id: str = "chat-111",
    message: str = "Ligar pro médico",
    hours_ahead: float = 24.0,
    recurrence: Optional[str] = None,
    fired: bool = False,
    cancelled: bool = False,
) -> Dict[str, Any]:
    remind_at = (_utcnow() + timedelta(hours=hours_ahead)).isoformat()
    return {
        "id": rid or str(uuid.uuid4()),
        "user_id": user_id,
        "chat_id": chat_id,
        "message": message,
        "remind_at": remind_at,
        "recurrence": recurrence,
        "fired": fired,
        "cancelled": cancelled,
        "created_at": _utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE: DatabaseService mockado em memória
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_db():
    _store: List[Dict] = []
    db = MagicMock()
    db.is_initialized.return_value = True

    client = MagicMock()
    db.get_client.return_value = client

    def table(name):
        t = MagicMock()

        def insert(payload):
            r = MagicMock()
            row = {
                **payload,
                "id": str(uuid.uuid4()),
                "created_at": _utcnow().isoformat(),
                "updated_at": _utcnow().isoformat(),
            }
            _store.append(row)
            r.execute.return_value = MagicMock(data=[row])
            return r

        def select(*args):
            q = MagicMock()
            q._filters = {}
            q._lte = {}
            q._limit_val = 50
            q._order_field = None
            q._order_desc = False

            def eq(f, v):
                q._filters[f] = v
                return q

            def lte(f, v):
                q._lte[f] = v
                return q

            def order(f, desc=False):
                q._order_field = f
                q._order_desc = desc
                return q

            def limit(n):
                q._limit_val = n
                return q

            def execute():
                res = list(_store)
                for f, v in q._filters.items():
                    res = [r for r in res if r.get(f) == v]
                for f, v in q._lte.items():
                    res = [r for r in res if r.get(f, "9999") <= v]
                if q._order_field:
                    res = sorted(res, key=lambda r: r.get(q._order_field, ""),
                                 reverse=q._order_desc)
                res = res[:q._limit_val]
                return MagicMock(data=res)

            q.eq = eq
            q.lte = lte
            q.order = order
            q.limit = limit
            q.execute = execute
            return q

        def update(payload):
            u = MagicMock()
            u._filters = {}
            u._payload = payload

            def eq(f, v):
                u._filters[f] = v
                return u

            def execute():
                updated = []
                for i, row in enumerate(_store):
                    if all(row.get(f) == v for f, v in u._filters.items()):
                        _store[i] = {**row, **u._payload}
                        updated.append(_store[i])
                return MagicMock(data=updated)

            u.eq = eq
            u.execute = execute
            return u

        t.insert = insert
        t.select = select
        t.update = update
        t._store = _store
        return t

    client.table = table
    db._store = _store
    return db


@pytest.fixture
def reminder_service(mock_db):
    from services.business.reminder_service import ReminderService
    svc = ReminderService()
    svc._db = mock_db
    svc._redis = None
    svc._initialized = True
    return svc


@pytest.fixture
def reminder_agent():
    from agents.specialized.reminder_agent import ReminderAgent
    return ReminderAgent()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. REMINDER SERVICE — create
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminderServiceCreate:

    @pytest.mark.asyncio
    async def test_create_basic(self, reminder_service):
        r = await reminder_service.create_reminder(
            "u1", "c1", "Ligar pro médico", _future(24)
        )
        assert r["id"]
        assert r["message"] == "Ligar pro médico"
        assert r["user_id"] == "u1"
        assert r["fired"] is False
        assert r["cancelled"] is False

    @pytest.mark.asyncio
    async def test_create_with_recurrence(self, reminder_service):
        r = await reminder_service.create_reminder(
            "u1", "c1", "Tomar remédio", _future(1), recurrence="daily"
        )
        assert r["recurrence"] == "daily"

    @pytest.mark.asyncio
    async def test_create_empty_message_raises(self, reminder_service):
        with pytest.raises(ValueError, match="vazia"):
            await reminder_service.create_reminder("u1", "c1", "", _future(1))

    @pytest.mark.asyncio
    async def test_create_past_datetime_raises(self, reminder_service):
        past = _utcnow() - timedelta(hours=1)
        with pytest.raises(ValueError, match="futura"):
            await reminder_service.create_reminder("u1", "c1", "Teste", past)

    @pytest.mark.asyncio
    async def test_create_invalid_recurrence_raises(self, reminder_service):
        with pytest.raises(ValueError, match="Recorrência"):
            await reminder_service.create_reminder(
                "u1", "c1", "Teste", _future(1), recurrence="hourly"
            )

    @pytest.mark.asyncio
    async def test_create_message_too_long_raises(self, reminder_service):
        with pytest.raises(ValueError, match="longa"):
            await reminder_service.create_reminder(
                "u1", "c1", "x" * 501, _future(1)
            )

    @pytest.mark.asyncio
    async def test_create_naive_datetime_gets_utc(self, reminder_service):
        naive = datetime.now() + timedelta(hours=5)
        r = await reminder_service.create_reminder("u1", "c1", "Teste", naive)
        assert "+00:00" in r["remind_at"] or "Z" in r["remind_at"] or r["remind_at"].endswith("+00:00")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. REMINDER SERVICE — cancel & list
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminderServiceCancelList:

    @pytest.mark.asyncio
    async def test_cancel_success(self, reminder_service):
        r = await reminder_service.create_reminder("u1", "c1", "Teste", _future(1))
        result = await reminder_service.cancel_reminder("u1", r["id"])
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, reminder_service):
        result = await reminder_service.cancel_reminder("u1", str(uuid.uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_wrong_user(self, reminder_service):
        r = await reminder_service.create_reminder("u1", "c1", "Teste", _future(1))
        result = await reminder_service.cancel_reminder("u2", r["id"])
        assert result is False

    @pytest.mark.asyncio
    async def test_list_returns_only_own(self, reminder_service):
        await reminder_service.create_reminder("u1", "c1", "A", _future(1))
        await reminder_service.create_reminder("u1", "c1", "B", _future(2))
        await reminder_service.create_reminder("u2", "c2", "C", _future(1))

        u1 = await reminder_service.list_reminders("u1")
        u2 = await reminder_service.list_reminders("u2")
        assert len(u1) == 2
        assert len(u2) == 1

    @pytest.mark.asyncio
    async def test_list_excludes_cancelled(self, reminder_service):
        r = await reminder_service.create_reminder("u1", "c1", "Cancelar", _future(1))
        await reminder_service.cancel_reminder("u1", r["id"])

        active = await reminder_service.list_reminders("u1")
        assert all(not x["cancelled"] for x in active)

    @pytest.mark.asyncio
    async def test_list_excludes_fired(self, reminder_service):
        await reminder_service.create_reminder("u1", "c1", "Normal", _future(2))
        reminders = await reminder_service.list_reminders("u1")
        assert all(not x["fired"] for x in reminders)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REMINDER SERVICE — check_and_fire_due
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminderServiceFire:

    @pytest.mark.asyncio
    async def test_fires_due_reminder(self, reminder_service, mock_db):
        """Lembrete vencido deve ser disparado."""
        past = (_utcnow() - timedelta(minutes=1)).isoformat()
        row = {
            "id": str(uuid.uuid4()),
            "user_id": "u1",
            "chat_id": "c1",
            "message": "Vencido",
            "remind_at": past,
            "recurrence": None,
            "fired": False,
            "cancelled": False,
        }
        mock_db._store.append(row)

        fired = []
        async def capture(r): fired.append(r)

        result = await reminder_service.check_and_fire_due(notify_fn=capture)
        assert len(result) == 1
        assert len(fired) == 1
        assert fired[0]["message"] == "Vencido"

    @pytest.mark.asyncio
    async def test_marks_fired_true(self, reminder_service, mock_db):
        past = (_utcnow() - timedelta(minutes=1)).isoformat()
        row = {
            "id": str(uuid.uuid4()),
            "user_id": "u1",
            "chat_id": "c1",
            "message": "Marcar",
            "remind_at": past,
            "recurrence": None,
            "fired": False,
            "cancelled": False,
        }
        mock_db._store.append(row)

        await reminder_service.check_and_fire_due()

        updated = next(r for r in mock_db._store if r["id"] == row["id"])
        assert updated["fired"] is True

    @pytest.mark.asyncio
    async def test_does_not_fire_future(self, reminder_service):
        await reminder_service.create_reminder("u1", "c1", "Futuro", _future(1))
        result = await reminder_service.check_and_fire_due()
        assert result == []

    @pytest.mark.asyncio
    async def test_recurrence_creates_next(self, reminder_service, mock_db):
        """Lembrete daily disparado deve criar próxima entrada (+1 dia)."""
        past = (_utcnow() - timedelta(minutes=1)).isoformat()
        row = {
            "id": str(uuid.uuid4()),
            "user_id": "u1",
            "chat_id": "c1",
            "message": "Remédio",
            "remind_at": past,
            "recurrence": "daily",
            "fired": False,
            "cancelled": False,
        }
        mock_db._store.append(row)
        initial_count = len(mock_db._store)

        await reminder_service.check_and_fire_due()

        # Deve ter criado mais 1 entry (próximo dia)
        assert len(mock_db._store) > initial_count
        new_entry = [
            r for r in mock_db._store
            if r.get("recurrence") == "daily"
            and r.get("fired") is False
            and r["id"] != row["id"]
        ]
        assert len(new_entry) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RECORRÊNCIA — próxima data
# ═══════════════════════════════════════════════════════════════════════════════

class TestNextOccurrence:

    def test_daily(self):
        from services.business.reminder_service import _next_occurrence
        base = datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc)
        nxt = _next_occurrence(base, "daily")
        assert nxt == datetime(2026, 2, 22, 10, 0, tzinfo=timezone.utc)

    def test_weekly(self):
        from services.business.reminder_service import _next_occurrence
        base = datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc)
        nxt = _next_occurrence(base, "weekly")
        assert nxt == datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc)

    def test_monthly(self):
        from services.business.reminder_service import _next_occurrence
        base = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
        nxt = _next_occurrence(base, "monthly")
        assert nxt.month == 2
        assert nxt.day == 15

    def test_monthly_last_day_feb(self):
        from services.business.reminder_service import _next_occurrence
        base = datetime(2026, 1, 31, 10, 0, tzinfo=timezone.utc)
        nxt = _next_occurrence(base, "monthly")
        assert nxt.month == 2
        assert nxt.day in (28, 29)  # fevereiro não tem 31

    def test_none_recurrence(self):
        from services.business.reminder_service import _next_occurrence
        base = datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc)
        assert _next_occurrence(base, None) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PARSER — _parse_remind_datetime
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminderParser:

    _base = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)  # sábado

    def _parse(self, text):
        from agents.specialized.reminder_agent import _parse_remind_datetime
        return _parse_remind_datetime(text, base=self._base)

    def test_amanha_hora(self):
        dt, rec = self._parse("amanhã às 9h")
        assert dt is not None
        assert dt.hour == 9
        assert dt.day == 22
        assert rec is None

    def test_sexta(self):
        dt, rec = self._parse("sexta às 10h")
        assert dt is not None
        assert dt.hour == 10
        assert dt.weekday() == 4  # sexta

    def test_em_3_dias(self):
        dt, rec = self._parse("em 3 dias para pagar o aluguel")
        assert dt is not None
        assert dt.day == 24  # 21 + 3

    def test_todo_dia_recurrence(self):
        dt, rec = self._parse("todo dia às 8h me lembra de tomar remédio")
        assert dt is not None
        assert dt.hour == 8
        assert rec == "daily"

    def test_toda_semana(self):
        dt, rec = self._parse("toda semana às 15h reunião de time")
        assert rec == "weekly"

    def test_todo_mes(self):
        dt, rec = self._parse("todo mês às 10h pagar aluguel")
        assert rec == "monthly"

    def test_no_date_returns_none(self):
        dt, rec = self._parse("lembrete sem data")
        assert dt is None

    def test_only_time(self):
        dt, rec = self._parse("às 20h")
        assert dt is not None
        assert dt.hour == 20


# ═══════════════════════════════════════════════════════════════════════════════
# 6. REMINDER AGENT — intents
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminderAgent:

    @pytest.fixture
    def mock_svc(self):
        from services.business.reminder_service import ReminderService
        svc = AsyncMock(spec=ReminderService)
        svc.is_initialized.return_value = True

        reminder = _make_reminder(rid="abc12345-" + "0" * 27)

        svc.create_reminder = AsyncMock(return_value=reminder)
        svc.cancel_reminder = AsyncMock(return_value=True)
        svc.list_reminders = AsyncMock(return_value=[reminder])
        svc.format_remind_at = MagicMock(return_value="22/02/2026 às 10:00")
        svc.format_recurrence = MagicMock(return_value="uma vez")
        return svc, reminder

    @pytest.mark.asyncio
    async def test_create_reminder(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute(
                "Me lembra sexta às 10h para ligar pro médico",
                {"user_id": "u1", "chat_id": "c1"},
            )
        assert r.is_success()
        svc.create_reminder.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_daily_reminder(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        svc.format_recurrence.return_value = "todo dia"
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute(
                "Todo dia às 8h me lembra de tomar o remédio",
                {"user_id": "u1", "chat_id": "c1"},
            )
        assert r.is_success()
        call_kwargs = svc.create_reminder.call_args
        assert call_kwargs.kwargs.get("recurrence") == "daily" or \
               (len(call_kwargs.args) > 4 and call_kwargs.args[4] == "daily")

    @pytest.mark.asyncio
    async def test_list_reminders(self, reminder_agent, mock_svc):
        svc, reminder = mock_svc
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute(
                "Meus lembretes", {"user_id": "u1"}
            )
        assert r.is_success()
        svc.list_reminders.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_list_empty(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        svc.list_reminders.return_value = []
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute("Meus lembretes", {"user_id": "u1"})
        assert r.is_success()
        assert "não tem" in r.response.lower() or "ativos" in r.response.lower()

    @pytest.mark.asyncio
    async def test_cancel_by_id(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute(
                "Cancela o lembrete abc12345", {"user_id": "u1"}
            )
        assert r.is_success()
        svc.cancel_reminder.assert_called_once_with("u1", "abc12345")

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        svc.cancel_reminder.return_value = False
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute("Cancela abc12345", {"user_id": "u1"})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_cancel_all(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute(
                "Cancela todos os lembretes", {"user_id": "u1"}
            )
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_no_user_id_error(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute("Me lembra amanhã às 9h", {})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_no_date_returns_help(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute(
                "Me lembra algo", {"user_id": "u1"}
            )
        assert not r.is_success()
        assert "sexta" in r.response.lower() or "amanhã" in r.response.lower()

    @pytest.mark.asyncio
    async def test_service_unavailable(self, reminder_agent):
        with patch("agents.specialized.reminder_agent.get_service", return_value=None):
            r = await reminder_agent.execute(
                "Me lembra amanhã às 9h: reunião",
                {"user_id": "u1"},
            )
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_context_override_remind_at(self, reminder_agent, mock_svc):
        svc, _ = mock_svc
        future = _future(48).isoformat()
        with patch("agents.specialized.reminder_agent.get_service", return_value=svc):
            r = await reminder_agent.execute(
                "Me lembra",
                {
                    "user_id": "u1",
                    "chat_id": "c1",
                    "action": "create",
                    "message": "Pagar contas",
                    "remind_at": future,
                },
            )
        assert r.is_success()
        svc.create_reminder.assert_called_once()

    def test_capabilities(self, reminder_agent):
        caps = reminder_agent.get_capabilities()
        assert "create_reminder" in caps
        assert "recurring_reminders" in caps
        assert "cancel_reminder" in caps
