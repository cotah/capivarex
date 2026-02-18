"""
Tests for PromptCleanerService — refactored architecture.

The refactored PromptCleanerService is a BaseService subclass that creates its
own ``_openai_client`` during ``_initialize()``.  Tests create an instance
and inject the mock client directly.
"""
import pytest

from services.business.prompt_cleaner import PromptCleanerService


def _build_cleaner(openai_client=None):
    """Create a PromptCleanerService with optional mocked OpenAI client."""
    cleaner = PromptCleanerService()
    cleaner._initialized = True
    if openai_client is not None:
        cleaner._openai_client = openai_client
    return cleaner


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_calendar_create_event(mock_openai_client):
    """Test calendar cleaning for create event query."""
    cleaner = _build_cleaner(openai_client=mock_openai_client)

    result = await cleaner._clean_calendar(
        "Agendar um evento de reunião amanhã às 15 horas em Cork",
        {"user_id": "test"},
    )

    assert result["action"] == "create_event"
    assert "event_params" in result
    assert result["event_params"]["title"] == "Test Event"
    assert result["event_params"]["location"] == "Cork"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_calendar_non_create_query():
    """Test calendar cleaning for non-create query."""
    cleaner = _build_cleaner()

    result = await cleaner._clean_calendar(
        "What's my next meeting?",
        {},
    )

    assert result["action"] == "calendar"
    assert "event_params" not in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_calendar_error_handling_client_unavailable():
    """Test calendar cleaning error handling when OpenAI client is unavailable."""
    cleaner = _build_cleaner(openai_client=None)

    result = await cleaner._clean_calendar(
        "Agendar um evento para amanhã às 10h",
        {},
    )

    assert result["action"] == "calendar"
    assert "error" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_calendar_error_handling_openai_exception():
    """Test calendar cleaning fallback when OpenAI request raises."""

    class _FailingCompletions:
        async def create(self, *args, **kwargs):
            raise RuntimeError("boom")

    client = type(
        "Client", (), {"chat": type("Chat", (), {"completions": _FailingCompletions()})()}
    )()

    cleaner = _build_cleaner(openai_client=client)

    result = await cleaner._clean_calendar(
        "Criar evento hoje às 14h",
        {},
    )

    assert result["action"] == "calendar"
    assert "error" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_for_agent_dispatch_research():
    """Test clean_for_agent dispatches to research cleaner."""
    cleaner = _build_cleaner()

    result = await cleaner.clean_for_agent(
        "search",
        "pesquise sobre inteligência artificial",
        {},
    )

    assert result["action"] == "search"
    assert "query" in result
    assert "inteligência artificial" in result["query"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_for_agent_voice_image_video():
    """Test cleaners for voice/image/video strip command prefixes."""
    cleaner = _build_cleaner()

    voice = await cleaner.clean_for_agent("voice", "gere um audio dizendo oi", {})
    image = await cleaner.clean_for_agent("image", "gere uma imagem de uma praia", {})
    video = await cleaner.clean_for_agent("video", "gere um video de um carro", {})

    assert voice["action"] == "text_to_speech"
    assert voice["text"] == "oi"
    assert image["action"] == "image"
    assert image["description"] == "uma praia"
    assert video["action"] == "video"
    assert video["description"] == "um carro"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_for_agent_weather_finance_traffic(monkeypatch):
    """Test weather/finance/traffic cleaners with extracted parameters."""
    cleaner = _build_cleaner()

    async def _location(self, msg):
        return "Porto"

    async def _symbol(self, msg):
        return "TSLA"

    async def _traffic(self, msg):
        return {"origin": "Dublin", "destination": "Cork"}

    monkeypatch.setattr(PromptCleanerService, "_extract_location", _location)
    monkeypatch.setattr(PromptCleanerService, "_extract_stock_symbol", _symbol)
    monkeypatch.setattr(PromptCleanerService, "_extract_traffic_locations", _traffic)

    weather = await cleaner.clean_for_agent("weather", "tempo", {})
    finance = await cleaner.clean_for_agent("finance", "ação da tesla", {})
    traffic = await cleaner.clean_for_agent("traffic", "tráfego", {})

    assert weather["location"] == "Porto"
    assert finance["symbol"] == "TSLA"
    assert traffic["origin"] == "Dublin"
    assert traffic["destination"] == "Cork"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clean_for_agent_default_unknown_type():
    """Test unknown agent type falls back to default chat cleaner."""
    cleaner = _build_cleaner()

    result = await cleaner.clean_for_agent("unknown", "hello", {})

    assert result["action"] == "chat"
    assert result["prompt"] == "hello"


@pytest.mark.unit
def test_strip_prefix_removes_known_prefix():
    """Test _strip_prefix removes command prefix."""
    cleaned = PromptCleanerService._strip_prefix(
        "pesquise sobre carros elétricos", ["pesquise sobre"]
    )

    assert cleaned == "carros elétricos"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_location_success():
    """Test _extract_location success path."""
    response = type("Response", (), {})()
    choice = type("Choice", (), {})()
    message = type("Message", (), {})()
    message.content = "Lisbon"
    choice.message = message
    response.choices = [choice]

    class _Completions:
        async def create(self, *args, **kwargs):
            return response

    client = type(
        "Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()}
    )()

    cleaner = _build_cleaner(openai_client=client)
    result = await cleaner._extract_location("tempo em Lisboa")

    assert result == "Lisbon"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_stock_symbol_invalid_returns_none():
    """Test _extract_stock_symbol returns None for invalid output."""
    response = type("Response", (), {})()
    choice = type("Choice", (), {})()
    message = type("Message", (), {})()
    message.content = "@@@"
    choice.message = message
    response.choices = [choice]

    class _Completions:
        async def create(self, *args, **kwargs):
            return response

    client = type(
        "Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()}
    )()

    cleaner = _build_cleaner(openai_client=client)
    result = await cleaner._extract_stock_symbol("qual ação comprar?")

    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_traffic_locations_success():
    """Test _extract_traffic_locations success path."""
    response = type("Response", (), {})()
    choice = type("Choice", (), {})()
    message = type("Message", (), {})()
    message.content = "Dublin|Cork"
    choice.message = message
    response.choices = [choice]

    class _Completions:
        async def create(self, *args, **kwargs):
            return response

    client = type(
        "Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()}
    )()

    cleaner = _build_cleaner(openai_client=client)
    result = await cleaner._extract_traffic_locations("tráfego de dublin para cork")

    assert result == {"origin": "Dublin", "destination": "Cork"}
