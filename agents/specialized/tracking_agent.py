# -*- coding: utf-8 -*-
"""
agents/specialized/tracking_agent.py
=======================================
TrackingAgent — rastreia encomendas de qualquer transportadora via 17TRACK.

Exemplos de queries:
  - "Rastreia NB123456789IE"
  - "Onde está meu pacote LB987654321CN?"
  - "Status do meu pedido 1Z999AA10123456784"
  - "Rastreia NB123456789IE pela An Post"
  - "Minha encomenda chegou?"
  - "Tracking QR123456789BR"
  - "Quanto de quota me resta?"
"""

import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang

# ─── Regex de detecção de código de rastreio ─────────────────────────────────
#
# Formatos cobertos:
#   An Post / Ireland:  NB123456789IE, CN123456789IE  (2 letras + 9 dígitos + 2 letras)
#   Correios BR:        QR123456789BR, AA123456789BR  (igual acima)
#   UPS:                1Z999AA10123456784            (18 chars)
#   Amazon:             TBA123456789000               (TBA + dígitos)
#   FedEx/DHL numérico: 123456789012                  (12-22 dígitos)
#   China Post ePacket: RA123456789CN, LB987654321CN  (padrão postal)
#   Genérico:           5-50 chars alfanumérico
#
_RE_TRACKING = re.compile(
    r"\b("
    r"[A-Z]{2}\d{9}[A-Z]{2}"  # padrão postal universal (An Post, Correios, etc.)
    r"|1Z[A-Z0-9]{16}"  # UPS
    r"|TBA\d{9,}"  # Amazon Logistics
    r"|\d{12,22}"  # FedEx / DHL numérico
    r"|[A-Z]{1,3}\d{8,14}[A-Z]{0,2}"  # genérico alfanumérico
    r")\b",
    re.IGNORECASE,
)

# Palavras que indicam intenção de rastrear
_TRACK_WORDS = [
    "rastreia",
    "rastrear",
    "rastreio",
    "rastreamento",
    "tracking",
    "track",
    "onde está",
    "onde esta",
    "status do pacote",
    "status do pedido",
    "meu pacote",
    "meu pedido",
    "minha encomenda",
    "encomenda",
    "chegou",
    "entregue",
]

# Palavras que indicam consulta de quota
_QUOTA_WORDS = [
    "quota",
    "cota",
    "crédito",
    "credito",
    "quantos rastreios",
    "quanto resta",
]


@register_agent("tracking")
class TrackingAgent(BaseAgent):
    """
    Tracking agent — rastreamento de encomendas via 17TRACK (2600+ carriers).

    Intents:
        track  → rastreia código detectado no prompt ou context
        quota  → consulta quota restante na conta 17TRACK
    """

    def __init__(self):
        super().__init__(
            name="tracking",
            description="Rastreia encomendas de qualquer transportadora do mundo",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        lang = get_user_lang(context)
        try:
            svc = get_service("tracking")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("tracking_service_unavailable", lang=lang),
                    error="TrackingService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            prompt_clean = (prompt or "").strip()
            prompt_lower = prompt_clean.lower()

            # ── Intent: quota ─────────────────────────────────────────────────
            if any(w in prompt_lower for w in _QUOTA_WORDS):
                return await self._handle_quota(svc)

            # ── Context override (código direto) ──────────────────────────────
            if context.get("tracking_number"):
                return await self._handle_track(
                    svc,
                    context["tracking_number"],
                    context.get("carrier"),
                )

            # ── Extrai código do prompt ───────────────────────────────────────
            tracking_number = self._extract_tracking_number(prompt_clean)

            # Se o prompt inteiro parecer um código de rastreio
            if not tracking_number:
                stripped = prompt_clean.replace(" ", "").upper()
                if re.match(r"^[A-Z0-9]{5,50}$", stripped):
                    tracking_number = stripped

            if not tracking_number:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "🔍 Não encontrei um código de rastreio na mensagem.\n\n"
                        "Exemplos de uso:\n"
                        "• *Rastreia NB123456789IE*\n"
                        "• *Onde está meu pacote QR123456789BR?*\n"
                        "• *Tracking 1Z999AA10123456784*"
                    ),
                    error="No tracking number found",
                )

            # Detecta transportadora mencionada no prompt
            carrier = self._extract_carrier(prompt_lower, context)

            return await self._handle_track(svc, tracking_number, carrier)

        except ValueError as e:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=str(e),
                error=str(e),
            )
        except RuntimeError as e:
            msg = str(e)
            # Erro de API key
            if "17track_api_key" in msg.lower() or "api_key" in msg.lower():
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "⚙️ Serviço de rastreamento não configurado.\n"
                        "Adicione a `17TRACK_API_KEY` no `.env`.\n"
                        "Cadastro gratuito: https://api.17track.net"
                    ),
                    error=msg,
                )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao rastrear encomenda: {msg}",
                error=msg,
            )
        except Exception as e:
            self.logger.error("TrackingAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro inesperado ao rastrear a encomenda.",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_track(
        self,
        svc: Any,
        tracking_number: str,
        carrier: Optional[Any],
    ) -> AgentResponse:
        if carrier:
            data = await svc.track_with_carrier(tracking_number, carrier)
        else:
            data = await svc.track(tracking_number)

        if not data:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Não foi possível rastrear `{tracking_number}`.",
                error="No data returned",
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=self._format_tracking(data),
            data=data,
        )

    async def _handle_quota(self, svc: Any) -> AgentResponse:
        quota = await svc.get_quota()
        remaining = quota.get("quota_remaining", 0)
        total = quota.get("quota_total", 0)
        used = quota.get("quota_used", 0)

        emoji = "🟢" if remaining > 50 else "🟡" if remaining > 10 else "🔴"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"📊 **Quota 17TRACK**\n"
                f"{emoji} Disponível: **{remaining}** rastreios\n"
                f"✅ Usados: {used} · 📦 Total: {total}"
            ),
            data=quota,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Formatação
    # ──────────────────────────────────────────────────────────────────────────

    def _format_tracking(self, data: Dict[str, Any]) -> str:
        emoji = data.get("status_emoji", "📦")
        label = data.get("status_label", "")
        sub = data.get("sub_status", "")
        number = data.get("tracking_number", "")
        carrier = data.get("carrier", "").strip() or "Auto-detectada"
        last_msg = data.get("last_message", "")
        last_loc = data.get("last_location", "")
        last_upd = data.get("last_update", "")
        eta = data.get("estimated_delivery", "")
        events = data.get("events", [])

        # Cabeçalho
        sub_line = f" — _{sub}_" if sub else ""
        lines = [
            f"{emoji} **{label}**{sub_line}",
            f"📦 `{number}` · 🚛 {carrier}",
        ]

        # Último evento
        if last_msg:
            loc_part = f" — {last_loc}" if last_loc else ""
            date_part = f" _({last_upd})_" if last_upd else ""
            lines.append(f"\n📍 {last_msg}{loc_part}{date_part}")

        # Entregue
        if data.get("delivered"):
            lines.append("🎉 _Sua encomenda foi entregue!_")

        # ETA
        if eta and not data.get("delivered"):
            lines.append(f"\n📅 Previsão de entrega: **{eta}**")

        # Histórico — últimos 3 eventos (exceto o mais recente já mostrado)
        history = [ev for ev in events if ev.get("message")]
        if len(history) > 1:
            lines.append("\n**Histórico:**")
            for ev in history[1:4]:  # mostra até 3 eventos anteriores
                d = f"`{ev['date']}`" if ev.get("date") else ""
                loc_str = f" — {ev['location']}" if ev.get("location") else ""
                lines.append(f"  • {d} {ev['message']}{loc_str}")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers de extração
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_tracking_number(self, text: str) -> Optional[str]:
        match = _RE_TRACKING.search(text)
        return match.group(1).upper() if match else None

    def _extract_carrier(self, text: str, context: Dict[str, Any]) -> Optional[Any]:
        """Detecta transportadora mencionada no prompt ou no context."""
        if context.get("carrier"):
            return context["carrier"]

        from services.integrations.tracking_service import CARRIER_CODES

        # Testa do nome mais longo para o mais curto
        for name in sorted(CARRIER_CODES.keys(), key=len, reverse=True):
            if name in text.lower():
                return CARRIER_CODES[name]
        return None

    def get_capabilities(self) -> List[str]:
        return [
            "track_package",
            "auto_detect_carrier",
            "track_with_carrier",
            "delivery_status",
            "tracking_history",
            "estimated_delivery",
            "check_quota",
        ]
