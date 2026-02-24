# -*- coding: utf-8 -*-
"""
agents/specialized/timer_agent.py
===================================
TimerAgent — cria alarmes, cronômetros e lembretes.

FIX [2025-02]: Melhorado tratamento de erros para diagnosticar problemas
               de conexão Redis/Upstash.

  ANTES: Qualquer erro → "Erro ao configurar o timer." (sem diagnóstico)
  DEPOIS: Distingue erro de Redis vs erro de parsing vs erro genérico.
          Mensagem útil ao utilizador + log detalhado para Railway logs.

Exemplos de queries suportadas:
- "Marque 10 minutos"
- "Me acorde às 7h"
- "Timer de 30 segundos"
- "Me lembra em 1 hora para ligar pro João"
- "Cancela o alarme abc12345"
- "Quais timers tenho ativos?"
- "Cancela todos os timers"
"""

import logging
import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

logger = logging.getLogger(__name__)

# ─── Regex de extração de duração ───────────────────────────────────────────────
_RE_DURATION = re.compile(
    r"""
    (?:
        (\d+)\s*h(?:ora(?:s)?)?\s*(?:e\s*)?(\d+)\s*(?:min(?:uto(?:s)?)?)?  # 1h30 / 1h30min / 1 hora e 30 min
        |(\d+)\s*h(?:ora(?:s)?)?                                              # 2 horas / 2h
        |(\d+)\s*min(?:uto(?:s)?)?                                            # 10 minutos / 10min
        |(\d+)\s*s(?:eg(?:undo(?:s)?)?)?                                      # 30 segundos / 30s
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RE_CLOCK = re.compile(
    r"""
    (?:às\s*|as\s*)?
    (\d{1,2})   # hora
    [h:]
    (\d{0,2})   # minuto (opcional)
    (?:\s*h)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_CANCEL_WORDS = ["cancela", "cancel", "remove", "apaga", "deleta", "delete"]
_LIST_WORDS = ["lista", "list", "quais", "mostre", "ativos", "tenho"]
_ALARM_WORDS = ["acorde", "alarm", "desperte", "acorda"]
_REMIND_WORDS = ["lembra", "remind", "lembrete", "avisa"]


def _parse_duration(text: str) -> Optional[float]:
    match = _RE_DURATION.search(text)
    if not match:
        return None
    h_combo, m_combo, h_only, min_only, sec_only = match.groups()
    if h_combo is not None:
        return int(h_combo) * 3600 + (int(m_combo) if m_combo else 0) * 60
    if h_only is not None:
        return int(h_only) * 3600
    if min_only is not None:
        return int(min_only) * 60
    if sec_only is not None:
        return float(sec_only)
    return None


def _parse_clock_time(text: str) -> Optional[float]:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    match = _RE_CLOCK.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    if hour > 23 or minute > 59:
        return None

    now = datetime.now(ZoneInfo("UTC"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _extract_label(text: str) -> str:
    match = re.search(r"\bpara\b\s+(.+)$", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip("?!.")
    return ""


@register_agent("timer")
class TimerAgent(BaseAgent):
    """
    Timer agent — alarmes, cronômetros e lembretes.

    Intents detectadas:
    - criar timer (duração em minutos/horas/segundos)
    - criar alarme (hora específica)
    - criar lembrete (com mensagem)
    - cancelar timer (por ID ou todos)
    - listar timers ativos
    """

    def __init__(self):
        super().__init__(
            name="timer",
            description="Cria alarmes, cronômetros e lembretes",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        try:
            timer_svc = get_service("timer")
            if not timer_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço de timer não disponível.",
                    error="TimerService unavailable",
                )

            # FIX: inicialização com diagnóstico de erro Redis
            if not timer_svc.is_initialized():
                try:
                    await timer_svc.initialize()
                except Exception as init_err:
                    err_msg = str(init_err).lower()
                    self.logger.error("TimerService init failed: %s", init_err)

                    # Diagnóstico: é erro de configuração Redis?
                    if (
                        "upstash" in err_msg
                        or "redis" in err_msg
                        or "url" in err_msg
                        or "token" in err_msg
                    ):
                        return AgentResponse(
                            status=AgentStatus.ERROR,
                            response=(
                                "⚠️ O serviço de timer está temporariamente indisponível "
                                "(problema de conexão com o banco de dados Redis).\n"
                                "Tenta novamente em alguns instantes."
                            ),
                            error=f"Redis init failed: {init_err}",
                        )
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response="Não foi possível iniciar o serviço de timer.",
                        error=str(init_err),
                    )

            user_id = str(context.get("user_id", "default"))
            chat_id = str(context.get("chat_id", user_id))
            prompt_lower = (prompt or "").lower()

            # ── Intent: listar ───────────────────────────────────────────────
            if any(w in prompt_lower for w in _LIST_WORDS):
                return await self._handle_list(timer_svc, user_id)

            # ── Intent: cancelar ─────────────────────────────────────────────
            if any(w in prompt_lower for w in _CANCEL_WORDS):
                if "todos" in prompt_lower or "all" in prompt_lower:
                    return await self._handle_cancel_all(timer_svc, user_id)
                timer_id = self._extract_timer_id(prompt)
                if timer_id:
                    return await self._handle_cancel(timer_svc, user_id, timer_id)
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Qual timer você quer cancelar? "
                        "Diga o ID ou *'cancela todos os timers'*."
                    ),
                    error="No timer ID found",
                )

            # ── Intent: criar ────────────────────────────────────────────────
            duration = None
            timer_type = "timer"
            label = ""

            if any(w in prompt_lower for w in _ALARM_WORDS):
                duration = _parse_clock_time(prompt)
                timer_type = "alarm"
                label = context.get("label", "")
            elif any(w in prompt_lower for w in _REMIND_WORDS):
                duration = _parse_duration(prompt)
                timer_type = "remind"
                label = _extract_label(prompt) or context.get("label", "🔔 Lembrete")
            else:
                duration = _parse_duration(prompt)
                timer_type = "timer"
                label = context.get("label", "")

            # Context override
            if duration is None and context.get("duration_seconds"):
                duration = float(context["duration_seconds"])

            if duration is None:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Não entendi o tempo. Tente:\n"
                        "• *Marque 10 minutos*\n"
                        "• *Me acorde às 7h*\n"
                        "• *Me lembra em 30min para ligar pro João*"
                    ),
                    error="Could not parse duration",
                )

            return await self._handle_create(
                timer_svc, user_id, chat_id, duration, label, timer_type
            )

        except ValueError as e:
            return AgentResponse(
                status=AgentStatus.ERROR, response=str(e), error=str(e)
            )

        except Exception as e:
            self.logger.error("TimerAgent error: %s", e, exc_info=True)
            err_lower = str(e).lower()

            # FIX: mensagens de erro contextualizadas
            if (
                "redis" in err_lower
                or "upstash" in err_lower
                or "httpstatus" in err_lower
            ):
                msg = (
                    "⚠️ Não foi possível salvar o timer — problema de conexão com o Redis.\n"
                    "Verifica se UPSTASH_REDIS_REST_URL e UPSTASH_REDIS_REST_TOKEN "
                    "estão configuradas no Railway."
                )
            elif "duration" in err_lower or "seconds" in err_lower:
                msg = "Duração inválida. Exemplo: *Marque 10 minutos* ou *Timer de 2 horas*."
            else:
                msg = "Erro ao configurar o timer. Tenta novamente."

            return AgentResponse(status=AgentStatus.ERROR, response=msg, error=str(e))

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_create(
        self,
        svc: Any,
        user_id: str,
        chat_id: str,
        duration: float,
        label: str,
        timer_type: str,
    ) -> AgentResponse:
        timer = await svc.create_timer(
            user_id=user_id,
            chat_id=chat_id,
            duration_seconds=duration,
            label=label or None,
            timer_type=timer_type,
        )

        remaining = timer.format_remaining()
        fire_time = timer.format_fire_time()
        icons = {"timer": "⏱️", "alarm": "⏰", "remind": "🔔"}
        icon = icons.get(timer_type, "⏱️")

        if timer_type == "alarm":
            msg = (
                f"{icon} **Alarme configurado!**\n"
                f"Vou te acordar às **{fire_time} UTC** "
                f"(em {remaining}).\n"
                f"ID: `{timer.timer_id}`"
            )
        elif timer_type == "remind":
            msg = (
                f"{icon} **Lembrete criado!**\n"
                f"Em **{remaining}** vou te lembrar: _{timer.label}_\n"
                f"ID: `{timer.timer_id}`"
            )
        else:
            msg = (
                f"{icon} **Timer iniciado!**\n"
                f"Vou te avisar em **{remaining}**.\n"
                f"ID: `{timer.timer_id}`"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=msg,
            data=timer.to_dict(),
        )

    async def _handle_list(self, svc: Any, user_id: str) -> AgentResponse:
        timers = await svc.list_timers(user_id)
        if not timers:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Você não tem nenhum timer ativo no momento.",
                data={"timers": []},
            )
        icons = {"timer": "⏱️", "alarm": "⏰", "remind": "🔔"}
        lines = [f"**Seus timers ativos ({len(timers)}):**\n"]
        for t in timers:
            icon = icons.get(t.timer_type, "⏱️")
            lines.append(
                f"{icon} `{t.timer_id}` — {t.label} *(falta {t.format_remaining()})*"
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"timers": [t.to_dict() for t in timers]},
        )

    async def _handle_cancel(
        self, svc: Any, user_id: str, timer_id: str
    ) -> AgentResponse:
        cancelled = await svc.cancel_timer(user_id, timer_id)
        if cancelled:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"✅ Timer `{timer_id}` cancelado.",
                data={"timer_id": timer_id, "cancelled": True},
            )
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=f"Timer `{timer_id}` não encontrado.",
            error="Timer not found",
        )

    async def _handle_cancel_all(self, svc: Any, user_id: str) -> AgentResponse:
        count = await svc.cancel_all_timers(user_id)
        if count == 0:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Você não tinha nenhum timer ativo.",
                data={"cancelled_count": 0},
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"✅ {count} timer(s) cancelado(s).",
            data={"cancelled_count": count},
        )

    def _extract_timer_id(self, text: str) -> Optional[str]:
        match = re.search(r"\b([0-9a-f]{8})\b", text, re.IGNORECASE)
        return match.group(1).lower() if match else None

    def get_capabilities(self) -> List[str]:
        return [
            "create_timer",
            "create_alarm",
            "create_reminder",
            "cancel_timer",
            "list_active_timers",
        ]
