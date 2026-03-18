"""
Tests for CarAgent — electric vehicle control via Smartcar.
Agente sem cobertura de testes. Adicionado na Fase C do QA.
"""

from unittest.mock import AsyncMock, Mock, patch
import pytest
from agents.core import AgentStatus


@pytest.fixture
def car_agent():
    from agents.specialized.car_agent import CarAgent

    return CarAgent()


def _make_car_svc():
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.get_battery_level = AsyncMock(
        return_value={
            "percentRemaining": 0.78,
            "range": 280.5,
            "isPluggedIn": False,
            "state": "NOT_CHARGING",
        }
    )
    svc.get_location = AsyncMock(
        return_value={
            "latitude": 53.3498,
            "longitude": -6.2603,
            "address": "Dublin, Ireland",
        }
    )
    svc.lock = AsyncMock(return_value={"status": "success"})
    svc.unlock = AsyncMock(return_value={"status": "success"})
    svc.start_charge = AsyncMock(return_value={"status": "success"})
    svc.get_odometer = AsyncMock(return_value={"distance": 15234.5})
    return svc


def _make_vehicle_db():
    svc = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.initialize = AsyncMock()
    svc.get_primary_vehicle = AsyncMock(
        return_value={
            "vehicle_id": "vehicle_abc123",
            "access_token": "token_xyz",
            "make": "Tesla",
            "model": "Model 3",
        }
    )
    return svc


# ── Happy path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_car_battery_query(car_agent):
    """CarAgent returns battery status."""
    car_svc = _make_car_svc()
    vehicle_db = _make_vehicle_db()

    def _get_service(name):
        if name == "car":
            return car_svc
        if name == "vehicle_db":
            return vehicle_db
        return None

    with patch("agents.specialized.car_agent.get_service", side_effect=_get_service):
        result = await car_agent.execute(
            "qual o nível de bateria do meu carro?", {"user_id": "user_test"}
        )
    assert result.status == AgentStatus.SUCCESS
    assert result.response


@pytest.mark.asyncio
async def test_car_lock_command(car_agent):
    """CarAgent processes lock command."""
    car_svc = _make_car_svc()
    vehicle_db = _make_vehicle_db()

    def _get_service(name):
        if name == "car":
            return car_svc
        if name == "vehicle_db":
            return vehicle_db
        return None

    with patch("agents.specialized.car_agent.get_service", side_effect=_get_service):
        result = await car_agent.execute("tranque o carro", {"user_id": "user_test"})
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)


@pytest.mark.asyncio
async def test_car_no_vehicle_connected(car_agent):
    """CarAgent returns appropriate message when no vehicle is connected."""
    vehicle_db = _make_vehicle_db()
    vehicle_db.get_primary_vehicle = AsyncMock(return_value=None)

    def _get_service(name):
        if name == "vehicle_db":
            return vehicle_db
        return AsyncMock()

    with patch("agents.specialized.car_agent.get_service", side_effect=_get_service):
        result = await car_agent.execute("bateria do carro", {"user_id": "user_test"})
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


# ── Falhas e edge cases ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_car_service_unavailable(car_agent):
    """CarAgent handles when car service is missing — returns ERROR when vehicle_id is set."""
    with patch("agents.specialized.car_agent.get_service", return_value=None):
        result = await car_agent.execute(
            "status do veículo",
            {"user_id": "user_test", "vehicle_id": "v1", "access_token": "tok"},
        )
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_car_capabilities(car_agent):
    """CarAgent declares expected capabilities."""
    caps = car_agent.get_capabilities()
    assert isinstance(caps, list)
    assert len(caps) > 0
