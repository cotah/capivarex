# -*- coding: utf-8 -*-
"""
Time Agent
==========
Responde perguntas sobre hora, data, fuso horário e diferença entre cidades.
Não requer API externa — usa Python datetime + zoneinfo (stdlib, Python 3.9+).

Exemplos de queries:
  - "Que horas são em Tóquio?"
  - "Qual a diferença de horário entre Dublin e São Paulo?"
  - "Que dia é hoje?"
  - "Que horas são agora?"
  - "É de manhã ou de noite em Nova York?"
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent

logger = logging.getLogger(__name__)


# ─── Mapa de cidades/países → timezone IANA ───────────────────────────────────
CITY_TO_TZ: Dict[str, str] = {
    # Brasil
    "são paulo": "America/Sao_Paulo",
    "sao paulo": "America/Sao_Paulo",
    "sp": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    "rio": "America/Sao_Paulo",
    "brasilia": "America/Sao_Paulo",
    "brasília": "America/Sao_Paulo",
    "belo horizonte": "America/Sao_Paulo",
    "bh": "America/Sao_Paulo",
    "curitiba": "America/Sao_Paulo",
    "porto alegre": "America/Sao_Paulo",
    "fortaleza": "America/Fortaleza",
    "recife": "America/Recife",
    "manaus": "America/Manaus",
    "belem": "America/Belem",
    "belém": "America/Belem",
    "salvador": "America/Bahia",
    "brasil": "America/Sao_Paulo",
    "brazil": "America/Sao_Paulo",
    # Europa
    "dublin": "Europe/Dublin",
    "irlanda": "Europe/Dublin",
    "ireland": "Europe/Dublin",
    "london": "Europe/London",
    "londres": "Europe/London",
    "uk": "Europe/London",
    "paris": "Europe/Paris",
    "franca": "Europe/Paris",
    "france": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "alemanha": "Europe/Berlin",
    "germany": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "espanha": "Europe/Madrid",
    "spain": "Europe/Madrid",
    "roma": "Europe/Rome",
    "rome": "Europe/Rome",
    "italia": "Europe/Rome",
    "italy": "Europe/Rome",
    "amsterdam": "Europe/Amsterdam",
    "holanda": "Europe/Amsterdam",
    "netherlands": "Europe/Amsterdam",
    "lisboa": "Europe/Lisbon",
    "lisbon": "Europe/Lisbon",
    "portugal": "Europe/Lisbon",
    "moscou": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "russia": "Europe/Moscow",
    # América
    "new york": "America/New_York",
    "nova york": "America/New_York",
    "ny": "America/New_York",
    "miami": "America/New_York",
    "boston": "America/New_York",
    "washington": "America/New_York",
    "chicago": "America/Chicago",
    "houston": "America/Chicago",
    "denver": "America/Denver",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "toronto": "America/Toronto",
    "canada": "America/Toronto",
    "mexico city": "America/Mexico_City",
    "cidade do mexico": "America/Mexico_City",
    "mexico": "America/Mexico_City",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "argentina": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago",
    "chile": "America/Santiago",
    "bogota": "America/Bogota",
    "colombia": "America/Bogota",
    "lima": "America/Lima",
    "peru": "America/Lima",
    # Ásia
    "tokyo": "Asia/Tokyo",
    "toquio": "Asia/Tokyo",
    "tóquio": "Asia/Tokyo",
    "japao": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "seoul": "Asia/Seoul",
    "coreia": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "singapore": "Asia/Singapore",
    "singapura": "Asia/Singapore",
    "dubai": "Asia/Dubai",
    "mumbai": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "nova delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "bangkok": "Asia/Bangkok",
    "tailandia": "Asia/Bangkok",
    "thailand": "Asia/Bangkok",
    # Oceania
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "australia": "Australia/Sydney",
    "auckland": "Pacific/Auckland",
    "nova zelandia": "Pacific/Auckland",
    "new zealand": "Pacific/Auckland",
    # África / Oriente Médio
    "cairo": "Africa/Cairo",
    "egito": "Africa/Cairo",
    "egypt": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "africa do sul": "Africa/Johannesburg",
    "south africa": "Africa/Johannesburg",
    "nairobi": "Africa/Nairobi",
    "quenia": "Africa/Nairobi",
    "kenya": "Africa/Nairobi",
    "israel": "Asia/Jerusalem",
    "tel aviv": "Asia/Jerusalem",
    # UTC
    "utc": "UTC",
    "gmt": "UTC",
}

# Mapa de períodos do dia
_PERIODS = {
    (0, 5):   "de madrugada",
    (5, 12):  "de manhã",
    (12, 14): "ao meio-dia",
    (14, 18): "à tarde",
    (18, 21): "à noite",
    (21, 24): "à noite",
}

# Nomes dos dias em PT-BR
_WEEKDAYS_PT = ["segunda-feira", "terça-feira", "quarta-feira",
                "quinta-feira", "sexta-feira", "sábado", "domingo"]

# Meses em PT-BR
_MONTHS_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]


@register_agent("time")
class TimeAgent(BaseAgent):
    """
    Time agent for timezone and datetime queries.

    Handles:
    - Current time in any city/timezone
    - Current date and day of week
    - Timezone difference between two cities
    - Period of day (morning/afternoon/night)
    """

    def __init__(self):
        super().__init__(
            name="time",
            description="Informa hora, data e fuso horário em qualquer cidade do mundo",
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """
        Handle time/timezone queries.

        Detects intent from prompt:
          - "diferença" / "difference" → timezone diff between two places
          - two cities detected            → same as above
          - single city / no city         → current time in that city
          - "data" / "dia"                → current date
        """
        try:
            prompt_lower = (prompt or "").lower()

            # Intent: diferença de horário entre duas cidades
            if any(w in prompt_lower for w in ["diferença", "diferenca", "difference", "entre"]):
                return self._handle_diff(prompt_lower, context)

            # Extrai cidade(s) do prompt
            cities = self._extract_cities(prompt_lower)

            if len(cities) >= 2:
                return self._handle_diff(prompt_lower, context, cities)

            # Intent: data de hoje
            if any(w in prompt_lower for w in ["data", "dia de hoje", "hoje é", "que dia"]):
                tz = self._resolve_tz(cities[0] if cities else None, context)
                return self._handle_date(tz)

            # Intent: hora atual (com ou sem cidade)
            tz = self._resolve_tz(cities[0] if cities else None, context)
            return self._handle_time(tz, cities[0] if cities else None)

        except Exception as e:
            self.logger.error("TimeAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não consegui processar sua pergunta sobre horário.",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_time(
        self, tz: ZoneInfo, city_name: Optional[str]
    ) -> AgentResponse:
        """Returns current time in a timezone."""
        now = datetime.now(tz)
        tz_name = str(tz)
        hour = now.hour
        period = next(p for (h0, h1), p in _PERIODS.items() if h0 <= hour < h1)

        if city_name:
            city_display = city_name.title()
            text = (
                f"Agora em {city_display} são "
                f"**{now.strftime('%H:%M')}** {period} "
                f"({now.strftime('%d/%m/%Y')}, {_WEEKDAYS_PT[now.weekday()]}).\n"
                f"Fuso horário: {tz_name} (UTC{now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})"
            )
        else:
            text = (
                f"Agora são **{now.strftime('%H:%M')}** {period} "
                f"({now.strftime('%d/%m/%Y')}, {_WEEKDAYS_PT[now.weekday()]}).\n"
                f"Fuso horário local: {tz_name}"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={
                "time": now.strftime("%H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "timezone": tz_name,
                "utc_offset": now.strftime("%z"),
                "city": city_name,
            },
        )

    def _handle_date(self, tz: ZoneInfo) -> AgentResponse:
        """Returns current date."""
        now = datetime.now(tz)
        weekday = _WEEKDAYS_PT[now.weekday()]
        month = _MONTHS_PT[now.month]
        text = (
            f"Hoje é **{weekday}**, "
            f"{now.day} de {month} de {now.year}."
        )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={
                "date": now.strftime("%Y-%m-%d"),
                "weekday": weekday,
                "day": now.day,
                "month": month,
                "year": now.year,
            },
        )

    def _handle_diff(
        self,
        prompt: str,
        context: Dict[str, Any],
        cities: Optional[List[str]] = None,
    ) -> AgentResponse:
        """Returns timezone difference between two cities."""
        if cities is None:
            cities = self._extract_cities(prompt)

        if len(cities) < 2:
            # Tenta pegar do contexto
            city_a = context.get("city_a") or (cities[0] if cities else None)
            city_b = context.get("city_b")
            if not city_a or not city_b:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Para calcular a diferença de horário, informe duas cidades.\n"
                        "Exemplo: 'Diferença de horário entre Dublin e São Paulo?'"
                    ),
                    error="Need two cities for diff",
                )
            cities = [city_a, city_b]

        tz_a = self._resolve_tz(cities[0], context)
        tz_b = self._resolve_tz(cities[1], context)

        now = datetime.now()
        time_a = now.astimezone(tz_a)
        time_b = now.astimezone(tz_b)

        offset_a = time_a.utcoffset().total_seconds() / 3600
        offset_b = time_b.utcoffset().total_seconds() / 3600
        diff = offset_b - offset_a
        diff_abs = abs(diff)
        hours = int(diff_abs)
        mins = int((diff_abs - hours) * 60)

        diff_str = f"{hours}h" + (f"{mins:02d}min" if mins else "")
        direction = "à frente" if diff > 0 else "atrás"

        city_a_display = cities[0].title()
        city_b_display = cities[1].title()

        text = (
            f"**{city_a_display}**: {time_a.strftime('%H:%M')} "
            f"(UTC{int(offset_a):+d})\n"
            f"**{city_b_display}**: {time_b.strftime('%H:%M')} "
            f"(UTC{int(offset_b):+d})\n\n"
            f"**Diferença**: {city_b_display} está {diff_str} {direction} "
            f"de {city_a_display}."
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={
                "city_a": {"name": city_a_display, "time": time_a.strftime("%H:%M"),
                           "timezone": str(tz_a), "utc_offset": int(offset_a)},
                "city_b": {"name": city_b_display, "time": time_b.strftime("%H:%M"),
                           "timezone": str(tz_b), "utc_offset": int(offset_b)},
                "diff_hours": diff,
            },
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_cities(self, text: str) -> List[str]:
        """Extract known city/country names from text (longest match first)."""
        found = []
        # Sort keys by length (longest first) to prefer "new york" over "york"
        for key in sorted(CITY_TO_TZ.keys(), key=len, reverse=True):
            if key in text and key not in found:
                found.append(key)
                if len(found) == 2:
                    break
        return found

    def _resolve_tz(
        self, city: Optional[str], context: Dict[str, Any]
    ) -> ZoneInfo:
        """
        Resolve a ZoneInfo from city name, context, or default to UTC.
        Priority: city name → context["timezone"] → "UTC"
        """
        # From city name
        if city and city.lower() in CITY_TO_TZ:
            tz_str = CITY_TO_TZ[city.lower()]
            try:
                return ZoneInfo(tz_str)
            except ZoneInfoNotFoundError:
                pass

        # From context (explicit IANA timezone string)
        ctx_tz = context.get("timezone")
        if ctx_tz:
            try:
                return ZoneInfo(str(ctx_tz))
            except ZoneInfoNotFoundError:
                pass

        # Default: UTC
        return ZoneInfo("UTC")

    def get_capabilities(self) -> List[str]:
        return [
            "current_time",
            "current_date",
            "timezone_info",
            "timezone_difference",
            "time_by_city",
        ]
