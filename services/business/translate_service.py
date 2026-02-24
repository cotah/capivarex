# -*- coding: utf-8 -*-
"""
Translate Service
=================
Tradução de textos usando a API Google Generative AI (google-genai nova SDK),
que já está no requirements.txt do projeto.

Estratégia:
  - Usa o modelo Gemini 2.0 Flash (mais rápido e barato para traduções)
  - Detecta idioma de origem automaticamente quando não especificado
  - Suporta todos os idiomas que o Gemini conhece (~100+)
  - Cache simples em memória (LRU) para evitar chamadas repetidas
  - Usa mesma SDK que image_service e video_service (google-genai)

FIX [2025-02]: Migrado de google.generativeai (SDK antiga, deprecated)
               para google.genai (nova SDK unificada). A antiga retornava
               404 "model not found" no ambiente de produção Railway porque
               só a nova SDK (google-genai) está instalada no requirements.txt.
"""

import hashlib
import logging
import os
import time
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()
logger = logging.getLogger(__name__)

# Idiomas suportados com seus nomes em PT-BR
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "pt": "Português",
    "en": "Inglês",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
    "ja": "Japonês",
    "ko": "Coreano",
    "zh": "Chinês",
    "ru": "Russo",
    "ar": "Árabe",
    "hi": "Hindi",
    "nl": "Holandês",
    "pl": "Polonês",
    "tr": "Turco",
    "sv": "Sueco",
    "da": "Dinamarquês",
    "fi": "Finlandês",
    "no": "Norueguês",
    "uk": "Ucraniano",
    "he": "Hebraico",
    "th": "Tailandês",
    "id": "Indonésio",
    "vi": "Vietnamita",
    "ms": "Malaio",
    "cs": "Tcheco",
    "ro": "Romeno",
    "hu": "Húngaro",
    "el": "Grego",
    "bg": "Búlgaro",
}

# Mapa de nomes alternativos de idiomas → código ISO 639-1
LANG_ALIASES: Dict[str, str] = {
    "português": "pt",
    "portugues": "pt",
    "portuguese": "pt",
    "pt-br": "pt",
    "inglês": "en",
    "ingles": "en",
    "english": "en",
    "espanhol": "es",
    "spanish": "es",
    "castellano": "es",
    "francês": "fr",
    "frances": "fr",
    "french": "fr",
    "alemão": "de",
    "alemao": "de",
    "german": "de",
    "italiano": "it",
    "italian": "it",
    "japonês": "ja",
    "japones": "ja",
    "japanese": "ja",
    "coreano": "ko",
    "korean": "ko",
    "chinês": "zh",
    "chines": "zh",
    "chinese": "zh",
    "mandarim": "zh",
    "russo": "ru",
    "russian": "ru",
    "árabe": "ar",
    "arabe": "ar",
    "arabic": "ar",
    "hindi": "hi",
}


def _normalize_lang(lang: str) -> str:
    """Normaliza nome/código de idioma para código ISO 639-1."""
    lang_lower = lang.strip().lower()
    return LANG_ALIASES.get(lang_lower, lang_lower[:2])


@register_service("translate")
class TranslateService(BaseService):
    """
    Translation service via Google Generative AI (Gemini 2.0 Flash).

    FIX: Usa google-genai (nova SDK) em vez de google.generativeai (SDK antiga).
    Consistente com image_service.py e video_service.py.

    Features:
    - Automatic source language detection
    - ~100+ languages supported
    - In-memory LRU cache (avoid duplicate API calls)
    - Preserves formatting (markdown, code blocks, etc.)
    """

    # FIX: Modelo atualizado. gemini-1.5-flash estava deprecado na nova SDK.
    _MODEL_NAME = "gemini-2.0-flash"

    def __init__(self):
        super().__init__(name="translate")
        self._client = None
        self._cache: Dict[str, Dict] = {}
        self._cache_max = 200

    async def _initialize(self) -> None:
        """Initialize Google Generative AI client (nova SDK google-genai)."""
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        if not api_key:
            raise ServiceUnavailableError(
                "GEMINI_API_KEY não encontrada nas variáveis de ambiente"
            )

        try:
            # FIX: Usa nova SDK "google-genai" (from google import genai)
            # em vez de "google-generativeai" (import google.generativeai as genai)
            # A nova SDK é a única instalada no requirements.txt do projeto.
            from google import genai as google_genai  # noqa: F401 - nova SDK

            self._client = google_genai.Client(api_key=api_key)
            self.logger.info(
                "TranslateService inicializado com %s (google-genai nova SDK)",
                self._MODEL_NAME,
            )
        except ImportError:
            raise ServiceUnavailableError(
                "google-genai não instalado. Execute: pip install google-genai"
            )
        except Exception as e:
            raise ServiceUnavailableError(f"Falha ao inicializar cliente Gemini: {e}")

    async def _health_check(self) -> bool:
        return self._client is not None

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Translate text to target language.

        Args:
            text: Text to translate
            target_lang: Target language code or name (e.g. "en", "inglês")
            source_lang: Source language (auto-detected if None)

        Returns:
            Dict with: translated_text, source_lang, target_lang,
                       detected_lang, chars, latency_s
        """
        if not self.is_initialized():
            await self.initialize()

        target_code = _normalize_lang(target_lang)
        target_name = SUPPORTED_LANGUAGES.get(target_code, target_lang)
        source_code = _normalize_lang(source_lang) if source_lang else None

        # Cache lookup
        cache_key = self._cache_key(text, target_code, source_code)
        if cache_key in self._cache:
            self.logger.debug("Cache hit for translation")
            return self._cache[cache_key]

        start = time.time()
        translated, detected = await self._call_gemini(text, target_name, source_code)
        latency = time.time() - start

        result: Dict[str, Any] = {
            "translated_text": translated,
            "original_text": text,
            "source_lang": detected or source_code or "auto",
            "target_lang": target_code,
            "target_lang_name": target_name,
            "detected_lang": detected,
            "chars": len(text),
            "latency_s": round(latency, 3),
        }

        # Cache result (FIFO eviction)
        if len(self._cache) >= self._cache_max:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[cache_key] = result

        self._track_call(latency, error=False)
        return result

    async def detect_language(self, text: str) -> Dict[str, Any]:
        """
        Detect language of given text.

        Returns:
            Dict with: lang_code, lang_name, confidence
        """
        if not self.is_initialized():
            await self.initialize()

        prompt = (
            f"Detect the language of this text and respond ONLY with a JSON object.\n"
            f'Format: {{"lang_code": "xx", "lang_name": "Language Name", "confidence": "high"}}\n'
            f"Text: '''{text[:500]}'''"
        )

        try:
            # FIX: usa nova SDK client.aio.models.generate_content (async)
            response = await self._client.aio.models.generate_content(
                model=self._MODEL_NAME,
                contents=prompt,
            )
            import json

            raw = response.text.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            data = json.loads(raw)
            return {
                "lang_code": data.get("lang_code", "unknown"),
                "lang_name": data.get("lang_name", "Unknown"),
                "confidence": data.get("confidence", "unknown"),
            }
        except Exception as e:
            self.logger.error("Language detection failed: %s", e)
            return {"lang_code": "unknown", "lang_name": "Unknown", "confidence": "low"}

    def get_supported_languages(self) -> Dict[str, str]:
        """Returns dict of supported language codes → names."""
        return dict(SUPPORTED_LANGUAGES)

    def clear_cache(self) -> None:
        """Clear translation cache."""
        self._cache.clear()

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _call_gemini(
        self,
        text: str,
        target_lang_name: str,
        source_lang: Optional[str],
    ) -> tuple[str, Optional[str]]:
        """
        Call Gemini API for translation via nova SDK.
        Returns (translated_text, detected_source).
        """
        if source_lang:
            source_hint = f"from {SUPPORTED_LANGUAGES.get(source_lang, source_lang)} "
        else:
            source_hint = ""

        prompt = (
            f"Translate the following text {source_hint}to {target_lang_name}.\n"
            f"Rules:\n"
            f"- Return ONLY the translated text, nothing else\n"
            f"- Preserve formatting (markdown, line breaks, bullet points)\n"
            f"- Do not add explanations or notes\n"
            f"- If the text is already in {target_lang_name}, return it as-is\n\n"
            f"Text to translate:\n{text}"
        )

        # FIX: usa nova SDK client.aio.models.generate_content (async nativo)
        # Antes: self._client.generate_content_async(prompt) → SDK antiga
        # Agora: self._client.aio.models.generate_content(model=..., contents=...) → SDK nova
        response = await self._client.aio.models.generate_content(
            model=self._MODEL_NAME,
            contents=prompt,
        )
        translated = response.text.strip()
        return translated, None  # Gemini não retorna idioma detetado diretamente

    def _cache_key(
        self,
        text: str,
        target: str,
        source: Optional[str],
    ) -> str:
        content = f"{text}|{target}|{source or 'auto'}"
        return hashlib.md5(content.encode()).hexdigest()
