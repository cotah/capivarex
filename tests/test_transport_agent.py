# -*- coding: utf-8 -*-
"""
tests/test_transport_agent.py
==============================
Testes unitários para TransportAgent.

Cobre:
- Routing correcto pelo orchestrator (transport keyword detection)
- GPS fallback: usa last_latitude/last_longitude do Supabase
- Pedido de localização quando GPS não disponível
- Resposta com linhas/horários quando GPS disponível
- Extracção de destino do prompt
- Detecção de keywords transit
- Formatação da resposta (linhas, paragens, tempo)
- Serviço indisponível → erro amigável
- Sem resultados → mensagem útil
- get_capabilities retorna capacidades correctas
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORIES
# ═══════════════════════════════════════════════════════════════════════════════


def _make_transit_data(
    duration: float = 25.0,
    delay: float = 0.0,
    line: str = "46A",
) -> Dict[str, Any]:
    """Simula retorno do get_transit_with_delays do TransitService."""
    return {
        "success": True,
        "duration_minutes": duration,
        "realtime_delay_minutes": delay,
        "lines": [{"short_name": line, "long_name": f"Dublin Bus {line}"}],
        "steps": [
            {"mode": "WALK", "duration_minutes": 3.0},
            {
                "mode": "TRANSIT",
                "duration_minutes": duration - 6,
                "transit": {
                    "short_name": line,
                    "long_name": f"Dublin Bus {line}",
                    "departure_stop": "Rathmines Road",
                    "arrival_stop": "O'Connell St",
                    "departure_time": "09:32",
                    "arrival_time": "09:57",
                    "num_stops": 12,
                    "headsign": "City Centre",
                },
            },
            {"mode": "WALK", "duration_minutes": 3.0},
        ],
        "service_alerts": [],
        "has_disruption": delay >= 3,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def agent():
    from agents.specialized.transport_agent import TransportAgent

    return TransportAgent()


@pytest.fixture
def mock_transit_svc():
    svc = MagicMock()
    svc.is_initialized.return_value = True
    svc.get_transit_with_delays = AsyncMock(return_value=_make_transit_data())
    return svc


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Keyword detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestKeywordDetection:
    """Testa detecção de queries de transporte."""

    def test_onibus_br(self):
        from agents.specialized.transport_agent import _is_transport_query

        assert _is_transport_query("próximo ônibus para o centro") is True

    def test_onibus_sem_acento(self):
        from agents.specialized.transport_agent import _is_transport_query

        assert _is_transport_query("proximo onibus para o centro") is True

    def test_autocarro_pt(self):
        from agents.specialized.transport_agent import _is_transport_query

        assert _is_transport_query("próximo autocarro agora") is True

    def test_dart(self):
        from agents.specialized.transport_agent import _is_transport_query

        assert _is_transport_query("horários do DART") is True

    def test_luas(self):
        from agents.specialized.transport_agent import _is_transport_query

        assert _is_transport_query("luas para o centro") is True

    def test_next_bus_english(self):
        from agents.specialized.transport_agent import _is_transport_query

        assert _is_transport_query("next bus to city centre") is True

    def test_non_transport_query(self):
        from agents.specialized.transport_agent import _is_transport_query

        assert _is_transport_query("qual o tempo hoje?") is False
        assert _is_transport_query("marca um lembrete") is False

    def test_alert_keywords(self):
        from agents.specialized.transport_agent import _wants_alerts

        assert _wants_alerts("há atrasos no DART?") is True
        assert _wants_alerts("próximo ônibus") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Extracção de destino
# ═══════════════════════════════════════════════════════════════════════════════


class TestDestinationExtraction:
    def test_para_o_centro(self):
        from agents.specialized.transport_agent import _extract_destination

        dest = _extract_destination("próximo ônibus para o centro")
        assert dest is not None
        assert "centro" in dest.lower()

    def test_para_dublin_city(self):
        from agents.specialized.transport_agent import _extract_destination

        dest = _extract_destination("autocarro para Dublin City Centre")
        assert dest is not None
        assert "dublin" in dest.lower()

    def test_to_english(self):
        from agents.specialized.transport_agent import _extract_destination

        dest = _extract_destination("next bus to the airport")
        assert dest is not None
        assert "airport" in dest.lower()

    def test_no_destination(self):
        from agents.specialized.transport_agent import _extract_destination

        dest = _extract_destination("próximo ônibus agora")
        # Pode retornar None ou string vazia — ambos aceitáveis
        assert dest is None or len(dest) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GPS ausente — pede localização
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoGPS:
    @pytest.mark.asyncio
    async def test_asks_for_location_when_no_gps(self, agent):
        """Sem GPS no context e sem GPS guardado → pede localização."""
        with patch(
            "services.business.user_preferences_service.get_location",
            new=AsyncMock(return_value=None),
        ):
            r = await agent.execute("próximo ônibus para o centro", {})

        assert r.is_success()
        assert r.data.get("needs_location") is True
        assert "localização" in r.response.lower() or "location" in r.response.lower()
        assert "📎" in r.response or "Telegram" in r.response

    @pytest.mark.asyncio
    async def test_asks_for_location_no_user_id(self, agent):
        """Sem user_id no context → não consegue buscar GPS → pede localização."""
        with patch(
            "services.business.user_preferences_service.get_location",
            new=AsyncMock(return_value=None),
        ):
            r = await agent.execute("next bus to city centre", {"user_id": None})

        assert r.data.get("needs_location") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GPS disponível — responde com transportes
# ═══════════════════════════════════════════════════════════════════════════════


class TestWithGPS:
    @pytest.mark.asyncio
    async def test_uses_gps_from_context(self, agent, mock_transit_svc):
        """GPS vem directamente no context → usa sem chamar Supabase."""
        context = {
            "user_id": "test-uuid",
            "latitude": 53.32326,
            "longitude": -6.27183,
        }
        with patch(
            "agents.specialized.transport_agent.get_service",
            return_value=mock_transit_svc,
        ):
            r = await agent.execute("próximo ônibus para o centro", context)

        assert r.is_success()
        assert r.data is not None
        mock_transit_svc.get_transit_with_delays.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_gps_from_supabase(self, agent, mock_transit_svc):
        """GPS não vem no context → busca do Supabase."""
        context = {"user_id": "test-uuid"}

        with (
            patch(
                "services.business.user_preferences_service.get_location",
                new=AsyncMock(return_value=(53.32326, -6.27183)),
            ),
            patch(
                "agents.specialized.transport_agent.get_service",
                return_value=mock_transit_svc,
            ),
        ):
            r = await agent.execute("próximo ônibus", context)

        assert r.is_success()
        mock_transit_svc.get_transit_with_delays.assert_called_once()

    @pytest.mark.asyncio
    async def test_response_contains_line_name(self, agent, mock_transit_svc):
        """Resposta deve conter o nome da linha (46A)."""
        context = {"latitude": 53.32326, "longitude": -6.27183}

        with patch(
            "agents.specialized.transport_agent.get_service",
            return_value=mock_transit_svc,
        ):
            r = await agent.execute("próximo ônibus", context)

        assert "46A" in r.response

    @pytest.mark.asyncio
    async def test_response_contains_departure_stop(self, agent, mock_transit_svc):
        """Resposta deve mencionar a paragem de partida."""
        context = {"latitude": 53.32326, "longitude": -6.27183}

        with patch(
            "agents.specialized.transport_agent.get_service",
            return_value=mock_transit_svc,
        ):
            r = await agent.execute("próximo autocarro", context)

        assert "Rathmines" in r.response or "Partida" in r.response

    @pytest.mark.asyncio
    async def test_response_contains_duration(self, agent, mock_transit_svc):
        """Resposta deve indicar tempo de viagem."""
        context = {"latitude": 53.32326, "longitude": -6.27183}

        with patch(
            "agents.specialized.transport_agent.get_service",
            return_value=mock_transit_svc,
        ):
            r = await agent.execute("próximo ônibus", context)

        assert "25" in r.response or "min" in r.response

    @pytest.mark.asyncio
    async def test_response_with_delay(self, agent):
        """Resposta com atraso deve mencionar o atraso."""
        svc = MagicMock()
        svc.is_initialized.return_value = True
        svc.get_transit_with_delays = AsyncMock(
            return_value=_make_transit_data(delay=8.0)
        )
        context = {"latitude": 53.32326, "longitude": -6.27183}

        with patch("agents.specialized.transport_agent.get_service", return_value=svc):
            r = await agent.execute("próximo ônibus", context)

        assert (
            "8" in r.response
            or "atraso" in r.response.lower()
            or "delay" in r.response.lower()
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Sem resultados
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoResults:
    @pytest.mark.asyncio
    async def test_no_transit_data_returns_helpful_message(self, agent):
        """Quando o serviço não encontra transportes → mensagem útil."""
        svc = MagicMock()
        svc.is_initialized.return_value = True
        svc.get_transit_with_delays = AsyncMock(return_value=None)

        context = {"latitude": 53.32326, "longitude": -6.27183}

        with patch("agents.specialized.transport_agent.get_service", return_value=svc):
            r = await agent.execute("próximo ônibus para o aeroporto", context)

        assert r.is_success()
        assert (
            "não encontrei" in r.response.lower()
            or "no encontrei" in r.response.lower()
            or "not found" in r.response.lower()
            or "paragens" in r.response.lower()
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Serviço indisponível
# ═══════════════════════════════════════════════════════════════════════════════


class TestServiceUnavailable:
    @pytest.mark.asyncio
    async def test_service_none_returns_error(self, agent):
        context = {"latitude": 53.32326, "longitude": -6.27183}

        with patch("agents.specialized.transport_agent.get_service", return_value=None):
            r = await agent.execute("próximo ônibus", context)

        assert not r.is_success()
        assert "disponível" in r.response.lower() or "unavailable" in r.response.lower()

    @pytest.mark.asyncio
    async def test_service_exception_handled(self, agent):
        """Excepção no serviço → erro amigável, sem crash."""
        svc = MagicMock()
        svc.is_initialized.return_value = True
        svc.get_transit_with_delays = AsyncMock(side_effect=Exception("NTA timeout"))

        context = {"latitude": 53.32326, "longitude": -6.27183}

        with patch("agents.specialized.transport_agent.get_service", return_value=svc):
            r = await agent.execute("próximo ônibus", context)

        assert not r.is_success()
        assert r.error is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Capabilities e metadados
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilities:
    def test_agent_name(self, agent):
        assert agent.name == "transport"

    def test_capabilities_list(self, agent):
        caps = agent.get_capabilities()
        assert "next_bus" in caps
        assert "realtime_delays" in caps
        assert "gps_based_search" in caps
        assert "service_alerts" in caps

    def test_description_mentions_transport(self, agent):
        assert (
            "transporte" in agent.description.lower()
            or "transit" in agent.description.lower()
            or "ônibus" in agent.description.lower()
            or "autocarro" in agent.description.lower()
        )
