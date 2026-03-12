"""Core bot class for the refactored Telegram bot."""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional

from telegram.ext import Application

from services import get_service
from agents import get_agent
from agents.core.base_agent import AgentResponse
from services.i18n import (
    check_keywords,
    TWILIO_KEYWORDS,
    TRANSPORT_KEYWORDS,
    CALENDAR_CONNECT_KEYWORDS,
    EMAIL_KEYWORDS,
    MERCADO_KEYWORDS,
    MEDIA_CAST_KEYWORDS,
)
from services.i18n.keywords import check_keywords_with_phone

# NOTE: _TRANSPORT_KEYWORDS and _TWILIO_KEYWORDS removed — now in services/i18n/keywords.py


class CAPIVAREXBot:
    """Core bot class that manages state, services, and agents."""

    def __init__(self, application: Application) -> None:
        """Initialise the Telegram bot wrapper."""
        self.application: Application = application
        self.logger: logging.Logger = logging.getLogger("capivarex.telegram")
        self.services: Dict[str, Any] = {}
        self.agents: Dict[str, Any] = {}
        self._proactivity_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """
        Initialize services and agents.

        Attempts to bring up critical services (database, openai, redis)
        and the orchestrator agent.  Failures are logged but do not prevent
        the bot from starting.
        """
        self.logger.info("Initializing CAPIVAREX Bot...")

        # Initialize critical services
        critical_services: List[str] = ["database", "openai", "redis"]
        for service_name in critical_services:
            try:
                self.logger.debug("Attempting to initialize %s...", service_name)
                service = get_service(service_name)
                if service and not service.is_initialized():
                    await service.initialize()
                self.services[service_name] = service
                self.logger.info("Initialized %s service successfully", service_name)
            except Exception as e:
                self.logger.error(
                    "FAILED to initialize %s: %s",
                    service_name,
                    e,
                    exc_info=True,
                )

        # Initialize ALL agents
        agent_names: List[str] = [
            "orchestrator",
            "chat",
            "dev",
            "research",
            "image",
            "video",
            "voice",
            "calendar",
            "weather",
            "traffic",
            "car",
            "finance",
            "smarthome",
            "github",
            "time",
            "translate",
            "crypto",
            "timer",
            "reminder",
            "youtube",
            "tracking",
            "meeting",
            "search",
            "leaving_now",
            "mercado",
            "notes",
            "restaurant",
            "email",
            "transport",
            "travel",
            "twilio",
            "media_cast",
        ]
        for agent_name in agent_names:
            try:
                agent = get_agent(agent_name)
                if agent:
                    self.agents[agent_name] = agent
                    self.logger.info("Loaded %s agent", agent_name)
                else:
                    self.logger.warning(
                        "Agent %s returned None from registry", agent_name
                    )
            except Exception as e:
                self.logger.warning("Could not load %s agent: %s", agent_name, e)

        self.logger.info(
            "CAPIVAREX Bot initialized successfully — %d agents loaded: %s",
            len(self.agents),
            list(self.agents.keys()),
        )

    def start_proactivity_loop(self) -> None:
        """Start the proactivity loop as a background asyncio task.

        Must be called from within a running event loop (e.g. inside
        ``post_init`` or after ``run_polling`` has started).
        """
        try:
            from proactivity_loop import main_loop

            self._proactivity_task = asyncio.create_task(main_loop())
            self.logger.info("Proactivity loop started successfully")
        except Exception as e:
            self.logger.error("Failed to start proactivity loop: %s", e, exc_info=True)

    async def shutdown(self) -> None:
        """Shutdown bot and cleanup resources."""
        try:
            if self._proactivity_task and not self._proactivity_task.done():
                self._proactivity_task.cancel()
                try:
                    await self._proactivity_task
                except asyncio.CancelledError:
                    pass
            self.logger.info("Proactivity loop stopped")
        except Exception as e:
            self.logger.error("Error during shutdown: %s", e, exc_info=True)

    def _is_transport_query(self, text: str) -> bool:
        """Check if the text is clearly about public transport (multi-language)."""
        return check_keywords(text, TRANSPORT_KEYWORDS)

    def _is_twilio_query(self, text: str) -> bool:
        """Check if the text is clearly about making a phone call (multi-language)."""
        if check_keywords(text, TWILIO_KEYWORDS):
            return True
        return check_keywords_with_phone(text)

    def _is_travel_query(self, text: str) -> bool:
        """Check if the text is about travel/flights/hotels (multi-language)."""
        from services.i18n.keywords import TRAVEL_KEYWORDS

        return check_keywords(text, TRAVEL_KEYWORDS)

    def _is_calendar_connect_query(self, text: str) -> bool:
        """Check if the user wants to connect Google Calendar (multi-language)."""
        return check_keywords(text, CALENDAR_CONNECT_KEYWORDS)

    def _is_email_query(self, text: str) -> bool:
        """Check if the text is clearly about email management (multi-language)."""
        return check_keywords(text, EMAIL_KEYWORDS)

    def _is_media_cast_query(self, text: str) -> bool:
        """Check if text matches media cast/TV keywords."""
        return check_keywords(text, MEDIA_CAST_KEYWORDS)

    def _is_mercado_query(self, text: str) -> bool:
        """Check if text matches mercado/shopping keywords."""
        return check_keywords(text, MERCADO_KEYWORDS)

    def _is_search_query(self, text: str) -> bool:
        """Check if the text is clearly a search/shopping/places query."""
        _SEARCH_KEYWORDS = [
            # Preço/compra (PT)
            "quanto custa",
            "qual o preço",
            "preço de",
            "preço do",
            "preço da",
            "onde comprar",
            "onde encontrar",
            "onde achar",
            # Preço/compra (EN)
            "how much",
            "price of",
            "where to buy",
            "where can i buy",
            # Lugares
            "perto de mim",
            "near me",
            "nearby",
            "open now",
            "aberto agora",
            "aberta agora",
            # Shopping
            "mais barato",
            "cheapest",
            "best deal",
            "melhor preço",
        ]
        lower = text.lower()
        return any(kw in lower for kw in _SEARCH_KEYWORDS)

    async def process_message(
        self, text: str, context: Dict[str, Any]
    ) -> "AgentResponse":
        """
        Process a message using the orchestrator agent.

        Args:
            text: The message text to process.
            context: Context dict with user_id, chat_id, username, etc.

        Returns:
            AgentResponse from the specialized agent (includes data/metadata
            with file paths for media agents).
        """
        from agents.core import AgentResponse, AgentStatus

        # ── 1. Resolve Telegram numeric ID → internal UUID ────────────
        telegram_id = str(context.get("user_id", ""))
        if telegram_id and not self._is_uuid(telegram_id):
            try:
                db_svc = get_service("database")
                if db_svc and db_svc.is_initialized():
                    user_row = await db_svc.get_user_by_telegram_id(telegram_id)
                    if user_row:
                        context = {
                            **context,
                            "user_id": user_row["id"],  # UUID para o DB
                            "telegram_user_id": telegram_id,  # ID original preservado
                        }
                        self.logger.info(
                            "Resolved telegram_id %s → UUID %s",
                            telegram_id,
                            user_row["id"],
                        )
                    else:
                        self.logger.warning(
                            "Could not find user for telegram_id=%s", telegram_id
                        )
            except Exception as e:
                self.logger.warning("Could not resolve user UUID: %s", e)

        # ── 1b. Get or create conversation for memory ─────────────
        try:
            db_svc = get_service("database")
            if db_svc and db_svc.is_initialized():
                user_uuid = context.get("user_id", "")
                if self._is_uuid(str(user_uuid)):
                    conv_id = await db_svc.get_or_create_conversation(str(user_uuid))
                    if conv_id:
                        context["conversation_id"] = conv_id
                        # Store the user message
                        await db_svc.store_message(conv_id, "user", text)
                        self.logger.info(
                            "Conversation %s: stored user message", conv_id[:8]
                        )
        except Exception as e:
            self.logger.warning("Could not setup conversation memory: %s", e)

        try:
            # ── 2. Orchestrator decide qual agent usar ────────────────
            orchestrator = self.agents.get("orchestrator")
            if not orchestrator:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Bot não está pronto. Tente novamente em alguns segundos.",
                )

            decision = await orchestrator.process(text, context)
            agent_name = (
                decision.response if hasattr(decision, "response") else str(decision)
            )

            self.logger.info(
                "Orchestrator routed '%s' → agent='%s' (reason: %s)",
                text[:60],
                agent_name,
                decision.data.get("reason", "")
                if hasattr(decision, "data") and decision.data
                else "",
            )

            # ── 3. KEYWORD SAFETY NET ─────────────────────────────────
            # Protege contra falhas do GPT-4o-mini no routing.
            # "conectar google" → calendar (LLM confunde "google" com search)
            # "meus emails" → email (LLM pode enviar para chat/search)
            if agent_name in ("chat", "search", "research") and self._is_calendar_connect_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → calendar (was: %s)",
                    text[:60],
                    agent_name,
                )
                agent_name = "calendar"

            if agent_name in ("chat", "search", "research") and self._is_email_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → email (was: %s)",
                    text[:60],
                    agent_name,
                )
                agent_name = "email"

            # Media cast safety net: "põe na TV", "play on TV", "chromecast"
            if agent_name in (
                "chat", "youtube", "smarthome", "search", "research"
            ) and self._is_media_cast_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → media_cast (was: %s)",
                    text[:60],
                    agent_name,
                )
                agent_name = "media_cast"

            # Mercado safety net: GPT often misroutes shopping commands to
            # notes ("ver lista" → nota), calendar ("exportar março" → events),
            # or chat. Override when mercado keywords match.
            if agent_name in (
                "chat", "notes", "reminder", "calendar", "search", "research"
            ) and self._is_mercado_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → mercado (was: %s)",
                    text[:60],
                    agent_name,
                )
                agent_name = "mercado"

            if agent_name == "chat" and self._is_transport_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → transport (was: chat)", text[:60]
                )
                agent_name = "transport"

            if agent_name == "chat" and self._is_twilio_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → twilio (was: chat)", text[:60]
                )
                agent_name = "twilio"

            if agent_name == "chat" and self._is_travel_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → travel (was: chat)", text[:60]
                )
                agent_name = "travel"

            if agent_name == "chat" and self._is_search_query(text):
                self.logger.info(
                    "KEYWORD OVERRIDE: '%s' → search (was: chat)", text[:60]
                )
                agent_name = "search"

            # ── 4. Obter e executar o agent ───────────────────────────
            agent = get_agent(agent_name)
            if not agent:
                self.logger.error(
                    "Agent '%s' NOT FOUND in registry, falling back to chat",
                    agent_name,
                )
                agent = get_agent("chat") or self.agents.get("chat")

            if not agent:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=f"Agente '{agent_name}' não disponível.",
                )

            self.logger.info("Executing agent: %s", agent.name)
            result = await agent.process(text, context)

            # ── 5. Store bot response in conversation memory ──────────
            try:
                conv_id = context.get("conversation_id")
                if conv_id and result and result.response:
                    db_svc = get_service("database")
                    if db_svc and db_svc.is_initialized():
                        await db_svc.store_message(
                            conv_id, "assistant", result.response
                        )
            except Exception as e:
                self.logger.warning("Could not store bot response: %s", e)

            # ── 6. Background: extract personal info if shared ────────
            user_uuid = str(context.get("user_id", ""))
            if user_uuid and self._is_uuid(user_uuid):
                try:
                    from services.business.user_profile_service import (
                        extract_and_save_personal_info,
                    )

                    asyncio.create_task(
                        extract_and_save_personal_info(user_uuid, text)
                    )
                except Exception as e:
                    self.logger.debug("Could not schedule info extraction: %s", e)

            return result

        except Exception as e:
            self.logger.error("Error processing message: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar mensagem: {str(e)}",
            )

    @staticmethod
    def _is_uuid(value: str) -> bool:
        """Check if a string is a valid UUID."""
        return bool(
            re.match(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                value,
                re.I,
            )
        )
