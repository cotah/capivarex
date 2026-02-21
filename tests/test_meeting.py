# -*- coding: utf-8 -*-
"""
tests/test_meeting.py
======================
Testes para MeetingAgent e helpers de parsing.

Cobre:
  - Extração de emails do prompt
  - Extração de duração (minutos/horas)
  - Extração de título
  - Extração de data/hora (hoje, amanhã, dias da semana, DD/MM, horários)
  - Agent: criação via prompt natural
  - Agent: criação via context (action=create_meeting)
  - Agent: resposta contém Meet link
  - Agent: CalendarService indisponível
  - Agent: CalendarService retorna None → erro amigável
  - Agent: sem email → cria sem participantes
  - Agent: duração default 60min quando não especificada
  - Agent: formato da resposta (emoji, data, link)
  - Agent: capabilities
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def meeting_agent():
    from agents.specialized.meeting_agent import MeetingAgent
    return MeetingAgent()


@pytest.fixture
def mock_cal_svc():
    """CalendarService mockado que retorna dados de reunião com Meet link."""
    svc = MagicMock()
    svc.is_initialized.return_value = True
    svc.initialize = AsyncMock()
    svc.create_meeting = MagicMock(return_value={
        "id": "event_abc123",
        "summary": "Reunião com João",
        "html_link": "https://calendar.google.com/event?eid=abc123",
        "meet_link": "https://meet.google.com/abc-defg-hij",
        "start": "2026-02-25T10:00:00+00:00",
        "end": "2026-02-25T11:00:00+00:00",
        "attendees": ["joao@email.com"],
        "status": "created",
    })
    return svc


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Helpers de extração
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpers:

    def test_extract_emails_single(self):
        from agents.specialized.meeting_agent import _extract_emails
        emails = _extract_emails("Convida joao@email.com para reunião")
        assert "joao@email.com" in emails

    def test_extract_emails_multiple(self):
        from agents.specialized.meeting_agent import _extract_emails
        emails = _extract_emails("com ana@x.com e pedro@y.com")
        assert len(emails) == 2
        assert "ana@x.com" in emails
        assert "pedro@y.com" in emails

    def test_extract_emails_none(self):
        from agents.specialized.meeting_agent import _extract_emails
        assert _extract_emails("reunião sem email") == []

    def test_extract_duration_minutes(self):
        from agents.specialized.meeting_agent import _extract_duration_minutes
        assert _extract_duration_minutes("30 minutos") == 30
        assert _extract_duration_minutes("1 hora") == 60
        assert _extract_duration_minutes("2 horas") == 120
        assert _extract_duration_minutes("45min") == 45
        assert _extract_duration_minutes("2h") == 120

    def test_extract_duration_default(self):
        from agents.specialized.meeting_agent import _extract_duration_minutes
        assert _extract_duration_minutes("reunião amanhã às 10h") == 60

    def test_extract_title_basic(self):
        from agents.specialized.meeting_agent import _extract_title
        title = _extract_title("Cria uma reunião Daily Standup amanhã às 9h")
        assert title is not None
        assert "Daily Standup" in title

    def test_extract_title_with_email_removed(self):
        from agents.specialized.meeting_agent import _extract_title
        title = _extract_title("Agenda meet Revisão com ana@x.com sexta 15h")
        assert title is not None
        assert "ana@x.com" not in (title or "")

    def test_extract_title_fallback_none(self):
        from agents.specialized.meeting_agent import _extract_title
        # Prompt muito genérico sem título identificável
        result = _extract_title("cria reunião")
        # Pode retornar None ou string vazia — ambos são aceitáveis
        assert result is None or len(result.strip()) <= 2

    def test_extract_datetime_amanha(self):
        from agents.specialized.meeting_agent import _extract_datetime
        dt = _extract_datetime("reunião amanhã às 10h")
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        assert dt.day == tomorrow.day
        assert dt.hour == 10

    def test_extract_datetime_hoje(self):
        from agents.specialized.meeting_agent import _extract_datetime
        dt = _extract_datetime("call hoje às 14h30")
        now = datetime.now(timezone.utc)
        assert dt.day == now.day
        assert dt.hour == 14
        assert dt.minute == 30

    def test_extract_datetime_sexta(self):
        from agents.specialized.meeting_agent import _extract_datetime
        dt = _extract_datetime("reunião na sexta às 15h")
        assert dt.weekday() == 4  # sexta = 4

    def test_extract_datetime_explicit_date(self):
        from agents.specialized.meeting_agent import _extract_datetime
        dt = _extract_datetime("25/02 às 16h")
        assert dt.day == 25
        assert dt.month == 2
        assert dt.hour == 16

    def test_extract_datetime_explicit_date_full(self):
        from agents.specialized.meeting_agent import _extract_datetime
        dt = _extract_datetime("reunião em 25/02/2026 às 9h")
        assert dt.day == 25
        assert dt.month == 2
        assert dt.year == 2026
        assert dt.hour == 9


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MeetingAgent — criação via prompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestMeetingAgentCreate:

    @pytest.mark.asyncio
    async def test_create_meeting_basic(self, meeting_agent, mock_cal_svc):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria uma reunião com joao@email.com amanhã às 10h", {}
            )
        assert r.is_success()
        mock_cal_svc.create_meeting.assert_called_once()
        # Verifica que o email foi detectado
        call_kwargs = mock_cal_svc.create_meeting.call_args.kwargs
        assert "joao@email.com" in call_kwargs.get("attendees", [])

    @pytest.mark.asyncio
    async def test_create_meeting_meet_link_in_response(self, meeting_agent, mock_cal_svc):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Agenda meet com ana@x.com sexta às 15h", {}
            )
        assert r.is_success()
        assert "meet.google.com" in r.response

    @pytest.mark.asyncio
    async def test_create_meeting_no_email(self, meeting_agent, mock_cal_svc):
        """Deve criar reunião mesmo sem participantes especificados."""
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião Daily Standup amanhã às 9h", {}
            )
        assert r.is_success()
        call_kwargs = mock_cal_svc.create_meeting.call_args.kwargs
        assert call_kwargs.get("attendees", []) == []

    @pytest.mark.asyncio
    async def test_create_meeting_duration_30min(self, meeting_agent, mock_cal_svc):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            await meeting_agent.execute(
                "Cria meet de 30 minutos com equipe hoje às 14h", {}
            )
        call_kwargs = mock_cal_svc.create_meeting.call_args.kwargs
        start = call_kwargs["start_time"]
        end = call_kwargs["end_time"]
        delta = (end - start).total_seconds() / 60
        assert delta == 30

    @pytest.mark.asyncio
    async def test_create_meeting_default_duration_60min(self, meeting_agent, mock_cal_svc):
        """Sem duração especificada → 60 minutos."""
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            await meeting_agent.execute(
                "Cria reunião com joao@email.com amanhã às 10h", {}
            )
        call_kwargs = mock_cal_svc.create_meeting.call_args.kwargs
        start = call_kwargs["start_time"]
        end = call_kwargs["end_time"]
        delta = (end - start).total_seconds() / 60
        assert delta == 60

    @pytest.mark.asyncio
    async def test_create_meeting_multiple_attendees(self, meeting_agent, mock_cal_svc):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            await meeting_agent.execute(
                "Nova reunião com ana@x.com e pedro@y.com na sexta às 15h", {}
            )
        call_kwargs = mock_cal_svc.create_meeting.call_args.kwargs
        attendees = call_kwargs.get("attendees", [])
        assert "ana@x.com" in attendees
        assert "pedro@y.com" in attendees

    @pytest.mark.asyncio
    async def test_create_meeting_context_override(self, meeting_agent, mock_cal_svc):
        """Context com action=create_meeting usa dados estruturados."""
        context = {
            "action": "create_meeting",
            "title": "Sprint Review",
            "start_datetime": "2026-02-25T14:00:00+00:00",
            "duration_minutes": 90,
            "attendees": ["dev@company.com"],
            "description": "Revisão da sprint 12",
        }
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute("", context)
        assert r.is_success()
        call_kwargs = mock_cal_svc.create_meeting.call_args.kwargs
        assert call_kwargs["summary"] == "Sprint Review"
        assert call_kwargs["attendees"] == ["dev@company.com"]
        # 90 minutos
        delta = (call_kwargs["end_time"] - call_kwargs["start_time"]).total_seconds() / 60
        assert delta == 90


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MeetingAgent — erros
# ═══════════════════════════════════════════════════════════════════════════════

class TestMeetingAgentErrors:

    @pytest.mark.asyncio
    async def test_service_unavailable(self, meeting_agent):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=None):
            r = await meeting_agent.execute(
                "Cria reunião amanhã às 10h", {}
            )
        assert not r.is_success()
        assert "calendário" in r.response.lower() or "calendar" in r.response.lower()

    @pytest.mark.asyncio
    async def test_create_meeting_returns_none(self, meeting_agent, mock_cal_svc):
        """CalendarService retorna None → erro amigável."""
        mock_cal_svc.create_meeting.return_value = None
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião amanhã às 10h", {}
            )
        assert not r.is_success()
        assert "não foi possível" in r.response.lower()

    @pytest.mark.asyncio
    async def test_context_missing_start_datetime(self, meeting_agent, mock_cal_svc):
        """Context com action mas sem start_datetime → erro claro."""
        context = {
            "action": "create_meeting",
            "title": "Reunião sem data",
        }
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute("", context)
        assert not r.is_success()
        assert "data" in r.response.lower() or "hora" in r.response.lower()

    @pytest.mark.asyncio
    async def test_calendar_service_exception(self, meeting_agent, mock_cal_svc):
        """Exceção no CalendarService → resposta de erro sem crash."""
        mock_cal_svc.create_meeting.side_effect = RuntimeError("Google API error")
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião amanhã às 10h", {}
            )
        assert not r.is_success()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Formato da resposta
# ═══════════════════════════════════════════════════════════════════════════════

class TestMeetingAgentResponse:

    @pytest.mark.asyncio
    async def test_response_has_emoji_check(self, meeting_agent, mock_cal_svc):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião com joao@email.com amanhã às 10h", {}
            )
        assert "✅" in r.response

    @pytest.mark.asyncio
    async def test_response_has_meet_link(self, meeting_agent, mock_cal_svc):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião amanhã às 10h", {}
            )
        assert "meet.google.com" in r.response

    @pytest.mark.asyncio
    async def test_response_has_calendar_link(self, meeting_agent, mock_cal_svc):
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião amanhã às 10h", {}
            )
        assert "calendar.google.com" in r.response

    @pytest.mark.asyncio
    async def test_response_data_has_meet_link(self, meeting_agent, mock_cal_svc):
        """O campo data do AgentResponse deve ter o meet_link."""
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião amanhã às 10h", {}
            )
        assert r.data is not None
        assert "meet_link" in r.data
        assert "meet.google.com" in r.data["meet_link"]

    @pytest.mark.asyncio
    async def test_response_no_meet_link_still_succeeds(self, meeting_agent, mock_cal_svc):
        """Se por algum motivo o Meet link não vier, ainda retorna sucesso."""
        mock_cal_svc.create_meeting.return_value = {
            "id": "event_xyz",
            "summary": "Reunião",
            "html_link": "https://calendar.google.com/event?eid=xyz",
            "meet_link": "",  # sem link
            "start": "2026-02-25T10:00:00+00:00",
            "end": "2026-02-25T11:00:00+00:00",
            "attendees": [],
            "status": "created",
        }
        with patch("agents.specialized.meeting_agent.get_service",
                   return_value=mock_cal_svc):
            r = await meeting_agent.execute(
                "Cria reunião amanhã às 10h", {}
            )
        assert r.is_success()

    def test_capabilities(self, meeting_agent):
        caps = meeting_agent.get_capabilities()
        assert "create_meeting" in caps
        assert "google_meet_link" in caps
        assert "invite_attendees" in caps
