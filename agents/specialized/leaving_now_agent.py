# -*- coding: utf-8 -*-
"""
agents/specialized/leaving_now_agent.py
=========================================
LeavingNowAgent — "Hora de Sair" proactivo e reactivo.

Modos de activação:
  1. Reactivo  → utilizador pergunta: "quando devo sair?"
  2. Proactivo → ProactivityService chama via context action="check_departure"
  3. Específico → "quando devo sair para a reunião das 15h?"

GPS auto-use (Passo 4C): Quando user_location não está no context,
busca coordenadas do Supabase via get_location() antes de usar Dublin default.

Exemplos de queries:
  - "Quando devo sair?"
  - "A que horas saio para o próximo evento?"
  - "Quanto tempo tenho para a reunião?"
  - "Devo sair de carro ou autocarro?"
  - "Eventos de hoje com hora de saída"
  - "Hora de sair para o dentista"
"""

import re
from typing import Any, Dict, List

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.business.leaving_now_service import LeavingNowResult


# ─── Keywords de intent ───────────────────────────────────────────────────────

_REACTIVE_KEYWORDS = [
    "quando sair",
    "quando devo sair",
    "hora de sair",
    "que horas saio",
    "quanto tempo tenho",
    "devo sair",
    "when to leave",
    "time to leave",
    "when should i leave",
    "should i leave",
    "a que horas saio",
    "quando precisar sair",
]

_TODAY_ALL_KEYWORDS = [
    "eventos de hoje",
    "todos os eventos",
    "agenda de hoje",
    "today's events",
    "all events today",
    "todos hoje",
]

_TRANSIT_KEYWORDS = [
    "autocarro",
    "bus",
    "metro",
    "luas",
    "dart",
    "comboio",
    "train",
    "transporte público",
    "public transport",
    "transit",
    "sem carro",
    "without car",
    "a pé não",
]

_DRIVING_KEYWORDS = [
    "de carro",
    "car",
    "driving",
    "drive",
    "carro",
]


def _detect_transport_mode(prompt: str, context: Dict) -> str:
    """Detecta modo de transporte preferido. Default: driving."""
    if context.get("transport_mode"):
        return str(context["transport_mode"])
    text = prompt.lower()
    if any(kw in text for kw in _TRANSIT_KEYWORDS):
        return "transit"
    if any(kw in text for kw in _DRIVING_KEYWORDS):
        return "driving"
    return context.get("default_transport", "driving")


def _detect_all_today(prompt: str) -> bool:
    """Detecta se utilizador quer ver todos os eventos de hoje."""
    text = prompt.lower()
    return any(kw in text for kw in _TODAY_ALL_KEYWORDS)


def _extract_prep_minutes(prompt: str, context: Dict) -> float:
    """Extrai tempo de preparação do prompt ou context. Default: 10 min."""
    if context.get("prep_minutes"):
        try:
            return float(context["prep_minutes"])
        except (ValueError, TypeError):
            pass

    # "preciso de 15 minutos para me preparar"
    match = re.search(
        r"(\d+)\s*(minutos?|min)\s*(para me preparar|de preparação|para sair)",
        prompt.lower(),
    )
    if match:
        return float(match.group(1))

    return 10.0


@register_agent("leaving_now")
class LeavingNowAgent(BaseAgent):
    """
    Agente "Hora de Sair" — nunca mais te atrases.

    Calcula exactamente quando sair, considerando:
    - Trânsito em tempo real (Google Maps)
    - Transporte público + atrasos TFI GTFS-Realtime
    - Clima (buffer de chuva automático)
    - Tempo de preparação pessoal
    - GPS auto-use do Supabase quando sem localização explícita

    Activa-se de forma proactiva via ProactivityService
    ou reactiva quando o utilizador pergunta.
    """

    def __init__(self):
        super().__init__(
            name="leaving_now",
            description=(
                "Calcula quando sair para eventos do calendário. "
                "Considera trânsito, clima, transporte público e atrasos TFI."
            ),
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        try:
            svc = get_service("leaving_now")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Serviço 'Hora de Sair' não disponível.\n"
                        "Verifica se o LeavingNowService está registado."
                    ),
                    error="LeavingNowService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            # Localização do utilizador
            user_location = context.get("user_location") or context.get("location")

            # ── GPS AUTO-USE (Passo 4C) ────────────────────────────────
            # Se não há user_location no context, tenta GPS do Supabase
            if not user_location:
                user_uuid = context.get("user_id")
                if user_uuid:
                    try:
                        from services.business.user_preferences_service import (
                            get_location,
                        )

                        loc = await get_location(str(user_uuid), prefer="last")
                        if loc:
                            lat, lng = loc
                            user_location = f"{lat},{lng}"
                            self.logger.info(
                                "LeavingNowAgent GPS auto-use: %s,%s for user %s",
                                lat,
                                lng,
                                user_uuid,
                            )
                    except Exception as e:
                        self.logger.warning(
                            "Could not fetch GPS for leaving_now: %s", e
                        )

            # Último fallback — Dublin hardcoded
            if not user_location:
                user_location = "Dublin, Ireland"
            # ── FIM GPS AUTO-USE ───────────────────────────────────────

            transport_mode = _detect_transport_mode(prompt, context)
            prep_minutes = _extract_prep_minutes(prompt, context)

            # ── Action override (ProactivityService) ─────────────────────────
            if context.get("action") == "check_departure":
                return await self._handle_proactive(
                    svc, user_location, transport_mode, prep_minutes
                )

            # ── Todos os eventos de hoje ──────────────────────────────────────
            if _detect_all_today(prompt):
                return await self._handle_all_today(
                    svc, user_location, transport_mode, prep_minutes
                )

            # ── Evento específico no context ──────────────────────────────────
            if context.get("event"):
                return await self._handle_specific_event(
                    svc, context["event"], user_location, transport_mode, prep_minutes
                )

            # ── Query natural → próximo evento ────────────────────────────────
            return await self._handle_next_event(
                svc, user_location, transport_mode, prep_minutes
            )

        except Exception as e:
            self.logger.error("LeavingNowAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao calcular hora de saída: {str(e)}",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_next_event(
        self, svc: Any, location: str, transport_mode: str, prep_minutes: float
    ) -> AgentResponse:
        """Calcula hora de saída para o próximo evento."""
        result = await svc.calculate_for_next_event(
            user_location=location,
            transport_mode=transport_mode,
            prep_minutes=prep_minutes,
        )

        if not result:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    "📅 Não encontrei nenhum evento próximo com localização definida.\n"
                    "Verifique se seus eventos do Google Calendar "
                    "têm o campo *Local* preenchido."
                ),
                data={"event": None},
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=self._format_result(result),
            data=result.to_dict(),
        )

    async def _handle_specific_event(
        self,
        svc: Any,
        event: Dict,
        location: str,
        transport_mode: str,
        prep_minutes: float,
    ) -> AgentResponse:
        """Calcula para um evento específico passado no context."""
        result = await svc.calculate_for_event(
            event=event,
            user_location=location,
            transport_mode=transport_mode,
            prep_minutes=prep_minutes,
        )

        if not result:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não foi possível calcular a hora de saída para este evento.",
                error="Calculation failed",
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=self._format_result(result),
            data=result.to_dict(),
        )

    async def _handle_all_today(
        self, svc: Any, location: str, transport_mode: str, prep_minutes: float
    ) -> AgentResponse:
        """Lista hora de saída para todos os eventos de hoje."""
        results = await svc.get_all_events_today(
            user_location=location,
            transport_mode=transport_mode,
            prep_minutes=prep_minutes,
        )

        if not results:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="📅 Não tens eventos com localização definida para hoje.",
                data={"events": []},
            )

        lines = ["📋 **Agenda de Hoje — Horas de Saída**\n"]
        for i, r in enumerate(results, 1):
            urgency_emoji = {
                "LATE": "🚨",
                "URGENT": "🔴",
                "SOON": "🟡",
                "COMFORTABLE": "🟢",
                "RELAXED": "📅",
            }.get(r.urgency, "📅")

            departure_str = r.suggested_departure.strftime("%H:%M")
            event_str = r.event_time.strftime("%H:%M")

            lines.append(
                f"{urgency_emoji} **{i}. {r.event_title}**\n"
                f"   📍 {r.event_location}\n"
                f"   ⏰ Evento: {event_str} · Sair às: **{departure_str}**\n"
                f"   🚗 {r.travel_minutes:.0f} min de viagem"
            )

            if r.weather_buffer_minutes > 0:
                lines[-1] += f" · 🌧️ +{r.weather_buffer_minutes:.0f} min chuva"
            if r.transit_delay_minutes > 0:
                lines[-1] += f" · 🚌 +{r.transit_delay_minutes:.0f} min atraso"

            lines.append("")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines).strip(),
            data={"events": [r.to_dict() for r in results]},
        )

    async def _handle_proactive(
        self, svc: Any, location: str, transport_mode: str, prep_minutes: float
    ) -> AgentResponse:
        """
        Chamado pelo ProactivityService.
        Só retorna resposta se urgência for SOON ou superior.
        """
        result = await svc.calculate_for_next_event(
            user_location=location,
            transport_mode=transport_mode,
            prep_minutes=prep_minutes,
        )

        if not result:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="",  # silêncio — sem eventos
                data={"proactive": True, "triggered": False},
            )

        # Só notifica se urgente (evita spam)
        if result.urgency in ("LATE", "URGENT", "SOON"):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=self._format_result(result),
                data={**result.to_dict(), "proactive": True, "triggered": True},
            )

        # Ainda há muito tempo — silêncio proactivo
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="",
            data={**result.to_dict(), "proactive": True, "triggered": False},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Formatação
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_result(result: LeavingNowResult) -> str:
        """Formata o resultado para resposta ao utilizador."""
        lines = [result.message, ""]

        # Detalhes de transporte público
        if result.transport_mode == "transit" and result.transit_lines:
            lines.append("🚌 **Percurso sugerido:**")
            for step in result.transit_steps[:5]:
                mode = step.get("mode", "")
                duration = step.get("duration_minutes", 0)
                transit = step.get("transit", {})

                if mode == "TRANSIT" and transit:
                    line_name = transit.get("short_name", transit.get("long_name", ""))
                    dep_stop = transit.get("departure_stop", "")
                    arr_stop = transit.get("arrival_stop", "")
                    dep_time = transit.get("departure_time", "")
                    stops = transit.get("num_stops", 0)
                    headsign = transit.get("headsign", "")

                    line_str = f"   🚌 **{line_name}**"
                    if headsign:
                        line_str += f" → {headsign}"
                    if dep_time:
                        line_str += f" às {dep_time}"
                    lines.append(line_str)

                    if dep_stop and arr_stop:
                        lines.append(f"   De: {dep_stop} → Até: {arr_stop}")
                    if stops:
                        lines.append(f"   ({stops} paragens · {duration:.0f} min)")

                elif mode == "WALK":
                    lines.append(f"   🚶 A pé — {duration:.0f} min")

            lines.append("")

        # Disruption / alerta
        if result.has_transit_disruption and result.disruption_message:
            lines.append(result.disruption_message)

        if result.service_alerts:
            lines.append("📢 **Alertas de serviço:**")
            for alert in result.service_alerts[:2]:
                if alert:
                    lines.append(f"   • {alert}")
            lines.append("")

        # Breakdown do cálculo
        lines.append("📊 **Cálculo:**")
        lines.append(f"   🚗 Viagem: {result.travel_minutes:.0f} min")

        if result.weather_buffer_minutes > 0:
            lines.append(
                f"   🌧️ Buffer clima ({result.weather_condition}): "
                f"+{result.weather_buffer_minutes:.0f} min"
            )

        if result.transit_delay_minutes > 0:
            lines.append(f"   🚌 Atraso TFI: +{result.transit_delay_minutes:.0f} min")

        lines.append(f"   ⏱️ Preparação: +{result.prep_minutes:.0f} min")

        total_buffer = (
            result.weather_buffer_minutes
            + result.transit_delay_minutes
            + result.prep_minutes
        )
        lines.append(
            f"   **Total: {result.travel_minutes:.0f} + {total_buffer:.0f} = "
            f"{result.travel_minutes + total_buffer:.0f} min antes do evento**"
        )

        # CTA
        if result.action_message:
            lines.append("")
            lines.append(result.action_message)

        return "\n".join(lines)

    def get_capabilities(self) -> List[str]:
        return [
            "departure_time_calculation",
            "traffic_aware_routing",
            "transit_routing",
            "tfi_realtime_delays",
            "weather_buffer",
            "proactive_departure_alerts",
            "all_day_schedule",
        ]
