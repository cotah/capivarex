"""Tests for user_profile_service — persistent memory."""

from unittest.mock import AsyncMock, Mock, patch
import pytest


_SVC_PATH = "services.business.user_profile_service.get_service"


def _mock_db(user=None, personal=None):
    """Return a mock DatabaseService."""
    db = AsyncMock()
    db.is_initialized = Mock(return_value=True)
    db.initialize = AsyncMock()
    db.get_user_by_id = AsyncMock(return_value=user)
    db.get_user_context = AsyncMock(return_value=personal)
    db.save_user_context = AsyncMock(return_value=True)
    db.update_user_preferences = AsyncMock(return_value=True)
    return db


# ── build_user_profile_prompt ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_profile_no_db():
    """Returns empty string when database is not available."""
    from services.business.user_profile_service import build_user_profile_prompt

    with patch(_SVC_PATH, return_value=None):
        result = await build_user_profile_prompt("00000000-0000-0000-0000-000000000123")
    assert result == ""


@pytest.mark.asyncio
async def test_build_profile_with_name():
    """Returns profile block with user name."""
    from services.business.user_profile_service import build_user_profile_prompt

    db = _mock_db(user={"full_name": "Henrique", "preferred_language": "pt"})
    with patch(_SVC_PATH, return_value=db):
        result = await build_user_profile_prompt("00000000-0000-0000-0000-000000000123")
    assert "Henrique" in result
    assert "User Profile" in result
    assert "Language: pt" in result


@pytest.mark.asyncio
async def test_build_profile_with_personal_info():
    """Returns profile block with personal info from user_context."""
    from services.business.user_profile_service import build_user_profile_prompt

    db = _mock_db(
        user={"full_name": "João"},
        personal={"city": "Dublin", "job": "developer"},
    )
    with patch(_SVC_PATH, return_value=db):
        result = await build_user_profile_prompt("00000000-0000-0000-0000-000000000123")
    assert "João" in result
    assert "Dublin" in result
    assert "developer" in result


@pytest.mark.asyncio
async def test_build_profile_no_data():
    """Returns empty when user has no profile data."""
    from services.business.user_profile_service import build_user_profile_prompt

    db = _mock_db(user={}, personal=None)
    with patch(_SVC_PATH, return_value=db):
        result = await build_user_profile_prompt("00000000-0000-0000-0000-000000000123")
    assert result == ""


@pytest.mark.asyncio
async def test_build_profile_db_exception():
    """Returns empty when DB raises exception."""
    from services.business.user_profile_service import build_user_profile_prompt

    db = _mock_db()
    db.get_user_by_id = AsyncMock(side_effect=Exception("DB error"))
    with patch(_SVC_PATH, return_value=db):
        result = await build_user_profile_prompt("00000000-0000-0000-0000-000000000123")
    # Should not crash, returns empty since no data was gathered
    assert result == ""


# ── extract_and_save_personal_info ────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_no_trigger_keywords():
    """Skips extraction when no trigger keywords found."""
    from services.business.user_profile_service import extract_and_save_personal_info

    # No OpenAI call should be made
    with patch(_SVC_PATH) as mock_svc:
        await extract_and_save_personal_info("00000000-0000-0000-0000-000000000123", "what's the weather?")
    # get_service should not be called for openai since we skip early
    calls = [c for c in mock_svc.call_args_list if c[0][0] == "openai"]
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_extract_with_name_trigger():
    """Extracts and saves when user shares their name."""
    from services.business.user_profile_service import extract_and_save_personal_info

    # Mock OpenAI
    mock_response = Mock()
    mock_response.choices = [
        Mock(message=Mock(content='{"name": "Maria"}'))
    ]
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    openai_svc = AsyncMock()
    openai_svc.initialize = AsyncMock()
    openai_svc.get_client = Mock(return_value=mock_client)

    db = _mock_db(user={"full_name": None}, personal={})

    def side_effect(name):
        if name == "openai":
            return openai_svc
        if name == "database":
            return db
        return None

    with patch(_SVC_PATH, side_effect=side_effect):
        await extract_and_save_personal_info("00000000-0000-0000-0000-000000000123", "my name is Maria")

    db.save_user_context.assert_called_once()
    saved_data = db.save_user_context.call_args[0][2]
    assert saved_data["name"] == "Maria"
    # Also updates full_name since user didn't have one
    db.update_user_preferences.assert_called_once()


@pytest.mark.asyncio
async def test_extract_no_openai():
    """Gracefully handles missing OpenAI service."""
    from services.business.user_profile_service import extract_and_save_personal_info

    with patch(_SVC_PATH, return_value=None):
        # Should not raise
        await extract_and_save_personal_info("00000000-0000-0000-0000-000000000123", "my name is Test")


@pytest.mark.asyncio
async def test_extract_gpt_returns_empty():
    """Handles GPT returning empty JSON."""
    from services.business.user_profile_service import extract_and_save_personal_info

    mock_response = Mock()
    mock_response.choices = [Mock(message=Mock(content="{}"))]
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    openai_svc = AsyncMock()
    openai_svc.initialize = AsyncMock()
    openai_svc.get_client = Mock(return_value=mock_client)

    with patch(_SVC_PATH, return_value=openai_svc):
        # Should not raise, just return without saving
        await extract_and_save_personal_info("00000000-0000-0000-0000-000000000123", "meu nome é nada")


@pytest.mark.asyncio
async def test_extract_merges_with_existing():
    """New info merges with existing personal_info context."""
    from services.business.user_profile_service import extract_and_save_personal_info

    mock_response = Mock()
    mock_response.choices = [
        Mock(message=Mock(content='{"city": "Dublin"}'))
    ]
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    openai_svc = AsyncMock()
    openai_svc.initialize = AsyncMock()
    openai_svc.get_client = Mock(return_value=mock_client)

    db = _mock_db(user={"full_name": "João"}, personal={"name": "João"})

    def side_effect(name):
        if name == "openai":
            return openai_svc
        if name == "database":
            return db
        return None

    with patch(_SVC_PATH, side_effect=side_effect):
        await extract_and_save_personal_info("00000000-0000-0000-0000-000000000123", "i live in Dublin")

    db.save_user_context.assert_called_once()
    saved = db.save_user_context.call_args[0][2]
    # Should have both existing name and new city
    assert saved["name"] == "João"
    assert saved["city"] == "Dublin"
