"""
Capivarex i18n — Internationalization package.

Usage:
    from services.i18n import t, get_user_lang

    lang = get_user_lang(context)
    msg = t("error_processing", lang=lang)
    msg = t("twilio_call_success", lang=lang, to="+353...", from_num="+1...")
"""

try:
    from services.i18n.strings import t, get_user_lang, SUPPORTED_LANGS, DEFAULT_LANG
    from services.i18n.keywords import (
        check_keywords,
        VOICE_KEYWORDS,
        TWILIO_KEYWORDS,
        TRANSPORT_KEYWORDS,
    )
except ImportError:
    from .strings import t, get_user_lang, SUPPORTED_LANGS, DEFAULT_LANG
    from .keywords import (
        check_keywords,
        VOICE_KEYWORDS,
        TWILIO_KEYWORDS,
        TRANSPORT_KEYWORDS,
    )

__all__ = [
    "t",
    "get_user_lang",
    "SUPPORTED_LANGS",
    "DEFAULT_LANG",
    "check_keywords",
    "VOICE_KEYWORDS",
    "TWILIO_KEYWORDS",
    "TRANSPORT_KEYWORDS",
]
