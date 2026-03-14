"""
Tests for SmartHomeAgent — Tuya Smart Home control.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from agents.core import AgentStatus
from agents.specialized.smarthome_agent import SmartHomeAgent


@pytest.fixture
def smarthome_agent():
    return SmartHomeAgent()


def _mock_tuya(connected=True, devices=None, send_ok=True):
    t = MagicMock()
    t.client_id = "test_id"
    t.client_secret = "test_secret"
    t.is_connected = AsyncMock(return_value=connected)
    t.get_user_devices = AsyncMock(return_value=devices if devices is not None else [
        {"id": "d1", "name": "Zigbee Smart Bulb", "category": "dj", "online": True},
        {"id": "d2", "name": "Bedroom", "category": "dj", "online": False},
    ])
    t.get_device_status = AsyncMock(return_value=[
        {"code": "switch_led", "value": True},
    ])
    t.send_command = AsyncMock(return_value=send_ok)
    return t


def _setup(agent, tuya, intent_result):
    """Monkey-patch both _get_tuya_oauth and _analyze_intent."""
    agent._get_tuya_oauth = lambda: tuya
    agent._analyze_intent = AsyncMock(return_value=intent_result)


# ── Happy path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_devices(smarthome_agent):
    tuya = _mock_tuya()
    _setup(smarthome_agent, tuya, {"intent": "list_devices", "device_name": None})
    result = await smarthome_agent.execute(
        "list my devices", {"user_id": "u123", "lang": "en"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert "Zigbee Smart Bulb" in result.response
    assert result.data.get("count") == 2


@pytest.mark.asyncio
async def test_turn_on(smarthome_agent):
    tuya = _mock_tuya()
    _setup(smarthome_agent, tuya, {"intent": "turn_on", "device_name": "Zigbee Smart Bulb"})
    result = await smarthome_agent.execute(
        "turn on the Zigbee Smart Bulb", {"user_id": "u123", "lang": "en"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert result.data.get("action") == "on"


@pytest.mark.asyncio
async def test_turn_off(smarthome_agent):
    tuya = _mock_tuya()
    _setup(smarthome_agent, tuya, {"intent": "turn_off", "device_name": "Bedroom"})
    result = await smarthome_agent.execute(
        "turn off bedroom", {"user_id": "u123", "lang": "en"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert result.data.get("action") == "off"


@pytest.mark.asyncio
async def test_device_not_found(smarthome_agent):
    tuya = _mock_tuya()
    _setup(smarthome_agent, tuya, {"intent": "turn_on", "device_name": "kitchen light"})
    result = await smarthome_agent.execute(
        "turn on the kitchen light", {"user_id": "u123", "lang": "en"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert "not found" in result.response.lower()


@pytest.mark.asyncio
async def test_device_status(smarthome_agent):
    tuya = _mock_tuya()
    _setup(smarthome_agent, tuya, {"intent": "device_status", "device_name": "Zigbee Smart Bulb"})
    result = await smarthome_agent.execute(
        "status of the bulb", {"user_id": "u123", "lang": "en"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert "Zigbee Smart Bulb" in result.response


@pytest.mark.asyncio
async def test_capabilities(smarthome_agent):
    caps = smarthome_agent.get_capabilities()
    assert isinstance(caps, list)
    assert "device_control" in caps


# ── Not connected ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_not_connected(smarthome_agent):
    tuya = _mock_tuya(connected=False)
    smarthome_agent._get_tuya_oauth = lambda: tuya
    result = await smarthome_agent.execute(
        "list my devices", {"user_id": "u123", "lang": "en"},
    )
    assert result.data.get("needs_connection") is True


@pytest.mark.asyncio
async def test_no_tuya_env(smarthome_agent):
    smarthome_agent._get_tuya_oauth = lambda: None
    result = await smarthome_agent.execute(
        "list my devices", {"user_id": "u123", "lang": "en"},
    )
    assert result.data.get("needs_connection") is True


@pytest.mark.asyncio
async def test_no_devices(smarthome_agent):
    tuya = _mock_tuya(devices=[])
    _setup(smarthome_agent, tuya, {"intent": "list_devices", "device_name": None})
    result = await smarthome_agent.execute(
        "list my devices", {"user_id": "u123", "lang": "en"},
    )
    assert result.status == AgentStatus.SUCCESS
    assert "no device" in result.response.lower() or result.data.get("devices") == []


@pytest.mark.asyncio
async def test_command_fails(smarthome_agent):
    tuya = _mock_tuya(send_ok=False)
    _setup(smarthome_agent, tuya, {"intent": "turn_on", "device_name": "Zigbee Smart Bulb"})
    result = await smarthome_agent.execute(
        "turn on the bulb", {"user_id": "u123", "lang": "en"},
    )
    assert result.status == AgentStatus.ERROR
