# -*- coding: utf-8 -*-
"""
Translate Agent
===============
Detecta intenções de tradução e delega ao TranslateService.

Exemplos:
  - "Traduz 'hello world' para português"
  - "Como se diz 'obrigado' em japonês?"
  - "Translate this text to English: [texto]"
  - "Qual o idioma desse texto: Bonjour le monde"
  - "Traduz: [texto longo]"
"""

import logging
import re
from typing import Any, Dict, List, Optional  # FIX F401: removed unused Tuple

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang

logger = logging.getLogger(__name__)

_RE_TRANSLATE = re.compile(
    r"""
    (?:traduz(?:ir)?|translate)\s+
    (?:["']?(.+?)["']?\s+)?
    (?:para|to|into|em)\s+
    ([a-záéíóúàâêôãõüçñ\s]+?)
    (?:\s*[:;,]|\s*$)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RE_HOW_TO_SAY = re.compile(
    r"""
    (?:como\s+se\s+diz|how\s+(?:do\s+you\s+say|to\s+say))\s+
    ["']?(.+?)["']?\s+
    (?:em|in)\s+
    ([a-záéíóúàâêôãõüçñ\s]+?)
    (?:\s*\?|\s*$)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RE_DETECT = re.compile(
    r"""
    (?:qual\s+(?:o\s+)?idioma|detect\s+language|que\s+(?:idioma|língua|lingua)\s+(?:é|e))\s*
    (?:(?:d[aeo]|is|of)\s+)?
    (?:(?:(?:essa|este|this|the)\s+)?(?:text[oa]?|phrase|frase)[\s:]*)?
    [:"]?\s*(.+)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _normalize_lang(lang: str) -> str:
    """Normaliza nome de idioma para código ISO."""
    # FIX F401: removed unused LANG_ALIASES from import
    from services.business.translate_service import _normalize_lang as _nl

    return _nl(lang)


@register_agent("translate")
class TranslateAgent(BaseAgent):
    """
    Translation agent — handles text translation and language detection.

    Supports:
    - Translation to/from any language (100+)
    - Automatic source language detection
    - "How do you say X in Y?" queries
    - Language detection of arbitrary text
    """

    def __init__(self):
        super().__init__(
            name="translate",
            description="Traduz textos entre idiomas e detecta idioma de origem",
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Route translation request based on detected intent."""
        lang = get_user_lang(context)
        try:
            translate_svc = get_service("translate")
            if not translate_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("translate_service_unavailable", lang=lang),
                    error="TranslateService unavailable",
                )
            if not translate_svc.is_initialized():
                await translate_svc.initialize()

            prompt_stripped = (prompt or "").strip()

            detect_match = _RE_DETECT.search(prompt_stripped)
            if detect_match or any(
                w in prompt_stripped.lower()
                for w in [
                    "qual idioma",
                    "que idioma",
                    "detect language",
                    "que língua",
                    "que lingua",
                ]
            ):
                text_to_detect = (
                    detect_match.group(1).strip() if detect_match else prompt_stripped
                )
                return await self._handle_detect(translate_svc, text_to_detect)

            say_match = _RE_HOW_TO_SAY.search(prompt_stripped)
            if say_match:
                text = say_match.group(1).strip().strip("'\"")
                lang = say_match.group(2).strip()
                return await self._handle_translate(translate_svc, text, lang)

            target_lang = context.get("target_lang") or context.get("language")
            text_override = context.get("text")
            trans_match = _RE_TRANSLATE.search(prompt_stripped)
            if trans_match:
                text = (
                    (trans_match.group(1) or text_override or "").strip().strip("'\"")
                )
                lang = trans_match.group(2).strip()
                if not text:
                    text = (
                        self._extract_text_after_colon(prompt_stripped)
                        or prompt_stripped
                    )
                return await self._handle_translate(translate_svc, text, lang)

            if target_lang:
                text = text_override or prompt_stripped
                return await self._handle_translate(translate_svc, text, target_lang)

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Não entendi o pedido de tradução. Tente:\n"
                    "• *Traduz 'bom dia' para inglês*\n"
                    "• *Como se diz 'obrigado' em japonês?*\n"
                    "• *Qual o idioma desse texto: Bonjour le monde*"
                ),
                error="Could not parse translation intent",
            )

        except Exception as e:
            self.logger.error("TranslateAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao traduzir: {str(e)}",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_translate(
        self,
        svc: Any,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
    ) -> AgentResponse:
        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Por favor, informe o texto a ser traduzido.",
                error="Empty text",
            )
        result = await svc.translate(text, target_lang, source_lang)
        translated = result["translated_text"]
        lang_name = result["target_lang_name"]
        if len(text) <= 50:
            response = f"**{translated}**\n_(em {lang_name})_"
        else:
            response = (
                f"**Tradução para {lang_name}:**\n\n"
                f"{translated}\n\n"
                f"_{len(text)} caracteres traduzidos em {result['latency_s']}s_"
            )
        return AgentResponse(status=AgentStatus.SUCCESS, response=response, data=result)

    async def _handle_detect(self, svc: Any, text: str) -> AgentResponse:
        if not text or len(text.strip()) < 3:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Texto muito curto para detectar o idioma.",
                error="Text too short",
            )
        result = await svc.detect_language(text)
        lang_name = result["lang_name"]
        lang_code = result["lang_code"]
        confidence = result.get("confidence", "")
        response = (
            f"O idioma detectado é **{lang_name}** (`{lang_code}`)"
            + (f" — confiança: {confidence}" if confidence else "")
            + "."
        )
        return AgentResponse(status=AgentStatus.SUCCESS, response=response, data=result)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_text_after_colon(self, prompt: str) -> Optional[str]:
        if ":" in prompt:
            parts = prompt.split(":", 1)
            if len(parts[1].strip()) > 0:
                return parts[1].strip()
        return None

    def get_capabilities(self) -> List[str]:
        return [
            "translate_text",
            "detect_language",
            "multi_language_support",
            "auto_source_detection",
        ]
