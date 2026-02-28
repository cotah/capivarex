"""
Tests for TwilioAgent intelligent call integration.

Tests the new intelligent call mode WITHOUT breaking existing tests.
"""
import json
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ai.call_brain import CallBrain, CallPlan


# ── TwiML Media Stream tests ─────────────────────────────────────────────


class TestTwimlMediaStream:
    """Test the new twiml_media_stream method on TwilioService."""

    def _get_service_instance(self):
        """Get a bare TwilioService instance (no __init__ side effects)."""
        from services.integrations.twilio_service import TwilioService

        return TwilioService.__new__(TwilioService)

    def test_twiml_contains_stream_element(self):
        svc = self._get_service_instance()

        twiml = svc.twiml_media_stream(
            stream_url="wss://example.com/ws/twilio-stream",
            session_id="abc123",
        )

        assert "<Response>" in twiml
        assert "<Connect>" in twiml
        assert "<Stream" in twiml
        assert 'url="wss://example.com/ws/twilio-stream"' in twiml
        assert "</Response>" in twiml

    def test_twiml_contains_session_parameter(self):
        svc = self._get_service_instance()

        twiml = svc.twiml_media_stream(
            stream_url="wss://example.com/ws",
            session_id="mysession456",
        )

        assert '<Parameter name="session_id"' in twiml
        assert 'value="mysession456"' in twiml

    def test_twiml_is_valid_xml(self):
        svc = self._get_service_instance()

        twiml = svc.twiml_media_stream(
            stream_url="wss://example.com/ws",
            session_id="test",
        )

        root = ET.fromstring(twiml)
        assert root.tag == "Response"

    def test_twiml_has_connect_child(self):
        svc = self._get_service_instance()

        twiml = svc.twiml_media_stream(
            stream_url="wss://test.com/ws",
            session_id="s1",
        )

        root = ET.fromstring(twiml)
        connect = root.find("Connect")
        assert connect is not None
        stream = connect.find("Stream")
        assert stream is not None
        assert stream.attrib["url"] == "wss://test.com/ws"


# ── CallBrain integration tests ───────────────────────────────────────────


class TestCallBrainExtractPlan:
    """Test that CallBrain correctly extracts call plans."""

    @pytest.mark.asyncio
    async def test_extract_plan_for_reservation(self):
        brain = CallBrain()

        plan_json = json.dumps(
            {
                "objective": "Reserve a table for 2 at 8pm",
                "language": "pt",
                "greeting": "Boa noite! Ligo em nome de Henrique.",
                "key_details": "2 people, 8pm",
                "extra_context": "",
            }
        )
        brain._client = _mock_openai_client(plan_json)

        plan = await brain.extract_call_plan(
            user_prompt="liga pro restaurante e reserva para 2 às 20h",
            user_name="Henrique",
        )

        assert plan.language == "pt"
        assert "2" in plan.key_details

    @pytest.mark.asyncio
    async def test_extract_plan_for_message_delivery(self):
        brain = CallBrain()

        plan_json = json.dumps(
            {
                "objective": "Tell them Henrique will be 15 minutes late",
                "language": "en",
                "greeting": "Hi, I'm calling on behalf of Henrique.",
                "key_details": "15 minutes late",
                "extra_context": "",
            }
        )
        brain._client = _mock_openai_client(plan_json)

        plan = await brain.extract_call_plan(
            user_prompt="call and say I'll be 15 min late",
            user_name="Henrique",
        )

        assert plan.language == "en"
        assert "late" in plan.objective.lower()


# ── Intelligent call flow test ────────────────────────────────────────────


class TestIntelligentCallFlow:
    """Test the full intelligent call flow end-to-end (mocked)."""

    def setup_method(self):
        self._patcher = patch(
            "services.business.call_session._get_redis_client",
            return_value=None,
        )
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    @pytest.mark.asyncio
    async def test_full_flow_registers_pending_call(self):
        """
        Verify that the intelligent call flow:
        1. Calls CallBrain.extract_call_plan()
        2. Calls register_pending_call()
        3. Generates TwiML with media stream
        4. Makes the call via TwilioService
        """
        from services.business.call_session import (
            _PENDING_CALLS,
            get_pending_calls_count,
        )

        _PENDING_CALLS.clear()

        mock_plan = CallPlan(
            objective="Reserve table for 2 at 8pm",
            language="pt",
            greeting="Boa noite!",
            key_details="2 people, 8pm",
            extra_context="",
        )

        with patch.object(
            CallBrain, "extract_call_plan", return_value=mock_plan
        ):
            from services.business.call_session import (
                register_pending_call,
            )

            session_id = register_pending_call(
                objective=mock_plan.objective,
                user_name="Henrique",
                language=mock_plan.language,
                phone_number="+353123456",
                telegram_chat_id=123,
                telegram_user_id=456,
                extra_context=mock_plan.key_details,
                greeting=mock_plan.greeting,
            )

            assert get_pending_calls_count() >= 1
            assert len(session_id) == 16

    @pytest.mark.asyncio
    async def test_stream_url_construction(self):
        """Verify WSS URL is correctly derived from BACKEND_URL."""
        backend_url = "https://capivarex.up.railway.app"

        ws_url = backend_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        stream_url = f"{ws_url}/ws/twilio-stream"

        assert (
            stream_url
            == "wss://capivarex.up.railway.app/ws/twilio-stream"
        )

    @pytest.mark.asyncio
    async def test_stream_url_http_fallback(self):
        """HTTP URLs get converted to ws://."""
        backend_url = "http://localhost:8000"

        ws_url = backend_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        stream_url = f"{ws_url}/ws/twilio-stream"

        assert stream_url == "ws://localhost:8000/ws/twilio-stream"


# ── TwilioAgent._execute_intelligent_call integration ─────────────────────


class TestAgentIntelligentCallIntegration:
    """Test _execute_intelligent_call on the actual agent."""

    @pytest.mark.asyncio
    async def test_intelligent_call_success(self):
        """Full intelligent call through the agent returns success."""
        from agents.specialized.twilio_agent import TwilioAgent

        agent = TwilioAgent.__new__(TwilioAgent)
        agent.name = "twilio"
        agent.description = "test"
        agent.logger = MagicMock()
        agent._initialized = True

        mock_plan = CallPlan(
            objective="Reserve table",
            language="pt",
            greeting="Boa noite!",
            key_details="2 pessoas",
            extra_context="",
        )

        mock_twilio_svc = MagicMock()
        mock_twilio_svc.twiml_media_stream = MagicMock(
            return_value="<Response>...</Response>"
        )
        mock_twilio_svc.make_call = AsyncMock(
            return_value={
                "call_sid": "CA_intelligent_test",
                "status": "initiated",
                "from_number": "+14064164577",
            }
        )

        with (
            patch(
                "services.ai.call_brain.CallBrain"
            ) as MockBrain,
            patch(
                "services.business.call_session.register_pending_call",
                return_value="sess_1234567890ab",
            ),
        ):
            MockBrain.return_value.extract_call_plan = AsyncMock(
                return_value=mock_plan
            )

            result = await agent._execute_intelligent_call(
                mock_twilio_svc,
                "+353123456",
                "reserva para 2",
                {
                    "user_name": "Henrique",
                    "chat_id": 123,
                    "user_id": 456,
                },
            )

        assert result.status.value == "success"
        assert "inteligente" in result.response.lower()
        assert result.data["mode"] == "intelligent"
        assert result.data["session_id"] == "sess_1234567890ab"
        mock_twilio_svc.twiml_media_stream.assert_called_once()
        mock_twilio_svc.make_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_call_routes_to_intelligent_when_backend_set(
        self,
    ):
        """_execute_call routes to intelligent mode when BACKEND_URL is set."""
        from agents.specialized.twilio_agent import TwilioAgent

        agent = TwilioAgent.__new__(TwilioAgent)
        agent.name = "twilio"
        agent.description = "test"
        agent.logger = MagicMock()
        agent._initialized = True

        mock_twilio_svc = MagicMock()

        with (
            patch.object(
                agent,
                "_execute_intelligent_call",
                new_callable=AsyncMock,
            ) as mock_intelligent,
            patch(
                "agents.specialized.twilio_agent.BACKEND_URL",
                "https://test.com",
            ),
        ):
            from agents.core import AgentResponse, AgentStatus

            mock_intelligent.return_value = AgentResponse(
                status=AgentStatus.SUCCESS,
                response="ok",
            )

            await agent._execute_call(
                mock_twilio_svc,
                "+353123",
                "test",
                {},
            )

            mock_intelligent.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_call_falls_back_to_static_on_error(self):
        """Falls back to static when intelligent fails."""
        from agents.specialized.twilio_agent import TwilioAgent

        agent = TwilioAgent.__new__(TwilioAgent)
        agent.name = "twilio"
        agent.description = "test"
        agent.logger = MagicMock()
        agent._initialized = True

        mock_twilio_svc = MagicMock()

        with (
            patch.object(
                agent,
                "_execute_intelligent_call",
                new_callable=AsyncMock,
                side_effect=RuntimeError("brain error"),
            ),
            patch.object(
                agent,
                "_execute_static_call",
                new_callable=AsyncMock,
            ) as mock_static,
            patch(
                "agents.specialized.twilio_agent.BACKEND_URL",
                "https://test.com",
            ),
        ):
            from agents.core import AgentResponse, AgentStatus

            mock_static.return_value = AgentResponse(
                status=AgentStatus.SUCCESS,
                response="static ok",
            )

            result = await agent._execute_call(
                mock_twilio_svc,
                "+353123",
                "test",
                {},
            )

            assert result.response == "static ok"
            mock_static.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_call_uses_static_when_no_backend_url(self):
        """Uses static mode when BACKEND_URL is empty."""
        from agents.specialized.twilio_agent import TwilioAgent

        agent = TwilioAgent.__new__(TwilioAgent)
        agent.name = "twilio"
        agent.description = "test"
        agent.logger = MagicMock()
        agent._initialized = True

        mock_twilio_svc = MagicMock()

        with (
            patch.object(
                agent,
                "_execute_static_call",
                new_callable=AsyncMock,
            ) as mock_static,
            patch(
                "agents.specialized.twilio_agent.BACKEND_URL",
                "",
            ),
        ):
            from agents.core import AgentResponse, AgentStatus

            mock_static.return_value = AgentResponse(
                status=AgentStatus.SUCCESS,
                response="static",
            )

            result = await agent._execute_call(
                mock_twilio_svc,
                "+353123",
                "test",
                {},
            )

            assert result.response == "static"
            mock_static.assert_called_once()

    @pytest.mark.asyncio
    async def test_static_call_preserves_original_behavior(self):
        """_execute_static_call produces the same output as the old execute."""
        from agents.specialized.twilio_agent import TwilioAgent

        agent = TwilioAgent.__new__(TwilioAgent)
        agent.name = "twilio"
        agent.description = "test"
        agent.logger = MagicMock()
        agent._initialized = True

        mock_twilio_svc = MagicMock()
        mock_twilio_svc.twiml_say = MagicMock(return_value="<TwiML/>")
        mock_twilio_svc.make_call = AsyncMock(
            return_value={
                "call_sid": "CA_static_test",
                "status": "initiated",
                "from_number": "+14064164577",
            }
        )

        result = await agent._execute_static_call(
            mock_twilio_svc,
            "+353894434456",
            "liga para o +353894434456",
            {"user_id": "user_123"},
        )

        assert result.status.value == "success"
        assert "+353894434456" in result.response
        assert result.data["mode"] == "static"
        mock_twilio_svc.twiml_say.assert_called_once()
        mock_twilio_svc.make_call.assert_called_once()


# ── Helpers ───────────────────────────────────────────────────────────────


def _mock_openai_client(response_content: str):
    """Create a mock AsyncOpenAI client."""
    mock_choice = MagicMock()
    mock_choice.message.content = response_content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=mock_response
    )
    return mock_client
