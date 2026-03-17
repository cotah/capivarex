"""Tests for Smart Follow-up service."""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.smart_followup_service import (
    detect_followable_event,
    store_followup,
    check_pending_followups,
    mark_followup_done,
    generate_followup_message,
    _generate_fallback_followup,
    _load_followups,
)


class TestDetectFollowableEvent:
    def test_doctor_pt(self):
        result = detect_followable_event("Amanhã tenho uma consulta no médico")
        assert result is not None
        assert result["category"] == "health"

    def test_dentist_pt(self):
        result = detect_followable_event("Vou ao dentista amanhã")
        assert result is not None
        assert result["category"] == "health"

    def test_interview_pt(self):
        result = detect_followable_event("Tenho uma entrevista de emprego amanhã")
        assert result is not None
        assert result["category"] == "career"

    def test_interview_en(self):
        result = detect_followable_event("I have a job interview tomorrow")
        assert result is not None
        assert result["category"] == "career"

    def test_exam_pt(self):
        result = detect_followable_event("Minha prova é amanhã")
        assert result is not None
        assert result["category"] == "education"

    def test_travel_pt(self):
        result = detect_followable_event("Viajo amanhã para Lisboa")
        assert result is not None
        assert result["category"] == "travel"

    def test_wedding(self):
        result = detect_followable_event("Casamento da minha prima no sábado")
        assert result is not None
        assert result["category"] == "social"

    def test_presentation(self):
        result = detect_followable_event("Tenho uma apresentação importante amanhã")
        assert result is not None
        assert result["category"] == "work"

    def test_deadline(self):
        result = detect_followable_event("O deadline é amanhã")
        assert result is not None
        assert result["category"] == "work"

    def test_general_tomorrow(self):
        result = detect_followable_event("Amanhã tenho uma coisa importante")
        assert result is not None
        assert result["category"] == "general"

    def test_next_week(self):
        result = detect_followable_event("Semana que vem tenho algo importante")
        assert result is not None
        assert result["days_until_followup"] == 7

    def test_not_followable(self):
        assert detect_followable_event("Qual a previsão do tempo?") is None

    def test_too_short(self):
        assert detect_followable_event("oi") is None

    def test_empty(self):
        assert detect_followable_event("") is None

    def test_stores_original(self):
        result = detect_followable_event("Vou ao médico amanhã fazer exames de sangue")
        assert "Vou ao médico" in result["original_message"]


class TestStoreFollowup:
    @pytest.mark.asyncio
    async def test_store_no_db(self):
        with patch("services.business.smart_followup_service.get_service", return_value=None):
            result = await store_followup("u1", {"category": "health", "days_until_followup": 1, "original_message": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_store_success(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"value": "[]"}])
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.business.smart_followup_service.get_service", return_value=mock_db):
            result = await store_followup("u1", {"category": "health", "days_until_followup": 1, "original_message": "test"})
        assert result is True

    @pytest.mark.asyncio
    async def test_store_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("DB error")
        with patch("services.business.smart_followup_service.get_service", return_value=mock_db):
            result = await store_followup("u1", {"category": "test"})
        assert result is False


class TestCheckPending:
    @pytest.mark.asyncio
    async def test_no_followups(self):
        with patch("services.business.smart_followup_service._load_followups", new_callable=AsyncMock, return_value=[]):
            result = await check_pending_followups("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_pending_found(self):
        followups = [
            {"id": "fu_1", "followup_at": time.time() - 100, "done": False, "category": "health"},
            {"id": "fu_2", "followup_at": time.time() + 86400, "done": False, "category": "travel"},
            {"id": "fu_3", "followup_at": time.time() - 200, "done": True, "category": "career"},
        ]
        with patch("services.business.smart_followup_service._load_followups", new_callable=AsyncMock, return_value=followups):
            result = await check_pending_followups("u1")
        assert len(result) == 1
        assert result[0]["id"] == "fu_1"


class TestMarkDone:
    @pytest.mark.asyncio
    async def test_mark_done(self):
        followups = [{"id": "fu_1", "done": False}]
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with (
            patch("services.business.smart_followup_service._load_followups", new_callable=AsyncMock, return_value=followups),
            patch("services.business.smart_followup_service.get_service", return_value=mock_db),
        ):
            await mark_followup_done("u1", "fu_1")
        assert followups[0]["done"] is True

    @pytest.mark.asyncio
    async def test_mark_done_exception(self):
        with (
            patch("services.business.smart_followup_service._load_followups", new_callable=AsyncMock, side_effect=Exception("err")),
        ):
            await mark_followup_done("u1", "fu_1")  # Should not raise


class TestFallbackFollowup:
    def test_health(self):
        msg = _generate_fallback_followup("João", "health", "consulta no médico")
        assert "consulta" in msg.lower() or "médico" in msg.lower() or "🏥" in msg

    def test_career(self):
        msg = _generate_fallback_followup("Ana", "career", "entrevista de emprego")
        assert "entrevista" in msg.lower() or "🤞" in msg

    def test_education(self):
        msg = _generate_fallback_followup("", "education", "prova amanhã")
        assert "prova" in msg.lower() or "📚" in msg

    def test_travel(self):
        msg = _generate_fallback_followup("João", "travel", "viajo para Lisboa")
        assert "viagem" in msg.lower() or "✈️" in msg

    def test_social(self):
        msg = _generate_fallback_followup("", "social", "casamento")
        assert "evento" in msg.lower() or "🎉" in msg

    def test_work(self):
        msg = _generate_fallback_followup("João", "work", "apresentação")
        assert "apresentação" in msg.lower() or "💼" in msg

    def test_unknown(self):
        msg = _generate_fallback_followup("João", "unknown", "something")
        assert "💭" in msg


class TestGenerateFollowupMessage:
    @pytest.mark.asyncio
    async def test_fallback(self):
        with patch("services.business.smart_followup_service.get_service", return_value=None):
            msg = await generate_followup_message("João", {"category": "health", "original_message": "médico"})
        assert len(msg) > 10

    @pytest.mark.asyncio
    async def test_with_ai(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = "Oi João! Como foi no médico? 🏥"
        with patch("services.business.smart_followup_service.get_service", return_value=mock_openai):
            msg = await generate_followup_message("João", {"category": "health", "original_message": "médico"})
        assert "médico" in msg.lower()


class TestLoadFollowups:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.smart_followup_service.get_service", return_value=None):
            assert await _load_followups("u1") == []

    @pytest.mark.asyncio
    async def test_with_data(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": '[{"id": "fu_1", "category": "health"}]'}]
        )
        with patch("services.business.smart_followup_service.get_service", return_value=mock_db):
            result = await _load_followups("u1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.smart_followup_service.get_service", return_value=mock_db):
            assert await _load_followups("u1") == []
