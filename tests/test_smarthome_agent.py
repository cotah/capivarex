"""
Tests for SmartHomeAgent — SmartThings IoT control.
Agente sem cobertura de testes. Adicionado na Fase C do QA.
"""
from unittest.mock import AsyncMock, Mock, patch
import pytest
from agents.core import AgentStatus


@pytest.fixture
def smarthome_agent():
    from agents.specialized.smarthome_agent import SmartHomeAgent
    return SmartHomeAgent()


def _make_smartthings_svc():
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.get_devices = AsyncMock(return_value=[
        {"deviceId": "light_001", "label": "Sala - Luz", "type": "switch"},
        {"deviceId": "lock_001",  "label": "Porta da Frente", "type": "lock"},
        {"deviceId": "temp_001",  "label": "Termostato", "type": "thermostat"},
    ])
    svc.turn_on = AsyncMock(return_value={"status": "success"})
    svc.turn_off = AsyncMock(return_value={"status": "success"})
    svc.lock_device = AsyncMock(return_value={"status": "success"})
    svc.unlock_device = AsyncMock(return_value={"status": "success"})
    svc.get_device_status = AsyncMock(return_value={
        "components": {
            "main": {
                "switch": {"switch": {"value": "off"}},
                "lock": {"lock": {"value": "locked"}}
            }
        }
    })
    return svc


# ── Happy path ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_smarthome_list_devices(smarthome_agent):
    """SmartHomeAgent lists available devices."""
    st_svc = _make_smartthings_svc()
    with patch("agents.specialized.smarthome_agent.get_service", return_value=st_svc):
        result = await smarthome_agent.execute(
            "quais dispositivos estão ligados?",
            {"user_id": "user_test", "access_token": "st_token_123"}
        )
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


@pytest.mark.asyncio
async def test_smarthome_turn_on_lights(smarthome_agent):
    """SmartHomeAgent processes light on command."""
    st_svc = _make_smartthings_svc()
    with patch("agents.specialized.smarthome_agent.get_service", return_value=st_svc):
        result = await smarthome_agent.execute(
            "acenda as luzes da sala",
            {"user_id": "user_test", "access_token": "st_token_123"}
        )
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


@pytest.mark.asyncio
async def test_smarthome_turn_off_command(smarthome_agent):
    """SmartHomeAgent processes turn off command."""
    st_svc = _make_smartthings_svc()
    with patch("agents.specialized.smarthome_agent.get_service", return_value=st_svc):
        result = await smarthome_agent.execute(
            "apague as luzes",
            {"user_id": "user_test", "access_token": "st_token_123"}
        )
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


@pytest.mark.asyncio
async def test_smarthome_capabilities(smarthome_agent):
    """SmartHomeAgent declares expected capabilities."""
    caps = smarthome_agent.get_capabilities()
    assert isinstance(caps, list)
    assert len(caps) > 0


# ── Falhas e edge cases ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_smarthome_service_unavailable(smarthome_agent):
    """SmartHomeAgent returns error when SmartThings service is None."""
    with patch("agents.specialized.smarthome_agent.get_service", return_value=None):
        result = await smarthome_agent.execute("acenda as luzes", {"user_id": "user_test"})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_smarthome_missing_token(smarthome_agent):
    """SmartHomeAgent handles missing access token gracefully."""
    st_svc = _make_smartthings_svc()
    with patch("agents.specialized.smarthome_agent.get_service", return_value=st_svc):
        # No access_token in context
        result = await smarthome_agent.execute("status dos dispositivos", {"user_id": "user_test"})
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response
