# -*- coding: utf-8 -*-
"""
agents/specialized/reminder_agent.py
=======================================
ReminderAgent — cria e gerencia lembretes persistentes.

Diferença vs TimerAgent:
  - TimerAgent → "marque 10 minutos" (efêmero, Redis)
  - ReminderAgent → "sexta às 10h" / "todo dia às 8h" (persistente, Supabase)

Exemplos suportados:
  - "Me lembra sexta às 10h para ligar pro médico"
  - "Todo dia às 8h me lembra de tomar o remédio"
  - "Lembrete para amanhã às 9h: reunião com o João"
  - "Me lembra em 3 dias para pagar o aluguel"
  - "Cancela o lembrete abc12345"
  - "Meus lembretes"
  - "Cancela todos os lembretes"
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

logger = logging.getLogger(__name__)

# ─── Regex de detecção de intenção ────────────────────────────────────────────

_CANCEL_WORDS  = ["cancela", "cancel", "remove", "apaga", "delete"]
_LIST_WORDS    = ["meus lembretes", "listar lembretes", "ver lembretes",
                  "lembretes ativos", "quais lembretes"]
_REMIND_WORDS  = ["me lembra", "lembrete", "remind", "me avisa", "me notifica"]

# Recorrência
_RE_DAILY   = re.compile(r"\btodo\s*dia\b|\bdiariamente\b|\bdaily\b", re.I)
_RE_WEEKLY  = re.compile(r"\btoda\s*semana\b|\bsemanalmente\b|\bweekly\b", re.I)
_RE_MONTHLY = re.compile(r"\btodo\s*m[eê]s\b|\bmensalmente\b|\bmonthly\b", re.I)

# FIX BUG 3 (regex): Aceita horário sem sufixo "h" — ex: "as 18", "às 18", "18h", "18:30"
# Antes: r"(?:às\s*|as\s*)?(\d{1,2})[h:](\d{0,2})(?:\s*h)?"  ← exigia [h:] obrigatório
# Agora:  o grupo [h:] é opcional usando (?:[h:](\d{0,2}))? para capturar minutos
_RE_TIME = re.compile(
    r"(?:às\s*|as\s*)?(\d{1,2})(?:[h:](\d{0,2}))?(?:\s*h(?:oras?)?)?",
    re.I,
)

# Dias relativos: "em 3 dias", "daqui 2 dias"
_RE_IN_DAYS = re.compile(r"(?:em|daqui)\s+(\d+)\s+dias?", re.I)
_RE_IN_WEEKS = re.compile(r"(?:em|daqui)\s+(\d+)\s+semanas?", re.I)

# Dias nomeados
_DAY_NAMES = {
    "segunda": 0, "segunda-feira": 0,
    "terça": 1, "terca": 1, "terça-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sábado": 5, "sabado": 5,
    "domingo": 6,
}

# UUID parcial (8 chars) para ID do lembrete
_RE_REMINDER_ID = re.compile(r"\b([0-9a-f]{8})\b", re.I)

# Mensagem após "para" ou ":"
_RE_MESSAGE = re.compile(
    r"(?:para\s+|:\s*)(.+?)(?:\s+(?:todo\s*dia|toda\s*semana|todo\s*m[eê]s))?$",
    re.I,
)


def _parse_remind_datetime(
    text: str, base: Optional[datetime] = None
) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Extrai (datetime_utc, recurrence) do texto.

    Retorna (None, None) se não conseguir parsear.

    Exemplos:
      "sexta às 10h"              → (próxima sexta 10:00 UTC, None)
      "todo dia às 8h"            → (amanhã 8:00 UTC, "daily")
      "amanhã às 9h"              → (amanhã 9:00 UTC, None)
      "em 3 dias para pagar"      → (agora + 3d, None)
      "toda semana às 15h"        → (próxima semana mesma hora, "weekly")
    """
    now = base or datetime.now(timezone.utc)
    text_lower = text.lower()

    # Detecta recorrência
    recurrence = None
    if _RE_DAILY.search(text_lower):
        recurrence = "daily"
    elif _RE_WEEKLY.search(text_lower):
        recurrence = "weekly"
    elif _RE_MONTHLY.search(text_lower):
        recurrence = "monthly"

    # Extrai hora — a regex agora aceita "18" sem "h" obrigatório
    hour, minute = 9, 0  # default: 9h
    time_match = _RE_TIME.search(text)
    if time_match:
        candidate = int(time_match.group(1))
        # Só considera válido se for um horário plausível (0–23)
        if 0 <= candidate <= 23:
            hour = candidate
            raw_min = time_match.group(2) if time_match.lastindex and time_match.lastindex >= 2 else None
            minute = int(raw_min) if raw_min else 0
            minute = min(minute, 59)
        else:
            time_match = None  # número fora do range de horas — ignorar

    # Tenta "em X dias"
    m = _RE_IN_DAYS.search(text_lower)
    if m:
        days = int(m.group(1))
        target = now + timedelta(days=days)
        target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target, recurrence

    # Tenta "em X semanas"
    m = _RE_IN_WEEKS.search(text_lower)
    if m:
        weeks = int(m.group(1))
        target = now + timedelta(weeks=weeks)
        target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target, recurrence

    # "amanhã"
    if "amanhã" in text_lower or "amanha" in text_lower or "tomorrow" in text_lower:
        target = (now + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return target, recurrence

    # "hoje"
    if "hoje" in text_lower or "today" in text_lower:
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, recurrence

    # Dia da semana nomeado: "sexta", "segunda-feira", etc.
    for day_name, weekday in _DAY_NAMES.items():
        if day_name in text_lower:
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # Mesmo dia da semana → próxima semana
            target = (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return target, recurrence

    # Recorrência sem data específica → usa amanhã na hora indicada
    if recurrence and time_match:
        target = (now + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return target, recurrence

    # Só hora informada → hoje se ainda não passou, senão amanhã
    if time_match:
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, recurrence

    return None, recurrence


def _extract_message(text: str) -> str:
    """Extrai a mensagem do lembrete do prompt."""
    # Remove palavras de comando no início
    cleaned = re.sub(
        r"^(me\s+lembra[r]?|lembrete|me\s+avisa[r]?|me\s+notifica[r]?)\s*",
        "", text, flags=re.I
    ).strip()

    # Tenta extrair após "para" ou ":"
    m = _RE_MESSAGE.search(cleaned)
    if m:
        msg = m.group(1).strip()
        # Remove resíduos de data/hora
        msg = re.sub(r"\b(?:às?\s*)?\d{1,2}[h:]\d{0,2}\b", "", msg, flags=re.I).strip()
        msg = re.sub(r"\b(?:amanhã|hoje|sexta|segunda|terça|quarta|quinta|sábado|domingo)\b",
                     "", msg, flags=re.I).strip()
        if len(msg) >= 3:
            return msg.rstrip(".,!?")

    # Fallback: usa o texto limpo
    return cleaned[:200].rstrip(".,!?") or text[:100]


@register_agent("reminder")
class ReminderAgent(BaseAgent):
    """
    Reminder agent — lembretes persistentes com suporte a recorrência.

    Intents:
        create  → cria lembrete com data/hora e mensagem
        list    → lista lembretes ativos
        cancel  → cancela por ID ou todos
    """

    def __init__(self):
        super().__init__(
            name="reminder",
            description="Cria lembretes persistentes com data/hora e recorrência",
        )

    async def execute(
        self, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        try:
            svc = get_service("reminder")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço de lembretes não disponível.",
                    error="ReminderService unavailable",
                )
            if not svc.is_initialized():
                try:
                    await svc.initialize()
                except Exception as init_err:
                    logger.error("ReminderService init failed: %s", init_err)
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response=(
                            "Não foi possível conectar ao serviço de lembretes. "
                            "Verifique as configurações do banco de dados (SUPABASE_URL / SUPABASE_SERVICE_KEY)."
                        ),
                        error=str(init_err),
                    )

            user_id = str(context.get("user_id", ""))
            chat_id = str(context.get("chat_id", user_id))
            if not user_id:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Usuário não identificado.",
                    error="No user_id",
                )

            prompt_lower = (prompt or "").lower()

            # ── Intent: listar ────────────────────────────────────────────────
            if any(w in prompt_lower for w in _LIST_WORDS):
                return await self._handle_list(svc, user_id)

            # ── Intent: cancelar ─────────────────────────────────────────────
            if any(w in prompt_lower for w in _CANCEL_WORDS):
                if "todos" in prompt_lower or "all" in prompt_lower:
                    return await self._handle_cancel_all(svc, user_id)
                rid = self._extract_id(prompt)
                if rid:
                    return await self._handle_cancel(svc, user_id, rid)
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Qual lembrete cancelar? Diga o ID ou *'cancela todos os lembretes'*.",
                    error="No reminder ID",
                )

            # ── Intent: criar ─────────────────────────────────────────────────
            if any(w in prompt_lower for w in _REMIND_WORDS) or context.get("action") == "create":
                # Context override tem prioridade
                if context.get("remind_at"):
                    remind_at = context["remind_at"]
                    if isinstance(remind_at, str):
                        remind_at = datetime.fromisoformat(remind_at)
                    recurrence = context.get("recurrence")
                else:
                    remind_at, recurrence = _parse_remind_datetime(prompt)

                message = context.get("message") or _extract_message(prompt)

                if remind_at is None:
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response=(
                            "Não entendi quando você quer ser lembrado. Tente:\n"
                            "• *Me lembra sexta às 10h para ligar pro médico*\n"
                            "• *Todo dia às 8h me lembra de tomar o remédio*\n"
                            "• *Lembrete para amanhã às 9h: reunião*"
                        ),
                        error="Could not parse datetime",
                    )

                return await self._handle_create(
                    svc, user_id, chat_id, message, remind_at, recurrence
                )

            # ── Fallback: tenta criar com o prompt inteiro ────────────────────
            remind_at, recurrence = _parse_remind_datetime(prompt)
            if remind_at:
                message = _extract_message(prompt)
                return await self._handle_create(
                    svc, user_id, chat_id, message, remind_at, recurrence
                )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Não entendi o pedido. Exemplos:\n"
                    "• *Me lembra sexta às 10h para ligar pro médico*\n"
                    "• *Todo dia às 8h: tomar remédio*\n"
                    "• *Meus lembretes*"
                ),
                error="Could not detect intent",
            )

        except ValueError as e:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=str(e),
                error=str(e),
            )
        except Exception as e:
            self.logger.error("ReminderAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro ao configurar o lembrete.",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_create(
        self,
        svc: Any,
        user_id: str,
        chat_id: str,
        message: str,
        remind_at: datetime,
        recurrence: Optional[str],
    ) -> AgentResponse:
        reminder = await svc.create_reminder(
            user_id=user_id,
            chat_id=chat_id,
            message=message,
            remind_at=remind_at,
            recurrence=recurrence,
        )

        short_id = reminder["id"][:8]
        date_str = svc.format_remind_at(reminder["remind_at"])
        rec_str = svc.format_recurrence(recurrence)
        rec_line = f"\n🔁 Recorrência: *{rec_str}*" if recurrence else ""

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"🔔 **Lembrete criado!**\n"
                f"📅 {date_str}\n"
                f"💬 _{message}_{rec_line}\n"
                f"ID: `{short_id}`"
            ),
            data=reminder,
        )

    async def _handle_list(self, svc: Any, user_id: str) -> AgentResponse:
        reminders = await svc.list_reminders(user_id)

        if not reminders:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Você não tem lembretes ativos.",
                data={"reminders": []},
            )

        lines = [f"🔔 **Seus lembretes ativos ({len(reminders)}):**\n"]
        for r in reminders:
            short_id = r["id"][:8]
            date_str = svc.format_remind_at(r["remind_at"])
            rec = " 🔁" if r.get("recurrence") else ""
            lines.append(f"`{short_id}` {date_str}{rec} — _{r['message'][:60]}_")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"reminders": reminders},
        )

    async def _handle_cancel(
        self, svc: Any, user_id: str, reminder_id: str
    ) -> AgentResponse:
        cancelled = await svc.cancel_reminder(user_id, reminder_id)
        if cancelled:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"✅ Lembrete `{reminder_id}` cancelado.",
                data={"reminder_id": reminder_id, "cancelled": True},
            )
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=f"Lembrete `{reminder_id}` não encontrado.",
            error="Reminder not found",
        )

    async def _handle_cancel_all(self, svc: Any, user_id: str) -> AgentResponse:
        reminders = await svc.list_reminders(user_id)
        count = 0
        for r in reminders:
            if await svc.cancel_reminder(user_id, r["id"]):
                count += 1

        if count == 0:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Você não tinha lembretes ativos.",
                data={"cancelled_count": 0},
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"✅ {count} lembrete(s) cancelado(s).",
            data={"cancelled_count": count},
        )

    def _extract_id(self, text: str) -> Optional[str]:
        m = _RE_REMINDER_ID.search(text)
        return m.group(1).lower() if m else None

    def get_capabilities(self) -> List[str]:
        return [
            "create_reminder",
            "recurring_reminders",
            "cancel_reminder",
            "list_reminders",
        ]
