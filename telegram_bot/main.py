"""
Main entry point for the CAPIVAREX Telegram Bot - Refactored and Fixed.

Features:
- Modular handler architecture
- Integration with agents and services
- Autofix system integration
- Proactivity loop
- All services and agents properly registered

FIXES APPLIED:
1. Added imports for ALL services (to trigger @register_service decorators)
2. Added imports for ALL agents (to trigger @register_agent decorators)
3. Fixed event loop issue by using proper async initialization
4. Corrected all import paths based on actual file names
"""

import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message="error reading bcrypt version")

import os  # noqa: E402
import signal  # noqa: E402
import asyncio  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from telegram.error import Conflict, NetworkError, TimedOut  # noqa: E402
from telegram.ext import ApplicationBuilder, CommandHandler  # noqa: E402
from telegram.request import HTTPXRequest  # noqa: E402

# Note: Also called in api/main.py. Registry has idempotency guard, safe to call twice.
from services.registration import register_all_services  # noqa: E402
from agents.registration import register_all_agents  # noqa: E402

register_all_services()
register_all_agents()

# ====================================================================
#                  IMPORTS DO TELEGRAM BOT
# ====================================================================
from telegram_bot.core.bot import CAPIVAREXBot  # noqa: E402
from telegram_bot.handlers import register_all_handlers  # noqa: E402
from telegram_bot.commands.proactivity import toggle_proactivity  # noqa: E402
from telegram_bot.utils.logger import get_logger  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

load_dotenv()

from services.infrastructure.sentry_service import init_sentry  # noqa: E402

init_sentry()

logger = get_logger(__name__)


def main_sync():
    """Main function to start the Telegram bot (synchronous entry point).

    Uses a dedicated event loop for bot initialization, then delegates to
    ``application.run_polling()`` which manages its own event loop internally.
    This avoids the ``RuntimeError: This event loop is already running``
    caused by nesting ``asyncio.run()`` with ``run_polling()``.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not found in environment")

    # Create application with tuned timeouts to avoid false ReadErrors
    # read_timeout MUST be > polling timeout (10s) to prevent httpcore ReadError
    request = HTTPXRequest(
        connect_timeout=5.0,
        read_timeout=30.0,
        write_timeout=5.0,
        pool_timeout=1.0,
        http_version="1.1",
    )
    application = (
        ApplicationBuilder()
        .token(token)
        .request(request)
        .get_updates_request(HTTPXRequest(
            connect_timeout=5.0,
            read_timeout=30.0,
            write_timeout=5.0,
            pool_timeout=1.0,
            http_version="1.1",
        ))
        .build()
    )

    # Initialize bot core synchronously using a temporary event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        bot = CAPIVAREXBot(application)
        loop.run_until_complete(bot.initialize())
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    # Register all handlers (also stores bot in bot_data)
    register_all_handlers(application, bot)

    # Register proactivity toggle command
    application.add_handler(CommandHandler("proatividade", toggle_proactivity))

    # --- Proactivity loop lifecycle callbacks ---
    async def on_post_init(app):
        """Called by run_polling once the event loop is running."""
        capivarax_bot = app.bot_data.get("capivarax_bot")
        if capivarax_bot:
            capivarax_bot.start_proactivity_loop()

    async def on_post_shutdown(app):
        """Called by run_polling when the application is shutting down."""
        capivarax_bot = app.bot_data.get("capivarax_bot")
        if capivarax_bot:
            await capivarax_bot.shutdown()

    application.post_init = on_post_init
    application.post_shutdown = on_post_shutdown

    # --- Graceful shutdown on SIGTERM (Railway sends this during deploys) ---
    def _handle_sigterm(signum, frame):
        logger.info("SIGTERM received — shutting down gracefully...")
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    # --- Error handler: suppress transient network errors, log real ones ---
    async def _telegram_error_handler(update, context):
        """Centralized error handler for the Telegram bot.

        Transient network errors (NetworkError, TimedOut) are logged as
        warnings so the built-in retry loop can recover silently.
        All other errors are logged as errors and forwarded to Sentry.
        """
        error = context.error

        if isinstance(error, (NetworkError, TimedOut)):
            logger.warning(
                "Telegram network error (transient): %s — auto-retry active.",
                type(error).__name__,
            )
            return  # Don't re-raise — let the retry loop handle it

        logger.error(
            "Unhandled Telegram bot error: %s", error, exc_info=context.error
        )

    application.add_error_handler(_telegram_error_handler)

    logger.info("CAPIVAREX Telegram Bot starting...")

    try:
        # run_polling handles its own event loop internally
        application.run_polling(
            poll_interval=0.5,
            timeout=10,
            drop_pending_updates=False,
        )
    except Conflict:
        logger.warning(
            "Telegram Conflict: another instance is already polling. "
            "This is expected during rolling deploys — exiting cleanly."
        )
    except SystemExit:
        logger.info("Bot stopped via SystemExit (SIGTERM or manual).")


if __name__ == "__main__":
    setup_logging()
    main_sync()
