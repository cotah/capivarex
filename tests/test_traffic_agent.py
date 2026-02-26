"""
Tests for TrafficAgent — refactored architecture.

The refactored TrafficAgent uses ``get_service("traffic")`` to obtain the
traffic service wrapper.  Tests mock ``_get_traffic_service`` to inject
a controlled service mock directly.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from agents.core import AgentStatus
from agents.specialized.traffic_agent import TrafficAgent


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_requires_origin_destination():
    """Test execute asks for locations when missing."""
    agent = TrafficAgent()

    result = await agent.execute("Como está o trânsito?", {})

    assert result.status == AgentStatus.ERROR
    assert result.data.get("needs_location") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_success(mock_traffic_service):
    """Test execute returns formatted success payload."""
    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=mock_traffic_service)

    result = await agent.execute("trafego", {"origin": "Dublin", "destination": "Cork"})

    assert result.is_success()
    assert result.response == "Resumo de tráfego"
    assert "route_data" in result.data
    assert "traffic_data" in result.data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_route_failure(mock_traffic_service):
    """Test execute handles route lookup failure."""
    mock_traffic_service.get_route_with_traffic = AsyncMock(
        return_value={"success": False, "error": "unavailable"}
    )
    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=mock_traffic_service)

    result = await agent.execute("trafego", {"origin": "Dublin", "destination": "Cork"})

    assert result.status == AgentStatus.ERROR
    assert result.error is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_traffic_for_event_success(mock_traffic_service):
    """Test check_traffic_for_event success response."""
    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=mock_traffic_service)

    result = await agent.check_traffic_for_event(
        event_location="Cork",
        user_location="Dublin",
        event_time=datetime(2026, 2, 15, 15, 0, 0),
    )

    assert result.is_success()
    assert result.data["urgency"] == "BREVE"
    assert "Tempo de viagem" in result.response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_traffic_for_event_failure(mock_traffic_service):
    """Test check_traffic_for_event failure response."""
    mock_traffic_service.check_traffic_before_event = AsyncMock(
        return_value={"success": False, "error": "no route"}
    )
    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=mock_traffic_service)

    result = await agent.check_traffic_for_event(
        event_location="Cork",
        user_location="Dublin",
        event_time=datetime(2026, 2, 15, 15, 0, 0),
    )

    assert result.status == AgentStatus.ERROR
    assert (
        "não foi possível" in result.response.lower()
        or "nao foi possivel" in result.response.lower()
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_exception_path():
    """Test execute handles unexpected exception path."""

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    mock_svc = Mock()
    mock_svc.get_route_with_traffic = _boom

    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=mock_svc)

    result = await agent.execute("trafego", {"origin": "Dublin", "destination": "Cork"})

    assert result.status == AgentStatus.ERROR
    assert "erro" in result.response.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_traffic_for_event_exception_path():
    """Test check_traffic_for_event handles unexpected exception."""

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    mock_svc = Mock()
    mock_svc.check_traffic_before_event = _boom

    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=mock_svc)

    result = await agent.check_traffic_for_event(
        event_location="Cork",
        user_location="Dublin",
        event_time=datetime(2026, 2, 15, 15, 0, 0),
    )

    assert result.status == AgentStatus.ERROR
    assert (
        "erro ao verificar tráfego" in result.response.lower()
        or "erro ao verificar trafego" in result.response.lower()
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_service_unavailable():
    """Test execute returns error when traffic service is None."""
    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=None)

    result = await agent.execute("trafego", {"origin": "Dublin", "destination": "Cork"})

    assert result.status == AgentStatus.ERROR
    assert (
        "unavailable" in result.response.lower()
        or "disponível" in result.response.lower()
        or "disponivel" in result.response.lower()
    )


# -------------------------------------------------------------------
# Location extraction tests
# -------------------------------------------------------------------


@pytest.mark.unit
def test_extract_locations_portuguese():
    """Test _extract_locations parses Portuguese 'de X para Y' pattern."""
    agent = TrafficAgent()
    origin, dest = agent._extract_locations("como está o trânsito de Dublin para Cork?")
    assert origin == "Dublin"
    assert dest == "Cork"


@pytest.mark.unit
def test_extract_locations_english():
    """Test _extract_locations parses English 'from X to Y' pattern."""
    agent = TrafficAgent()
    origin, dest = agent._extract_locations("traffic from London to Manchester")
    assert origin == "London"
    assert dest == "Manchester"


@pytest.mark.unit
def test_extract_locations_missing():
    """Test _extract_locations returns None when pattern not found."""
    agent = TrafficAgent()
    origin, dest = agent._extract_locations("como está o trânsito?")
    assert origin is None
    assert dest is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_with_prompt_parsing(mock_traffic_service):
    """Test execute parses origin/destination from prompt (no context needed)."""
    agent = TrafficAgent()
    agent._get_traffic_service = AsyncMock(return_value=mock_traffic_service)

    # Empty context — locations come from prompt
    result = await agent.execute("como está o trânsito de Dublin para Cork?", {})

    assert result.is_success()
    mock_traffic_service.get_route_with_traffic.assert_called_once_with(
        "Dublin", "Cork"
    )
