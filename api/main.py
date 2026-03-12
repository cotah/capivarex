"""
Main FastAPI Application - Refactored Architecture.

Entry point for the CAPIVAREX Bot API with:
- Modular router structure
- Integration with agents and services
- Improved middleware and error handling
- Dependency injection
"""

# ====================================================================
# ALL IMPORTS AT TOP (ruff E402 compliance)
# ====================================================================
import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from api.middleware.autofix import autofix_exception_middleware
from api.middleware.error_handler import setup_error_handlers
from api.middleware.logging import logging_middleware
from api.middleware.rate_limit import setup_rate_limiting
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.routes import (
    admin,
    agent_generic,
    auth,
    billing,
    chat,
    notes,
    research,
    dev,
    workspace,
    weather,
    finance,
    image,
    video,
    voice,
    calendar,
    car,
    traffic,
    smartthings,
    health,
    music,
    google_auth,
    spotify_auth,
    webapp,
    upload,
    images_serve,
)
from api.routes import webhooks
from api.routes.voice_pipeline_routes import router_pipeline as voice_pipeline_router
from api.routes.twilio_stream import router as twilio_stream_router

# Load environment variables
load_dotenv()

# Suppress bot token leaks in httpx/telegram HTTP request logs
import logging as _std_logging  # noqa: E402

_std_logging.getLogger("httpx").setLevel(_std_logging.WARNING)
_std_logging.getLogger("httpcore").setLevel(_std_logging.WARNING)
_std_logging.getLogger("telegram").setLevel(_std_logging.WARNING)

# Sentry — must be initialised before anything else
from services.infrastructure.sentry_service import init_sentry  # noqa: E402

init_sentry()

# Explicit service and agent registration
from services.registration import register_all_services  # noqa: E402
from agents.registration import register_all_agents  # noqa: E402

register_all_services()
register_all_agents()

# ====================================================================
# TIMER / REMINDER BACKGROUND LOOP
# ====================================================================

from services.i18n import t  # noqa: E402
from utils.logger import get_logger  # noqa: E402

_bg_logger = get_logger("timer_loop")
_monthly_report_sent: set = set()  # tracks "{year}-{month}" to avoid re-sending
_weekly_price_check_sent: set = set()  # tracks "{year}-{week}" to avoid re-sending
_daily_shopping_reminder_sent: set = set()  # tracks "{year}-{month}-{day}"


async def _get_user_lang(db, user_id: str) -> str:
    """Get preferred_language from user_preferences table (NOT users)."""
    try:
        result = (
            db.table("user_preferences")
            .select("preferred_language")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("preferred_language", "en") or "en"
    except Exception:
        pass
    return "en"


async def _timer_loop() -> None:
    """
    Background loop que verifica timers e lembretes vencidos a cada 10s.
    Corre dentro do processo FastAPI — sem worker separado.
    """
    from services.core import get_service

    _bg_logger.info("Timer background loop started.")

    while True:
        try:
            # --- Timers ---
            timer_svc = get_service("timer")
            if timer_svc:
                if not timer_svc.is_initialized():
                    await timer_svc.initialize()

                notification_svc = get_service("notification")
                if notification_svc and not notification_svc.is_initialized():
                    await notification_svc.initialize()

                async def notify_timer(timer):
                    _bg_logger.info(
                        "AUDIT: Timer fired | timer_id=%s user_chat=%s message='%s'",
                        getattr(timer, "timer_id", "?"),
                        getattr(timer, "chat_id", "?"),
                        (getattr(timer, "label", "") or "")[:50],
                    )
                    icons = {"timer": "⏱️", "alarm": "⏰", "remind": "🔔"}
                    icon = icons.get(timer.timer_type, "⏱️")
                    if timer.timer_type == "alarm":
                        msg = f"{icon} *Bom dia!* Seu alarme disparou!"
                    elif timer.timer_type == "remind":
                        msg = f"{icon} *Lembrete:* {timer.label}"
                    else:
                        msg = f"{icon} *Timer concluído!* {timer.label or ''}"
                    if notification_svc:
                        await notification_svc.send_message(
                            "telegram", timer.chat_id, msg
                        )

                fired = await timer_svc.check_and_fire_due(notify_fn=notify_timer)
                if fired:
                    _bg_logger.info("Fired %d timer(s)", len(fired))

            # --- Lembretes ---
            reminder_svc = get_service("reminder")
            if reminder_svc:
                if not reminder_svc.is_initialized():
                    await reminder_svc.initialize()

                async def notify_reminder(reminder):
                    _bg_logger.info(
                        "AUDIT: Reminder fired | reminder_id=%s user_chat=%s message='%s'",
                        reminder.get("id", "?"),
                        reminder.get("chat_id", "?"),
                        (reminder.get("message", "") or "")[:50],
                    )
                    msg = f"🔔 *Lembrete:* {reminder['message']}"
                    notif_svc = get_service("notification")
                    if notif_svc:
                        await notif_svc.send_message(
                            "telegram", reminder["chat_id"], msg
                        )

                await reminder_svc.check_and_fire_due(notify_fn=notify_reminder)

        except Exception as e:
            _bg_logger.error("Timer loop error: %s", e, exc_info=True)

        # --- Monthly Mercado Excel Report (day 1 of month, 9 AM) ---
        try:
            now_dt = datetime.now()
            month_key = f"{now_dt.year}-{now_dt.month}"

            if (
                now_dt.day == 1
                and now_dt.hour == 9
                and month_key not in _monthly_report_sent
            ):
                _monthly_report_sent.add(month_key)
                _bg_logger.info("Monthly report trigger — generating reports...")

                mercado_svc = get_service("mercado")
                gmail_svc = get_service("gmail")
                notification_svc = get_service("notification")

                if mercado_svc:
                    if not mercado_svc.is_initialized():
                        await mercado_svc.initialize()

                    if gmail_svc and not gmail_svc.is_initialized():
                        await gmail_svc.initialize()

                    # Get all users
                    db = mercado_svc._get_client()
                    users_result = (
                        db.table("users")
                        .select("id,telegram_chat_id,email")
                        .execute()
                    )

                    for user in users_result.data or []:
                        user_id = user.get("id")
                        chat_id = user.get("telegram_chat_id")
                        email = user.get("email")
                        lang = await _get_user_lang(db, user_id) if user_id else "en"

                        if not chat_id:
                            continue

                        try:
                            # Generate Excel for previous month
                            result = await mercado_svc.gerar_excel_mensal(
                                chat_id=str(chat_id), lang=lang
                            )

                            if not result.get("sucesso"):
                                continue  # No purchases, skip

                            excel_bytes = result["excel_bytes"]
                            filename = result["filename"]
                            resumo = result["resumo"]

                            # Determine month name for subject
                            prev_month = now_dt.month - 1 if now_dt.month > 1 else 12
                            prev_year = (
                                now_dt.year if now_dt.month > 1 else now_dt.year - 1
                            )
                            month_name = t(f"month_{prev_month}", lang=lang)

                            email_sent = False

                            # Send via Gmail if connected
                            if gmail_svc and email and user_id:
                                try:
                                    connected = await gmail_svc.is_connected(user_id)
                                    if connected:
                                        profile = await gmail_svc.get_profile(user_id)
                                        user_email = profile.get("emailAddress", email)

                                        subject = t(
                                            "mercado_excel_subject",
                                            lang=lang,
                                            month=month_name,
                                            year=prev_year,
                                        )
                                        body = t(
                                            "mercado_excel_email_body",
                                            lang=lang,
                                            summary=resumo,
                                        )

                                        await gmail_svc.send_email_with_attachment(
                                            user_id=user_id,
                                            to=user_email,
                                            subject=subject,
                                            body=body,
                                            attachment_bytes=excel_bytes,
                                            attachment_filename=filename,
                                        )
                                        email_sent = True
                                        _bg_logger.info(
                                            "Monthly report emailed to user %s",
                                            user_id,
                                        )
                                except Exception as e:
                                    _bg_logger.warning(
                                        "Email report failed for user %s: %s",
                                        user_id,
                                        e,
                                    )

                            # Notify via Telegram
                            if notification_svc:
                                if not notification_svc.is_initialized():
                                    await notification_svc.initialize()

                                tg_key = (
                                    "mercado_excel_telegram_with_email"
                                    if email_sent
                                    else "mercado_excel_telegram_no_email"
                                )
                                tg_msg = t(tg_key, lang=lang, summary=resumo)

                                _bg_logger.info(
                                    "AUDIT: Monthly Report sent to chat_id=%s",
                                    chat_id,
                                )
                                await notification_svc.send_notification(
                                    "telegram", str(chat_id), tg_msg
                                )

                        except Exception as e:
                            _bg_logger.warning(
                                "Monthly report failed for chat %s: %s",
                                chat_id,
                                e,
                            )

                    _bg_logger.info("Monthly report cycle complete.")

        except Exception as e:
            _bg_logger.error("Monthly report check error: %s", e)

        # --- Weekly Price Drop Alerts (Monday, 10 AM) ---
        try:
            now_dt = datetime.now()
            week_key = f"{now_dt.year}-W{now_dt.isocalendar()[1]}"

            if (
                now_dt.weekday() == 0  # Monday
                and now_dt.hour == 10
                and week_key not in _weekly_price_check_sent
            ):
                _weekly_price_check_sent.add(week_key)
                _bg_logger.info("Weekly price drop check triggered...")

                mercado_svc = get_service("mercado")
                notification_svc = get_service("notification")

                if mercado_svc:
                    if not mercado_svc.is_initialized():
                        await mercado_svc.initialize()

                    # Get all users
                    db = mercado_svc._get_client()
                    users_result = db.table("users").select(
                        "id,telegram_chat_id"
                    ).execute()

                    for user in users_result.data or []:
                        chat_id = user.get("telegram_chat_id")
                        u_id = user.get("id")
                        lang = await _get_user_lang(db, u_id) if u_id else "en"

                        if not chat_id:
                            continue

                        try:
                            result = await mercado_svc.verificar_descidas_preco(
                                chat_id=str(chat_id), lang=lang
                            )

                            if result.get("has_alerts") and notification_svc:
                                if not notification_svc.is_initialized():
                                    await notification_svc.initialize()

                                _bg_logger.info(
                                    "AUDIT: Price Alert sent to chat_id=%s",
                                    chat_id,
                                )
                                await notification_svc.send_notification(
                                    "telegram",
                                    str(chat_id),
                                    result["mensagem"],
                                )

                        except Exception as e:
                            _bg_logger.warning(
                                "Price drop check failed for chat %s: %s",
                                chat_id,
                                e,
                            )

                    _bg_logger.info("Weekly price drop check complete.")

        except Exception as e:
            _bg_logger.error("Weekly price drop check error: %s", e)

        # --- Daily Shopping Reminder (18:00) ---
        try:
            now_dt = datetime.now()
            day_key = f"{now_dt.year}-{now_dt.month:02d}-{now_dt.day:02d}"

            if (
                now_dt.hour == 18
                and day_key not in _daily_shopping_reminder_sent
            ):
                _daily_shopping_reminder_sent.add(day_key)
                _bg_logger.info("Daily shopping reminder check triggered...")

                mercado_svc = get_service("mercado")
                notification_svc = get_service("notification")

                if mercado_svc:
                    if not mercado_svc.is_initialized():
                        await mercado_svc.initialize()

                    db = mercado_svc._get_client()
                    users_result = db.table("users").select(
                        "id,telegram_chat_id"
                    ).execute()

                    for user in (users_result.data or []):
                        chat_id = user.get("telegram_chat_id")
                        u_id = user.get("id")
                        lang = await _get_user_lang(db, u_id) if u_id else "en"

                        if not chat_id:
                            continue

                        try:
                            result = await mercado_svc.verificar_lista_pendente(
                                chat_id=str(chat_id), lang=lang
                            )

                            if result.get("has_pending") and notification_svc:
                                if not notification_svc.is_initialized():
                                    await notification_svc.initialize()

                                # Send with inline keyboard
                                from telegram_bot.handlers.mercado_callback import (
                                    build_shopping_reminder_keyboard,
                                )

                                # Use telegram bot directly for keyboard support
                                from telegram import Bot

                                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                                if bot_token:
                                    tg_bot = Bot(token=bot_token)
                                    _bg_logger.info(
                                        "AUDIT: Shopping Reminder sent to chat_id=%s",
                                        chat_id,
                                    )
                                    await tg_bot.send_message(
                                        chat_id=int(chat_id),
                                        text=result["mensagem"],
                                        reply_markup=build_shopping_reminder_keyboard(
                                            lang
                                        ),
                                    )

                        except Exception as e:
                            _bg_logger.warning(
                                "Shopping reminder failed for chat %s: %s",
                                chat_id,
                                e,
                            )

                    _bg_logger.info("Daily shopping reminder check complete.")

        except Exception as e:
            _bg_logger.error("Daily shopping reminder error: %s", e)

        await asyncio.sleep(10)  # verifica a cada 10 segundos


# ====================================================================
# LIFESPAN (startup + shutdown)
# ====================================================================

import logging as _logging  # noqa: E402

_startup_logger = _logging.getLogger("capivarex.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup → yield → Shutdown."""
    # --- Startup ---
    _startup_logger.info("CAPIVAREX Bot API starting up...")
    from services import get_service

    for service_name in ["database", "openai", "redis"]:
        try:
            service = get_service(service_name)
            if service and not service.is_initialized():
                await service.initialize()
                _startup_logger.info("Initialized %s service", service_name)
        except Exception as e:
            _startup_logger.warning(
                "Service %s not found or failed to initialize: %s",
                service_name,
                e,
            )

    # Schema health check — warn on startup if critical tables are missing
    # Prevents PGRST205 errors from reaching production undetected.
    _CRITICAL_TABLES = [
        "users",
        "webapp_conversations",
        "webapp_messages",
        "security_events",
    ]
    try:
        _db_svc = get_service("database")
        if _db_svc and _db_svc.is_initialized():
            _client = _db_svc.get_client()
            for _tbl in _CRITICAL_TABLES:
                try:
                    _client.table(_tbl).select("id").limit(1).execute()
                    _startup_logger.info("SCHEMA_HEALTH: table '%s' OK", _tbl)
                except Exception as _te:
                    _startup_logger.warning(
                        "SCHEMA_HEALTH: table '%s' NOT FOUND — %s. "
                        "Run the corresponding migration in Supabase.",
                        _tbl,
                        _te,
                    )
    except Exception as _sche:
        _startup_logger.warning("SCHEMA_HEALTH: check failed (non-fatal): %s", _sche)

    # Background timer/reminder loop
    timer_task = asyncio.create_task(_timer_loop())
    _startup_logger.info("CAPIVAREX Bot API started successfully")

    yield

    # --- Shutdown ---
    _startup_logger.info("CAPIVAREX Bot API shutting down...")
    timer_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await timer_task


# ====================================================================
# CRIAÇÃO DA APLICAÇÃO
# ====================================================================

app = FastAPI(
    title="CAPIVAREX Bot API",
    description="API Backend do CAPIVAREX Bot - Assistente de IA Unificado com Arquitetura Refatorada",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ====================================================================
# PROMETHEUS METRICS
# ====================================================================

Instrumentator().instrument(app).expose(app)

# ====================================================================
# MIDDLEWARE
# ====================================================================

app.middleware("http")(logging_middleware)
app.middleware("http")(autofix_exception_middleware)
app.add_middleware(SecurityHeadersMiddleware)
setup_rate_limiting(app)
setup_error_handlers(app)

_cors_origins = []

# Always allow localhost for development
if os.getenv("ENVIRONMENT") == "development":
    _cors_origins.extend(
        [
            os.getenv("CORS_ORIGIN_LOCALHOST", "http://localhost:3000"),
            os.getenv("CORS_ORIGIN_VITE", "http://localhost:5173"),
            "https://*.replit.dev",
        ]
    )

# WebApp production origins
_cors_origins.extend(
    [
        "https://app.capivarex.com",
        "https://capivarex.com",
    ]
)

# Add configured frontend URL (production or staging)
_frontend_url = os.getenv("FRONTEND_URL")
if _frontend_url:
    _cors_origins.append(_frontend_url)

# Admin dashboard origin
_admin_url = os.getenv("ADMIN_URL")
if _admin_url:
    _cors_origins.append(_admin_url)

# Safety: if no origins configured, block all cross-origin requests
if not _cors_origins:
    import logging

    logging.getLogger("capivarex.api").error(
        "SECURITY: No CORS origins configured! "
        "Blocking all cross-origin requests. "
        "Set FRONTEND_URL or CORS_ORIGIN_* variables."
    )
    _cors_origins = []  # Block everything instead of allowing everything

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ====================================================================
# HEALTH CHECKS
# ====================================================================


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "status": "online",
        "service": "CAPIVAREX Bot API",
        "version": "2.0.0",
        "architecture": "refactored",
    }


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "version": "2.0.0",
    }


@app.get("/api/health/detailed")
async def detailed_health_check(request: Request):
    """Detailed health check with service status."""
    health_token = os.environ.get("HEALTH_CHECK_TOKEN", "")
    if health_token:
        provided = request.headers.get("X-Health-Token", "")
        if provided != health_token:
            raise HTTPException(status_code=404, detail="Not found")
    from services.core import registry as service_registry
    from agents.core import registry as agent_registry

    service_health = {}
    try:
        service_metrics = service_registry.get_all_metrics()
        for name, metrics in service_metrics.items():
            service_health[name] = {
                "status": metrics.get("status"),
                "initialized": metrics.get("initialized"),
                "call_count": metrics.get("call_count"),
                "error_rate": metrics.get("error_rate"),
            }
    except Exception as e:
        service_health["error"] = str(e)

    agent_health = {}
    try:
        agents = agent_registry.list_agents()
        agent_health = {"registered_agents": agents, "count": len(agents)}
    except Exception as e:
        agent_health["error"] = str(e)

    return {
        "status": "healthy",
        "version": "2.0.0",
        "services": service_health,
        "agents": agent_health,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


# ====================================================================
# DEBUG ENDPOINTS
# ====================================================================


@app.get("/debug/services")
def debug_services():
    """List registered services — development only."""
    if os.getenv("ENVIRONMENT") != "development":
        raise HTTPException(status_code=404, detail="Not found")
    from services.core import registry as service_registry

    try:
        all_services = service_registry.list_services()
        metrics = service_registry.get_all_metrics()
        return {
            "total": len(all_services),
            "services": all_services,
            "metrics": metrics,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug/agents")
def debug_agents():
    """List registered agents — development only."""
    if os.getenv("ENVIRONMENT") != "development":
        raise HTTPException(status_code=404, detail="Not found")
    from agents.core import registry as agent_registry

    try:
        all_agents = agent_registry.list_agents()
        return {"total": len(all_agents), "agents": all_agents}
    except Exception as e:
        return {"error": str(e)}


# ====================================================================
# ROUTERS
# ====================================================================

API_V1 = "/api/v1"

app.include_router(auth.router, prefix=f"{API_V1}/auth", tags=["Authentication"])
app.include_router(google_auth.router, tags=["Google Auth"])
app.include_router(spotify_auth.router, tags=["Spotify Auth"])
app.include_router(chat.router, prefix=f"{API_V1}/chat", tags=["Chat"])
app.include_router(notes.router, prefix=f"{API_V1}/notes", tags=["Notes"])
app.include_router(workspace.router, prefix=f"{API_V1}/workspace", tags=["Workspace"])
app.include_router(research.router, prefix=f"{API_V1}/research", tags=["Research"])
app.include_router(dev.router, prefix=f"{API_V1}/dev", tags=["Development"])
app.include_router(image.router, prefix=f"{API_V1}/image", tags=["Image"])
app.include_router(video.router, prefix=f"{API_V1}/video", tags=["Video"])
app.include_router(voice.router, prefix=f"{API_V1}/voice", tags=["Voice"])
app.include_router(
    voice_pipeline_router, prefix=f"{API_V1}/voice/pipeline", tags=["Voice Pipeline"]
)
app.include_router(weather.router, prefix=f"{API_V1}/weather", tags=["Weather"])
app.include_router(finance.router, prefix=f"{API_V1}/finance", tags=["Finance"])
app.include_router(calendar.router, prefix=f"{API_V1}/calendar", tags=["Calendar"])
app.include_router(car.router, prefix=f"{API_V1}/car", tags=["Car"])
app.include_router(traffic.router, prefix=f"{API_V1}/traffic", tags=["Traffic"])
app.include_router(
    smartthings.router, prefix=f"{API_V1}/smartthings", tags=["SmartThings"]
)
app.include_router(music.router, prefix=f"{API_V1}/music", tags=["Music"])
app.include_router(
    agent_generic.router, prefix=f"{API_V1}/agent", tags=["Generic Agent"]
)
app.include_router(webapp.router, prefix="/api/webapp", tags=["WebApp"])
app.include_router(upload.router, prefix="/api/webapp", tags=["WebApp"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(billing.router, prefix="/api/billing", tags=["Billing"])
app.include_router(images_serve.router, tags=["Images"])
app.include_router(webhooks.router, prefix=f"{API_V1}/webhooks", tags=["Webhooks"])
app.include_router(twilio_stream_router, tags=["Twilio Stream"])
app.include_router(health.router, tags=["Monitoring"])
