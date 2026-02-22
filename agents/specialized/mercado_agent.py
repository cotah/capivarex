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
        try:
            svc = get_service("mercado")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço de mercado não disponível.",
                    error="MercadoService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            texto = (prompt or "").strip()

            # ── Foto de nota fiscal ───────────────────────────────────────────
            image_data: Optional[bytes] = context.get("image_data")
            if image_data:
                chat_id = str(context.get("chat_id", "unknown"))
                mime_type = context.get("image_mime", "image/jpeg")
                result = await svc.processar_nota(image_data, chat_id, mime_type=mime_type)
                status = AgentStatus.SUCCESS if result.get("sucesso") else AgentStatus.ERROR
                return AgentResponse(
                    status=status,
                    response=result.get("mensagem", "❌ Erro ao processar nota."),
                    data=result,
                )

            # ── Relatório mensal ──────────────────────────────────────────────
            if _RE_RELATORIO.search(texto):
                chat_id = str(context.get("chat_id", "unknown"))
                mes = context.get("mes")
                ano = context.get("ano")
                result = await svc.relatorio_mensal(chat_id, mes=mes, ano=ano)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao gerar relatório."),
                    data=result,
                )

            # ── Ranking de mercados ───────────────────────────────────────────
            if _RE_RANKING.search(texto):
                chat_id = str(context.get("chat_id", "unknown"))
                result = await svc.ranking_mercados(chat_id)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao gerar ranking."),
                    data=result,
                )

            # ── Comparar produto ──────────────────────────────────────────────
            m = _RE_COMPARAR.search(texto)
            if m:
                produto = m.group(1).strip().rstrip("?!.")
                chat_id = str(context.get("chat_id", "unknown"))
                result = await svc.comparar_produto(produto, chat_id)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao comparar."),
                    data=result,
                )

            # ── Histórico da lista ────────────────────────────────────────────
            if _RE_HISTORICO_LISTA.search(texto):
                result = await svc.historico_lista()
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao obter histórico."),
                    data=result,
                )

            # ── Limpar lista ──────────────────────────────────────────────────
            if _RE_LIMPAR.search(texto):
                result = await svc.limpar_lista()
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao limpar."),
                    data=result,
                )

            # ── Ver lista ─────────────────────────────────────────────────────
            if _RE_VER.search(texto):
                result = await svc.ver_lista()
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao obter lista."),
                    data=result,
                )

            # ── Remover item ──────────────────────────────────────────────────
            m = _RE_REMOVER.search(texto)
            if m:
                item = m.group(1).strip().rstrip("?!.,")
                result = await svc.remover(item)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao remover."),
                    data=result,
                )

            # ── Adicionar item(s) ─────────────────────────────────────────────
            m = _RE_ADICIONAR.search(texto)
            if m:
                itens = m.group(1).strip().rstrip("?!.,")
                result = await svc.adicionar(itens)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=result.get("mensagem", "❌ Erro ao adicionar."),
                    data=result,
                )

            # ── Fallback: tenta adicionar o texto directamente ────────────────
            if texto and len(texto) < 150:
                result = await svc.adicionar(texto)
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
