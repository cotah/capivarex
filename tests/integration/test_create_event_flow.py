"""
Integration test for the complete create event flow — refactored architecture.

Flow: PromptCleanerService → CalendarAgent → CalendarService
"""

import pytest

from agents.specialized.calendar_agent import CalendarAgent
from services.business.prompt_cleaner import PromptCleanerService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_create_event_flow(
    mock_openai_client,
    mock_calendar_service,
    sample_context,
):
    """Test complete flow: PromptCleaner → CalendarAgent → CalendarService."""
    # Step 1: Clean the user prompt
    cleaner = PromptCleanerService()
    cleaner._initialized = True
    cleaner._openai_client = mock_openai_client

    cleaned = await cleaner._clean_calendar(
        "Agendar um evento de reunião amanhã às 15 horas em Cork",
        sample_context,
    )

    assert cleaned["action"] == "create_event"
    assert "event_params" in cleaned

    # Step 2: Pass cleaned data to the CalendarAgent
    agent = CalendarAgent()
    agent._calendar_service = mock_calendar_service

    context_with_params = {
        **sample_context,
        "action": cleaned["action"],
        "event_params": cleaned["event_params"],
    }

    result = await agent.execute(
        "Agendar um evento de reunião amanhã às 15 horas em Cork",
        context_with_params,
    )

    assert result.is_success()
    assert "event" in result.data
    mock_calendar_service.async_create_event.assert_called_once()
