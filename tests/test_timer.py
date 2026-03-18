# -*- coding: utf-8 -*-
"""
Tests para TimerService e TimerAgent.

Cobre:
  - Timer: create, cancel, list, check_and_fire_due
  - Agent: intents (timer, alarm, remind, list, cancel, cancel_all)
  - Parser: _parse_duration, _parse_clock_time, _extract_label
  - Edge cases: timer não encontrado, duração inválida, máximo 7 dias
  - Segurança: usuário só cancela seus próprios timers
  - Worker: check_timers dispara notificação correta
"""

import time
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_redis():
    """Redis mockado com armazenamento em memória para testes."""
    store: Dict[str, Any] = {}

    redis = AsyncMock()
    redis.is_initialized.return_value = True

    async def fake_get(key, parse_json=True):
        return store.get(key)

    async def fake_set(key, value, expire_seconds=None):
        store[key] = value
        return True

    async def fake_delete(key):
        existed = key in store
        store.pop(key, None)
        return existed

    redis.get = AsyncMock(side_effect=fake_get)
    redis.set = AsyncMock(side_effect=fake_set)
    redis.delete = AsyncMock(side_effect=fake_delete)
    redis._store = store  # acesso direto nos testes
    return redis


@pytest.fixture
def timer_service(mock_redis):
    """TimerService com Redis mockado."""
    from services.business.timer_service import TimerService

    svc = TimerService()
    svc._redis = mock_redis
    svc._initialized = True
    return svc


@pytest.fixture
def timer_agent():
    from agents.specialized.timer_agent import TimerAgent

    return TimerAgent()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TIMER — modelo e helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimerModel:
    def test_is_due_when_expired(self):
        from services.business.timer_service import Timer

        t = Timer("abc", "u1", "c1", "test", fire_at=time.time() - 1)
        assert t.is_due is True

    def test_not_due_when_future(self):
        from services.business.timer_service import Timer

        t = Timer("abc", "u1", "c1", "test", fire_at=time.time() + 60)
        assert t.is_due is False

    def test_seconds_remaining(self):
        from services.business.timer_service import Timer

        t = Timer("abc", "u1", "c1", "test", fire_at=time.time() + 100)
        assert 95 <= t.seconds_remaining <= 105

    def test_format_remaining_seconds(self):
        from services.business.timer_service import Timer

        t = Timer("abc", "u1", "c1", "test", fire_at=time.time() + 45)
        assert "45s" in t.format_remaining() or "s" in t.format_remaining()

    def test_format_remaining_minutes(self):
        from services.business.timer_service import Timer

        # Use +601 to avoid race condition where <1s elapses before format_remaining()
        t = Timer("abc", "u1", "c1", "test", fire_at=time.time() + 601)
        result = t.format_remaining()
        assert "min" in result

    def test_format_remaining_hours(self):
        from services.business.timer_service import Timer

        t = Timer("abc", "u1", "c1", "test", fire_at=time.time() + 7201)
        result = t.format_remaining()
        assert "2h" in result

    def test_to_dict_and_from_dict(self):
        from services.business.timer_service import Timer

        t = Timer(
            "abc12345",
            "u1",
            "c1",
            "Ligar pro João",
            fire_at=time.time() + 300,
            timer_type="remind",
        )
        d = t.to_dict()
        restored = Timer.from_dict(d)
        assert restored.timer_id == t.timer_id
        assert restored.label == t.label
        assert restored.timer_type == t.timer_type
        assert restored.fire_at == pytest.approx(t.fire_at)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TIMER SERVICE
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimerService:
    @pytest.mark.asyncio
    async def test_create_timer_returns_timer(self, timer_service):
        t = await timer_service.create_timer("u1", "c1", 300, "Test", "timer")
        assert t.timer_id
        assert t.user_id == "u1"
        assert t.label == "Test"
        assert not t.is_due

    @pytest.mark.asyncio
    async def test_create_timer_persisted_in_redis(self, timer_service, mock_redis):
        await timer_service.create_timer("u1", "c1", 300)
        # Redis.set deve ter sido chamado
        mock_redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_create_timer_invalid_duration(self, timer_service):
        with pytest.raises(ValueError, match="positivo"):
            await timer_service.create_timer("u1", "c1", -10)

    @pytest.mark.asyncio
    async def test_create_timer_max_7_days(self, timer_service):
        with pytest.raises(ValueError, match="7 dias"):
            await timer_service.create_timer("u1", "c1", 7 * 24 * 3600 + 1)

    @pytest.mark.asyncio
    async def test_list_timers_empty(self, timer_service):
        result = await timer_service.list_timers("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_timers_shows_only_own(self, timer_service):
        await timer_service.create_timer("u1", "c1", 300, "Timer U1")
        await timer_service.create_timer("u2", "c2", 300, "Timer U2")

        u1_timers = await timer_service.list_timers("u1")
        u2_timers = await timer_service.list_timers("u2")

        assert len(u1_timers) == 1
        assert u1_timers[0].label == "Timer U1"
        assert len(u2_timers) == 1
        assert u2_timers[0].label == "Timer U2"

    @pytest.mark.asyncio
    async def test_list_timers_sorted_by_fire_at(self, timer_service):
        await timer_service.create_timer("u1", "c1", 600)  # 10min
        await timer_service.create_timer("u1", "c1", 60)  # 1min
        await timer_service.create_timer("u1", "c1", 3600)  # 1h

        timers = await timer_service.list_timers("u1")
        assert len(timers) == 3
        assert timers[0].fire_at <= timers[1].fire_at <= timers[2].fire_at

    @pytest.mark.asyncio
    async def test_cancel_timer_success(self, timer_service):
        t = await timer_service.create_timer("u1", "c1", 300)
        result = await timer_service.cancel_timer("u1", t.timer_id)
        assert result is True

        remaining = await timer_service.list_timers("u1")
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_cancel_timer_not_found(self, timer_service):
        result = await timer_service.cancel_timer("u1", "nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_timer_security_other_user(self, timer_service):
        """Usuário não pode cancelar timer de outro usuário."""
        t = await timer_service.create_timer("u1", "c1", 300)
        result = await timer_service.cancel_timer("u2", t.timer_id)
        assert result is False

        # Timer de u1 ainda existe
        u1_timers = await timer_service.list_timers("u1")
        assert len(u1_timers) == 1

    @pytest.mark.asyncio
    async def test_cancel_all_timers(self, timer_service):
        await timer_service.create_timer("u1", "c1", 300)
        await timer_service.create_timer("u1", "c1", 600)
        await timer_service.create_timer("u2", "c2", 300)

        count = await timer_service.cancel_all_timers("u1")
        assert count == 2

        # u2 ainda tem o seu
        u2_timers = await timer_service.list_timers("u2")
        assert len(u2_timers) == 1

    @pytest.mark.asyncio
    async def test_check_and_fire_due_fires_expired(self, timer_service):
        """Timers vencidos devem ser disparados e removidos."""
        from services.business.timer_service import TIMERS_KEY

        # Injeta timer já vencido diretamente no Redis mock
        expired = {
            "timer_id": "exp12345",
            "user_id": "u1",
            "chat_id": "c1",
            "label": "Teste",
            "fire_at": time.time() - 5,
            "timer_type": "timer",
            "created_at": time.time() - 10,
        }
        timer_service._redis._store[TIMERS_KEY] = [expired]

        fired = []

        async def capture(t):
            fired.append(t)

        result = await timer_service.check_and_fire_due(notify_fn=capture)
        assert len(result) == 1
        assert result[0].timer_id == "exp12345"
        assert len(fired) == 1

    @pytest.mark.asyncio
    async def test_check_and_fire_does_not_fire_future(self, timer_service):
        """Timers futuros não devem ser disparados."""
        await timer_service.create_timer("u1", "c1", 300)
        fired = await timer_service.check_and_fire_due()
        assert fired == []

    @pytest.mark.asyncio
    async def test_check_and_fire_removes_from_list(self, timer_service):
        """Timer disparado deve ser removido da lista ativa."""
        from services.business.timer_service import TIMERS_KEY

        expired = {
            "timer_id": "rem12345",
            "user_id": "u1",
            "chat_id": "c1",
            "label": "Remover",
            "fire_at": time.time() - 1,
            "timer_type": "timer",
            "created_at": time.time() - 5,
        }
        future = {
            "timer_id": "fut12345",
            "user_id": "u1",
            "chat_id": "c1",
            "label": "Manter",
            "fire_at": time.time() + 300,
            "timer_type": "timer",
            "created_at": time.time(),
        }
        timer_service._redis._store[TIMERS_KEY] = [expired, future]

        await timer_service.check_and_fire_due()
        remaining = await timer_service.list_timers("u1")

        assert len(remaining) == 1
        assert remaining[0].timer_id == "fut12345"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PARSERS
# ═══════════════════════════════════════════════════════════════════════════════


class TestDurationParser:
    def test_minutes(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("marque 10 minutos") == pytest.approx(600)

    def test_seconds(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("timer de 30 segundos") == pytest.approx(30)

    def test_hours(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("2 horas") == pytest.approx(7200)

    def test_hours_and_minutes(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("1h30") == pytest.approx(5400)

    def test_short_form_min(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("5min") == pytest.approx(300)

    def test_short_form_h(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("3h") == pytest.approx(10800)

    def test_no_duration_returns_none(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("como está o tempo?") is None

    def test_short_form_s(self):
        from agents.specialized.timer_agent import _parse_duration

        assert _parse_duration("45s") == pytest.approx(45)


class TestClockParser:
    def test_parse_clock_7h(self):
        from agents.specialized.timer_agent import _parse_clock_time

        result = _parse_clock_time("me acorde às 7h")
        # Deve retornar segundos até as 7h (entre 0 e 86400)
        assert result is not None
        assert 0 < result <= 86400

    def test_parse_clock_1430(self):
        from agents.specialized.timer_agent import _parse_clock_time

        result = _parse_clock_time("às 14:30")
        assert result is not None
        assert 0 < result <= 86400

    def test_invalid_clock_returns_none(self):
        from agents.specialized.timer_agent import _parse_clock_time

        assert _parse_clock_time("sem horário aqui") is None


class TestLabelExtractor:
    def test_extract_label_with_para(self):
        from agents.specialized.timer_agent import _extract_label

        label = _extract_label("me lembra em 30min para ligar pro João")
        assert "João" in label
        assert "ligar" in label

    def test_extract_label_no_para(self):
        from agents.specialized.timer_agent import _extract_label

        label = _extract_label("me lembra em 1 hora")
        assert isinstance(label, str)  # pode ser vazio, não deve crashar


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TIMER AGENT
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimerAgent:
    @pytest.fixture
    def mock_svc(self):
        from services.business.timer_service import Timer, TimerService

        svc = AsyncMock(spec=TimerService)
        svc.is_initialized.return_value = True

        fake_timer = Timer(
            timer_id="abc12345",
            user_id="u1",
            chat_id="c1",
            label="⏱️ Cronômetro",
            fire_at=time.time() + 600,
            timer_type="timer",
        )
        svc.create_timer = AsyncMock(return_value=fake_timer)
        svc.cancel_timer = AsyncMock(return_value=True)
        svc.cancel_all_timers = AsyncMock(return_value=2)
        svc.list_timers = AsyncMock(return_value=[fake_timer])
        return svc, fake_timer

    @pytest.mark.asyncio
    async def test_create_timer_10_minutes(self, timer_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute(
                "Marque 10 minutos", {"user_id": "u1", "chat_id": "c1"}
            )
        assert r.is_success()
        assert "Timer" in r.response or "iniciado" in r.response
        svc.create_timer.assert_called_once()
        call_kwargs = svc.create_timer.call_args
        duration = call_kwargs.kwargs.get("duration_seconds") or call_kwargs.args[2]
        assert duration == pytest.approx(600)

    @pytest.mark.asyncio
    async def test_create_alarm(self, timer_agent, mock_svc):
        svc, fake_timer = mock_svc
        fake_timer.timer_type = "alarm"
        svc.create_timer.return_value = fake_timer
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute(
                "Me acorde às 7h", {"user_id": "u1", "chat_id": "c1"}
            )
        assert r.is_success()
        assert "Alarme" in r.response or "alarm" in r.response.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_with_label(self, timer_agent, mock_svc):
        svc, fake_timer = mock_svc
        fake_timer.timer_type = "remind"
        fake_timer.label = "ligar pro João"
        svc.create_timer.return_value = fake_timer
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute(
                "Me lembra em 30min para ligar pro João",
                {"user_id": "u1", "chat_id": "c1"},
            )
        assert r.is_success()
        assert "Lembrete" in r.response or "lembrar" in r.response.lower()

    @pytest.mark.asyncio
    async def test_list_timers(self, timer_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute(
                "Quais timers tenho ativos?", {"user_id": "u1"}
            )
        assert r.is_success()
        assert "abc12345" in r.response
        svc.list_timers.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_list_timers_empty(self, timer_agent, mock_svc):
        svc, _ = mock_svc
        svc.list_timers.return_value = []
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute("lista meus timers", {"user_id": "u1"})
        assert r.is_success()
        assert "nenhum" in r.response.lower()

    @pytest.mark.asyncio
    async def test_cancel_by_id(self, timer_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute("Cancela o timer abc12345", {"user_id": "u1"})
        assert r.is_success()
        svc.cancel_timer.assert_called_once_with("u1", "abc12345")

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, timer_agent, mock_svc):
        svc, _ = mock_svc
        svc.cancel_timer.return_value = False
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute("Cancela abc12345", {"user_id": "u1"})
        assert not r.is_success()
        assert "não encontrado" in r.response.lower()

    @pytest.mark.asyncio
    async def test_cancel_all(self, timer_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute("Cancela todos os timers", {"user_id": "u1"})
        assert r.is_success()
        assert "2" in r.response
        svc.cancel_all_timers.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_unknown_intent_returns_help(self, timer_agent, mock_svc):
        svc, _ = mock_svc
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute("blablabla", {"user_id": "u1"})
        assert not r.is_success()
        assert "minutos" in r.response.lower() or "7h" in r.response

    @pytest.mark.asyncio
    async def test_service_unavailable(self, timer_agent):
        with patch("agents.specialized.timer_agent.get_service", return_value=None):
            r = await timer_agent.execute("marque 10 minutos", {"user_id": "u1"})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_context_duration_fallback(self, timer_agent, mock_svc):
        """Context com duration_seconds deve funcionar sem texto de duração."""
        svc, _ = mock_svc
        with patch("agents.specialized.timer_agent.get_service", return_value=svc):
            r = await timer_agent.execute(
                "timer", {"user_id": "u1", "chat_id": "c1", "duration_seconds": 120}
            )
        assert r.is_success()

    def test_capabilities(self, timer_agent):
        caps = timer_agent.get_capabilities()
        assert "create_timer" in caps
        assert "create_alarm" in caps
        assert "cancel_timer" in caps
