"""Tests for implicit action detection service — S7: Voice/Text → Notes + Reminders."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.implicit_action_service import (
    detect_implicit_action,
    detect_implicit_action_gpt,
    execute_implicit_action,
    check_and_execute_implicit_action,
    _humanize_confirmation,
)


class TestKeywordDetection:
    """Tests for fast keyword-based action detection."""

    def test_detect_note_pt(self):
        assert detect_implicit_action("nota que o Pedro disse 50k") == "note"

    def test_detect_note_en(self):
        assert detect_implicit_action("take note that the meeting is at 3") == "note"

    def test_detect_reminder_pt(self):
        assert detect_implicit_action("lembra-me amanhã de ligar ao banco") == "reminder"

    def test_detect_reminder_en(self):
        assert detect_implicit_action("remind me to call the bank tomorrow") == "reminder"

    def test_detect_calendar_pt(self):
        assert detect_implicit_action("agenda reunião com a Ana sexta") == "calendar"

    def test_detect_calendar_en(self):
        assert detect_implicit_action("schedule a meeting with John on Friday") == "calendar"

    def test_detect_shopping(self):
        assert detect_implicit_action("tenho que comprar leite e pão") == "shopping"

    def test_detect_shopping_en(self):
        assert detect_implicit_action("shopping list: milk, bread, eggs") == "shopping"

    def test_detect_none(self):
        assert detect_implicit_action("que horas são?") is None

    def test_detect_none_greeting(self):
        assert detect_implicit_action("bom dia, como estás?") is None

    def test_reminder_before_note(self):
        """Reminder keywords should take priority over note keywords."""
        assert detect_implicit_action("lembra-me de anotar o orçamento") == "reminder"

    def test_dont_forget(self):
        assert detect_implicit_action("não esquecer de enviar o relatório") == "reminder"

    def test_anota(self):
        assert detect_implicit_action("anota: o cliente quer entrega até sexta") == "note"

    def test_marca_reuniao(self):
        assert detect_implicit_action("marca reunião com o João amanhã") == "calendar"

    def test_buy_list(self):
        assert detect_implicit_action("preciso de comprar arroz e feijão") == "shopping"


class TestGPTDetection:
    """Tests for GPT-based detection."""

    @pytest.mark.asyncio
    async def test_gpt_fallback_to_keywords(self):
        """When GPT unavailable, falls back to keyword detection."""
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await detect_implicit_action_gpt("nota que o budget é 50k")
        assert result is not None
        assert result["action"] == "note"

    @pytest.mark.asyncio
    async def test_gpt_no_action(self):
        """Returns None for regular messages when GPT unavailable."""
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await detect_implicit_action_gpt("que horas são?")
        assert result is None


class TestExecuteAction:
    """Tests for action execution."""

    @pytest.mark.asyncio
    async def test_execute_note(self):
        """Execute note action via notes agent."""
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=MagicMock(response="Note saved"))

        with (
            patch("services.business.implicit_action_service.get_service", return_value=None),
            patch("agents.core.get_agent", return_value=mock_agent),
        ):
            result = await execute_implicit_action(
                user_id="u1",
                action_data={"action": "note", "content": "Budget is 50k", "time": "", "title": "Budget"},
                user_name="Marcos",
            )

        assert result is not None
        assert "Marcos" in result or "50k" in result or "📝" in result

    @pytest.mark.asyncio
    async def test_execute_reminder(self):
        """Execute reminder action via reminder agent."""
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=MagicMock(response="Reminder set"))

        with (
            patch("services.business.implicit_action_service.get_service", return_value=None),
            patch("agents.core.get_agent", return_value=mock_agent),
        ):
            result = await execute_implicit_action(
                user_id="u1",
                action_data={"action": "reminder", "content": "Call bank", "time": "tomorrow 10:00", "title": ""},
                user_name="Ana",
            )

        assert result is not None
        assert "Ana" in result or "⏰" in result

    @pytest.mark.asyncio
    async def test_execute_calendar(self):
        """Execute calendar action."""
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=MagicMock(response="Event created"))

        with (
            patch("services.business.implicit_action_service.get_service", return_value=None),
            patch("agents.core.get_agent", return_value=mock_agent),
        ):
            result = await execute_implicit_action(
                user_id="u1",
                action_data={"action": "calendar", "content": "Meeting with Ana", "time": "Friday 15:00", "title": "Meeting Ana"},
                user_name="Marcos",
            )

        assert result is not None
        assert "📅" in result or "Marcos" in result

    @pytest.mark.asyncio
    async def test_execute_shopping(self):
        """Execute shopping list (stored as note)."""
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=MagicMock(response="List saved"))

        with (
            patch("services.business.implicit_action_service.get_service", return_value=None),
            patch("agents.core.get_agent", return_value=mock_agent),
        ):
            result = await execute_implicit_action(
                user_id="u1",
                action_data={"action": "shopping", "content": "milk, bread, eggs", "time": "", "title": ""},
                user_name="Test",
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_no_agent(self):
        """Returns None when agent not available."""
        with (
            patch("services.business.implicit_action_service.get_service", return_value=None),
            patch("agents.core.get_agent", return_value=None),
        ):
            result = await execute_implicit_action(
                user_id="u1",
                action_data={"action": "note", "content": "test", "time": "", "title": ""},
                user_name="Test",
            )

        assert result is None


class TestMainEntryPoint:
    """Tests for check_and_execute_implicit_action."""

    @pytest.mark.asyncio
    async def test_keyword_match_executes(self):
        """Keyword match triggers execution."""
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=MagicMock(response="Done"))

        with (
            patch("services.business.implicit_action_service.get_service", return_value=None),
            patch("agents.core.get_agent", return_value=mock_agent),
        ):
            result = await check_and_execute_implicit_action(
                user_id="u1",
                message="nota que o orçamento é 50k",
                user_name="Marcos",
                use_gpt=False,
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        """Regular message returns None."""
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await check_and_execute_implicit_action(
                user_id="u1",
                message="que horas são?",
                user_name="Marcos",
                use_gpt=False,
            )

        assert result is None


class TestHumanizedConfirmation:
    """Tests for humanized confirmations."""

    @pytest.mark.asyncio
    async def test_note_fallback(self):
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await _humanize_confirmation("Marcos", "note", "Budget is 50k")
        assert "📝" in result
        assert "Marcos" in result

    @pytest.mark.asyncio
    async def test_reminder_fallback(self):
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await _humanize_confirmation("Ana", "reminder", "Call bank", "tomorrow 10:00")
        assert "⏰" in result
        assert "Ana" in result

    @pytest.mark.asyncio
    async def test_calendar_fallback(self):
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await _humanize_confirmation("Test", "calendar", "Meeting", "Friday 15:00")
        assert "📅" in result

    @pytest.mark.asyncio
    async def test_shopping_fallback(self):
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await _humanize_confirmation("Test", "shopping", "milk and bread")
        assert "🛒" in result

    @pytest.mark.asyncio
    async def test_unknown_type_fallback(self):
        with patch("services.business.implicit_action_service.get_service", return_value=None):
            result = await _humanize_confirmation("Test", "unknown", "stuff")
        assert "✅" in result


class TestEdgeCases:
    """Edge case tests for extra coverage."""

    @pytest.mark.asyncio
    async def test_gpt_detection_with_mock_openai(self):
        """GPT detection parses response correctly."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = '{"action": "note", "content": "Budget is 50k", "time": "", "title": "Budget"}'

        with patch("services.business.implicit_action_service.get_service", return_value=mock_openai):
            result = await detect_implicit_action_gpt("the budget is 50k according to Pedro")

        assert result is not None
        assert result["action"] == "note"

    @pytest.mark.asyncio
    async def test_gpt_returns_none_action(self):
        """GPT returns none action for regular messages."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = '{"action": "none", "content": "", "time": "", "title": ""}'

        with patch("services.business.implicit_action_service.get_service", return_value=mock_openai):
            result = await detect_implicit_action_gpt("hello, how are you?")

        assert result is None

    @pytest.mark.asyncio
    async def test_gpt_detection_exception(self):
        """GPT exception falls back to keywords."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.side_effect = Exception("API error")

        with patch("services.business.implicit_action_service.get_service", return_value=mock_openai):
            result = await detect_implicit_action_gpt("nota que o budget é 50k")

        assert result is not None
        assert result["action"] == "note"

    @pytest.mark.asyncio
    async def test_main_entry_with_gpt_fallback(self):
        """Main entry uses GPT when keywords don't match."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = '{"action": "none", "content": "", "time": "", "title": ""}'

        with patch("services.business.implicit_action_service.get_service", return_value=mock_openai):
            result = await check_and_execute_implicit_action(
                user_id="u1",
                message="hello world",
                user_name="Test",
                use_gpt=True,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self):
        """Unknown action type returns None gracefully."""
        result = await execute_implicit_action(
            user_id="u1",
            action_data={"action": "unknown_type", "content": "test"},
            user_name="Test",
        )
        assert result is None
