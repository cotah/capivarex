# -*- coding: utf-8 -*-
"""
services/business/timer_service.py
====================================
Gerencia alarmes e cronômetros no Redis (Upstash).

Estratégia de armazenamento:
  - Chave única: "jarvis:timers:active"  → JSON list com todos os timers ativos
  - TTL da chave: 7 dias (máximo de um timer)
  - O arq worker faz poll a cada 10s, checa timers vencidos e dispara notificações

Por que uma única chave JSON (e não uma chave por timer):
  - RedisService não suporta SCAN — não dá para descobrir chaves por padrão
  - Lista única é simples, funciona para uso pessoal (dezenas de timers, não milhões)
  - Operação atômica via pipeline: lê + escreve em um round-trip

Tipos de timer:
  - "timer"  → cronômetro simples ("marque 10 minutos")
  - "alarm"  → hora específica ("me acorde às 7h")
  - "remind" → lembrete com mensagem ("me lembra em 30min para ligar pro João")
"""

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from services.core import BaseService, register_service, ServiceUnavailableError

# Chave única no Redis para todos os timers ativos
TIMERS_KEY = "jarvis:timers:active"

# TTL da chave: 7 dias (máximo razoável para um alarme)
TIMERS_KEY_TTL = 7 * 24 * 3600

# Tipos válidos
TIMER_TYPES = {"timer", "alarm", "remind"}

# Labels padrão por tipo
DEFAULT_LABELS = {
    "timer": "⏱️ Cronômetro",
    "alarm": "⏰ Alarme",
    "remind": "🔔 Lembrete",
}


class Timer:
    """Representa um timer/alarme ativo."""

    def __init__(
        self,
        timer_id: str,
        user_id: str,
        chat_id: str,
        label: str,
        fire_at: float,       # Unix timestamp
        timer_type: str = "timer",
        created_at: float = 0.0,
    ):
        self.timer_id = timer_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.label = label
        self.fire_at = fire_at
        self.timer_type = timer_type
        self.created_at = created_at or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timer_id": self.timer_id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "label": self.label,
            "fire_at": self.fire_at,
            "timer_type": self.timer_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Timer":
        return cls(
            timer_id=d["timer_id"],
            user_id=d["user_id"],
            chat_id=d["chat_id"],
            label=d["label"],
            fire_at=float(d["fire_at"]),
            timer_type=d.get("timer_type", "timer"),
            created_at=float(d.get("created_at", 0)),
        )

    @property
    def seconds_remaining(self) -> float:
        return max(0.0, self.fire_at - time.time())

    @property
    def is_due(self) -> bool:
        return time.time() >= self.fire_at

    def format_remaining(self) -> str:
        """Formata o tempo restante em linguagem natural."""
        secs = int(self.seconds_remaining)
        if secs <= 0:
            return "agora"
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            m, s = divmod(secs, 60)
            return f"{m}min" + (f" {s}s" if s else "")
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f"{h}h" + (f" {m}min" if m else "")

    def format_fire_time(self, tz: str = "UTC") -> str:
        """Formata o horário de disparo."""
        dt = datetime.fromtimestamp(self.fire_at, tz=ZoneInfo(tz))
        return dt.strftime("%H:%M:%S")


@register_service("timer")
class TimerService(BaseService):
    """
    Timer service — alarmes e cronômetros via Redis.

    Interface pública:
        create_timer(user_id, chat_id, duration_seconds, label, timer_type) → Timer
        cancel_timer(user_id, timer_id) → bool
        list_timers(user_id) → List[Timer]
        check_and_fire_due(notify_fn) → List[Timer]   ← chamado pelo arq worker
    """

    def __init__(self):
        super().__init__(name="timer")
        self._redis = None
        self._lock = None  # asyncio.Lock created on first use

    async def _get_lock(self):
        """Lazy-init asyncio.Lock (must be created in async context)."""
        if self._lock is None:
            import asyncio
            self._lock = asyncio.Lock()
        return self._lock

    async def _initialize(self) -> None:
        from services.core import get_service
        self._redis = get_service("redis")
        if not self._redis:
            raise ServiceUnavailableError("RedisService indisponível para TimerService")
        if not self._redis.is_initialized():
            await self._redis.initialize()
        self.logger.info("TimerService initialized")

    async def _health_check(self) -> bool:
        return self._redis is not None and self._redis.is_initialized()

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def create_timer(
        self,
        user_id: str,
        chat_id: str,
        duration_seconds: float,
        label: Optional[str] = None,
        timer_type: str = "timer",
    ) -> Timer:
        """
        Cria um novo timer.

        Args:
            user_id:          ID do usuário
            chat_id:          Chat ID para notificação (Telegram)
            duration_seconds: Segundos até disparar
            label:            Mensagem do lembrete (opcional)
            timer_type:       "timer", "alarm" ou "remind"

        Returns:
            Timer criado
        """
        if not self.is_initialized():
            await self.initialize()

        if duration_seconds <= 0:
            raise ValueError("duration_seconds deve ser positivo")
        if duration_seconds > TIMERS_KEY_TTL:
            raise ValueError(f"Máximo permitido: 7 dias ({TIMERS_KEY_TTL}s)")
        if timer_type not in TIMER_TYPES:
            timer_type = "timer"

        timer = Timer(
            timer_id=uuid.uuid4().hex[:8],
            user_id=str(user_id),
            chat_id=str(chat_id),
            label=label or DEFAULT_LABELS[timer_type],
            fire_at=time.time() + duration_seconds,
            timer_type=timer_type,
        )

        lock = await self._get_lock()
        async with lock:
            timers = await self._load_timers()
            timers.append(timer)
            await self._save_timers(timers)

        self.logger.info(
            "Timer created: %s for user %s, fires in %.0fs",
            timer.timer_id, user_id, duration_seconds,
        )
        return timer

    async def cancel_timer(self, user_id: str, timer_id: str) -> bool:
        """
        Cancela um timer pelo ID.

        Args:
            user_id:  ID do usuário (segurança: só cancela timers do próprio usuário)
            timer_id: ID do timer

        Returns:
            True se cancelado, False se não encontrado
        """
        if not self.is_initialized():
            await self.initialize()

        lock = await self._get_lock()
        async with lock:
            timers = await self._load_timers()
            original_count = len(timers)

            timers = [
                t for t in timers
                if not (t.timer_id == timer_id and t.user_id == str(user_id))
            ]

            if len(timers) == original_count:
                return False  # não encontrado

            await self._save_timers(timers)
        self.logger.info("Timer %s cancelled for user %s", timer_id, user_id)
        return True

    async def cancel_all_timers(self, user_id: str) -> int:
        """
        Cancela todos os timers de um usuário.

        Returns:
            Número de timers cancelados
        """
        if not self.is_initialized():
            await self.initialize()

        timers = await self._load_timers()
        user_timers = [t for t in timers if t.user_id == str(user_id)]
        remaining = [t for t in timers if t.user_id != str(user_id)]

        if user_timers:
            lock = await self._get_lock()
            async with lock:
                # Re-read to avoid overwriting concurrent changes
                timers = await self._load_timers()
                remaining = [t for t in timers if t.user_id != str(user_id)]
                await self._save_timers(remaining)

        return len(user_timers)

    async def list_timers(self, user_id: str) -> List[Timer]:
        """
        Lista timers ativos de um usuário (não vencidos).

        Returns:
            Lista ordenada por fire_at (mais próximo primeiro)
        """
        if not self.is_initialized():
            await self.initialize()

        timers = await self._load_timers()
        user_timers = [
            t for t in timers
            if t.user_id == str(user_id) and not t.is_due
        ]
        return sorted(user_timers, key=lambda t: t.fire_at)

    async def check_and_fire_due(
        self,
        notify_fn=None,
    ) -> List[Timer]:
        """
        Verifica timers vencidos, remove da lista e retorna-os.
        Chamado pelo arq worker a cada 10 segundos.

        Args:
            notify_fn: Coroutine async opcional para notificar o usuário.
                       Signature: async notify_fn(timer: Timer) → None
                       Se None, apenas retorna os timers vencidos sem notificar.

        Returns:
            Lista de timers que venceram neste ciclo
        """
        if not self.is_initialized():
            await self.initialize()

        lock = await self._get_lock()
        async with lock:
            timers = await self._load_timers()
            due = [t for t in timers if t.is_due]
            remaining = [t for t in timers if not t.is_due]

            if not due:
                return []

            # Salva lista sem os vencidos
            await self._save_timers(remaining)

        # Notifica (outside lock — no need to hold it during I/O)
        if notify_fn:
            for timer in due:
                try:
                    await notify_fn(timer)
                except Exception as e:
                    self.logger.error(
                        "Failed to notify timer %s: %s", timer.timer_id, e
                    )

        self.logger.info("Fired %d timer(s)", len(due))
        return due

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _load_timers(self) -> List[Timer]:
        """Carrega lista de timers do Redis."""
        raw = await self._redis.get(TIMERS_KEY, parse_json=True)
        if not raw or not isinstance(raw, list):
            return []
        timers = []
        for item in raw:
            try:
                timers.append(Timer.from_dict(item))
            except Exception as e:
                self.logger.warning("Skipping corrupt timer entry: %s", e)
        return timers

    async def _save_timers(self, timers: List[Timer]) -> None:
        """Salva lista de timers no Redis."""
        data = [t.to_dict() for t in timers]
        await self._redis.set(TIMERS_KEY, data, expire_seconds=TIMERS_KEY_TTL)
