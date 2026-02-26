# -*- coding: utf-8 -*-
"""
agents/specialized/meeting_agent.py
=====================================
MeetingAgent — cria reuniões Google Meet via CalendarService existente.

Não precisa de nova API key — usa a mesma service_account.json do Calendar.

Exemplos de queries:
  - "Cria uma reunião com João amanhã às 10h"
  - "Agenda uma call com maria@email.com sexta às 15h"
  - "Cria meet de 30 minutos com equipe hoje às 14h"
  - "Nova reunião: Daily Standup amanhã 9h com ana@x.com e pedro@x.com"
  - "Agenda reunião de revisão para 25/02 às 16h"
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


# ─── Regex helpers ────────────────────────────────────────────────────────────

# Email
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", re.IGNORECASE)

# Duração: "30 minutos", "1 hora", "2h", "45min"
_RE_DURATION = re.compile(r"(\d+)\s*(hora[s]?|h\b|minuto[s]?|min\b)", re.IGNORECASE)

# Hora: "10h", "10:30", "às 14h30", "at 3pm", "3:00pm"
_RE_TIME = re.compile(r"\b(\d{1,2})[:h](\d{0,2})\s*(am|pm)?\b", re.IGNORECASE)

# Data relativa
_RELATIVE_DAYS = {
    "hoje": 0,
    "today": 0,
    "amanhã": 1,
    "amanha": 1,
    "tomorrow": 1,
    "depois de amanhã": 2,
    "depois de amanha": 2,
}

# Dias da semana (PT + EN) → weekday index (0=segunda)
_WEEKDAYS = {
    "segunda": 0,
    "monday": 0,
    "terça": 1,
    "terca": 1,
    "tuesday": 1,
    "quarta": 2,
    "wednesday": 2,
    "quinta": 3,
    "thursday": 3,
    "sexta": 4,
    "friday": 4,
    "sábado": 5,
    "sabado": 5,
    "saturday": 5,
    "domingo": 6,
    "sunday": 6,
}

# Meses abreviados PT/EN
_MONTHS = {
    "jan": 1,
    "fev": 2,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "aug": 8,
    "set": 9,
    "sep": 9,
    "out": 10,
    "oct": 10,
    "nov": 11,
    "dez": 12,
    "dec": 12,
}


def _extract_emails(text: str) -> List[str]:
    """Extrai todos os emails do texto."""
    return _RE_EMAIL.findall(text)


def _extract_duration_minutes(text: str) -> int:
    """Extrai duração em minutos. Default: 60 minutos."""
    lower = text.lower()
    # Remove padrões de horário (às 10h, 14h30) para não confundir com duração
    cleaned = re.sub(r"(?:às|as)\s*\d{1,2}[:h]\d{0,2}", "", lower)
    cleaned = re.sub(r"\b\d{1,2}[:h]\d{2}\b", "", cleaned)
    match = _RE_DURATION.search(cleaned)
    if not match:
        return 60
    value = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("h"):
        return value * 60
    return value


def _extract_title(text: str) -> Optional[str]:
    """
    Tenta extrair título da reunião do prompt.
    Remove palavras de comando e retorna o que sobra.
    """
    cleaned = text.strip()

    # Remove prefixos de comando
    for prefix in [
        r"cria(r)?\s+(uma\s+)?(nova\s+)?(reunião|reuniao|meet|call|meeting)",
        r"agenda(r)?\s+(uma\s+)?(nova\s+)?(reunião|reuniao|meet|call|meeting)",
        r"nova\s+(reunião|reuniao|meet|call|meeting)",
        r"mark(a|ar)?\s+(uma\s+)?(reunião|reuniao|meet|call)",
        r"schedule\s+(a\s+)?(new\s+)?(meeting|call|meet)",
        r"create\s+(a\s+)?(new\s+)?(meeting|call|meet)",
    ]:
        cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE).strip()

    # Remove emails, datas, horários do título
    cleaned = _RE_EMAIL.sub("", cleaned)
    cleaned = re.sub(
        r"\b(hoje|amanhã?|tomorrow|monday|segunda|terça|terca|quarta|quinta|sexta|sábado?|domingo)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b\d{1,2}[:/h]\d{0,2}\s*(am|pm)?\b", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", "", cleaned)
    cleaned = re.sub(
        r"\b\d+\s*(hora[s]?|h|minuto[s]?|min)\b", "", cleaned, flags=re.IGNORECASE
    )

    # Remove stop-words
    for word in [
        "com",
        "with",
        "para",
        "for",
        "às",
        "as",
        "at",
        "de",
        "em",
        "uma",
        "um",
        "a",
        "o",
        "e",
        ":",
    ]:
        cleaned = re.sub(rf"\b{word}\b", " ", cleaned, flags=re.IGNORECASE)

    # Capitaliza e limpa espaços
    title = " ".join(cleaned.split()).strip(": ,.-")
    return title if len(title) > 2 else None


def _extract_datetime(text: str) -> Optional[datetime]:
    """
    Extrai data+hora do texto.
    Suporta: hoje, amanhã, dias da semana, DD/MM, DD/MM/AAAA + HH:MM / HHh
    """
    text_lower = text.lower()
    now = datetime.now(timezone.utc)
    target_date: Optional[datetime] = None

    # 1. Data relativa ("hoje", "amanhã")
    for word, delta in _RELATIVE_DAYS.items():
        if word in text_lower:
            target_date = now + timedelta(days=delta)
            break

    # 2. Dia da semana ("sexta", "friday")
    if target_date is None:
        for day_name, weekday in _WEEKDAYS.items():
            if day_name in text_lower:
                days_ahead = (weekday - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7  # próxima ocorrência
                target_date = now + timedelta(days=days_ahead)
                break

    # 3. Data explícita DD/MM ou DD/MM/AAAA
    if target_date is None:
        date_match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year_raw = date_match.group(3)
            year = int(year_raw) if year_raw else now.year
            if year < 100:
                year += 2000
            try:
                target_date = datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                pass

    # 4. Fallback: hoje
    if target_date is None:
        target_date = now

    # 5. Extrai hora
    time_match = _RE_TIME.search(text)
    hour, minute = 9, 0  # default 09:00

    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        ampm = (time_match.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

    return target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)


@register_agent("meeting")
class MeetingAgent(BaseAgent):
    """
    Meeting agent — cria reuniões Google Meet.

    Usa CalendarService existente (sem nova API key).
    O link do Google Meet é gerado automaticamente pelo Google Calendar API
    adicionando conferenceData ao criar o evento.

    Intents:
        create  → cria reunião e retorna link Meet
        list    → lista próximas reuniões (delega ao CalendarAgent)
    """

    def __init__(self):
        super().__init__(
            name="meeting",
            description="Cria reuniões Google Meet e gerencia agenda de reuniões",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        try:
            cal_svc = get_service("calendar")
            if not cal_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Serviço de calendário não disponível.\n"
                        "Verifique se o `GOOGLE_SERVICE_ACCOUNT_FILE` está configurado."
                    ),
                    error="CalendarService unavailable",
                )
            if not cal_svc.is_initialized():
                await cal_svc.initialize()

            # ── Context override (dados já parseados pelo orquestrador) ──────
            if context.get("action") == "create_meeting":
                return await self._create_from_context(cal_svc, context)

            # ── Extrai dados do prompt natural ────────────────────────────────
            return await self._create_from_prompt(cal_svc, prompt, context)

        except Exception as e:
            self.logger.error("MeetingAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao criar reunião: {str(e)}",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _create_from_prompt(
        self, cal_svc: Any, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        """Cria reunião extraindo dados do prompt natural."""

        # Título
        title = context.get("title") or _extract_title(prompt) or "Reunião"

        # Data/hora
        start_dt = _extract_datetime(prompt)

        # Duração
        duration_min = _extract_duration_minutes(prompt)
        end_dt = start_dt + timedelta(minutes=duration_min)

        # Participantes (emails)
        attendees = context.get("attendees") or _extract_emails(prompt)

        # Descrição
        description = context.get("description", "Reunião criada pelo Jarvis 🤖")

        # Timezone do contexto ou default Dublin/Irlanda
        tz_str = context.get("timezone", "Europe/Dublin")

        return await self._create_meeting(
            cal_svc=cal_svc,
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            attendees=attendees,
            description=description,
            tz_str=tz_str,
        )

    async def _create_from_context(
        self, cal_svc: Any, context: Dict[str, Any]
    ) -> AgentResponse:
        """Cria reunião com dados estruturados do context."""
        title = context.get("title", "Reunião")
        attendees = context.get("attendees", [])
        description = context.get("description", "Reunião criada pelo Jarvis 🤖")
        tz_str = context.get("timezone", "Europe/Dublin")
        duration_min = int(context.get("duration_minutes", 60))

        # start_datetime pode vir como string ISO ou datetime
        raw_start = context.get("start_datetime")
        if isinstance(raw_start, str):
            try:
                start_dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            except ValueError:
                start_dt = _extract_datetime(raw_start)
        elif isinstance(raw_start, datetime):
            start_dt = raw_start
        else:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Data e hora da reunião não especificadas.",
                error="Missing start_datetime",
            )

        end_dt = start_dt + timedelta(minutes=duration_min)

        return await self._create_meeting(
            cal_svc=cal_svc,
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            attendees=attendees,
            description=description,
            tz_str=tz_str,
        )

    async def _create_meeting(
        self,
        cal_svc: Any,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        attendees: List[str],
        description: str,
        tz_str: str,
    ) -> AgentResponse:
        """Cria o evento com Google Meet link via CalendarService."""

        # Usa o método create_meeting do CalendarService (com conferenceData)
        result = cal_svc.create_meeting(
            summary=title,
            start_time=start_dt,
            end_time=end_dt,
            attendees=attendees,
            description=description,
            timezone=tz_str,
        )

        if not result:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Não foi possível criar a reunião. "
                    "Verifique as permissões da service account no Google Calendar."
                ),
                error="CalendarService.create_meeting returned None",
            )

        meet_link = result.get("meet_link", "")
        event_link = result.get("html_link", "")

        response = self._format_response(
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            attendees=attendees,
            meet_link=meet_link,
            event_link=event_link,
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=result,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Formatação
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_response(
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        attendees: List[str],
        meet_link: str,
        event_link: str,
    ) -> str:
        date_str = start_dt.strftime("%d/%m/%Y")
        start_str = start_dt.strftime("%H:%M")
        end_str = end_dt.strftime("%H:%M")

        lines = [
            "✅ **Reunião criada com sucesso!**\n",
            f"📌 **{title}**",
            f"📅 {date_str} · {start_str} – {end_str}",
        ]

        if attendees:
            att_list = ", ".join(attendees)
            lines.append(f"👥 {att_list}")

        if meet_link:
            lines.append(f"\n🎥 **Google Meet:** {meet_link}")

        if event_link:
            lines.append(f"📆 **Ver no Calendar:** {event_link}")

        return "\n".join(lines)

    def get_capabilities(self) -> List[str]:
        return [
            "create_meeting",
            "google_meet_link",
            "schedule_call",
            "invite_attendees",
            "meeting_duration",
        ]
