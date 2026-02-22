"""Unit tests for ChatService dispatch logic."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from services.business.chat_service import ChatService


def _make_ws():
    """Return a mocked WebSocket."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _make_service(ws=None, user_id="u1", user_plan="basic"):
    """Build a ChatService with a mocked WebSocket and no real services."""
    ws = ws or _make_ws()
    with patch("services.business.chat_service.get_service", return_value=None):
        svc = ChatService(websocket=ws, user_id=user_id, user_plan=user_plan)
    return svc, ws


# -------------------------------------------------------------------
# Dispatch routing
# -------------------------------------------------------------------

class TestChatServiceDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_known_action(self):
        """Known action routes to the correct handler."""
        svc, ws = _make_service()

        # _ACTION_HANDLERS is a class-level dict of unbound functions,
        # so we must patch the dict entry rather than the instance method.
        mock_handler = AsyncMock(return_value="chat reply")
        with patch.dict(ChatService._ACTION_HANDLERS, {"chat": mock_handler}):
            result = await svc.dispatch("chat", "hello", {}, [])
        assert result == "chat reply"
        mock_handler.assert_called_once_with(svc, "hello", {}, [])

    @pytest.mark.asyncio
    async def test_dispatch_unknown_action_falls_back(self):
        """Unknown action triggers fallback handler."""
        svc, ws = _make_service()
        # Patch _handle_fallback as an instance override
        svc._handle_fallback
        svc._handle_fallback = AsyncMock(return_value="fallback reply")
        result = await svc.dispatch("unknown_action", "msg", {}, [])
        assert result == "fallback reply"

    @pytest.mark.asyncio
    async def test_all_actions_registered(self):
        """Every action in _ACTION_HANDLERS maps to a callable."""
        svc, _ = _make_service()
        expected = {
            "search", "dev", "image", "video", "voice",
            "finance", "calendar", "weather", "traffic", "car", "chat",
        }
        assert set(svc._ACTION_HANDLERS.keys()) == expected


# -------------------------------------------------------------------
# Handler: search
# -------------------------------------------------------------------

class TestHandleSearch:
    @pytest.mark.asyncio
    async def test_search_success(self):
        svc, ws = _make_service()
        mock_perplexity = Mock()
        mock_perplexity.search = AsyncMock(
            return_value={"answer": "AI is cool", "sources": ["src1"]}
        )

        async def _stream(msgs):
            for tok in ["Result", " text"]:
                yield tok

        mock_openai = Mock()
        mock_openai.stream_chat_completion = _stream
        svc._openai_svc = mock_openai

        with patch(
            "services.business.chat_service.get_service",
            side_effect=lambda name: mock_perplexity if name == "perplexity" else None,
        ):
            result = await svc._handle_search("what is AI", {"query": "AI"}, [])

        assert result == "Result text"

    @pytest.mark.asyncio
    async def test_search_no_perplexity(self):
        """Search works even when perplexity is unavailable."""
        svc, ws = _make_service()

        async def _stream(msgs):
            yield "fallback"

        svc._openai_svc = Mock()
        svc._openai_svc.stream_chat_completion = _stream

        with patch("services.business.chat_service.get_service", return_value=None):
            result = await svc._handle_search("query", {}, [])
        assert "fallback" in result


# -------------------------------------------------------------------
# Handler: dev
# -------------------------------------------------------------------

class TestHandleDev:
    @pytest.mark.asyncio
    async def test_dev_missing_prompt(self):
        svc, ws = _make_service()
        result = await svc._handle_dev("msg", {}, [])
        assert result == ""
        ws.send_json.assert_called()  # error sent

    @pytest.mark.asyncio
    async def test_dev_success(self):
        svc, ws = _make_service()
        mock_anthropic = Mock()

        async def _stream(p):
            for chunk in ["def ", "foo():"]:
                yield chunk

        mock_anthropic.generate_code_stream = _stream

        with patch(
            "services.business.chat_service.get_service",
            return_value=mock_anthropic,
        ):
            result = await svc._handle_dev("code", {"prompt": "write code"}, [])
        assert result == "def foo():"

    @pytest.mark.asyncio
    async def test_dev_no_service(self):
        svc, ws = _make_service()
        with patch("services.business.chat_service.get_service", return_value=None):
            result = await svc._handle_dev("m", {"prompt": "p"}, [])
        assert result == ""


# -------------------------------------------------------------------
# Handler: finance
# -------------------------------------------------------------------

class TestHandleFinance:
    @pytest.mark.asyncio
    async def test_finance_success(self):
        svc, ws = _make_service()
        mock_fin = Mock()
        mock_fin.get_quote = Mock(return_value={
            "name": "Apple", "symbol": "AAPL", "price": 150.0,
            "currency": "USD", "change": 2.5, "percent_change": 1.5,
            "high": 152.0, "low": 148.0,
        })
        with patch("services.business.chat_service.get_service", return_value=mock_fin):
            result = await svc._handle_finance("cotacao", {"symbol": "AAPL"}, [])
        assert "AAPL" in result
        assert "$150.00" in result

    @pytest.mark.asyncio
    async def test_finance_no_service(self):
        svc, ws = _make_service()
        with patch("services.business.chat_service.get_service", return_value=None):
            result = await svc._handle_finance("cotacao", {}, [])
        assert result == ""


# -------------------------------------------------------------------
# Handler: weather
# -------------------------------------------------------------------

class TestHandleWeather:
    @pytest.mark.asyncio
    async def test_weather_success(self):
        svc, ws = _make_service()
        mock_weather = Mock()
        mock_weather.get_forecast = Mock(return_value={
            "location": {"name": "Dublin", "region": "Leinster"},
            "forecast": [{"condition": "Cloudy", "max_temp_c": 12, "min_temp_c": 5, "chance_of_rain": 60}],
        })
        with patch("services.business.chat_service.get_service", return_value=mock_weather):
            result = await svc._handle_weather("tempo", {"location": "Dublin"}, [])
        assert "Dublin" in result
        assert "Cloudy" in result

    @pytest.mark.asyncio
    async def test_weather_no_forecast(self):
        svc, ws = _make_service()
        mock_weather = Mock()
        mock_weather.get_forecast = Mock(return_value={"location": {}, "forecast": []})
        with patch("services.business.chat_service.get_service", return_value=mock_weather):
            result = await svc._handle_weather("tempo", {}, [])
        assert "Nao foi possivel" in result


# -------------------------------------------------------------------
# Handler: chat
# -------------------------------------------------------------------

class TestHandleChat:
    @pytest.mark.asyncio
    async def test_chat_success(self):
        svc, ws = _make_service()
        mock_agent = AsyncMock()
        mock_resp = Mock()
        mock_resp.response = "agent reply"
        mock_agent.execute = AsyncMock(return_value=mock_resp)

        with patch("services.business.chat_service.get_agent", return_value=mock_agent):
            result = await svc._handle_chat("hi", {}, [])
        assert result == "agent reply"

    @pytest.mark.asyncio
    async def test_chat_no_agent(self):
        svc, ws = _make_service()
        with patch("services.business.chat_service.get_agent", return_value=None):
            result = await svc._handle_chat("hi", {}, [])
        assert "Erro" in result


# -------------------------------------------------------------------
# Handler: traffic
# -------------------------------------------------------------------

class TestHandleTraffic:
    @pytest.mark.asyncio
    async def test_traffic_success(self):
        svc, ws = _make_service()
        mock_traffic = Mock()
        mock_traffic.get_traffic_summary = Mock(return_value="30 min de viagem")
        with patch("services.business.chat_service.get_service", return_value=mock_traffic):
            result = await svc._handle_traffic("trafego", {"origin": "A", "destination": "B"}, [])
        assert result == "30 min de viagem"

    @pytest.mark.asyncio
    async def test_traffic_no_service(self):
        svc, ws = _make_service()
        with patch("services.business.chat_service.get_service", return_value=None):
            result = await svc._handle_traffic("trafego", {}, [])
        assert result == ""


# -------------------------------------------------------------------
# Handler: voice
# -------------------------------------------------------------------

class TestHandleVoice:
    @pytest.mark.asyncio
    async def test_voice_success(self):
        svc, ws = _make_service()
        mock_agent = AsyncMock()
        mock_result = Mock()
        mock_result.response = "https://audio.url/file.mp3"
        mock_agent.execute = AsyncMock(return_value=mock_result)

        with patch("services.business.chat_service.get_agent", return_value=mock_agent):
            result = await svc._handle_voice("diga ola", {"text": "ola"}, [])
        assert "audio.url" in result

    @pytest.mark.asyncio
    async def test_voice_no_agent(self):
        svc, ws = _make_service()
        with patch("services.business.chat_service.get_agent", return_value=None):
            result = await svc._handle_voice("fale", {}, [])
        assert "Erro" in result


# -------------------------------------------------------------------
# Handler: image
# -------------------------------------------------------------------

class TestHandleImage:
    @pytest.mark.asyncio
    async def test_image_success(self):
        svc, ws = _make_service()
        mock_image = AsyncMock()
        mock_image.generate_image = AsyncMock(
            return_value={"success": True, "image_path": "/img/cat.png"}
        )
        with patch("services.business.chat_service.get_service", return_value=mock_image):
            result = await svc._handle_image("gere gato", {"description": "gato"}, [])
        assert "cat.png" in result

    @pytest.mark.asyncio
    async def test_image_failure(self):
        svc, ws = _make_service()
        mock_image = AsyncMock()
        mock_image.generate_image = AsyncMock(
            return_value={"success": False, "error": "quota exceeded"}
        )
        with patch("services.business.chat_service.get_service", return_value=mock_image):
            result = await svc._handle_image("gere", {}, [])
        assert result == ""


# -------------------------------------------------------------------
# Handler: video
# -------------------------------------------------------------------

class TestHandleVideo:
    @pytest.mark.asyncio
    async def test_video_success(self):
        svc, ws = _make_service()
        mock_video = AsyncMock()
        mock_video.generate_text_to_video = AsyncMock(return_value={
            "success": True, "video_url": "https://vid.io/v.mp4",
            "model_used": "veo3", "duration": 5, "ratio": "16:9",
        })
        with patch("services.business.chat_service.get_service", return_value=mock_video):
            result = await svc._handle_video("gere video", {"prompt": "ondas"}, [])
        assert "vid.io" in result

    @pytest.mark.asyncio
    async def test_video_no_service(self):
        svc, ws = _make_service()
        with patch("services.business.chat_service.get_service", return_value=None):
            result = await svc._handle_video("gere", {}, [])
        assert result == ""


# -------------------------------------------------------------------
# Handler: calendar
# -------------------------------------------------------------------

class TestHandleCalendar:
    @pytest.mark.asyncio
    async def test_calendar_success_with_events(self):
        svc, ws = _make_service()
        mock_agent = AsyncMock()
        mock_resp = Mock()
        mock_resp.to_dict = Mock(return_value={
            "status": "success",
            "response": "Seus eventos:",
            "data": {"events": [
                {"summary": "Meeting", "start": "2026-02-15T15:00:00"},
            ]},
        })
        mock_agent.process = AsyncMock(return_value=mock_resp)

        with patch("services.business.chat_service.get_agent", return_value=mock_agent):
            result = await svc._handle_calendar("agenda", {"action": "today"}, [])
        assert "Meeting" in result

    @pytest.mark.asyncio
    async def test_calendar_no_agent(self):
        svc, ws = _make_service()
        with patch("services.business.chat_service.get_agent", return_value=None):
            result = await svc._handle_calendar("agenda", {}, [])
        assert result == ""


# -------------------------------------------------------------------
# Handler: car
# -------------------------------------------------------------------

class TestHandleCar:
    @pytest.mark.asyncio
    async def test_car_success(self):
        svc, ws = _make_service()
        mock_vdb = AsyncMock()
        mock_vdb.get_primary_vehicle = AsyncMock(return_value={
            "vehicle_id": "v1", "access_token": "tok", "refresh_token": "rtok",
        })
        mock_vdb.is_token_expired = AsyncMock(return_value=False)

        mock_car_agent = AsyncMock()
        mock_result = Mock()
        mock_result.response = "Battery: 80%"
        mock_car_agent.process = AsyncMock(return_value=mock_result)

        def _get_svc(name):
            return mock_vdb if name == "vehicle_db" else None

        with patch("services.business.chat_service.get_service", side_effect=_get_svc):
            with patch("services.business.chat_service.get_agent", return_value=mock_car_agent):
                result = await svc._handle_car("bateria", {"query": "bateria"}, [])
        assert "Battery: 80%" in result


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

class TestHelpers:
    @pytest.mark.asyncio
    async def test_send_system(self):
        svc, ws = _make_service()
        await svc._send_system("loading...")
        ws.send_json.assert_called_once_with({"type": "system", "content": "loading..."})

    @pytest.mark.asyncio
    async def test_send_error(self):
        svc, ws = _make_service()
        await svc._send_error("oops")
        ws.send_json.assert_called_once_with({"type": "error", "content": "oops"})

    @pytest.mark.asyncio
    async def test_stream_openai(self):
        svc, ws = _make_service()

        async def _stream(msgs):
            for tok in ["a", "b"]:
                yield tok

        svc._openai_svc = Mock()
        svc._openai_svc.stream_chat_completion = _stream
        result = await svc._stream_openai([{"role": "user", "content": "hi"}])
        assert result == "ab"

    @pytest.mark.asyncio
    async def test_stream_openai_no_service(self):
        svc, ws = _make_service()
        svc._openai_svc = None
        result = await svc._stream_openai([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_fallback_handler(self):
        svc, ws = _make_service()

        async def _stream(msgs):
            yield "fallback"

        svc._openai_svc = Mock()
        svc._openai_svc.stream_chat_completion = _stream
        result = await svc._handle_fallback("msg", {}, [{"role": "user", "content": "msg"}])
        assert result == "fallback"
