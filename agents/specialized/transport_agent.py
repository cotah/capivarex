# -*- coding: utf-8 -*-
"""
agents/specialized/transport_agent.py
=======================================
TransportAgent — Transporte Público em Tempo Real.

Responde a perguntas sobre:
- Próximo ônibus / autocarro / DART / Luas / comboio
- Horários de uma linha específica
- Estado do serviço (alertas, atrasos)
- Próximas paragens perto do utilizador

Usa automaticamente o GPS guardado do utilizador.
Integra com NTA GTFS-Realtime + Google Maps Routes API.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

logger = logging.getLogger("capivarex.transport_agent")

# ─── Keywords de intent ──────────────────────────────────────────────────────

_TRANSIT_KEYWORDS = [
    # Português (BR + PT)
    "ônibus",
    "onibus",
    "autocarro",
    "autocarros",
    "metro",
    "metrô",
    "luas",
    "dart",
    "comboio",
    "trem",
    "transporte",
    "bus",
    "paragem",
    "paragem de",
    "próximo ônibus",
    "próximo autocarro",
    "próximo bus",
    "horário",
    "horarios",
    "quando passa",
    "linha",
    # English
    "next bus",
    "next dart",
    "next luas",
    "next tram",
    "bus stop",
    "train",
    "transit",
    "public transport",
    "timetable",
    "schedule",
    "when does",
]

_ALERT_KEYWORDS = [
    "atraso",
    "delay",
    "cancelled",
    "cancelado",
    "disruption",
    "perturbação",
    "alert",
    "alerta",
]


def _is_transport_query(prompt: str) -> bool:
    text = prompt.lower()
    return any(kw in text for kw in _TRANSIT_KEYWORDS)


def _wants_alerts(prompt: str) -> bool:
    text = prompt.lower()
    return any(kw in text for kw in _ALERT_KEYWORDS)


def _extract_destination(prompt: str) -> Optional[str]:
    """Tenta extrair destino da query. Ex: 'para o centro' → 'centro'."""
    patterns = [
        r"para (?:o |a |os |as )?(.+?)(?:\s+agora|\s+hoje|$)",
        r"até (?:o |a )?(.+?)(?:\s+agora|\s+hoje|$)",
        r"to (?:the )?(.+?)(?:\s+now|\s+today|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, prompt.lower())
        if m:
            dest = m.group(1).strip()
            if dest and len(dest) > 2:
                return dest
    return None


@register_agent("transport")
class TransportAgent(BaseAgent):
    """
    Agente de Transporte Público.

    Consulta horários, próximas partidas e alertas de serviço
    usando o GPS do utilizador automaticamente.
    Usa TransitService directamente (NTA GTFS-RT + Google Maps).
    """

    def __init__(self):
        super().__init__(
            name="transport",
            description=(
                "Informa sobre próximo ônibus, autocarro, DART, Luas ou comboio. "
                "Consulta horários em tempo real via NTA. "
                "Usa GPS do utilizador automaticamente."
            ),
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        try:
            # ── 1. Obter localização ──────────────────────────────────────
            user_uuid = context.get("user_id")
            lat = context.get("latitude")
            lng = context.get("longitude")

            # Tenta GPS guardado no Supabase se não vier no context
            # Import LAZY — não bloqueia o registo do agent se o DB não estiver pronto
            if not (lat and lng) and user_uuid:
                try:
                    from services.business.user_preferences_service import get_location

                    loc = await get_location(str(user_uuid), prefer="last")
                    if loc:
                        lat, lng = loc
                        logger.info(
                            "GPS loaded from Supabase for user %s: %s,%s",
                            user_uuid,
                            lat,
                            lng,
                        )
                except Exception as e:
                    logger.warning("Could not fetch GPS from Supabase: %s", e)

            # Sem GPS → pede localização ao utilizador
            if not lat or not lng:
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=(
                        "📍 Preciso da tua localização para encontrar transportes próximos.\n\n"
                        "Envia a tua localização pelo Telegram: **📎 → Localização**"
                    ),
                    data={"needs_location": True},
                )

            # ── 2. Obter TransitService (NTA + Google Maps) ───────────────
            transit_svc = get_service("transit")
            if not transit_svc:
                logger.error("TransitService not found in service registry")
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "⚠️ Serviço de transporte não disponível de momento.\n"
                        "Verifica as configurações do NTA_API_KEY e GOOGLE_MAPS_API_KEY."
                    ),
                    error="transit service unavailable",
                )

            if not transit_svc.is_initialized():
                logger.info("Initializing TransitService...")
                await transit_svc.initialize()

            # ── 3. Construir origem e destino ─────────────────────────────
            destination = _extract_destination(prompt)
            origin = f"{lat},{lng}"
            dest_query = destination or "Dublin City Centre, Ireland"

            logger.info(
                "TransportAgent: origin=%s dest=%s user=%s",
                origin,
                dest_query,
                user_uuid,
            )

            # ── 4. Consultar próximas partidas via NTA + Google Maps ───────
            travel_data = await transit_svc.get_transit_with_delays(
                origin=origin,
                destination=dest_query,
            )

            if not travel_data or not travel_data.get("success"):
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=(
                        f"🚌 Não encontrei transportes próximos"
                        f"{f' para {destination}' if destination else ''}.\n\n"
                        "Verifica se há paragens de autocarro, DART ou Luas perto de ti."
                    ),
                )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=self._format_transit(travel_data, destination),
                data=travel_data,
            )

        except Exception as e:
            logger.error("TransportAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao consultar transportes: {str(e)}",
                error=str(e),
            )

    @staticmethod
    def _format_transit(data: Dict, destination: Optional[str]) -> str:
        lines = []

        dest_str = f" → **{destination.title()}**" if destination else ""
        lines.append(f"🚌 **Próximos transportes{dest_str}**\n")

        steps = data.get("steps", [])
        transit_lines = data.get("lines", [])
        delay = data.get("realtime_delay_minutes", 0)
        duration = data.get("duration_minutes", 0)
        alerts = data.get("service_alerts", [])

        if steps:
            for step in steps[:6]:
                mode = step.get("mode", "")
                transit = step.get("transit", {})
                step_dur = step.get("duration_minutes", 0)

                if mode == "TRANSIT" and transit:
                    line_name = transit.get("short_name") or transit.get(
                        "long_name", "?"
                    )
                    dep_stop = transit.get("departure_stop", "")
                    arr_stop = transit.get("arrival_stop", "")
                    dep_time = transit.get("departure_time", "")
                    num_stops = transit.get("num_stops", 0)
                    headsign = transit.get("headsign", "")

                    line_str = f"🚌 **{line_name}**"
                    if headsign:
                        line_str += f" → {headsign}"
                    if dep_time:
                        line_str += f"  ⏱ {dep_time}"
                    lines.append(line_str)

                    if dep_stop:
                        lines.append(f"   📍 Partida: {dep_stop}")
                    if arr_stop:
                        lines.append(f"   📍 Chegada: {arr_stop}")
                    if num_stops:
                        lines.append(f"   🔢 {num_stops} paragens · {step_dur:.0f} min")
                    lines.append("")

                elif mode == "WALK":
                    lines.append(f"🚶 A pé — {step_dur:.0f} min\n")

        elif transit_lines:
            # Fallback: apenas nomes de linhas sem steps detalhados
            for line in transit_lines[:4]:
                name = (
                    line.get("short_name")
                    or line.get("long_name")
                    or line.get("name", "?")
                )
                lines.append(f"🚌 **{name}**")
            lines.append("")

        # Tempo total
        if duration:
            delay_str = f" *(+{delay:.0f} min atraso)*" if delay > 0 else ""
            lines.append(f"⏱ Tempo total: **{duration:.0f} min**{delay_str}")

        # Alertas de serviço
        if alerts:
            lines.append("\n⚠️ **Alertas de serviço:**")
            for alert in alerts[:2]:
                if alert:
                    lines.append(f"  • {alert}")

        if not steps and not transit_lines:
            lines.append("Nenhuma ligação encontrada para este destino.")

        # Mostrar alternativas se existirem
        alternatives = data.get("alternatives", [])
        if alternatives:
            lines.append("\n📋 **Outras opções:**")
            for i, alt in enumerate(alternatives, 1):
                alt_lines_str = " → ".join(alt.get("lines", []))
                alt_dur = alt.get("duration_minutes", 0)
                alt_transfers = alt.get("num_transfers", 0)
                transfer_text = (
                    "directo" if alt_transfers <= 1 else f"{alt_transfers} linhas"
                )
                lines.append(
                    f"  {i}. {alt_lines_str} ({transfer_text}, {alt_dur:.0f} min)"
                )

        return "\n".join(lines).strip()

    def get_capabilities(self) -> List[str]:
        return [
            "next_bus",
            "next_dart",
            "next_luas",
            "transit_schedule",
            "realtime_delays",
            "service_alerts",
            "gps_based_search",
        ]
