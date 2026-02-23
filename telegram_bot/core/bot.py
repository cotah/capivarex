"""Core bot class for the refactored Telegram bot."""
import asyncio
import logging
from typing import Dict, Any, List, Optional

from telegram.ext import Application

from services import get_service
from agents import get_agent
from agents.core.base_agent import AgentResponse


class CapivaraXBot:
    """Core bot class that manages state, services, and agents."""

    def __init__(self, application: Application) -> None:
        """Initialise the Telegram bot wrapper."""
        self.application: Application = application
        self.logger: logging.Logger = logging.getLogger("capivarax.telegram")
        self.services: Dict[str, Any] = {}
        self.agents: Dict[str, Any] = {}
        self._proactivity_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """
        Initialize services and agents.

        Attempts to bring up critical services (database, openai, redis)
        and the orchestrator agent. Failures are logged but do not prevent
        the bot from starting.
        """
        self.logger.info("Initializing CapivaraX Bot...")

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
                else:
                    self.logger.warning(
                        "Service %s already initialized or not found", service_name
                    )
            except Exception as e:
                self.logger.error(
                    "FAILED to initialize %s: %s", service_name, e, exc_info=True
                )

        # Initialize ALL agents
        agent_names: List[str] = [
            "orchestrator", "chat", "dev", "research", "image", "video",
            "voice", "calendar", "weather", "traffic", "car", "finance",
            "smarthome", "github"
        ]
        for agent_name in agent_names:
            try:
                agent = get_agent(agent_name)
                if agent:
                    self.agents[agent_name] = agent
                    self.logger.info("Loaded %s agent", agent_name)
            except Exception as e:
                self.logger.warning("Could not load %s agent: %s", agent_name, e)

        self.logger.info("CapivaraX Bot initialized successfully")

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

    async def process_message(self, text: str, context: Dict[str, Any]) -> "AgentResponse":
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

        try:
            orchestrator = self.agents.get("orchestrator")
            if not orchestrator:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Bot não está pronto. Tente novamente em alguns segundos.",
                )

            # Orchestrator identifies the target agent
            decision = await orchestrator.process(text, context)
            agent_name = decision.response if hasattr(decision, "response") else str(decision)

            # Execute the identified agent
            agent = get_agent(agent_name)
            if not agent:
                # Fallback to chat agent
                agent = get_agent("chat") or self.agents.get("chat")

            if not agent:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=f"Agente '{agent_name}' não disponível.",
                )

            # Process the message with the specific agent
            result = await agent.process(text, context)
            return result
        except Exception as e:
            self.logger.error("Error processing message: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar mensagem: {str(e)}",
            )

