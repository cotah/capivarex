"""Unit tests for WeatherAgent."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from agents.core import AgentStatus
from agents.specialized.weather_agent import WeatherAgent, LOCATION_PATTERN


@pytest.fixture
def agent():
    return WeatherAgent()


class TestLocationExtraction:
    def test_from_context(self, agent):
        loc = agent._extract_location("anything", {"location": "Cork"})
        assert loc == "Cork"

    def test_from_prompt_em(self, agent):
        loc = agent._extract_location("tempo em Lisboa", {})
        assert loc == "Lisboa"

    def test_from_prompt_in(self, agent):
        loc = agent._extract_location("weather in London", {})
        assert loc == "London"

    def test_fallback_to_prompt(self, agent):
        loc = agent._extract_location("Dublin", {})
        assert loc == "Dublin"

    def test_regex_pattern(self):
        m = LOCATION_PATTERN.search("como esta o tempo em Sao Paulo?")
        assert m is not None
        assert "Sao Paulo" in m.group(1)


class TestWeatherAgentExecute:
    @pytest.mark.asyncio
    async def test_success(self, agent):
        mock_svc = AsyncMock()
        mock_svc.initialize = AsyncMock()
        mock_svc.get_forecast = AsyncMock(return_value={
            "location": {"name": "Dublin", "region": "Leinster"},
            "forecast": [{"condition": "Rain", "max_temp_c": 10, "min_temp_c": 5, "chance_of_rain": 80}],
        })
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            result = await agent.execute("tempo em Dublin", {"location": "Dublin"})
        assert result.is_success()
        assert "Dublin" in result.response
        assert "Rain" in result.response

    @pytest.mark.asyncio
    async def test_no_service(self, agent):
        with patch("agents.specialized.weather_agent.get_service", return_value=None):
            result = await agent.execute("tempo", {"location": "Dublin"})
        assert result.status == AgentStatus.ERROR
        assert "nao disponivel" in result.response.lower()

    @pytest.mark.asyncio
    async def test_no_location(self, agent):
        """Empty prompt and no context location."""
        result = await agent.execute("", {})
        assert result.status == AgentStatus.ERROR

    @pytest.mark.asyncio
    async def test_no_forecast_data(self, agent):
        mock_svc = AsyncMock()
        mock_svc.initialize = AsyncMock()
        mock_svc.get_forecast = AsyncMock(return_value={"location": {}, "forecast": []})
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            result = await agent.execute("tempo", {"location": "Mars"})
        assert result.status == AgentStatus.ERROR

    @pytest.mark.asyncio
    async def test_service_exception(self, agent):
        mock_svc = AsyncMock()
        mock_svc.initialize = AsyncMock()
        mock_svc.get_forecast = AsyncMock(side_effect=RuntimeError("API down"))
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            result = await agent.execute("tempo", {"location": "Dublin"})
        assert result.status == AgentStatus.ERROR

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        assert "current_weather" in caps
        assert "weather_forecast" in caps
