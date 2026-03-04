# -*- coding: utf-8 -*-
"""
Mercado Agent
=============
Agente de lista de compras + análise inteligente de notas fiscais.

Exemplos:
  - "adicionar leite, pão, ovos"
  - "ver lista"
  - "remover leite"
  - "limpar lista"
  - [foto de nota fiscal] → processamento automático
  - "relatório mensal"
  - "comparar leite"
  - "ranking mercados"
"""

import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang

# ── Padrões de intenção ───────────────────────────────────────────────────────
_RE_ADICIONAR = re.compile(
    r"(?:adiciona[r]?|coloca[r]?|p[õo]e|acrescenta[r]?|bota[r]?)\s+(.+)",
    re.IGNORECASE,
)
_RE_REMOVER = re.compile(
    r"(?:remove[r]?|apaga[r]?|tira[r]?|retira[r]?|exclui[r]?|deleta[r]?)\s+(.+)",
    re.IGNORECASE,
)
_RE_VER = re.compile(
    r"^(?:ver|ve|mostra[r]?|lista[r]?)\s+(?:a\s+)?(?:lista|compras)|(?:o\s+que\s+tem|minha\s+lista|lista\s+de\s+compras?|quais\s+itens)",
    re.IGNORECASE,
)
_RE_LIMPAR = re.compile(
    r"(?:limpa[r]?|zera[r]?|apaga[r]?\s+tudo|clear|esvazia[r]?)\s*(?:lista|tudo)?",
    re.IGNORECASE,
)
_RE_HISTORICO_LISTA = re.compile(
    r"hist[oó]rico\s+(?:da\s+)?lista",
    re.IGNORECASE,
)
_RE_RELATORIO = re.compile(
    r"relat[oó]rio\s*(?:mensal|do\s+m[eê]s)?",
    re.IGNORECASE,
)
_RE_COMPARAR = re.compile(
    r"(?:compara[r]?|onde\s+[eé]\s+mais\s+barato|pre[çc]o\s+de|quanto\s+custa)\s+(.+)",
    re.IGNORECASE,
)
_RE_RANKING = re.compile(
    r"ranking\s+(?:de\s+)?mercados?|onde\s+(?:eu\s+)?gast(?:o|ei)\s+mais|qual\s+mercado\s+(?:[eé]\s+)?mais\s+(?:barato|caro)",
    re.IGNORECASE,
)
_RE_EXPORT = re.compile(
    r"(?:export(?:ar)?|excel|baixar?\s+relat[oó]rio|download\s+report)"
    r"(?:\s+(.+))?",
    re.IGNORECASE,
)


@register_agent("mercado")
class MercadoAgent(BaseAgent):
    """
    Agente de mercado inteligente.
    Gere lista de compras e analisa notas fiscais com IA.
    """

    def __init__(self):
        super().__init__(
            name="mercado",
            description=(
                "Lista de compras, processamento de notas fiscais por foto, "
                "comparação de preços entre mercados e relatórios de gastos."
            ),
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Ponto de entrada principal — detecta intenção e delega ao serviço."""
        lang = get_user_lang(context)
        try:
            svc = get_service("mercado")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("mercado_service_unavailable", lang=lang),
                    error="MercadoService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            texto = (prompt or "").strip()
            user_id = str(
                context.get(
                    "chat_id",
                    context.get("user_id", "default"),
                )
            )

            # ── Foto de nota fiscal ───────────────────────────────────────────
            image_data: Optional[bytes] = context.get("image_data")
            if image_data:
                chat_id = str(context.get("chat_id", "unknown"))
                mime_type = context.get("image_mime", "image/jpeg")
                result = await svc.processar_nota(
                    image_data, chat_id, mime_type=mime_type, lang=lang
                )
                status = (
                    AgentStatus.SUCCESS if result.get("sucesso") else AgentStatus.ERROR
                )
                return AgentResponse(
                    status=status,
                    response=result.get(
                        "mensagem", t("mercado_receipt_failed", lang=lang)
                    ),
                    data=result,
                )

            # ── Relatório mensal (interativo) ──────────────────────────────
            if _RE_RELATORIO.search(texto):
                from telegram_bot.handlers.mercado_callback import (
                    build_months_keyboard,
                )

                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=t("mercado_interactive_choose_month", lang=lang),
                    data={"inline_keyboard": True},
                    metadata={
                        "type": "inline_keyboard",
                        "reply_markup": build_months_keyboard(lang),
                    },
                )

            # ── Ranking de mercados ───────────────────────────────────────────
            if _RE_RANKING.search(texto):
                chat_id = str(context.get("chat_id", "unknown"))
                result = await svc.ranking_mercados(chat_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get(
                        "mensagem", t("mercado_ranking_error", lang=lang)
                    ),
                    data=result,
                )

            # ── Exportar Excel ────────────────────────────────────────────────
            m_export = _RE_EXPORT.match(texto)
            if m_export:
                import tempfile

                # Parse optional month
                month_text = (m_export.group(1) or "").strip()
                mes, ano = None, None

                if month_text:
                    mes = self._parse_month(month_text, lang)

                result = await svc.gerar_excel_mensal(
                    chat_id=user_id, mes=mes, ano=ano, lang=lang
                )

                if not result.get("sucesso"):
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response=result.get(
                            "mensagem", t("mercado_report_error", lang=lang)
                        ),
                    )

                # Save bytes to temp file
                excel_bytes = result["excel_bytes"]
                filename = result["filename"]
                resumo = result.get("resumo", "")

                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".xlsx", prefix="mercado_"
                )
                tmp.write(excel_bytes)
                tmp.close()

                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=f"📊 {resumo}",
                    data={"document_path": tmp.name},
                    metadata={
                        "type": "document",
                        "file_path": tmp.name,
                        "filename": filename,
                    },
                )

            # ── Comparar produto ──────────────────────────────────────────────
            m = _RE_COMPARAR.search(texto)
            if m:
                produto = m.group(1).strip().rstrip("?!.")
                chat_id = str(context.get("chat_id", "unknown"))
                result = await svc.comparar_produto(produto, chat_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get(
                        "mensagem", t("mercado_compare_error", lang=lang)
                    ),
                    data=result,
                )

            # ── Histórico da lista ────────────────────────────────────────────
            if _RE_HISTORICO_LISTA.search(texto):
                result = await svc.historico_lista(user_id=user_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", t("mercado_no_history", lang=lang)),
                    data=result,
                )

            # ── Limpar lista ──────────────────────────────────────────────────
            if _RE_LIMPAR.search(texto):
                result = await svc.limpar_lista(user_id=user_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get(
                        "mensagem", t("mercado_clear_error", lang=lang)
                    ),
                    data=result,
                )

            # ── Ver lista ─────────────────────────────────────────────────────
            if _RE_VER.search(texto):
                result = await svc.ver_lista(user_id=user_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", t("mercado_list_empty", lang=lang)),
                    data=result,
                )

            # ── Remover item ──────────────────────────────────────────────────
            m = _RE_REMOVER.search(texto)
            if m:
                item = m.group(1).strip().rstrip("?!.,")
                result = await svc.remover(item, user_id=user_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get(
                        "mensagem", t("mercado_what_to_remove", lang=lang)
                    ),
                    data=result,
                )

            # ── Adicionar item(s) ─────────────────────────────────────────────
            m = _RE_ADICIONAR.search(texto)
            if m:
                itens = m.group(1).strip().rstrip("?!.,")
                result = await svc.adicionar(itens, user_id=user_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get(
                        "mensagem", t("mercado_what_to_add", lang=lang)
                    ),
                    data=result,
                )

            # ── Fallback: tenta adicionar o texto directamente ────────────────
            if texto and len(texto) < 150:
                result = await svc.adicionar(texto, user_id=user_id, lang=lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", self._ajuda()),
                    data=result,
                )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=self._ajuda(),
            )

        except Exception as e:
            self.logger.error("MercadoAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro no agente de mercado: {e}",
                error=str(e),
            )

    def get_capabilities(self) -> List[str]:
        return [
            "shopping_list_add",
            "shopping_list_view",
            "shopping_list_remove",
            "shopping_list_clear",
            "shopping_list_history",
            "receipt_scan",
            "price_comparison",
            "spending_report",
            "market_ranking",
            "price_alerts",
        ]

    @staticmethod
    def _parse_month(text: str, lang: str = "en") -> Optional[int]:
        """Parse month name or number from text. Returns 1-12 or None."""
        text = text.lower().strip()

        # Try numeric
        try:
            n = int(text)
            if 1 <= n <= 12:
                return n
        except ValueError:
            pass

        # Month name mapping (all 3 languages)
        months = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
            "janeiro": 1,
            "fevereiro": 2,
            "março": 3,
            "marco": 3,
            "abril": 4,
            "maio": 5,
            "junho": 6,
            "julho": 7,
            "agosto": 8,
            "setembro": 9,
            "outubro": 10,
            "novembro": 11,
            "dezembro": 12,
            "enero": 1,
            "febrero": 2,
            "marzo": 3,
            "mayo": 5,
            "junio": 6,
            "julio": 7,
            "septiembre": 9,
            "octubre": 10,
            "noviembre": 11,
            "diciembre": 12,
        }

        for name, num in months.items():
            if name in text:
                return num

        return None

    @staticmethod
    def _ajuda() -> str:
        return (
            "🛒 *Mercado Inteligente — Ajuda*\n\n"
            "*Lista de compras:*\n"
            "  • `adicionar leite, pão, ovos`\n"
            "  • `ver lista`\n"
            "  • `remover leite`\n"
            "  • `limpar lista`\n"
            "  • `histórico lista`\n\n"
            "*Notas fiscais:*\n"
            "  • 📷 Envia uma foto da nota → processo automaticamente\n\n"
            "*Relatórios e análise:*\n"
            "  • `relatório mensal`\n"
            "  • `comparar leite`\n"
            "  • `ranking mercados`\n"
        )
