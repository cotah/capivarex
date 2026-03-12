# -*- coding: utf-8 -*-
"""
services/business/quota_service.py
====================================
Gestão de quotas por tenant — Resource Metering para o Jarvis SaaS.

Planos:
    Free        → porta de entrada, funcionalidades básicas
    Me          → assistente pessoal (Telegram), uso moderado
    Everywhere  → presença total, todos os canais, quotas generosas

Recursos controlados (cobre TODOS os serviços do Jarvis):

    ── IA / LLM ──────────────────────────────────────────────────
    gpt_tokens          → tokens OpenAI/Claude (Chat, IA geral)
    image_gen           → imagens geradas (ImageAgent / Gemini)
    video_gen           → vídeos gerados (VideoAgent / Gemini Veo)

    ── Voz ───────────────────────────────────────────────────────
    twilio_mins         → minutos de chamada (TwilioService)
    elevenlabs_chars    → caracteres TTS (ElevenLabs)

    ── Google APIs ───────────────────────────────────────────────
    google_places       → buscas Places API (RestaurantAgent)
    maps_reqs           → Maps/Directions (LeavingNow, Transit)
    search_reqs         → Google Search (SearchAgent)

    ── APIs Externas ─────────────────────────────────────────────
    weather_reqs        → previsões tempo (WeatherService)
    crypto_reqs         → cotações crypto (CryptoAgent)
    youtube_reqs        → buscas YouTube (YouTubeAgent)
    translate_reqs      → traduções (TranslateAgent)
    tracking_reqs       → rastreio encomendas (TrackingAgent)
    perplexity_reqs     → pesquisas web (ResearchAgent)
    smartcar_reqs       → comandos carro (CarAgent)
    mercado_scans       → scan de recibos (MercadoAgent)

    ── Stock (não resetam mensalmente) ───────────────────────────
    reminders           → lembretes activos simultâneos
    notes               → notas guardadas

Arquitectura:
    Supabase  → estado persistente (usage mensal, histórico)
    Redis     → rate limiting em tempo real (verificação rápida)
    Fallback  → se Redis indisponível, usa Supabase directamente
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.core import BaseService, register_service

# ─── Definição dos planos ────────────────────────────────────────────────────

PLANS: Dict[str, Dict[str, Any]] = {
    "free": {
        "display_name": "Free",
        "price_eur": 0.0,
        "description": "Experimenta o Jarvis sem compromisso",
        "quotas": {
            # IA / LLM
            "gpt_tokens":           5_000,
            "image_gen":            2,       # 2 imagens/mês
            "video_gen":            0,       # sem vídeo
            # Voz
            "twilio_mins":          0,       # sem chamadas
            "elevenlabs_chars":     0,       # sem TTS
            # Google APIs
            "google_places":        10,
            "maps_reqs":            10,
            "search_reqs":          10,
            # APIs Externas
            "weather_reqs":         20,
            "crypto_reqs":          20,
            "youtube_reqs":         10,
            "translate_reqs":       10,
            "tracking_reqs":        5,
            "perplexity_reqs":      5,
            "smartcar_reqs":        0,       # sem carro
            "mercado_scans":        3,       # 3 recibos/mês
            # Stock
            "reminders":            3,
            "notes":                10,
        },
    },
    "me": {
        "display_name": "Me",
        "price_eur": 9.99,
        "description": "O teu assistente pessoal, focado em ti — Telegram",
        "quotas": {
            # IA / LLM
            "gpt_tokens":           50_000,
            "image_gen":            20,
            "video_gen":            3,
            # Voz
            "twilio_mins":          15,
            "elevenlabs_chars":     10_000,
            # Google APIs
            "google_places":        100,
            "maps_reqs":            100,
            "search_reqs":          100,
            # APIs Externas
            "weather_reqs":         200,
            "crypto_reqs":          200,
            "youtube_reqs":         100,
            "translate_reqs":       100,
            "tracking_reqs":        30,
            "perplexity_reqs":      50,
            "smartcar_reqs":        50,
            "mercado_scans":        20,
            # Stock
            "reminders":            20,
            "notes":                100,
        },
    },
    "everywhere": {
        "display_name": "Everywhere",
        "price_eur": 29.99,
        "description": "O Jarvis em todo o lado — todos os canais",
        "quotas": {
            # IA / LLM
            "gpt_tokens":           200_000,
            "image_gen":            100,
            "video_gen":            20,
            # Voz
            "twilio_mins":          60,
            "elevenlabs_chars":     50_000,
            # Google APIs
            "google_places":        500,
            "maps_reqs":            500,
            "search_reqs":          500,
            # APIs Externas
            "weather_reqs":         1_000,
            "crypto_reqs":          1_000,
            "youtube_reqs":         500,
            "translate_reqs":       500,
            "tracking_reqs":        100,
            "perplexity_reqs":      200,
            "smartcar_reqs":        200,
            "mercado_scans":        100,
            # Stock
            "reminders":            100,
            "notes":                500,
        },
    },
}

# Recursos cumulativos: contagem reset no início de cada mês
CUMULATIVE_RESOURCES = {
    "gpt_tokens", "image_gen", "video_gen",
    "twilio_mins", "elevenlabs_chars",
    "google_places", "maps_reqs", "search_reqs",
    "weather_reqs", "crypto_reqs", "youtube_reqs",
    "translate_reqs", "tracking_reqs", "perplexity_reqs",
    "smartcar_reqs", "mercado_scans",
}

# Recursos de stock: limite de quantidade total (não resetam)
STOCK_RESOURCES = {"reminders", "notes"}

# Ícones para formatação no Telegram
RESOURCE_ICONS: Dict[str, str] = {
    "gpt_tokens":           "🧠 IA (tokens)",
    "image_gen":            "🖼️ Imagens IA",
    "video_gen":            "🎬 Vídeos IA",
    "twilio_mins":          "📞 Chamadas",
    "elevenlabs_chars":     "🎙️ Voz TTS",
    "google_places":        "🗺️ Restaurantes",
    "maps_reqs":            "🧭 Mapas",
    "search_reqs":          "🔎 Pesquisas Web",
    "weather_reqs":         "🌤️ Meteorologia",
    "crypto_reqs":          "💰 Crypto",
    "youtube_reqs":         "▶️ YouTube",
    "translate_reqs":       "🌐 Traduções",
    "tracking_reqs":        "📦 Rastreio",
    "perplexity_reqs":      "🔍 Research",
    "smartcar_reqs":        "🚗 Carro",
    "mercado_scans":        "🧾 Recibos",
    "reminders":            "🔔 Lembretes",
    "notes":                "📝 Notas",
}

USAGE_TABLE = "tenant_usage"
USAGE_LOG_TABLE = "tenant_usage_log"
SUBSCRIPTIONS_TABLE = "tenant_subscriptions"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _month_start() -> str:
    now = _utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


class QuotaExceededError(Exception):
    """Levantado quando o tenant não tem quota suficiente."""

    def __init__(self, resource: str, used: int, limit: int, plan: str):
        self.resource = resource
        self.used = used
        self.limit = limit
        self.plan = plan
        label = RESOURCE_ICONS.get(resource, resource)
        super().__init__(
            f"Quota de '{label}' esgotada no plano '{plan}': "
            f"{used}/{limit}. Faz upgrade para continuar."
        )


@register_service("quota")
class QuotaService(BaseService):
    """
    Serviço de quotas por tenant — cobre todos os serviços do Jarvis.

    Interface pública:
        get_plan(tenant_id)                              → str
        get_quota(tenant_id, resource)                   → int
        get_usage(tenant_id, resource?)                  → Dict
        check(tenant_id, resource, amount=1)             → bool
        consume(tenant_id, resource, amount=1)           → Dict
        check_and_consume(tenant_id, resource, amount=1) → Dict (ou raise)
        get_summary(tenant_id)                           → Dict
        format_summary_telegram(tenant_id)               → str
    """

    def __init__(self):
        super().__init__(name="quota")
        self._db = None
        self._redis = None

    async def _initialize(self) -> None:
        from services.core import get_service
        self._db = get_service("database")
        if self._db and not self._db.is_initialized():
            await self._db.initialize()
        self._redis = get_service("redis")
        if self._redis:
            try:
                if not self._redis.is_initialized():
                    await self._redis.initialize()
            except Exception as e:
                self.logger.warning("Redis indisponível: %s", e)
                self._redis = None
        self.logger.info(
            "QuotaService initialized — %d recursos por plano",
            len(next(iter(PLANS.values()))["quotas"]),
        )

    async def _health_check(self) -> bool:
        return self._db is not None and self._db.is_initialized()

    def _client(self):
        return self._db.get_client()

    def _loop(self):
        return asyncio.get_event_loop()

    # ──────────────────────────────────────────────────────────────────────────
    # PLANO
    # ──────────────────────────────────────────────────────────────────────────

    async def get_plan(self, tenant_id: str) -> str:
        """Retorna o plano actual do tenant. Default: 'free'."""
        if not self.is_initialized():
            await self.initialize()
        try:
            response = await self._loop().run_in_executor(
                None,
                lambda: (
                    self._client()
                    .table(SUBSCRIPTIONS_TABLE)
                    .select("plan")
                    .eq("tenant_id", str(tenant_id))
                    .eq("active", True)
                    .limit(1)
                    .execute()
                ),
            )
            if response.data:
                return response.data[0]["plan"]
        except Exception as e:
            self.logger.warning("Erro ao buscar plano de %s: %s", tenant_id, e)
        return "free"

    def get_plan_info(self, plan: str) -> Dict[str, Any]:
        """Informações completas de um plano."""
        return PLANS.get(plan, PLANS["free"])

    async def get_quota(self, tenant_id: str, resource: str) -> int:
        """Limite de quota para um recurso no plano actual do tenant."""
        plan = await self.get_plan(tenant_id)
        return PLANS.get(plan, PLANS["free"])["quotas"].get(resource, 0)

    # ──────────────────────────────────────────────────────────────────────────
    # USO
    # ──────────────────────────────────────────────────────────────────────────

    async def get_usage(
        self,
        tenant_id: str,
        resource: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Uso actual do tenant.

        Args:
            tenant_id: ID do tenant
            resource:  Se especificado, retorna só esse recurso

        Returns:
            Dict com used, limit, remaining, percent, plan
        """
        if not self.is_initialized():
            await self.initialize()

        plan = await self.get_plan(tenant_id)
        quotas = PLANS.get(plan, PLANS["free"])["quotas"]

        if resource:
            used = await self._get_used(tenant_id, resource)
            return self._usage_dict(resource, used, quotas.get(resource, 0), plan)

        result = {"plan": plan, "resources": {}}
        for res, limit in quotas.items():
            used = await self._get_used(tenant_id, res)
            result["resources"][res] = self._usage_dict(res, used, limit, plan)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # VERIFICAÇÃO E CONSUMO
    # ──────────────────────────────────────────────────────────────────────────

    async def check(
        self, tenant_id: str, resource: str, amount: int = 1
    ) -> bool:
        """Verifica se o tenant tem quota (sem consumir)."""
        if not self.is_initialized():
            await self.initialize()
        limit = await self.get_quota(tenant_id, resource)
        if limit == 0:
            return False
        used = await self._get_used(tenant_id, resource)
        return (used + amount) <= limit

    async def consume(
        self, tenant_id: str, resource: str, amount: int = 1
    ) -> Dict[str, Any]:
        """Regista consumo (sem verificar saldo). Usar check_and_consume para segurança."""
        if not self.is_initialized():
            await self.initialize()
        plan = await self.get_plan(tenant_id)
        limit = PLANS.get(plan, PLANS["free"])["quotas"].get(resource, 0)
        await self._increment_usage(tenant_id, resource, amount)
        await self._log_usage(tenant_id, resource, amount, plan)
        used = await self._get_used(tenant_id, resource)
        self.logger.info(
            "Consumed: tenant=%s resource=%s amount=%d used=%d/%d",
            tenant_id, resource, amount, used, limit,
        )
        return self._usage_dict(resource, used, limit, plan)

    async def check_and_consume(
        self, tenant_id: str, resource: str, amount: int = 1
    ) -> Dict[str, Any]:
        """
        Verifica e consome quota atomicamente.

        Raises:
            QuotaExceededError: se sem quota suficiente
        """
        if not self.is_initialized():
            await self.initialize()
        plan = await self.get_plan(tenant_id)
        limit = PLANS.get(plan, PLANS["free"])["quotas"].get(resource, 0)
        if limit == 0:
            raise QuotaExceededError(resource, 0, 0, plan)
        used = await self._get_used(tenant_id, resource)
        if (used + amount) > limit:
            raise QuotaExceededError(resource, used, limit, plan)
        return await self.consume(tenant_id, resource, amount)

    # ──────────────────────────────────────────────────────────────────────────
    # DASHBOARD / RESUMO
    # ──────────────────────────────────────────────────────────────────────────

    async def get_summary(self, tenant_id: str) -> Dict[str, Any]:
        """Resumo completo para dashboard."""
        usage = await self.get_usage(tenant_id)
        plan_name = usage["plan"]
        plan_info = PLANS.get(plan_name, PLANS["free"])

        exhausted = [
            r for r, d in usage["resources"].items()
            if d["remaining"] == 0 and d["limit"] > 0
        ]
        low = [
            r for r, d in usage["resources"].items()
            if 0 < d["remaining"] <= d["limit"] * 0.1
        ]

        return {
            "tenant_id":        tenant_id,
            "plan":             plan_name,
            "plan_display":     plan_info["display_name"],
            "plan_description": plan_info["description"],
            "price_eur":        plan_info["price_eur"],
            "resources":        usage["resources"],
            "exhausted_resources": exhausted,
            "low_resources":    low,
            "reset_date":       self._next_reset_date(),
            "upgrade_available": plan_name != "everywhere",
        }

    async def format_summary_telegram(self, tenant_id: str) -> str:
        """Formata resumo de quota para exibição no Telegram."""
        summary = await self.get_summary(tenant_id)
        plan = summary["plan_display"]
        price = summary["price_eur"]
        price_str = "Grátis" if price == 0 else f"€{price:.2f}/mês"

        lines = [
            "📊 *O teu plano Jarvis*\n",
            f"✨ **{plan}** — {price_str}\n",
            "─────────────────────",
        ]

        # Agrupa por categoria para melhor leitura
        categories = [
            ("🤖 Inteligência Artificial", ["gpt_tokens", "image_gen", "video_gen"]),
            ("📞 Comunicação", ["twilio_mins", "elevenlabs_chars"]),
            ("🗺️ Localização", ["google_places", "maps_reqs", "search_reqs"]),
            ("🌍 Serviços Externos", [
                "weather_reqs", "crypto_reqs", "youtube_reqs",
                "translate_reqs", "tracking_reqs", "perplexity_reqs",
                "smartcar_reqs", "mercado_scans",
            ]),
            ("💾 Dados Pessoais", ["reminders", "notes"]),
        ]

        for cat_name, resources in categories:
            lines.append(f"\n{cat_name}")
            for res in resources:
                data = summary["resources"].get(res)
                if not data:
                    continue
                label = RESOURCE_ICONS.get(res, res)
                used = data["used"]
                limit = data["limit"]
                pct = data["percent"]
                bar = self._progress_bar(pct, width=8)

                if limit == 0:
                    lines.append(f"  {label}: ❌ Não incluído")
                else:
                    lines.append(f"  {label}: {bar} {used}/{limit}")

        if summary["exhausted_resources"]:
            labels = [RESOURCE_ICONS.get(r, r) for r in summary["exhausted_resources"]]
            lines.append(f"\n⚠️ *Esgotado:* {', '.join(labels)}")

        if summary["low_resources"]:
            labels = [RESOURCE_ICONS.get(r, r) for r in summary["low_resources"]]
            lines.append(f"⚡ *Quase no limite:* {', '.join(labels)}")

        if summary["upgrade_available"]:
            next_plan = "me" if summary["plan"] == "free" else "everywhere"
            next_display = PLANS[next_plan]["display_name"]
            next_price = PLANS[next_plan]["price_eur"]
            lines.append(
                f"\n🚀 Faz upgrade para **{next_display}** "
                f"(€{next_price:.2f}/mês) e desbloqueia mais recursos!"
            )

        lines.append(f"\n🔄 Reset a {summary['reset_date']}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS INTERNOS
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_used(self, tenant_id: str, resource: str) -> int:
        """Uso actual com cache Redis → fallback Supabase → fallback users."""
        if self._redis:
            try:
                key = f"quota:{tenant_id}:{resource}"
                val = await self._redis.get(key)
                if val is not None:
                    return int(val)
            except Exception as e:
                self.logger.warning(
                    "Redis quota lookup failed for %s/%s, falling back to DB: %s",
                    tenant_id, resource, e,
                )

        try:
            period = _month_start() if resource in CUMULATIVE_RESOURCES else "stock"
            response = await self._loop().run_in_executor(
                None,
                lambda: (
                    self._client()
                    .table(USAGE_TABLE)
                    .select("used")
                    .eq("tenant_id", str(tenant_id))
                    .eq("resource", resource)
                    .eq("period_start", period)
                    .execute()
                ),
            )
            if response.data:
                return response.data[0]["used"]
            return 0  # No usage record yet — legitimate zero
        except Exception as e:
            self.logger.warning(
                "DB quota check failed for %s/%s, trying users fallback: %s",
                tenant_id, resource, e,
            )
            try:
                user_id = str(tenant_id).replace("user-", "")
                user_resp = await self._loop().run_in_executor(
                    None,
                    lambda: (
                        self._client()
                        .table("users")
                        .select("messages_used, messages_limit")
                        .eq("id", user_id)
                        .single()
                        .execute()
                    ),
                )
                if user_resp.data:
                    return user_resp.data.get("messages_used", 0)
                self.logger.error(
                    "User %s not found in fallback — blocking access", user_id,
                )
                return 999_999
            except Exception as db_error:
                self.logger.error("DB quota fallback also failed: %s", db_error)
                return 999_999  # fail-safe: block when all systems down

    async def _increment_usage(self, tenant_id: str, resource: str, amount: int) -> None:
        period = _month_start() if resource in CUMULATIVE_RESOURCES else "stock"
        now = _utcnow().isoformat()
        try:
            check = await self._loop().run_in_executor(
                None,
                lambda: (
                    self._client()
                    .table(USAGE_TABLE)
                    .select("id, used")
                    .eq("tenant_id", str(tenant_id))
                    .eq("resource", resource)
                    .eq("period_start", period)
                    .execute()
                ),
            )
            if check.data:
                current = check.data[0]["used"]
                row_id = check.data[0]["id"]
                await self._loop().run_in_executor(
                    None,
                    lambda: (
                        self._client()
                        .table(USAGE_TABLE)
                        .update({"used": current + amount, "updated_at": now})
                        .eq("id", row_id)
                        .execute()
                    ),
                )
            else:
                await self._loop().run_in_executor(
                    None,
                    lambda: (
                        self._client()
                        .table(USAGE_TABLE)
                        .insert({
                            "tenant_id": str(tenant_id),
                            "resource": resource,
                            "used": amount,
                            "period_start": period,
                            "created_at": now,
                            "updated_at": now,
                        })
                        .execute()
                    ),
                )
            if self._redis:
                try:
                    key = f"quota:{tenant_id}:{resource}"
                    new_val = await self._get_used(tenant_id, resource)
                    await self._redis.set(key, new_val, ex=3600)
                except Exception:
                    pass
        except Exception as e:
            self.logger.error("Erro ao incrementar %s/%s: %s", tenant_id, resource, e)

        # Sync tenant_usage to keep both systems consistent
        try:
            period_start = _utcnow().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            existing = await self._loop().run_in_executor(
                None,
                lambda: (
                    self._client()
                    .table("tenant_usage")
                    .select("id, used")
                    .eq("tenant_id", f"user-{tenant_id}")
                    .eq("resource", "gpt_tokens")
                    .gte("period_start", period_start)
                    .execute()
                ),
            )
            now_iso = _utcnow().isoformat()
            if existing.data:
                await self._loop().run_in_executor(
                    None,
                    lambda: (
                        self._client()
                        .table("tenant_usage")
                        .update(
                            {"used": existing.data[0]["used"] + 1,
                             "updated_at": now_iso}
                        )
                        .eq("id", existing.data[0]["id"])
                        .execute()
                    ),
                )
            else:
                await self._loop().run_in_executor(
                    None,
                    lambda: (
                        self._client()
                        .table("tenant_usage")
                        .insert({
                            "tenant_id": f"user-{tenant_id}",
                            "resource": "gpt_tokens",
                            "used": 1,
                            "period_start": period_start,
                            "created_at": now_iso,
                            "updated_at": now_iso,
                        })
                        .execute()
                    ),
                )
        except Exception:
            pass  # quota sync is best-effort, never block the main flow

    async def _log_usage(self, tenant_id: str, resource: str, amount: int, plan: str) -> None:
        try:
            await self._loop().run_in_executor(
                None,
                lambda: (
                    self._client()
                    .table(USAGE_LOG_TABLE)
                    .insert({
                        "tenant_id": str(tenant_id),
                        "resource": resource,
                        "amount": amount,
                        "plan": plan,
                        "created_at": _utcnow().isoformat(),
                    })
                    .execute()
                ),
            )
        except Exception as e:
            self.logger.warning("Erro ao log usage: %s", e)

    @staticmethod
    def _usage_dict(resource: str, used: int, limit: int, plan: str) -> Dict[str, Any]:
        remaining = max(0, limit - used) if limit > 0 else 0
        percent = round((used / limit) * 100, 1) if limit > 0 else 100.0
        return {
            "resource":  resource,
            "used":      used,
            "limit":     limit,
            "remaining": remaining,
            "percent":   percent,
            "plan":      plan,
            "exhausted": remaining == 0 and limit > 0,
        }

    @staticmethod
    def _progress_bar(percent: float, width: int = 8) -> str:
        filled = round(width * percent / 100)
        return f"[{'█' * filled}{'░' * (width - filled)}] {percent:.0f}%"

    @staticmethod
    def _next_reset_date() -> str:
        now = _utcnow()
        month = now.month % 12 + 1
        year = now.year + (1 if now.month == 12 else 0)
        months_pt = [
            "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
        ]
        return f"1 de {months_pt[month]} de {year}"


# ─── Decorator @requires_quota ───────────────────────────────────────────────

def requires_quota(resource: str, amount: int = 1):
    """
    Decorator que verifica e consome quota antes de executar o método.

    O método decorado deve receber tenant_id como 1º argumento (após self).

    Exemplo:
        @requires_quota("google_places")
        async def search_nearby(self, tenant_id: str, ...):
            ...

        @requires_quota("gpt_tokens", amount=500)
        async def chat(self, tenant_id: str, ...):
            ...
    """
    def decorator(func):
        import functools

        @functools.wraps(func)
        async def wrapper(self, tenant_id, *args, **kwargs):
            from services.core import get_service
            quota_svc = get_service("quota")
            if quota_svc:
                await quota_svc.check_and_consume(tenant_id, resource, amount)
            return await func(self, tenant_id, *args, **kwargs)

        return wrapper
    return decorator
