"""Tests for Mood Detection service."""
import pytest
from unittest.mock import MagicMock, patch

from services.business.mood_detection_service import (
    detect_mood,
    get_tone_instruction,
    save_mood,
    get_mood_trend,
    _detect_emoji_mood,
    _detect_keyword_mood,
    _detect_pattern_mood,
)


class TestDetectMood:
    def test_excited_keywords(self):
        result = detect_mood("CONSEGUI O EMPREGO!!!")
        assert result["mood"] == "excited"
        assert result["score"] > 0.5

    def test_happy_keywords(self):
        result = detect_mood("Estou muito feliz hoje, dia ótimo!")
        assert result["mood"] == "happy"

    def test_sad_keywords(self):
        result = detect_mood("Hoje está difícil, estou triste")
        assert result["mood"] == "sad"
        assert result["score"] < 0

    def test_angry_keywords(self):
        result = detect_mood("Que absurdo, estou com muita raiva")
        assert result["mood"] == "angry"

    def test_stressed_keywords(self):
        result = detect_mood("Estou muito estressado e cansado")
        assert result["mood"] == "stressed"

    def test_anxious_keywords(self):
        result = detect_mood("Estou muito nervoso e preocupado")
        assert result["mood"] == "anxious"

    def test_neutral(self):
        result = detect_mood("Qual a previsão do tempo amanhã?")
        assert result["mood"] == "neutral"

    def test_empty(self):
        result = detect_mood("")
        assert result["mood"] == "neutral"

    def test_short(self):
        result = detect_mood("a")
        assert result["mood"] == "neutral"

    def test_emoji_happy(self):
        result = detect_mood("Tudo bem 😊")
        assert result["mood"] == "happy"

    def test_emoji_sad(self):
        result = detect_mood("😢")
        assert result["mood"] == "sad"

    def test_emoji_excited(self):
        result = detect_mood("🎉🎉🎉")
        assert result["mood"] == "excited"

    def test_emoji_angry(self):
        result = detect_mood("Não acredito 😡")
        assert result["mood"] == "angry"

    def test_all_caps_excited(self):
        result = detect_mood("PASSEI NA PROVA!!!")
        assert result["mood"] == "excited"

    def test_ellipsis_sad(self):
        result = detect_mood("hmm...")
        assert result["mood"] == "sad"

    def test_multiple_questions_anxious(self):
        result = detect_mood("Será que vai dar certo? E se não der?")
        assert result["mood"] == "anxious"

    def test_english_happy(self):
        result = detect_mood("I'm feeling great and wonderful today!")
        assert result["mood"] == "happy"

    def test_english_sad(self):
        result = detect_mood("I feel terrible and lonely")
        assert result["mood"] == "sad"

    def test_combined_emoji_keyword(self):
        result = detect_mood("Consegui a vaga! 🎉")
        assert result["mood"] == "excited"
        assert result["confidence"] >= 0.8

    def test_confidence_high_multiple_keywords(self):
        result = detect_mood("Muito feliz, contente e grato, dia ótimo!")
        assert result["confidence"] >= 0.6


class TestDetectEmojiMood:
    def test_happy_emoji(self):
        assert _detect_emoji_mood("Hello 😊") == "happy"

    def test_sad_emoji(self):
        assert _detect_emoji_mood("😭 bad day") == "sad"

    def test_no_emoji(self):
        assert _detect_emoji_mood("no emojis here") is None

    def test_fire_emoji(self):
        assert _detect_emoji_mood("🔥") == "excited"

    def test_stressed_emoji(self):
        assert _detect_emoji_mood("😩") == "stressed"


class TestDetectKeywordMood:
    def test_happy(self):
        mood, count = _detect_keyword_mood("feliz e contente")
        assert mood == "happy"
        assert count >= 2

    def test_no_keywords(self):
        mood, count = _detect_keyword_mood("olá mundo")
        assert count == 0

    def test_angry(self):
        mood, count = _detect_keyword_mood("que raiva e ódio")
        assert mood == "angry"


class TestDetectPatternMood:
    def test_all_caps_with_exclamation(self):
        assert _detect_pattern_mood("THIS IS AMAZING!!!") == "excited"

    def test_all_caps_no_exclamation(self):
        assert _detect_pattern_mood("I AM SO DONE WITH THIS") == "angry"

    def test_triple_exclamation(self):
        assert _detect_pattern_mood("yes yes yes!!!") == "excited"

    def test_ellipsis_short(self):
        assert _detect_pattern_mood("ok then...") == "sad"

    def test_double_question(self):
        assert _detect_pattern_mood("really? are you sure?") == "anxious"

    def test_normal(self):
        assert _detect_pattern_mood("Hello there") is None


class TestToneInstruction:
    def test_excited(self):
        result = {"mood": "excited", "confidence": 0.8, "tone_guidance": "enthusiastic"}
        instruction = get_tone_instruction(result)
        assert "enthusiastic" in instruction.lower() or "excited" in instruction.lower()

    def test_sad(self):
        result = {"mood": "sad", "confidence": 0.7, "tone_guidance": "empathetic"}
        instruction = get_tone_instruction(result)
        assert "empathetic" in instruction.lower() or "gentle" in instruction.lower()

    def test_low_confidence(self):
        result = {"mood": "angry", "confidence": 0.2, "tone_guidance": "patient"}
        instruction = get_tone_instruction(result)
        assert instruction == ""

    def test_neutral(self):
        result = {"mood": "neutral", "confidence": 0.5, "tone_guidance": "friendly"}
        instruction = get_tone_instruction(result)
        assert instruction == ""

    def test_stressed(self):
        result = {"mood": "stressed", "confidence": 0.6, "tone_guidance": "supportive"}
        instruction = get_tone_instruction(result)
        assert "supportive" in instruction.lower() or "soothing" in instruction.lower()


class TestSaveMood:
    @pytest.mark.asyncio
    async def test_save_no_db(self):
        with patch("services.business.mood_detection_service.get_service", return_value=None):
            await save_mood("u1", {"mood": "happy", "score": 0.7, "confidence": 0.8})

    @pytest.mark.asyncio
    async def test_save_success(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"value": "[]"}])
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.business.mood_detection_service.get_service", return_value=mock_db):
            await save_mood("u1", {"mood": "happy", "score": 0.7, "confidence": 0.8})

    @pytest.mark.asyncio
    async def test_save_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.mood_detection_service.get_service", return_value=mock_db):
            await save_mood("u1", {"mood": "sad", "score": -0.7, "confidence": 0.5})


class TestMoodTrend:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.mood_detection_service.get_service", return_value=None):
            assert await get_mood_trend("u1") is None

    @pytest.mark.asyncio
    async def test_not_enough_data(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": '[{"score": 0.5, "timestamp": 1}]'}]
        )
        with patch("services.business.mood_detection_service.get_service", return_value=mock_db):
            assert await get_mood_trend("u1") is None

    @pytest.mark.asyncio
    async def test_improving(self):
        history = [
            {"score": -0.5, "timestamp": 1},
            {"score": -0.3, "timestamp": 2},
            {"score": -0.2, "timestamp": 3},
            {"score": 0.3, "timestamp": 4},
            {"score": 0.5, "timestamp": 5},
            {"score": 0.7, "timestamp": 6},
        ]
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": str(history).replace("'", '"')}]
        )
        with patch("services.business.mood_detection_service.get_service", return_value=mock_db):
            assert await get_mood_trend("u1") == "improving"

    @pytest.mark.asyncio
    async def test_declining(self):
        import json
        history = [
            {"score": 0.7, "timestamp": 1},
            {"score": 0.5, "timestamp": 2},
            {"score": 0.3, "timestamp": 3},
            {"score": -0.3, "timestamp": 4},
            {"score": -0.5, "timestamp": 5},
            {"score": -0.7, "timestamp": 6},
        ]
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps(history)}]
        )
        with patch("services.business.mood_detection_service.get_service", return_value=mock_db):
            assert await get_mood_trend("u1") == "declining"

    @pytest.mark.asyncio
    async def test_stable(self):
        import json
        history = [
            {"score": 0.0, "timestamp": 1},
            {"score": 0.1, "timestamp": 2},
            {"score": -0.1, "timestamp": 3},
            {"score": 0.0, "timestamp": 4},
            {"score": 0.1, "timestamp": 5},
            {"score": 0.0, "timestamp": 6},
        ]
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps(history)}]
        )
        with patch("services.business.mood_detection_service.get_service", return_value=mock_db):
            assert await get_mood_trend("u1") == "stable"

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.mood_detection_service.get_service", return_value=mock_db):
            assert await get_mood_trend("u1") is None
