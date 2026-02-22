# -*- coding: utf-8 -*-
"""
agents/specialized/weather_agent.py (versão melhorada)
========================================================
WeatherAgent com suporte a:
- Previsão 7 dias com emojis e tendência
- Alertas de chuva (>70% chance)
- Alertas de vento forte e UV alto
- Alertas meteorológicos oficiais (da WeatherAPI)
- Resumo semanal (melhor/pior dia)
- Clima atual enriquecido (UV, vento, sensação térmica)
- Intents: hoje / amanhã / semana / alertas / clima atual

Mantém backward compat: comportamento original para queries sem intent clara.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

logger = logging.getLogger(__name__)

LOCATION_PATTERN = re.compile(
    r"(?:em|in|para|for|de|of)\s+([a-zA-ZÀ-ÿ0-9 ,.\-]{2,}?)(?:\s*\?|$|,|\s+(?:hoje|amanhã|essa semana|week))",
    re.IGNORECASE,
)

_CONDITION_EMOJI = {
    "sun": "☀️", "clear": "☀️", "sol": "☀️",
    "cloud": "☁️", "nublado": "☁️", "overcast": "☁️",
    "partly": "⛅", "parcialmente": "⛅",
    "rain": "🌧️", "chuva": "🌧️", "drizzle": "🌦️",
    "thunder": "⛈️", "storm": "⛈️", "tempest": "⛈️",
    "snow": "❄️", "neve": "❄️", "sleet": "🌨️",
    "fog": "🌫️", "mist": "🌫️", "neblina": "🌫️",
    "wind": "💨", "vento": "💨", "hail": "🌨️",
}

_WEEKDAYS_PT = {0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui", 4: "Sex", 5: "Sáb", 6: "Dom"}
_WEEKDAYS_FULL_PT = {
    0: "segunda-feira", 1: "terça-feira", 2: "quarta-feira",
    3: "quinta-feira", 4: "sexta-feira", 5: "sábado", 6: "domingo",
}


def _condition_emoji(condition: str) -> str:
    cond_lower = condition.lower()
    for keyword, emoji in _CONDITION_EMOJI.items():
        if keyword in cond_lower:
            return emoji
    return "🌡️"


def _uv_label(uv: float) -> str:
    # FIX E701: expanded to multi-line
    if uv <= 2:
        return "baixo"
    if uv <= 5:
        return "moderado"
    if uv <= 7:
        return "alto"
    if uv <= 10:
        return "muito alto"
    return "extremo"


def _date_to_weekday(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return _WEEKDAYS_PT[dt.weekday()]
    except Exception:
        return date_str


@register_agent("weather")
class WeatherAgent(BaseAgent):
    """
    Weather agent for weather forecasts and conditions.

    Handles:
    - Current weather (temperature, condition, UV, wind)
    - 7-day forecast with trend
    - Rain/wind/UV alerts
    - Official meteorological alerts
    - Week summary (best/worst day)
    """

    def __init__(self):
        super().__init__(
            name="weather",
            description="Provides weather forecasts and current conditions",
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Route weather query based on detected intent."""
        try:
            weather_svc = get_service("weather")
            if not weather_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço de clima não disponível.",
                    error="Weather service not available",
                )
            if not weather_svc.is_initialized():
                await weather_svc.initialize()

            location = self._extract_location(prompt, context)
            if not location:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Não consegui identificar a cidade. Tente:\n"
                        "• *Clima em Dublin*\n"
                        "• *Previsão para São Paulo essa semana*\n"
                        "• *Vai chover amanhã em Lisboa?*"
                    ),
                    error="No location provided",
                )

            prompt_lower = (prompt or "").lower()

            if any(w in prompt_lower for w in ["alerta", "alert", "perigo", "risco"]):
                return await self._handle_alerts(weather_svc, location)

            if any(w in prompt_lower for w in [
                "semana", "week", "7 dias", "sete dias",
                "próximos dias", "próximos", "previsão", "previsao",
            ]):
                days = context.get("days", 7)
                return await self._handle_week(weather_svc, location, days)

            if any(w in prompt_lower for w in ["amanhã", "amanha", "tomorrow"]):
                return await self._handle_tomorrow(weather_svc, location)

            return await self._handle_today(weather_svc, location)

        except Exception as e:
            self.logger.error("WeatherAgent error for '%s': %s", prompt, e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                # FIX F541: removed f-string with no placeholders
                response="Não foi possível consultar o clima.",
                error=str(e),
                metadata={"prompt": prompt},
            )

    # ──────────────────────────────────────────────────────────────────────────
    # HANDLERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_today(self, svc: Any, location: str) -> AgentResponse:
        data = await svc.get_detailed_forecast(location, days=1)
        loc = data["location"]
        cur = data["current"]
        today = data["forecast"][0] if data["forecast"] else {}
        alerts = data.get("alerts", [])

        emoji = _condition_emoji(cur["condition"])
        uv = cur.get("uv", 0)
        wind = cur.get("wind_kph", 0)
        wind_dir = cur.get("wind_dir", "")

        lines = [
            f"{emoji} **{loc['name']}, {loc['country']}**",
            f"🌡️ {cur['temp_c']}°C (sensação {cur['feels_like_c']}°C) — {cur['condition']}",
            f"💧 Humidade: {cur['humidity']}%",
            f"💨 Vento: {wind} km/h {wind_dir}",
            f"🔆 UV: {uv} ({_uv_label(uv)})",
        ]
        if today:
            rain_pct = today.get("chance_of_rain", 0)
            if rain_pct > 0:
                rain_emoji = "🌧️" if rain_pct >= 70 else "🌦️"
                lines.append(f"{rain_emoji} Chance de chuva hoje: {rain_pct}%")
            if today.get("sunrise"):
                lines.append(f"🌅 Nascer: {today['sunrise']} 🌇 Pôr: {today['sunset']}")
        if alerts:
            lines.append("")
            lines.append(f"⚠️ **{len(alerts)} alerta(s) ativo(s):**")
            for a in alerts[:2]:
                lines.append(f" • {a['headline']}")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"location": loc, "current": cur, "today": today, "alerts": alerts},
        )

    async def _handle_tomorrow(self, svc: Any, location: str) -> AgentResponse:
        data = await svc.get_detailed_forecast(location, days=2)
        loc = data["location"]
        forecast = data["forecast"]
        if len(forecast) < 2:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Não foi possível obter a previsão de amanhã para {loc['name']}.",
                error="No tomorrow data",
            )
        tomorrow = forecast[1]
        emoji = _condition_emoji(tomorrow["condition"])
        rain_pct = tomorrow["chance_of_rain"]
        rain_line = f"🌧️ Chance de chuva: **{rain_pct}%**" if rain_pct > 0 else "☀️ Sem previsão de chuva"

        lines = [
            f"{emoji} **Amanhã em {loc['name']}**",
            f"🌡️ Máx {tomorrow['max_temp_c']}°C / Mín {tomorrow['min_temp_c']}°C",
            f"🌤️ {tomorrow['condition']}",
            rain_line,
        ]
        if tomorrow.get("max_wind_kph", 0) >= 30:
            lines.append(f"💨 Vento: até {tomorrow['max_wind_kph']} km/h")
        if tomorrow.get("uv", 0) >= 6:
            lines.append(f"🔆 UV: {tomorrow['uv']} ({_uv_label(tomorrow['uv'])})")
        if tomorrow.get("sunrise"):
            lines.append(f"🌅 Nascer: {tomorrow['sunrise']} 🌇 Pôr: {tomorrow['sunset']}")
        lines.extend(self._format_day_alerts(tomorrow))

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"location": loc, "tomorrow": tomorrow},
        )

    async def _handle_week(self, svc: Any, location: str, days: int = 7) -> AgentResponse:
        data = await svc.get_week_summary(location)
        loc = data["location"]
        forecast = data["forecast"]
        summary = data["summary"]
        alerts = data.get("alerts", [])

        lines = [f"📅 **Previsão 7 dias — {loc['name']}, {loc['country']}**\n"]
        for day in forecast:
            emoji = _condition_emoji(day["condition"])
            weekday = _date_to_weekday(day["date"])
            rain_pct = day["chance_of_rain"]
            rain_str = f" 🌧️{rain_pct}%" if rain_pct >= 30 else ""
            uv_str = f" 🔆UV{day['uv']}" if day.get("uv", 0) >= 6 else ""
            wind_str = f" 💨{day['max_wind_kph']}km/h" if day.get("max_wind_kph", 0) >= 40 else ""
            alert_str = " ⚠️" if day.get("rain_alert") or day.get("wind_alert") or day.get("uv_alert") else ""
            lines.append(
                f"{emoji} **{weekday}** {day['date'][5:]} "
                f"{day['max_temp_c']}°/{day['min_temp_c']}°C "
                f"{day['condition']}{rain_str}{uv_str}{wind_str}{alert_str}"
            )

        lines.append("")
        best = summary["best_day"]
        worst = summary["worst_day"]
        lines.append(
            f"✅ **Melhor dia:** {_date_to_weekday(best['date'])} "
            f"({best['max_temp_c']}°C, chuva {best['chance_of_rain']}%)"
        )
        lines.append(
            f"🌧️ **Mais chuvoso:** {_date_to_weekday(worst['date'])} "
            f"({worst['chance_of_rain']}% chuva)"
        )
        lines.append(
            f"🌡️ **Média:** máx {summary['avg_max_temp_c']}°C / mín {summary['avg_min_temp_c']}°C"
        )
        if summary["rainy_days_count"] > 0:
            lines.append(f"☔ {summary['rainy_days_count']} dia(s) com alta chance de chuva")

        if alerts:
            lines.append("")
            lines.append(f"⚠️ **{len(alerts)} alerta(s) meteorológico(s) ativo(s):**")
            for a in alerts[:3]:
                lines.append(f" • [{a['severity']}] {a['headline']}")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"location": loc, "forecast": forecast, "summary": summary, "alerts": alerts},
        )

    async def _handle_alerts(self, svc: Any, location: str) -> AgentResponse:
        data = await svc.get_detailed_forecast(location, days=3)
        loc = data["location"]
        official_alerts = data.get("alerts", [])
        forecast = data["forecast"]

        lines = [f"⚠️ **Alertas meteorológicos — {loc['name']}**\n"]
        if official_alerts:
            lines.append(f"🚨 **{len(official_alerts)} alerta(s) oficial(is):**")
            for a in official_alerts:
                lines.append(f"\n**{a['event']}** [{a['severity']}]")
                lines.append(f" {a['headline']}")
                if a.get("description"):
                    lines.append(f" _{a['description'][:200]}_")
                if a.get("expires"):
                    lines.append(f" Expira: {a['expires']}")
        else:
            lines.append("✅ Nenhum alerta oficial ativo no momento.")

        derived = []
        for day in forecast:
            day_alerts = self._format_day_alerts(day)
            if day_alerts:
                wd = _date_to_weekday(day["date"])
                for alert in day_alerts:
                    derived.append(f" • **{wd}** {day['date'][5:]}: {alert.strip()}")

        if derived:
            lines.append("")
            lines.append("📊 **Alertas dos próximos 3 dias:**")
            lines.extend(derived)

        if not official_alerts and not derived:
            lines = [
                f"✅ **Nenhum alerta para {loc['name']}**\n",
                "O tempo deve estar estável nos próximos 3 dias.",
            ]

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"location": loc, "official_alerts": official_alerts, "forecast": forecast},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    def _format_day_alerts(self, day: Dict[str, Any]) -> List[str]:
        alerts = []
        if day.get("rain_alert"):
            alerts.append(f"🌧️ Chuva forte: {day['chance_of_rain']}% de chance")
        if day.get("wind_alert"):
            alerts.append(f"💨 Vento forte: até {day['max_wind_kph']} km/h")
        if day.get("uv_alert"):
            alerts.append(f"🔆 UV alto: {day['uv']} ({_uv_label(day['uv'])})")
        return alerts

    def _extract_location(self, prompt: str, context: Dict[str, Any]) -> Optional[str]:
        if context.get("location"):
            return str(context["location"]).strip()
        match = LOCATION_PATTERN.search(prompt or "")
        if match:
            return match.group(1).strip(" .,!?:;")
        cleaned = (prompt or "").strip()
        for keyword in [
            "previsão", "previsao", "clima", "tempo", "weather",
            "alerta", "semana", "amanhã", "hoje", "vai chover",
        ]:
            cleaned = re.sub(rf"\b{keyword}\b", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned if len(cleaned) >= 2 else None

    def get_capabilities(self) -> List[str]:
        return [
            "current_weather",
            "weather_forecast",
            "7_day_forecast",
            "rain_alerts",
            "wind_alerts",
            "uv_alerts",
            "official_weather_alerts",
            "week_summary",
            "best_day_recommendation",
        ]
