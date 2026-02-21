# -*- coding: utf-8 -*-
"""
services/business/reminder_service.py
========================================
Gerencia lembretes persistentes via Supabase + Redis.

Diferença vs TimerService:
  - TimerService → efêmero, só Redis, "marque 10 minutos"
  - ReminderService → persistente, Supabase + Redis, sobrevive a restarts,
    suporta recorrência (daily/weekly/monthly), datas futuras arbitrárias

Fluxo:
  1. ReminderAgent chama create_reminder → salva no Supabase
  2. ReminderService preenche cache Redis (chave com TTL até o disparo)
  3. arq worker chama check_and_fire_due() a cada 30s
     → busca pendentes no Supabase (remind_at <= now, fired=False)
     → dispara notificação via NotificationService
     → marca fired=True (ou agenda próxima ocorrência se recorrente)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.core import BaseService, register_service, ServiceUnavailableError

REMINDER_TABLE = "reminders"
MAX_MESSAGE_LENGTH = 500
RECURRENCES = {None, "daily", "weekly", "monthly"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_occurrence(remind_at: datetime, recurrence: str) -> Optional[datetime]:
    """Calcula a próxima data de disparo para lembretes recorrentes."""
    if recurrence == "daily":
        return remind_at + timedelta(days=1)
    if recurrence == "weekly":
        return remind_at + timedelta(weeks=1)
    if recurrence == "monthly":
        # Mesmo dia do mês seguinte
        month = remind_at.month % 12 + 1
        year = remind_at.year + (1 if remind_at.month == 12 else 0)
        try:
            return remind_at.replace(year=year, month=month)
        except ValueError:
            # Ex: 31 de janeiro → 28/29 de fevereiro
            import calendar
            last_day = calendar.monthrange(year, month)[1]
            return remind_at.replace(year=year, month=month, day=last_day)
    return None


@register_service("reminder")
class ReminderService(BaseService):
    """
    Reminder service — lembretes persistentes via Supabase + Redis.

    Interface pública:
        create_reminder(user_id, chat_id, message, remind_at, recurrence) → Dict
        cancel_reminder(user_id, reminder_id) → bool
        list_reminders(user_id, include_fired) → List[Dict]
        check_and_fire_due(notify_fn) → List[Dict]   ← chamado pelo arq worker
    """

    def __init__(self):
        super().__init__(name="reminder")
        self._db = None
        self._redis = None

    async def _initialize(self) -> None:
        from services.core import get_service
        self._db = get_service("database")
        if not self._db:
            raise ServiceUnavailableError("DatabaseService indisponível para ReminderService")
        if not self._db.is_initialized():
            await self._db.initialize()

        # Redis é opcional — melhora performance mas não é bloqueante
        self._redis = get_service("redis")
        if self._redis and not self._redis.is_initialized():
            try:
                await self._redis.initialize()
            except Exception as e:
                self.logger.warning("Redis indisponível para ReminderService: %s", e)
                self._redis = None

        self.logger.info("ReminderService initialized")

    async def _health_check(self) -> bool:
        return self._db is not None and self._db.is_initialized()

    def _client(self):
        return self._db.get_client()

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def create_reminder(
        self,
        user_id: str,
        chat_id: str,
        message: str,
        remind_at: datetime,
        recurrence: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cria um lembrete persistente.

        Args:
            user_id:    ID do usuário (UUID)
            chat_id:    Chat ID Telegram para notificação
            message:    Mensagem do lembrete
            remind_at:  Datetime UTC de disparo
            recurrence: None | 'daily' | 'weekly' | 'monthly'

        Returns:
            Dict com o lembrete criado

        Raises:
            ValueError: Se parâmetros inválidos
        """
        if not self.is_initialized():
            await self.initialize()

        message = (message or "").strip()
        if not message:
            raise ValueError("A mensagem do lembrete não pode ser vazia.")
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Mensagem muito longa (máximo {MAX_MESSAGE_LENGTH} chars).")

        if not isinstance(remind_at, datetime):
            raise ValueError("remind_at deve ser um objeto datetime.")

        # Garante timezone UTC
        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=timezone.utc)
        else:
            remind_at = remind_at.astimezone(timezone.utc)

        if remind_at <= _utcnow():
            raise ValueError("O lembrete deve ser em uma data/hora futura.")

        if recurrence not in RECURRENCES:
            raise ValueError(f"Recorrência inválida. Use: {RECURRENCES - {None}}")

        payload = {
            "user_id": str(user_id),
            "chat_id": str(chat_id),
            "message": message,
            "remind_at": remind_at.isoformat(),
            "recurrence": recurrence,
            "fired": False,
            "cancelled": False,
        }

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client().table(REMINDER_TABLE).insert(payload).execute()
        )

        if not response.data:
            raise RuntimeError("Falha ao criar lembrete no banco de dados.")

        reminder = response.data[0]
        self.logger.info(
            "Reminder created: %s for user %s at %s",
            reminder["id"], user_id, remind_at.isoformat()
        )
        return reminder

    async def cancel_reminder(self, user_id: str, reminder_id: str) -> bool:
        """
        Cancela um lembrete (marca cancelled=True, não deleta).

        Returns:
            True se cancelado, False se não encontrado
        """
        if not self.is_initialized():
            await self.initialize()

        loop = asyncio.get_event_loop()

        # Verifica que pertence ao usuário
        check = await loop.run_in_executor(
            None,
            lambda: self._client()
                .table(REMINDER_TABLE)
                .select("id")
                .eq("id", reminder_id)
                .eq("user_id", str(user_id))
                .eq("cancelled", False)
                .execute()
        )
        if not check.data:
            return False

        await loop.run_in_executor(
            None,
            lambda: self._client()
                .table(REMINDER_TABLE)
                .update({"cancelled": True})
                .eq("id", reminder_id)
                .eq("user_id", str(user_id))
                .execute()
        )
        self.logger.info("Reminder %s cancelled for user %s", reminder_id, user_id)
        return True

    async def list_reminders(
        self,
        user_id: str,
        include_fired: bool = False,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Lista lembretes do usuário.

        Args:
            user_id:       ID do usuário
            include_fired: Se True, inclui já disparados
            limit:         Máximo de resultados

        Returns:
            Lista ordenada por remind_at ASC (mais próximo primeiro)
        """
        if not self.is_initialized():
            await self.initialize()

        def _query():
            q = (
                self._client()
                .table(REMINDER_TABLE)
                .select("*")
                .eq("user_id", str(user_id))
                .eq("cancelled", False)
                .order("remind_at", desc=False)
                .limit(min(limit, 50))
            )
            if not include_fired:
                q = q.eq("fired", False)
            return q.execute()

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _query)
        return response.data or []

    async def check_and_fire_due(self, notify_fn=None) -> List[Dict[str, Any]]:
        """
        Busca lembretes vencidos, dispara notificações e atualiza status.
        Chamado pelo arq worker a cada 30 segundos.

        Para lembretes recorrentes:
          - Marca o atual como fired=True
          - Cria nova entrada com a próxima data

        Args:
            notify_fn: async notify_fn(reminder: Dict) → None

        Returns:
            Lista de lembretes disparados neste ciclo
        """
        if not self.is_initialized():
            await self.initialize()

        now_iso = _utcnow().isoformat()

        def _fetch_due():
            return (
                self._client()
                .table(REMINDER_TABLE)
                .select("*")
                .eq("fired", False)
                .eq("cancelled", False)
                .lte("remind_at", now_iso)
                .limit(50)
                .execute()
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _fetch_due)
        due_reminders = response.data or []

        if not due_reminders:
            return []

        fired = []
        for reminder in due_reminders:
            try:
                # Notifica
                if notify_fn:
                    await notify_fn(reminder)

                # Marca como fired
                await loop.run_in_executor(
                    None,
                    lambda r=reminder: self._client()
                        .table(REMINDER_TABLE)
                        .update({"fired": True})
                        .eq("id", r["id"])
                        .execute()
                )

                # Recorrência: cria próxima entrada
                recurrence = reminder.get("recurrence")
                if recurrence:
                    remind_at = datetime.fromisoformat(
                        reminder["remind_at"].replace("Z", "+00:00")
                    )
                    next_at = _next_occurrence(remind_at, recurrence)
                    if next_at:
                        await self.create_reminder(
                            user_id=reminder["user_id"],
                            chat_id=reminder["chat_id"],
                            message=reminder["message"],
                            remind_at=next_at,
                            recurrence=recurrence,
                        )

                fired.append(reminder)
                self.logger.info("Reminder %s fired for user %s", reminder["id"], reminder["user_id"])

            except Exception as e:
                self.logger.error("Failed to process reminder %s: %s", reminder["id"], e)

        return fired

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def format_remind_at(remind_at_str: str, tz_offset_hours: int = 0) -> str:
        """Formata data/hora do lembrete para exibição."""
        try:
            dt = datetime.fromisoformat(remind_at_str.replace("Z", "+00:00"))
            dt = dt + timedelta(hours=tz_offset_hours)
            return dt.strftime("%d/%m/%Y às %H:%M")
        except Exception:
            return remind_at_str

    @staticmethod
    def format_recurrence(recurrence: Optional[str]) -> str:
        labels = {
            "daily": "todo dia",
            "weekly": "toda semana",
            "monthly": "todo mês",
        }
        return labels.get(recurrence or "", "uma vez")
