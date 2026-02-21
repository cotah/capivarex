# -*- coding: utf-8 -*-
"""
services/business/leaving_now_service.py
==========================================
LeavingNowService — calcula quando sair para nunca te atrasares.

Fórmula:
  hora_alerta = hora_evento
              - tempo_viagem           (TrafficService ou TransitService)
              - buffer_clima           (WeatherService → chuva, tempestade)
              - atraso_transporte      (TFI GTFS-Realtime via TransitService)
              - tempo_preparacao       (configurável pelo utilizador, default 10 min)

Níveis de urgência:
  LATE        → já devias ter saído
  URGENT      → sai AGORA (< 5 min)
  SOON        → prepara-te (5–20 min)
  COMFORTABLE → tens tempo (20–45 min)
  RELAXED     → muito tempo (> 45 min)

Serviços envolvidos:
  - CalendarService   → próximo evento com localização
  - TrafficService    → tempo de viagem de carro em tempo real
  - TransitService    → transporte público + atrasos TFI
  - WeatherService    → condições climatéricas e buffer de chuva
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from services.core import BaseService, register_service, get_service

logger = logging.getLogger(__name__)

# Buffers de clima (minutos a adicionar ao tempo de viagem)
_WEATHER_BUFFERS = {
    "clear":       0,
    "sunny":       0,
    "cloudy":      0,
    "overcast":    0,
    "light_rain":  5,
    "rain":        10,
    "heavy_rain":  15,
    "storm":       20,
    "snow":        25,
    "blizzard":    30,
}

# Tempo de preparação default (minutos)
_DEFAULT_PREP_MINUTES = 10


@dataclass
class LeavingNowResult:
    """Resultado completo do cálculo de hora de saída."""

    # Core
    event_title: str
    event_location: str
    event_time: datetime
    suggested_departure: datetime
    minutes_until_departure: float
    urgency: str                       # LATE | URGENT | SOON | COMFORTABLE | RELAXED
    message: str                       # Mensagem principal para o utilizador
    action_message: str                # CTA: "Sai agora" / "Prepara-te em 10 min"

    # Detalhes do cálculo
    travel_minutes: float = 0.0
    weather_buffer_minutes: float = 0.0
    transit_delay_minutes: float = 0.0
    prep_minutes: float = _DEFAULT_PREP_MINUTES
    transport_mode: str = "driving"    # driving | transit

    # Transporte público
    transit_lines: List[Dict] = field(default_factory=list)
    transit_steps: List[Dict] = field(default_factory=list)
    has_transit_disruption: bool = False
    disruption_message: str = ""
    service_alerts: List[str] = field(default_factory=list)

    # Clima
    weather_condition: str = ""
    weather_temp_c: float = 0.0
    is_raining: bool = False

    # Extras
    distance_km: float = 0.0
    estimated_arrival: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializa para dict (para AgentResponse.data)."""
        return {
            "event_title": self.event_title,
            "event_location": self.event_location,
            "event_time": self.event_time.isoformat(),
            "suggested_departure": self.suggested_departure.isoformat(),
            "minutes_until_departure": round(self.minutes_until_departure, 1),
            "urgency": self.urgency,
            "message": self.message,
            "action_message": self.action_message,
            "breakdown": {
                "travel_minutes": round(self.travel_minutes, 1),
                "weather_buffer_minutes": self.weather_buffer_minutes,
                "transit_delay_minutes": self.transit_delay_minutes,
                "prep_minutes": self.prep_minutes,
                "total_buffer_minutes": round(
                    self.weather_buffer_minutes +
                    self.transit_delay_minutes +
                    self.prep_minutes, 1
                ),
            },
            "transport_mode": self.transport_mode,
            "transit_lines": self.transit_lines,
            "has_transit_disruption": self.has_transit_disruption,
            "disruption_message": self.disruption_message,
            "service_alerts": self.service_alerts,
            "weather": {
                "condition": self.weather_condition,
                "temp_c": self.weather_temp_c,
                "is_raining": self.is_raining,
                "buffer_added": self.weather_buffer_minutes,
            },
            "distance_km": self.distance_km,
            "estimated_arrival": (
                self.estimated_arrival.isoformat()
                if self.estimated_arrival else None
            ),
        }


@register_service("leaving_now")
class LeavingNowService(BaseService):
    """
    Serviço de cálculo de hora de saída inteligente.

    Orquestra CalendarService, TrafficService, WeatherService e TransitService
    para calcular exactamente quando o utilizador deve sair para um evento.
    """

    def __init__(self) -> None:
        super().__init__(name="leaving_now")

    async def _initialize(self) -> None:
        self.logger.info("LeavingNowService inicializado")

    async def _health_check(self) -> bool:
        # Saudável se pelo menos CalendarService e TrafficService estão disponíveis
        cal = get_service("calendar")
        traffic = get_service("traffic")
        return bool(cal and traffic)

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def calculate_for_next_event(
        self,
        user_location: str,
        transport_mode: str = "driving",
        prep_minutes: float = _DEFAULT_PREP_MINUTES,
    ) -> Optional[LeavingNowResult]:
        """
        Calcula hora de saída para o próximo evento com localização.

        Args:
            user_location:  Localização actual do utilizador (endereço ou cidade)
            transport_mode: "driving" (carro) ou "transit" (transporte público)
            prep_minutes:   Tempo de preparação do utilizador (minutos)

        Returns:
            LeavingNowResult com todos os detalhes, ou None se não há evento.
        """
        if not self.is_initialized():
            await self.initialize()

        # 1. Próximo evento com localização
        event = await self._get_next_event_with_location()
        if not event:
            self.logger.info("Nenhum evento com localização encontrado")
            return None

        return await self.calculate_for_event(
            event=event,
            user_location=user_location,
            transport_mode=transport_mode,
            prep_minutes=prep_minutes,
        )

    async def calculate_for_event(
        self,
        event: Dict[str, Any],
        user_location: str,
        transport_mode: str = "driving",
        prep_minutes: float = _DEFAULT_PREP_MINUTES,
    ) -> Optional[LeavingNowResult]:
        """
        Calcula hora de saída para um evento específico.

        Args:
            event:          Evento do calendário (dict formatado pelo CalendarService)
            user_location:  Localização actual do utilizador
            transport_mode: "driving" ou "transit"
            prep_minutes:   Tempo de preparação (minutos)

        Returns:
            LeavingNowResult completo.
        """
        event_title = event.get("summary", "Evento")
        event_location = event.get("location", "")
        event_time = self._parse_event_time(event)

        if not event_location:
            self.logger.warning("Evento '%s' sem localização", event_title)
            return None

        if not event_time:
            self.logger.warning("Evento '%s' sem hora definida", event_title)
            return None

        self.logger.info(
            "A calcular hora de saída: %s → %s às %s",
            user_location, event_location,
            event_time.strftime("%H:%M")
        )

        # 2. Tempo de viagem + clima (paralelo)
        travel_data, weather_data = await self._gather_travel_and_weather(
            user_location=user_location,
            event_location=event_location,
            event_time=event_time,
            transport_mode=transport_mode,
        )

        # 3. Buffer de clima
        weather_buffer = self._calculate_weather_buffer(weather_data)
        weather_condition = self._extract_weather_condition(weather_data)
        weather_temp = self._extract_weather_temp(weather_data)
        is_raining = weather_buffer > 0

        # 4. Dados de viagem
        travel_minutes = travel_data.get("duration_minutes", 30.0)
        distance_km = travel_data.get("distance_km", 0.0)

        # 5. Atraso de transporte (TFI GTFS-RT)
        transit_delay = 0.0
        transit_lines: List[Dict] = []
        transit_steps: List[Dict] = []
        has_disruption = False
        disruption_msg = ""
        service_alerts: List[str] = []
        estimated_arrival: Optional[datetime] = None

        if transport_mode == "transit":
            transit_delay = travel_data.get("realtime_delay_minutes", 0.0)
            transit_lines = travel_data.get("lines", [])
            transit_steps = travel_data.get("steps", [])
            has_disruption = travel_data.get("has_disruption", False)
            disruption_msg = travel_data.get("disruption_message", "")
            service_alerts = travel_data.get("service_alerts", [])

            adj_arrival_str = travel_data.get("adjusted_arrival_time")
            if adj_arrival_str:
                try:
                    estimated_arrival = datetime.fromisoformat(adj_arrival_str)
                except ValueError:
                    pass

        # 6. Fórmula central
        total_buffer = weather_buffer + transit_delay + prep_minutes
        suggested_departure = event_time - timedelta(minutes=travel_minutes + total_buffer)

        now = datetime.now()
        if suggested_departure.tzinfo:
            import pytz
            now = now.replace(tzinfo=pytz.UTC)

        minutes_until = (suggested_departure - now).total_seconds() / 60

        # 7. Urgência e mensagens
        urgency, message, action_msg = self._build_urgency_messages(
            event_title=event_title,
            event_location=event_location,
            event_time=event_time,
            suggested_departure=suggested_departure,
            minutes_until=minutes_until,
            travel_minutes=travel_minutes,
            weather_buffer=weather_buffer,
            transit_delay=transit_delay,
            weather_condition=weather_condition,
            transport_mode=transport_mode,
        )

        return LeavingNowResult(
            event_title=event_title,
            event_location=event_location,
            event_time=event_time,
            suggested_departure=suggested_departure,
            minutes_until_departure=minutes_until,
            urgency=urgency,
            message=message,
            action_message=action_msg,
            travel_minutes=travel_minutes,
            weather_buffer_minutes=weather_buffer,
            transit_delay_minutes=transit_delay,
            prep_minutes=prep_minutes,
            transport_mode=transport_mode,
            transit_lines=transit_lines,
            transit_steps=transit_steps,
            has_transit_disruption=has_disruption,
            disruption_message=disruption_msg,
            service_alerts=service_alerts,
            weather_condition=weather_condition,
            weather_temp_c=weather_temp,
            is_raining=is_raining,
            distance_km=distance_km,
            estimated_arrival=estimated_arrival,
        )

    async def get_all_events_today(
        self,
        user_location: str,
        transport_mode: str = "driving",
        prep_minutes: float = _DEFAULT_PREP_MINUTES,
    ) -> List[LeavingNowResult]:
        """
        Calcula hora de saída para TODOS os eventos de hoje com localização.

        Útil para o ProactivityService fazer o loop matinal completo.

        Returns:
            Lista de LeavingNowResult ordenada por hora do evento.
        """
        if not self.is_initialized():
            await self.initialize()

        cal = get_service("calendar")
        if not cal:
            return []

        try:
            events = cal.get_today_events()
        except Exception as e:
            self.logger.error("Erro ao buscar eventos de hoje: %s", e)
            return []

        results = []
        for event in events:
            if not event.get("location"):
                continue
            result = await self.calculate_for_event(
                event=event,
                user_location=user_location,
                transport_mode=transport_mode,
                prep_minutes=prep_minutes,
            )
            if result:
                results.append(result)

        # Ordena por hora do evento
        return sorted(results, key=lambda r: r.event_time)

    # ──────────────────────────────────────────────────────────────────────────
    # Private — orquestração
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_next_event_with_location(self) -> Optional[Dict[str, Any]]:
        """Obtém o próximo evento do calendário que tem localização."""
        try:
            cal = get_service("calendar")
            if not cal:
                return None

            events = cal.get_upcoming_events(max_results=10)
            now = datetime.now()

            for event in events:
                if not event.get("location", "").strip():
                    continue
                event_time = self._parse_event_time(event)
                if event_time and event_time > now:
                    return event
        except Exception as e:
            self.logger.error("Erro ao buscar próximo evento: %s", e)
        return None

    async def _gather_travel_and_weather(
        self,
        user_location: str,
        event_location: str,
        event_time: datetime,
        transport_mode: str,
    ) -> tuple:
        """
        Recolhe dados de viagem e clima em paralelo para performance.

        Returns:
            (travel_data, weather_data)
        """
        import asyncio

        travel_task = self._get_travel_data(
            user_location, event_location, event_time, transport_mode
        )
        weather_task = self._get_weather_data(user_location)

        travel_data, weather_data = await asyncio.gather(
            travel_task, weather_task, return_exceptions=True
        )

        if isinstance(travel_data, Exception):
            self.logger.error("Travel data error: %s", travel_data)
            travel_data = {"duration_minutes": 30.0, "distance_km": 0.0}

        if isinstance(weather_data, Exception):
            self.logger.warning("Weather data error: %s", weather_data)
            weather_data = {}

        return travel_data, weather_data

    async def _get_travel_data(
        self,
        origin: str,
        destination: str,
        event_time: datetime,
        transport_mode: str,
    ) -> Dict[str, Any]:
        """Obtém dados de viagem (carro ou transporte público)."""

        if transport_mode == "transit":
            transit = get_service("transit")
            if transit:
                if not transit.is_initialized():
                    await transit.initialize()
                return await transit.get_transit_with_delays(
                    origin, destination, departure_time=datetime.now()
                )

        # Default: carro
        traffic = get_service("traffic")
        if not traffic:
            return {"duration_minutes": 30.0, "distance_km": 0.0}

        if not traffic.is_initialized():
            await traffic.initialize()

        result = await traffic.get_route_with_traffic(origin, destination)
        if result.get("success"):
            route = result["route"]
            return {
                "duration_minutes": route.get("duration_minutes", 30.0),
                "distance_km": route.get("distance_km", 0.0),
            }

        return {"duration_minutes": 30.0, "distance_km": 0.0}

    async def _get_weather_data(self, location: str) -> Dict[str, Any]:
        """Obtém dados de clima actual."""
        try:
            weather = get_service("weather")
            if not weather:
                return {}
            if not weather.is_initialized():
                await weather.initialize()
            return await weather.get_current_weather(location)
        except Exception as e:
            self.logger.warning("Weather fetch error: %s", e)
            return {}

    # ──────────────────────────────────────────────────────────────────────────
    # Private — cálculos
    # ──────────────────────────────────────────────────────────────────────────

    def _calculate_weather_buffer(self, weather_data: Dict) -> float:
        """Calcula buffer de tempo com base nas condições climáticas."""
        if not weather_data:
            return 0.0

        condition = (
            weather_data.get("current", {}).get("condition", "")
            or weather_data.get("condition", "")
        ).lower()

        # Exact match first (e.g. "heavy_rain" before "rain")
        if condition in _WEATHER_BUFFERS:
            return float(_WEATHER_BUFFERS[condition])

        # Longest-match substring (avoid "rain" matching before "heavy_rain")
        best_key = ""
        best_buffer = 0.0
        for key, buffer in _WEATHER_BUFFERS.items():
            if key in condition and len(key) > len(best_key):
                best_key = key
                best_buffer = float(buffer)
        if best_key:
            return best_buffer

        # Verifica palavras de chuva/neve genéricas
        rain_words = ["rain", "drizzle", "shower", "mist", "chuva", "chuvisco", "aguaceiro"]
        snow_words = ["snow", "sleet", "blizzard", "neve", "granizo"]

        if any(w in condition for w in snow_words):
            return 20.0
        if any(w in condition for w in rain_words):
            return 10.0

        return 0.0

    @staticmethod
    def _extract_weather_condition(weather_data: Dict) -> str:
        """Extrai condição climática como string limpa."""
        if not weather_data:
            return ""
        return (
            weather_data.get("current", {}).get("condition", "")
            or weather_data.get("condition", "")
            or ""
        )

    @staticmethod
    def _extract_weather_temp(weather_data: Dict) -> float:
        """Extrai temperatura actual em Celsius."""
        if not weather_data:
            return 0.0
        return float(
            weather_data.get("current", {}).get("temp_c", 0)
            or weather_data.get("temp_c", 0)
            or 0
        )

    @staticmethod
    def _parse_event_time(event: Dict[str, Any]) -> Optional[datetime]:
        """Parseia a hora de início de um evento do calendário."""
        start = event.get("start", "")
        if not start or "T" not in str(start):
            return None
        try:
            dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            return dt.replace(tzinfo=None)  # naive para comparação simples
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _build_urgency_messages(
        event_title: str,
        event_location: str,
        event_time: datetime,
        suggested_departure: datetime,
        minutes_until: float,
        travel_minutes: float,
        weather_buffer: float,
        transit_delay: float,
        weather_condition: str,
        transport_mode: str,
    ) -> tuple:
        """
        Constrói mensagem de urgência personalizada e contextual.

        Returns:
            (urgency_level, main_message, action_message)
        """
        event_time_str = event_time.strftime("%H:%M")
        departure_str = suggested_departure.strftime("%H:%M")
        travel_str = f"{round(travel_minutes)} min"

        # CTA de transporte
        if transport_mode == "transit":
            nav_cta = "🚌 Abre o Google Maps para o percurso de transporte."
        else:
            nav_cta = "🗺️ Quer que eu inicie a rota no Google Maps?"

        # Linha de buffers (apenas se relevante)
        buffer_parts = []
        if weather_buffer > 0:
            rain_emoji = "🌧️" if "rain" in weather_condition.lower() else "🌨️"
            buffer_parts.append(f"{rain_emoji} +{weather_buffer:.0f} min ({weather_condition})")
        if transit_delay > 0:
            buffer_parts.append(f"🚌 +{transit_delay:.0f} min atraso")
        buffer_note = f" ({' · '.join(buffer_parts)})" if buffer_parts else ""

        # Urgência
        if minutes_until < 0:
            urgency = "LATE"
            late_min = abs(round(minutes_until))
            message = (
                f"🚨 **ATENÇÃO — já devias ter saído há {late_min} minutos!**\n"
                f"Evento: *{event_title}* às {event_time_str} em {event_location}\n"
                f"Tempo de viagem: {travel_str}{buffer_note}"
            )
            action_message = f"Sai AGORA! {nav_cta}"

        elif minutes_until < 5:
            urgency = "URGENT"
            message = (
                f"🔴 **SAI AGORA para *{event_title}*!**\n"
                f"Tens {round(minutes_until)} minuto(s) para sair.\n"
                f"Viagem: {travel_str} → chegada prevista às {event_time_str}{buffer_note}"
            )
            action_message = f"Sai imediatamente! {nav_cta}"

        elif minutes_until < 20:
            urgency = "SOON"
            message = (
                f"🟡 **Prepara-te! Sai em {round(minutes_until)} minutos.**\n"
                f"*{event_title}* às {event_time_str} em {event_location}\n"
                f"Hora de saída: **{departure_str}** · Viagem: {travel_str}{buffer_note}"
            )
            action_message = f"Prepara-te para sair às {departure_str}. {nav_cta}"

        elif minutes_until < 45:
            urgency = "COMFORTABLE"
            message = (
                f"🟢 *{event_title}* às {event_time_str}\n"
                f"Sai às **{departure_str}** (em {round(minutes_until)} min)\n"
                f"Viagem: {travel_str} para {event_location}{buffer_note}"
            )
            action_message = f"Lembra-te de sair às {departure_str}."

        else:
            urgency = "RELAXED"
            message = (
                f"📅 *{event_title}* às {event_time_str}\n"
                f"Tens tempo — sai às **{departure_str}** "
                f"(em {round(minutes_until)} min)\n"
                f"Viagem estimada: {travel_str} para {event_location}"
            )
            action_message = "Tens tempo de sobra. Avisarei quando estiver na hora."

        return urgency, message, action_message
