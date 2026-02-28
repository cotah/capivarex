"""
Tests for CallBrain — GPT-powered phone call intelligence.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ai.call_brain import (
    BrainResponse,
    CallBrain,
    CallPlan,
    _FALLBACK_RESPONSES,
    _GOODBYE_FALLBACKS,
    _detect_language_simple,
)


# -- Helpers ------------------------------------------------------------------


def _mock_openai_response(content: str):
    """Create a mock OpenAI chat completion response."""
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def _mock_client(response_content: str):
    """Create a mock AsyncOpenAI client."""
    mock = AsyncMock()
    mock.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response(response_content)
    )
    return mock


# -- extract_call_plan tests --------------------------------------------------


class TestExtractCallPlan:
    @pytest.mark.asyncio
    async def test_extracts_plan_from_portuguese(self):
        """Parses a valid JSON plan from GPT response."""
        brain = CallBrain()

        plan_json = json.dumps({
            "objective": "Reserve a table for 2 people at 8pm",
            "language": "pt",
            "greeting": (
                "Boa noite! Estou a ligar em nome de Henrique "
                "para fazer uma reserva."
            ),
            "key_details": "2 people, 8pm, name Henrique",
            "extra_context": "Restaurant might be busy on weekends",
        })

        brain._client = _mock_client(plan_json)

        plan = await brain.extract_call_plan(
            user_prompt="liga pro restaurante e reserva para 2 as 20h",
            user_name="Henrique",
        )

        assert isinstance(plan, CallPlan)
        assert plan.language == "pt"
        assert "2" in plan.key_details
        assert "8pm" in plan.key_details or "20h" in plan.objective
        assert plan.greeting != ""

    @pytest.mark.asyncio
    async def test_extracts_plan_from_english(self):
        brain = CallBrain()

        plan_json = json.dumps({
            "objective": "Tell them Henrique will be 15 minutes late",
            "language": "en",
            "greeting": "Hello! I'm calling on behalf of Henrique.",
            "key_details": "15 minutes late",
            "extra_context": "",
        })

        brain._client = _mock_client(plan_json)

        plan = await brain.extract_call_plan(
            user_prompt="call them and say I'll be 15 minutes late",
            user_name="Henrique",
        )

        assert plan.language == "en"
        assert "15 minutes" in plan.key_details

    @pytest.mark.asyncio
    async def test_handles_json_with_markdown_fences(self):
        """GPT sometimes wraps JSON in code fences."""
        brain = CallBrain()

        response = (
            '```json\n{"objective":"Test","language":"en",'
            '"greeting":"Hi","key_details":"","extra_context":""}\n```'
        )
        brain._client = _mock_client(response)

        plan = await brain.extract_call_plan("test call", "Test User")

        assert plan.objective == "Test"
        assert plan.language == "en"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        """Invalid JSON falls back to user prompt."""
        brain = CallBrain()
        brain._client = _mock_client("This is not JSON at all")

        plan = await brain.extract_call_plan(
            user_prompt="liga pro restaurante",
            user_name="Henrique",
        )

        assert plan.objective == "liga pro restaurante"
        assert plan.language == "pt"

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self):
        """Exception falls back gracefully."""
        brain = CallBrain()
        mock = AsyncMock()
        mock.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API down")
        )
        brain._client = mock

        plan = await brain.extract_call_plan(
            "call the restaurant", "Henrique"
        )

        assert plan.objective == "call the restaurant"
        assert plan.language == "en"


# -- generate_response tests --------------------------------------------------


class TestGenerateResponse:
    @pytest.mark.asyncio
    async def test_normal_response(self):
        """Normal conversational response."""
        brain = CallBrain()
        brain._client = _mock_client(
            "Claro, para quantas pessoas seria a reserva?"
        )

        resp = await brain.generate_response(
            objective="Reserve table",
            user_name="Henrique",
            language="pt",
            key_details="2 people, 8pm",
            extra_context="",
            conversation_history=[],
            latest_speech="Alo, restaurante Roma",
        )

        assert isinstance(resp, BrainResponse)
        assert resp.text != ""
        assert resp.objective_complete is False
        assert resp.should_end_call is False
        assert resp.latency_s >= 0

    @pytest.mark.asyncio
    async def test_objective_complete_tag(self):
        """Detects [OBJECTIVE_COMPLETE] tag."""
        brain = CallBrain()
        brain._client = _mock_client(
            "Perfeito, reserva confirmada! [OBJECTIVE_COMPLETE]"
        )

        resp = await brain.generate_response(
            objective="Reserve table",
            user_name="Henrique",
            language="pt",
            key_details="",
            extra_context="",
            conversation_history=[],
            latest_speech="Confirmado para 2 as 20h",
        )

        assert resp.objective_complete is True
        assert "[OBJECTIVE_COMPLETE]" not in resp.text

    @pytest.mark.asyncio
    async def test_end_call_tag(self):
        """Detects [END_CALL] tag."""
        brain = CallBrain()
        brain._client = _mock_client(
            "Muito obrigado, boa noite! [OBJECTIVE_COMPLETE][END_CALL]"
        )

        resp = await brain.generate_response(
            objective="Test",
            user_name="Test",
            language="pt",
            key_details="",
            extra_context="",
            conversation_history=[],
            latest_speech="OK, confirmed",
        )

        assert resp.objective_complete is True
        assert resp.should_end_call is True
        assert "boa noite" in resp.text.lower()
        assert "[END_CALL]" not in resp.text
        assert "[OBJECTIVE_COMPLETE]" not in resp.text

    @pytest.mark.asyncio
    async def test_objective_failed_tag(self):
        """Detects [OBJECTIVE_FAILED] and sets should_end."""
        brain = CallBrain()
        brain._client = _mock_client(
            "I understand, thank you for letting me know. "
            "[OBJECTIVE_FAILED][END_CALL]"
        )

        resp = await brain.generate_response(
            objective="Reserve table",
            user_name="Henrique",
            language="en",
            key_details="",
            extra_context="",
            conversation_history=[],
            latest_speech="Sorry we're fully booked",
        )

        assert resp.objective_complete is False
        assert resp.should_end_call is True

    @pytest.mark.asyncio
    async def test_fallback_on_gpt_error(self):
        """GPT error returns polite fallback."""
        brain = CallBrain()
        mock = AsyncMock()
        mock.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("timeout")
        )
        brain._client = mock

        resp = await brain.generate_response(
            objective="Test",
            user_name="Test",
            language="pt",
            key_details="",
            extra_context="",
            conversation_history=[],
            latest_speech="Hello",
        )

        assert resp.text == _FALLBACK_RESPONSES["pt"]
        assert resp.objective_complete is False

    @pytest.mark.asyncio
    async def test_fallback_language_english(self):
        """English fallback when language is en."""
        brain = CallBrain()
        mock = AsyncMock()
        mock.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("err")
        )
        brain._client = mock

        resp = await brain.generate_response(
            objective="Test",
            user_name="Test",
            language="en",
            key_details="",
            extra_context="",
            conversation_history=[],
            latest_speech="Hello",
        )

        assert resp.text == _FALLBACK_RESPONSES["en"]


# -- generate_greeting tests --------------------------------------------------


class TestGenerateGreeting:
    @pytest.mark.asyncio
    async def test_uses_custom_greeting_if_provided(self):
        """Custom greeting skips GPT call."""
        brain = CallBrain()
        resp = await brain.generate_greeting(
            objective="Test",
            user_name="Henrique",
            language="pt",
            custom_greeting=(
                "Boa noite! Estou a ligar em nome de Henrique."
            ),
        )

        assert resp.text == (
            "Boa noite! Estou a ligar em nome de Henrique."
        )
        assert resp.latency_s == 0.0

    @pytest.mark.asyncio
    async def test_generates_greeting_via_gpt(self):
        """No custom greeting -> generates via GPT."""
        brain = CallBrain()
        brain._client = _mock_client(
            "Good evening! I'm calling on behalf of Henrique."
        )

        resp = await brain.generate_greeting(
            objective="Reserve table",
            user_name="Henrique",
            language="en",
        )

        assert "Henrique" in resp.text
        assert resp.latency_s >= 0

    @pytest.mark.asyncio
    async def test_fallback_greeting_on_error(self):
        """GPT error returns fallback greeting."""
        brain = CallBrain()
        mock = AsyncMock()
        mock.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("err")
        )
        brain._client = mock

        resp = await brain.generate_greeting(
            objective="Test",
            user_name="Henrique",
            language="pt",
        )

        assert "Henrique" in resp.text


# -- generate_goodbye tests ---------------------------------------------------


class TestGenerateGoodbye:
    @pytest.mark.asyncio
    async def test_generates_goodbye(self):
        brain = CallBrain()
        brain._client = _mock_client(
            "Muito obrigado pela ajuda! Boa noite!"
        )

        resp = await brain.generate_goodbye(
            language="pt", result="success"
        )

        assert resp.text != ""
        assert resp.should_end_call is True

    @pytest.mark.asyncio
    async def test_fallback_goodbye_on_error(self):
        brain = CallBrain()
        mock = AsyncMock()
        mock.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("err")
        )
        brain._client = mock

        resp = await brain.generate_goodbye(language="es")

        assert resp.text == _GOODBYE_FALLBACKS["es"]
        assert resp.should_end_call is True


# -- Language detection tests -------------------------------------------------


class TestLanguageDetection:
    def test_portuguese(self):
        assert (
            _detect_language_simple(
                "liga pro restaurante e reserva para 2"
            )
            == "pt"
        )

    def test_english(self):
        assert (
            _detect_language_simple(
                "call the restaurant and book a table"
            )
            == "en"
        )

    def test_spanish(self):
        assert (
            _detect_language_simple(
                "llama al restaurante y reserva para 2 personas"
            )
            == "es"
        )

    def test_mixed_defaults_to_english(self):
        assert _detect_language_simple("hello world") == "en"


# -- respond_to_session tests -------------------------------------------------


class TestRespondToSession:
    @pytest.mark.asyncio
    async def test_respond_to_session(self):
        """Convenience method uses session state."""
        brain = CallBrain()
        brain._client = _mock_client(
            "Sure, for 2 people at 8pm?"
        )

        mock_session = MagicMock()
        mock_session.objective = "Reserve table"
        mock_session.user_name = "Henrique"
        mock_session.language = "en"
        mock_session.extra_context = "2 people, 8pm"
        mock_session.get_conversation_history.return_value = []
        mock_session.get_last_user_message.return_value = (
            "Hi, I'd like to book"
        )

        resp = await brain.respond_to_session(mock_session)

        assert isinstance(resp, BrainResponse)
        assert resp.text != ""
