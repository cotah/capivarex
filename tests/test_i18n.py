"""
Tests for the i18n package — strings, keywords, prompts.
"""

from services.i18n.strings import t, get_user_lang, STRINGS, SUPPORTED_LANGS
from services.i18n.keywords import (
    check_keywords,
    check_keywords_with_phone,
    VOICE_KEYWORDS,
    TWILIO_KEYWORDS,
    TRANSPORT_KEYWORDS,
    LEAVING_NOW_KEYWORDS,
    MERCADO_KEYWORDS,
)
from services.i18n.prompts import get_orchestrator_prompt, get_chat_prompt


# ═══════════════════════════════════════════════════════════════════════════
# STRINGS TESTS
# ═══════════════════════════════════════════════════════════════════════════


def test_t_english_default():
    assert t("error_processing") == "Sorry, I couldn't process your message right now."


def test_t_portuguese():
    result = t("error_processing", lang="pt")
    assert "Desculpe" in result


def test_t_spanish():
    result = t("error_processing", lang="es")
    assert "Lo siento" in result


def test_t_fallback_to_english():
    """Unknown lang falls back to English."""
    result = t("error_processing", lang="xx")
    assert "Sorry" in result


def test_t_unknown_key():
    """Unknown key returns the key itself."""
    assert t("nonexistent_key_xyz") == "nonexistent_key_xyz"


def test_t_with_placeholders():
    result = t("tts_error", lang="en", error="timeout")
    assert result == "Error generating audio: timeout"


def test_t_with_placeholders_pt():
    result = t("tts_error", lang="pt", error="timeout")
    assert result == "Erro ao gerar áudio: timeout"


def test_t_missing_placeholder_graceful():
    """If placeholder is missing, returns unformatted string."""
    result = t("tts_error", lang="en")  # no error= provided
    assert "{error}" in result or "Error generating audio" in result


def test_t_none_lang():
    """None lang defaults to English."""
    result = t("error_processing", lang=None)
    assert "Sorry" in result


def test_all_strings_have_three_langs():
    """Every string in the catalog must have en, pt, es."""
    missing = []
    for key, translations in STRINGS.items():
        for lang in SUPPORTED_LANGS:
            if lang not in translations:
                missing.append(f"{key} missing '{lang}'")
    assert not missing, f"Missing translations: {missing}"


def test_no_empty_translations():
    """No translation should be empty."""
    empty = []
    for key, translations in STRINGS.items():
        for lang, text in translations.items():
            if not text or not text.strip():
                empty.append(f"{key}[{lang}] is empty")
    assert not empty, f"Empty translations: {empty}"


# ═══════════════════════════════════════════════════════════════════════════
# USER LANGUAGE DETECTION TESTS
# ═══════════════════════════════════════════════════════════════════════════


def test_get_user_lang_default():
    assert get_user_lang({}) == "en"
    assert get_user_lang(None) == "en"


def test_get_user_lang_explicit():
    assert get_user_lang({"lang": "pt"}) == "pt"
    assert get_user_lang({"lang": "es"}) == "es"


def test_get_user_lang_telegram():
    assert get_user_lang({"language_code": "pt-BR"}) == "pt"
    assert get_user_lang({"language_code": "es"}) == "es"
    assert get_user_lang({"language_code": "en-US"}) == "en"


def test_get_user_lang_preferences():
    ctx = {"user_preferences": {"language": "es"}}
    assert get_user_lang(ctx) == "es"


def test_get_user_lang_preferred_language():
    """preferred_language column name (alternative to language)."""
    ctx = {"user_preferences": {"preferred_language": "pt"}}
    assert get_user_lang(ctx) == "pt"


def test_get_user_lang_prefs_not_dict():
    """user_preferences that isn't a dict should not crash."""
    ctx = {"user_preferences": "pt"}
    assert get_user_lang(ctx) == "en"


def test_get_user_lang_prefs_unsupported():
    """Unsupported language in preferences falls back."""
    ctx = {"user_preferences": {"language": "ja"}}
    assert get_user_lang(ctx) == "en"


def test_get_user_lang_priority():
    """Explicit lang > preferences > telegram."""
    ctx = {
        "lang": "es",
        "user_preferences": {"language": "pt"},
        "language_code": "en",
    }
    assert get_user_lang(ctx) == "es"


def test_get_user_lang_unsupported_falls_back():
    assert get_user_lang({"language_code": "ja"}) == "en"
    assert get_user_lang({"language_code": "zh"}) == "en"


# ═══════════════════════════════════════════════════════════════════════════
# KEYWORD TESTS
# ═══════════════════════════════════════════════════════════════════════════


def test_twilio_keywords_pt():
    assert check_keywords("liga para o +353894434456", TWILIO_KEYWORDS)
    assert check_keywords("faz uma chamada para a Maria", TWILIO_KEYWORDS)


def test_twilio_keywords_en():
    assert check_keywords("call +1234567890", TWILIO_KEYWORDS)
    assert check_keywords("make a call to John", TWILIO_KEYWORDS)
    assert check_keywords("phone call to the office", TWILIO_KEYWORDS)


def test_twilio_keywords_es():
    assert check_keywords("llama al +34612345678", TWILIO_KEYWORDS)
    assert check_keywords("haz una llamada a María", TWILIO_KEYWORDS)


def test_twilio_keywords_no_match():
    assert not check_keywords("what's the weather?", TWILIO_KEYWORDS)
    assert not check_keywords("Eu te amo", TWILIO_KEYWORDS)


def test_voice_keywords_pt():
    assert check_keywords("manda um audio dizendo Eu te amo", VOICE_KEYWORDS)
    assert check_keywords("faz um áudio falando bom dia", VOICE_KEYWORDS)


def test_voice_keywords_en():
    assert check_keywords("send an audio saying hello", VOICE_KEYWORDS)
    assert check_keywords("create audio message", VOICE_KEYWORDS)
    assert check_keywords("text to speech please", VOICE_KEYWORDS)


def test_voice_keywords_es():
    assert check_keywords("manda un audio diciendo hola", VOICE_KEYWORDS)
    assert check_keywords("envía un audio por favor", VOICE_KEYWORDS)


def test_transport_keywords_pt():
    assert check_keywords("próximo autocarro para o centro", TRANSPORT_KEYWORDS)
    assert check_keywords("horário do DART hoje", TRANSPORT_KEYWORDS)


def test_transport_keywords_en():
    assert check_keywords("next bus to city centre", TRANSPORT_KEYWORDS)
    assert check_keywords("Dublin Bus schedule", TRANSPORT_KEYWORDS)
    assert check_keywords("DART train times", TRANSPORT_KEYWORDS)


def test_transport_keywords_es():
    assert check_keywords("próximo autobús al centro", TRANSPORT_KEYWORDS)


def test_leaving_now_keywords():
    assert check_keywords("when should i leave for the meeting?", LEAVING_NOW_KEYWORDS)
    assert check_keywords("quando devo sair para a reunião?", LEAVING_NOW_KEYWORDS)
    assert check_keywords("cuándo debo salir para la reunión?", LEAVING_NOW_KEYWORDS)


def test_mercado_keywords():
    assert check_keywords("add milk to shopping list", MERCADO_KEYWORDS)
    assert check_keywords("lista de compras do supermercado", MERCADO_KEYWORDS)
    assert check_keywords("lista de compras del supermercado", MERCADO_KEYWORDS)


def test_phone_with_keywords():
    assert check_keywords_with_phone("call +353 89 443 4456")
    assert check_keywords_with_phone("liga +351912345678")
    assert check_keywords_with_phone("llama al +34612345678")
    assert not check_keywords_with_phone("+353 89 443 4456")  # no call word
    assert not check_keywords_with_phone("call me back")  # no phone number


# ═══════════════════════════════════════════════════════════════════════════
# PROMPTS TESTS
# ═══════════════════════════════════════════════════════════════════════════


def test_orchestrator_prompt_is_english():
    prompt = get_orchestrator_prompt()
    assert "You are an AI orchestrator" in prompt
    assert "'chat'" in prompt
    assert "'twilio'" in prompt
    assert "'transport'" in prompt


def test_orchestrator_prompt_has_all_agents():
    prompt = get_orchestrator_prompt()
    expected_agents = [
        "chat",
        "research",
        "dev",
        "github",
        "weather",
        "finance",
        "image",
        "video",
        "voice",
        "calendar",
        "meeting",
        "traffic",
        "car",
        "smarthome",
        "time",
        "translate",
        "crypto",
        "timer",
        "reminder",
        "youtube",
        "tracking",
        "search",
        "transport",
        "leaving_now",
        "mercado",
        "notes",
        "restaurant",
        "email",
        "twilio",
    ]
    for agent in expected_agents:
        assert f"'{agent}'" in prompt, (
            f"Agent '{agent}' missing from orchestrator prompt"
        )


def test_chat_prompt_english():
    prompt = get_chat_prompt("en")
    assert "Capivarex" in prompt
    assert "English" in prompt


def test_chat_prompt_portuguese():
    prompt = get_chat_prompt("pt")
    assert "Capivarex" in prompt
    assert "português" in prompt


def test_chat_prompt_spanish():
    prompt = get_chat_prompt("es")
    assert "Capivarex" in prompt
    assert "español" in prompt


def test_chat_prompt_fallback():
    prompt = get_chat_prompt("xx")
    assert "English" in prompt  # Falls back to EN


# ═══════════════════════════════════════════════════════════════════════════
# STRING CATALOG COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════════


def test_service_unavailable_strings_for_all_agents():
    """Each agent that has a service should have an unavailable string."""
    agents_with_services = [
        "calendar",
        "weather",
        "finance",
        "crypto",
        "image",
        "video",
        "traffic",
        "car",
        "smarthome",
        "research",
        "restaurant",
        "youtube",
        "tracking",
        "mercado",
        "transport",
        "email",
        "translate",
        "github",
        "dev",
    ]
    missing = []
    for agent in agents_with_services:
        key = f"{agent}_service_unavailable"
        if key not in STRINGS:
            missing.append(key)
    assert not missing, f"Missing service_unavailable strings: {missing}"


# ═══════════════════════════════════════════════════════════════════════════
# HOTEL / TRAVEL I18N STRINGS
# ═══════════════════════════════════════════════════════════════════════════


def test_get_chat_prompt_pt():
    result = get_chat_prompt("pt")
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_chat_prompt_none_fallback():
    result = get_chat_prompt(None)
    assert isinstance(result, str)
    assert len(result) > 0


def test_models_schemas_import():
    """Ensure models/schemas.py can be imported successfully."""
    from models.schemas import UserBase

    u = UserBase(email="a@b.com")
    assert u.email == "a@b.com"


def test_hotel_need_location_all_langs():
    for lang in SUPPORTED_LANGS:
        result = t("hotel_need_location", lang=lang)
        assert "hotel" in result.lower() or "hotéis" in result.lower() or "hoteles" in result.lower()


def test_hotel_need_dates_all_langs():
    for lang in SUPPORTED_LANGS:
        result = t("hotel_need_dates", lang=lang)
        assert "check-in" in result.lower() or "check_in" in result.lower()


def test_hotel_search_result_en():
    result = t(
        "hotel_search_result",
        lang="en",
        city="Dublin",
        checkin="April 15",
        checkout="April 18",
        adults=2,
        rooms=1,
        url="https://www.booking.com/searchresults.html?ss=Dublin",
    )
    assert "Dublin" in result
    assert "April 15" in result
    assert "Booking.com" in result


def test_hotel_search_result_pt():
    result = t(
        "hotel_search_result",
        lang="pt",
        city="Lisboa",
        checkin="15 de abril",
        checkout="18 de abril",
        adults=2,
        rooms=1,
        url="https://www.booking.com/searchresults.html?ss=Lisboa",
    )
    assert "Lisboa" in result
    assert "Booking.com" in result
