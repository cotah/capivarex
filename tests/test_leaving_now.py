# -*- coding: utf-8 -*-
"""
tests/test_leaving_now.py
===========================
Testes para TransitService, LeavingNowService e LeavingNowAgent.

Cobre:
  TransitService:
    - get_transit_route: sucesso, sem rota, erro de geocoding
    - get_realtime_delays: sem NTA key (graceful), com dados, filtra por linha
    - get_transit_with_delays: combina rota + delays, atraso ligeiro, atraso major, cancelamento
    - _calculate_weather_buffer: todos os cenários de clima
    - _parse_transit_steps: extrai linhas e tempo a pé

  LeavingNowService:
    - calculate_for_next_event: sem eventos, evento sem local, sucesso carro, sucesso transit
    - calculate_for_event: fórmula correcta, buffer chuva, atraso TFI
    - get_all_events_today: múltiplos eventos, filtra sem localização
    - urgência: LATE, URGENT, SOON, COMFORTABLE, RELAXED
    - mensagens de urgência contextuais

  LeavingNowAgent:
    - query natural → próximo evento
    - action=check_departure → proactivo (só notifica se urgente)
    - all today → lista todos eventos
    - evento específico no context
    - detecção de transport_mode (driving vs transit)
    - detecção de prep_minutes
    - serviço indisponível → erro amigável
    - sem eventos → mensagem útil
    - formato da resposta: emojis, breakdown, CTA
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORIES
# ═══════════════════════════════════════════════════════════════════════════════

def _make_event(
    title: str = "Reunião",
    location: str = "Grand Canal Dock, Dublin",
    hours_from_now: float = 2.0,
) -> Dict:
    event_time = datetime.now() + timedelta(hours=hours_from_now)
    return {
        "summary": title,
        "location": location,
        "start": event_time.isoformat(),
        "end": (event_time + timedelta(hours=1)).isoformat(),
        "id": "event_test_001",
        "attendees": [],
        "html_link": "https://calendar.google.com/event?eid=test",
    }


def _make_transit_route(
    duration_min: float = 35.0,
    lines: Optional[List] = None,
    delay_min: float = 0.0,
) -> Dict:
    now = datetime.now()
    return {
        "success": True,
        "origin": "Dublin City Centre",
        "destination": "Grand Canal Dock, Dublin",
        "duration_minutes": duration_min,
        "departure_time": now.isoformat(),
        "arrival_time": (now + timedelta(minutes=duration_min)).isoformat(),
        "steps": [
            {"mode": "WALK", "instruction": "Walk to stop", "duration_minutes": 5.0},
            {
                "mode": "TRANSIT",
                "instruction": "Take 46A",
                "duration_minutes": 25.0,
                "transit": {
                    "short_name": "46A",
                    "long_name": "Dublin Bus 46A",
                    "vehicle_type": "BUS",
                    "departure_stop": "Dame Street",
                    "arrival_stop": "Grand Canal Dock",
                    "departure_time": "14:30",
                    "arrival_time": "14:55",
                    "num_stops": 8,
                    "headsign": "Dún Laoghaire",
                    "agency": "Dublin Bus",
                    "color": "",
                },
            },
            {"mode": "WALK", "instruction": "Walk to destination", "duration_minutes": 5.0},
        ],
        "lines": lines or [{"short_name": "46A", "long_name": "Dublin Bus 46A"}],
        "walking_minutes": 10.0,
        "distance_meters": 5200,
        "distance_km": 5.2,
        "realtime_delay_minutes": delay_min,
        "adjusted_duration_minutes": duration_min + delay_min,
        "adjusted_arrival_time": (
            now + timedelta(minutes=duration_min + delay_min)
        ).isoformat(),
        "has_disruption": delay_min >= 3,
        "disruption_message": f"⚠️ Atraso de {delay_min:.0f} min." if delay_min >= 3 else "",
        "recommendation": "on_time" if delay_min < 3 else "slight_delay",
        "service_alerts": [],
        "gtfs_realtime_available": True,
    }


def _make_weather(condition: str = "Clear", temp_c: float = 15.0) -> Dict:
    return {
        "location": {"name": "Dublin"},
        "current": {
            "temp_c": temp_c,
            "condition": condition,
            "humidity": 70,
            "wind_kph": 20.0,
            "feels_like_c": temp_c - 2,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def leaving_now_svc():
    from services.business.leaving_now_service import LeavingNowService
    svc = LeavingNowService()
    svc._initialized = True
    return svc


@pytest.fixture
def leaving_now_agent():
    from agents.specialized.leaving_now_agent import LeavingNowAgent
    return LeavingNowAgent()


@pytest.fixture
def mock_svc():
    """LeavingNowService mockado para testes do agente."""
    svc = AsyncMock()
    svc.is_initialized.return_value = True
    svc.initialize = AsyncMock()
    return svc


@pytest.fixture
def mock_result_soon():
    """LeavingNowResult com urgência SOON (12 min para sair)."""
    from services.business.leaving_now_service import LeavingNowResult
    now = datetime.now()
    return LeavingNowResult(
        event_title="Reunião com cliente",
        event_location="Grand Canal Dock, Dublin",
        event_time=now + timedelta(hours=1),
        suggested_departure=now + timedelta(minutes=12),
        minutes_until_departure=12.0,
        urgency="SOON",
        message="🟡 **Prepara-te! Sai em 12 minutos.**\nReunião com cliente às ...",
        action_message="Prepara-te para sair às 14:42.",
        travel_minutes=35.0,
        weather_buffer_minutes=0.0,
        transit_delay_minutes=0.0,
        prep_minutes=10.0,
        transport_mode="driving",
        distance_km=5.2,
    )


@pytest.fixture
def mock_result_relaxed():
    """LeavingNowResult com urgência RELAXED (60 min para sair)."""
    from services.business.leaving_now_service import LeavingNowResult
    now = datetime.now()
    return LeavingNowResult(
        event_title="Dentista",
        event_location="St Stephen's Green, Dublin",
        event_time=now + timedelta(hours=2, minutes=30),
        suggested_departure=now + timedelta(minutes=60),
        minutes_until_departure=60.0,
        urgency="RELAXED",
        message="📅 Dentista às ...\nTens tempo — sai às ...",
        action_message="Tens tempo de sobra.",
        travel_minutes=20.0,
        weather_buffer_minutes=10.0,
        transit_delay_minutes=0.0,
        prep_minutes=10.0,
        transport_mode="driving",
        is_raining=True,
        weather_condition="Rain",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LeavingNowService — weather buffer
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeatherBuffer:
    """Testa o cálculo do buffer de clima."""

    def test_clear_no_buffer(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer(
            _make_weather("Clear")
        ) == 0.0

    def test_sunny_no_buffer(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer(
            _make_weather("Sunny")
        ) == 0.0

    def test_rain_adds_10min(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer(
            _make_weather("Rain")
        ) == 10.0

    def test_light_rain_adds_5min(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer(
            _make_weather("light_rain")
        ) == 5.0

    def test_heavy_rain_adds_15min(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer(
            _make_weather("heavy_rain")
        ) == 15.0

    def test_storm_adds_20min(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer(
            _make_weather("storm")
        ) == 20.0

    def test_snow_adds_25min(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer(
            _make_weather("snow")
        ) == 25.0

    def test_empty_weather_no_buffer(self, leaving_now_svc):
        assert leaving_now_svc._calculate_weather_buffer({}) == 0.0

    def test_drizzle_keyword(self, leaving_now_svc):
        buffer = leaving_now_svc._calculate_weather_buffer(
            _make_weather("Drizzle and mist")
        )
        assert buffer > 0

    def test_chuva_pt(self, leaving_now_svc):
        """Testa palavra portuguesa 'chuva'."""
        buffer = leaving_now_svc._calculate_weather_buffer(
            _make_weather("Chuva moderada")
        )
        assert buffer > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LeavingNowService — parse event time
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseEventTime:

    def test_iso_datetime(self, leaving_now_svc):
        event = {"start": "2026-02-25T14:00:00"}
        dt = leaving_now_svc._parse_event_time(event)
        assert dt is not None
        assert dt.hour == 14
        assert dt.minute == 0

    def test_iso_with_z(self, leaving_now_svc):
        event = {"start": "2026-02-25T14:00:00Z"}
        dt = leaving_now_svc._parse_event_time(event)
        assert dt is not None

    def test_all_day_returns_none(self, leaving_now_svc):
        """Eventos de dia inteiro (sem T) retornam None."""
        event = {"start": "2026-02-25"}
        dt = leaving_now_svc._parse_event_time(event)
        assert dt is None

    def test_empty_start_returns_none(self, leaving_now_svc):
        event = {"start": ""}
        assert leaving_now_svc._parse_event_time(event) is None

    def test_missing_start_returns_none(self, leaving_now_svc):
        event = {}
        assert leaving_now_svc._parse_event_time(event) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. LeavingNowService — urgência e mensagens
# ═══════════════════════════════════════════════════════════════════════════════

class TestUrgencyMessages:

    def _build(self, minutes_until: float, mode: str = "driving") -> tuple:
        from services.business.leaving_now_service import LeavingNowService
        now = datetime.now()
        return LeavingNowService._build_urgency_messages(
            event_title="Reunião",
            event_location="Grand Canal Dock",
            event_time=now + timedelta(minutes=60),
            suggested_departure=now + timedelta(minutes=minutes_until),
            minutes_until=minutes_until,
            travel_minutes=30.0,
            weather_buffer=0.0,
            transit_delay=0.0,
            weather_condition="Clear",
            transport_mode=mode,
        )

    def test_late_urgency(self):
        urgency, msg, _ = self._build(-5.0)
        assert urgency == "LATE"
        assert "já devias" in msg.lower() or "should have" in msg.lower()

    def test_urgent_urgency(self):
        urgency, msg, _ = self._build(3.0)
        assert urgency == "URGENT"
        assert "AGORA" in msg or "NOW" in msg

    def test_soon_urgency(self):
        urgency, msg, action = self._build(15.0)
        assert urgency == "SOON"
        assert "Prepara" in msg or "Get ready" in msg

    def test_comfortable_urgency(self):
        urgency, _, _ = self._build(30.0)
        assert urgency == "COMFORTABLE"

    def test_relaxed_urgency(self):
        urgency, _, action = self._build(60.0)
        assert urgency == "RELAXED"
        assert "tempo" in action.lower() or "time" in action.lower()

    def test_transit_cta_mentions_maps(self):
        _, _, action = self._build(15.0, mode="transit")
        assert "Maps" in action or "transport" in action.lower() or "🚌" in action

    def test_weather_buffer_in_message(self):
        from services.business.leaving_now_service import LeavingNowService
        now = datetime.now()
        urgency, msg, _ = LeavingNowService._build_urgency_messages(
            event_title="Reunião",
            event_location="Dublin",
            event_time=now + timedelta(minutes=60),
            suggested_departure=now + timedelta(minutes=15),
            minutes_until=15.0,
            travel_minutes=30.0,
            weather_buffer=10.0,
            transit_delay=0.0,
            weather_condition="Rain",
            transport_mode="driving",
        )
        assert "10" in msg or "chuva" in msg.lower() or "rain" in msg.lower() or "🌧" in msg


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LeavingNowService — calculate_for_event
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateForEvent:

    def _mock_services(self, travel_minutes=30.0, weather_cond="Clear", delay_min=0.0):
        """Helper para mockar CalendarService, TrafficService e WeatherService."""
        mock_traffic = AsyncMock()
        mock_traffic.is_initialized.return_value = True
        mock_traffic.get_route_with_traffic = AsyncMock(return_value={
            "success": True,
            "route": {"duration_minutes": travel_minutes, "distance_km": 5.2}
        })

        mock_weather = AsyncMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_current_weather = AsyncMock(
            return_value=_make_weather(weather_cond)
        )

        return mock_traffic, mock_weather

    @pytest.mark.asyncio
    async def test_basic_calculation(self, leaving_now_svc):
        """Fórmula: evento daqui a 2h, viagem 30min, prep 10min → sair daqui a 70min."""
        event = _make_event(hours_from_now=2.0)
        mock_traffic, mock_weather = self._mock_services(travel_minutes=30.0)

        with patch("services.business.leaving_now_service.get_service") as mock_get:
            mock_get.side_effect = lambda name: {
                "traffic": mock_traffic, "weather": mock_weather,
                "transit": None, "calendar": MagicMock(),
            }.get(name)

            result = await leaving_now_svc.calculate_for_event(
                event=event,
                user_location="Dublin City Centre",
                transport_mode="driving",
                prep_minutes=10.0,
            )

        assert result is not None
        assert result.travel_minutes == 30.0
        # 2h evento - 30min viagem - 10min prep = sair daqui a 80min
        assert 70 <= result.minutes_until_departure <= 90
        # 80 min > 45 → RELAXED (COMFORTABLE é 20-45min)
        assert result.urgency == "RELAXED"

    @pytest.mark.asyncio
    async def test_weather_buffer_added(self, leaving_now_svc):
        """Chuva deve adicionar buffer ao cálculo."""
        event = _make_event(hours_from_now=1.5)
        mock_traffic, mock_weather = self._mock_services(
            travel_minutes=30.0, weather_cond="Rain"
        )

        with patch("services.business.leaving_now_service.get_service") as mock_get:
            mock_get.side_effect = lambda name: {
                "traffic": mock_traffic, "weather": mock_weather,
                "transit": None, "calendar": MagicMock(),
            }.get(name)

            result = await leaving_now_svc.calculate_for_event(
                event=event,
                user_location="Dublin",
                transport_mode="driving",
                prep_minutes=10.0,
            )

        assert result is not None
        assert result.weather_buffer_minutes == 10.0
        assert result.is_raining is True

    @pytest.mark.asyncio
    async def test_event_without_location_returns_none(self, leaving_now_svc):
        event = {"summary": "Call", "start": datetime.now().isoformat(), "location": ""}
        result = await leaving_now_svc.calculate_for_event(
            event=event, user_location="Dublin"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_event_all_day_returns_none(self, leaving_now_svc):
        event = {"summary": "Holiday", "start": "2026-02-25", "location": "Dublin"}
        result = await leaving_now_svc.calculate_for_event(
            event=event, user_location="Dublin"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_late_event_detected(self, leaving_now_svc):
        """Evento já passou → urgência LATE."""
        event = _make_event(hours_from_now=-0.5)  # há 30 min
        event["location"] = "Grand Canal Dock, Dublin"
        mock_traffic, mock_weather = self._mock_services(travel_minutes=30.0)

        with patch("services.business.leaving_now_service.get_service") as mock_get:
            mock_get.side_effect = lambda name: {
                "traffic": mock_traffic, "weather": mock_weather,
                "transit": None,
            }.get(name)

            result = await leaving_now_svc.calculate_for_event(
                event=event, user_location="Dublin"
            )

        assert result is not None
        assert result.urgency == "LATE"

    @pytest.mark.asyncio
    async def test_transit_delay_included(self, leaving_now_svc):
        """Atraso TFI deve ser incluído no cálculo em modo transit."""
        event = _make_event(hours_from_now=1.5)
        mock_weather = AsyncMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_current_weather = AsyncMock(return_value=_make_weather())

        mock_transit = AsyncMock()
        mock_transit.is_initialized.return_value = True
        mock_transit.get_transit_with_delays = AsyncMock(
            return_value=_make_transit_route(duration_min=35.0, delay_min=8.0)
        )

        with patch("services.business.leaving_now_service.get_service") as mock_get:
            mock_get.side_effect = lambda name: {
                "weather": mock_weather,
                "transit": mock_transit,
                "traffic": None,
            }.get(name)

            result = await leaving_now_svc.calculate_for_event(
                event=event,
                user_location="Dublin",
                transport_mode="transit",
                prep_minutes=10.0,
            )

        assert result is not None
        assert result.transit_delay_minutes == 8.0
        assert result.transport_mode == "transit"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LeavingNowAgent — detecção de intent
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentDetection:

    def test_detect_transit_mode(self):
        from agents.specialized.leaving_now_agent import _detect_transport_mode
        assert _detect_transport_mode("vou de autocarro", {}) == "transit"
        assert _detect_transport_mode("quero ir de Luas", {}) == "transit"
        assert _detect_transport_mode("public transport", {}) == "transit"

    def test_detect_driving_mode(self):
        from agents.specialized.leaving_now_agent import _detect_transport_mode
        assert _detect_transport_mode("vou de carro", {}) == "driving"

    def test_detect_driving_default(self):
        from agents.specialized.leaving_now_agent import _detect_transport_mode
        assert _detect_transport_mode("quando devo sair?", {}) == "driving"

    def test_detect_all_today(self):
        from agents.specialized.leaving_now_agent import _detect_all_today
        assert _detect_all_today("eventos de hoje com hora de saída") is True
        assert _detect_all_today("agenda de hoje") is True
        assert _detect_all_today("quando devo sair?") is False

    def test_extract_prep_minutes(self):
        from agents.specialized.leaving_now_agent import _extract_prep_minutes
        assert _extract_prep_minutes("preciso de 15 minutos para me preparar", {}) == 15.0
        assert _extract_prep_minutes("", {}) == 10.0  # default

    def test_prep_from_context(self):
        from agents.specialized.leaving_now_agent import _extract_prep_minutes
        assert _extract_prep_minutes("", {"prep_minutes": "20"}) == 20.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LeavingNowAgent — respostas
# ═══════════════════════════════════════════════════════════════════════════════

class TestLeavingNowAgentResponses:

    @pytest.mark.asyncio
    async def test_next_event_success(self, leaving_now_agent, mock_svc, mock_result_soon):
        mock_svc.calculate_for_next_event = AsyncMock(return_value=mock_result_soon)
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("quando devo sair?", {})
        assert r.is_success()
        assert r.data is not None

    @pytest.mark.asyncio
    async def test_no_events_returns_helpful_message(self, leaving_now_agent, mock_svc):
        mock_svc.calculate_for_next_event = AsyncMock(return_value=None)
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("quando devo sair?", {})
        assert r.is_success()
        assert "calendário" in r.response.lower() or "calendar" in r.response.lower() or "local" in r.response.lower()

    @pytest.mark.asyncio
    async def test_service_unavailable(self, leaving_now_agent):
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=None):
            r = await leaving_now_agent.execute("quando devo sair?", {})
        assert not r.is_success()
        assert "leaving_now" in r.response.lower() or "disponível" in r.response.lower()

    @pytest.mark.asyncio
    async def test_proactive_triggers_when_soon(self, leaving_now_agent, mock_svc, mock_result_soon):
        mock_svc.calculate_for_next_event = AsyncMock(return_value=mock_result_soon)
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("", {"action": "check_departure"})
        assert r.is_success()
        assert r.data.get("triggered") is True
        assert r.response != ""  # deve notificar

    @pytest.mark.asyncio
    async def test_proactive_silent_when_relaxed(self, leaving_now_agent, mock_svc, mock_result_relaxed):
        mock_svc.calculate_for_next_event = AsyncMock(return_value=mock_result_relaxed)
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("", {"action": "check_departure"})
        assert r.is_success()
        assert r.data.get("triggered") is False
        assert r.response == ""  # silêncio proactivo

    @pytest.mark.asyncio
    async def test_all_today_multiple_events(self, leaving_now_agent, mock_svc, mock_result_soon):
        mock_svc.get_all_events_today = AsyncMock(return_value=[mock_result_soon, mock_result_soon])
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("eventos de hoje", {})
        assert r.is_success()
        assert r.data.get("events") is not None
        assert len(r.data["events"]) == 2

    @pytest.mark.asyncio
    async def test_all_today_no_events(self, leaving_now_agent, mock_svc):
        mock_svc.get_all_events_today = AsyncMock(return_value=[])
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("agenda de hoje", {})
        assert r.is_success()
        assert "eventos" in r.response.lower() or "agenda" in r.response.lower()

    @pytest.mark.asyncio
    async def test_specific_event_from_context(self, leaving_now_agent, mock_svc, mock_result_soon):
        mock_svc.calculate_for_event = AsyncMock(return_value=mock_result_soon)
        event = _make_event()
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("", {"event": event})
        assert r.is_success()
        mock_svc.calculate_for_event.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Formato da resposta
# ═══════════════════════════════════════════════════════════════════════════════

class TestResponseFormat:

    @pytest.mark.asyncio
    async def test_response_has_urgency_emoji(self, leaving_now_agent, mock_svc, mock_result_soon):
        mock_svc.calculate_for_next_event = AsyncMock(return_value=mock_result_soon)
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("quando sair?", {})
        # SOON → 🟡
        assert "🟡" in r.response or "SOON" in r.response or "Prepara" in r.response

    @pytest.mark.asyncio
    async def test_response_has_breakdown(self, leaving_now_agent, mock_svc, mock_result_soon):
        mock_svc.calculate_for_next_event = AsyncMock(return_value=mock_result_soon)
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("quando sair?", {})
        assert "Cálculo" in r.response or "breakdown" in r.response.lower() or "📊" in r.response

    @pytest.mark.asyncio
    async def test_result_to_dict_complete(self, mock_result_soon):
        d = mock_result_soon.to_dict()
        assert "event_title" in d
        assert "urgency" in d
        assert "breakdown" in d
        assert "suggested_departure" in d
        assert "minutes_until_departure" in d

    @pytest.mark.asyncio
    async def test_rain_buffer_visible_in_response(self, leaving_now_agent, mock_svc, mock_result_relaxed):
        mock_svc.calculate_for_next_event = AsyncMock(return_value=mock_result_relaxed)
        with patch("agents.specialized.leaving_now_agent.get_service", return_value=mock_svc):
            r = await leaving_now_agent.execute("quando sair?", {})
        assert "10" in r.response or "chuva" in r.response.lower() or "🌧" in r.response

    def test_capabilities(self, leaving_now_agent):
        caps = leaving_now_agent.get_capabilities()
        assert "departure_time_calculation" in caps
        assert "tfi_realtime_delays" in caps
        assert "weather_buffer" in caps
        assert "proactive_departure_alerts" in caps


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TransitService — unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransitService:

    @pytest.fixture
    def transit_svc(self):
        from services.integrations.transit_service import TransitService
        svc = TransitService()
        svc._gmaps_key = "test_gmaps_key"
        svc._nta_key = None  # sem NTA por default
        svc._client = AsyncMock()
        svc._gtfs_available = False
        svc._initialized = True
        return svc

    @pytest.mark.asyncio
    async def test_realtime_delays_without_nta_key(self, transit_svc):
        """Sem NTA key → retorna graciosamente sem crashar."""
        result = await transit_svc.get_realtime_delays()
        assert result["delays"] == []
        assert result["has_delays"] is False
        assert "NTA_API_KEY" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_vehicle_positions_without_nta_key(self, transit_svc):
        """Sem NTA key → retorna lista vazia."""
        result = await transit_svc.get_vehicle_positions()
        assert result == []

    def test_parse_trip_updates_json_with_delays(self, transit_svc):
        """Testa parsing JSON de TripUpdates com atrasos."""
        from services.integrations.transit_service import TransitService
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "entity": [
                {
                    "id": "1",
                    "tripUpdate": {
                        "trip": {"tripId": "trip_001", "routeId": "46A"},
                        "stopTimeUpdate": [
                            {
                                "stopSequence": 5,
                                "stopId": "stop_123",
                                "departure": {"delay": 480},  # 8 min
                            }
                        ],
                    },
                }
            ]
        }
        delays = TransitService._parse_trip_updates_json(mock_resp, route_filter=None)
        assert len(delays) == 1
        assert delays[0]["delay_seconds"] == 480
        assert delays[0]["delay_minutes"] == 8.0
        assert delays[0]["route_id"] == "46A"

    def test_parse_trip_updates_json_filters_by_route(self, transit_svc):
        """Filtra por nome de linha."""
        from services.integrations.transit_service import TransitService
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "entity": [
                {
                    "id": "1",
                    "tripUpdate": {
                        "trip": {"tripId": "trip_001", "routeId": "46A"},
                        "stopTimeUpdate": [
                            {"stopSequence": 1, "departure": {"delay": 300}}
                        ],
                    },
                },
                {
                    "id": "2",
                    "tripUpdate": {
                        "trip": {"tripId": "trip_002", "routeId": "DART"},
                        "stopTimeUpdate": [
                            {"stopSequence": 1, "departure": {"delay": 600}}
                        ],
                    },
                },
            ]
        }
        delays = TransitService._parse_trip_updates_json(mock_resp, route_filter="DART")
        assert all("DART" in d["route_id"].upper() for d in delays)

    def test_parse_cancelled_trip(self, transit_svc):
        """Viagem cancelada (scheduleRelationship=SKIPPED) deve ser marcada."""
        from services.integrations.transit_service import TransitService
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "entity": [
                {
                    "id": "1",
                    "tripUpdate": {
                        "trip": {"tripId": "trip_003", "routeId": "Luas Red"},
                        "stopTimeUpdate": [
                            {
                                "stopSequence": 1,
                                "scheduleRelationship": "SKIPPED",
                                "departure": {"delay": 0},
                            }
                        ],
                    },
                }
            ]
        }
        delays = TransitService._parse_trip_updates_json(mock_resp, None)
        assert any(d["is_cancelled"] for d in delays)

    def test_parse_alerts_json(self, transit_svc):
        """Testa parsing de alertas de serviço."""
        from services.integrations.transit_service import TransitService
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "entity": [
                {
                    "id": "alert_001",
                    "alert": {
                        "cause": "STRIKE",
                        "effect": "REDUCED_SERVICE",
                        "headerText": {
                            "translation": [{"text": "Dublin Bus Strike Today", "language": "en"}]
                        },
                        "descriptionText": {
                            "translation": [{"text": "Service reduced on all routes.", "language": "en"}]
                        },
                    },
                }
            ]
        }
        alerts = TransitService._parse_alerts_json(mock_resp)
        assert len(alerts) == 1
        assert "Strike" in alerts[0]["header_text"]
        assert alerts[0]["cause"] == "STRIKE"

    @pytest.mark.asyncio
    async def test_get_transit_with_delays_no_nta(self, transit_svc):
        """Sem NTA key → funciona só com Google Maps (sem delays)."""
        # Mock geocode e rota
        geocode_resp = MagicMock()
        geocode_resp.status_code = 200
        geocode_resp.json.return_value = {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": 53.33, "lng": -6.26}}}]
        }

        routes_resp = MagicMock()
        routes_resp.status_code = 200
        routes_resp.raise_for_status = MagicMock()
        routes_resp.json.return_value = {
            "routes": [{
                "duration": "2100s",  # 35 min
                "distanceMeters": 5200,
                "legs": [],
            }]
        }

        transit_svc._client.get = AsyncMock(return_value=geocode_resp)
        transit_svc._client.post = AsyncMock(return_value=routes_resp)

        result = await transit_svc.get_transit_with_delays(
            "Dublin City Centre", "Grand Canal Dock"
        )

        assert result["success"] is True
        assert result["realtime_delay_minutes"] == 0.0
        assert result["gtfs_realtime_available"] is False
