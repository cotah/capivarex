"""
Orchestrator Agent - Routes requests to specialized agents.

Refactored to use new BaseAgent architecture.

FIX [2025-02]: Adicionados agentes 'transport' e 'twilio' ao ALLOWED_AGENTS
               e ao system_prompt de routing. Ambos os serviços estavam
               implementados mas nunca eram roteados pelo orquestrador.
"""

import json
import logging
from typing import Any, Dict

from pydantic import ValidationError

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from schemas.orchestrator import OrchestratorDecision
from services import get_service
from services.ai.model_config import ORCHESTRATOR_MODEL
from services.i18n.prompts import get_orchestrator_prompt


logger = logging.getLogger(__name__)

# FIX: Adicionados "transport" e "twilio" que estavam implementados mas não registados
ALLOWED_AGENTS = {
    "chat",
    "research",
    "dev",
    "weather",
    "finance",
    "image",
    "video",
    "voice",
    "calendar",
    "traffic",
    "car",
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
    "transport",  # Transporte público (autocarro, DART, Luas, comboio)
    "twilio",  # FIX: Phone calls via Twilio (credenciais configuradas)
}


@register_agent("orchestrator", lazy=False)
class OrchestratorAgent(BaseAgent):
    """
    Orchestrator agent that routes requests to specialized agents.

    Uses OpenAI to analyze the user's prompt and determine which
    specialized agent should handle the request.
    """

    def __init__(self):
        """Initialise the orchestrator agent."""
        super().__init__(
            name="orchestrator", description="Routes requests to specialized agents"
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """
        Analyze prompt and route to appropriate agent.

        Args:
            prompt: User's input prompt
            context: Execution context

        Returns:
            AgentResponse with routing decision
        """
        openai_service = get_service("openai")

        if not openai_service:
            self.logger.error("OpenAI service not available")
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="chat",
                data={"agent": "chat", "reason": "OpenAI service not available"},
                error="OpenAI service not registered",
            )

        if not openai_service.is_initialized():
            try:
                await openai_service.initialize()
            except Exception as e:
                self.logger.error("Failed to initialize OpenAI service: %s", e)
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="chat",
                    data={"agent": "chat", "reason": "Service initialization failed"},
                    error=str(e),
                )

        client = openai_service.client
        if not client:
            self.logger.warning("OpenAI client not available, defaulting to chat")
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="chat",
                data={"agent": "chat", "reason": "OpenAI client not available"},
            )

        # i18n: English orchestrator prompt for routing reliability
        system_prompt = get_orchestrator_prompt()

        try:
            response = await client.chat.completions.create(
                model=ORCHESTRATOR_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=150,
                temperature=0.0,
            )

            if not response.choices:
                self.logger.warning("OpenAI returned empty choices, defaulting to chat")
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response="chat",
                    data={"agent": "chat", "reason": "Empty OpenAI response"},
                )
            response_text = response.choices[0].message.content or ""
            decision_data = json.loads(response_text)

            # Validate with Pydantic
            validated_decision = OrchestratorDecision.model_validate(decision_data)
            decision = validated_decision.agent

            # Safety guard: ensure agent is in allowed set
            if decision not in ALLOWED_AGENTS:
                self.logger.warning(
                    "Agent '%s' not in ALLOWED_AGENTS, defaulting to chat", decision
                )
                decision = "chat"

            self.logger.info(
                "Routed to agent: %s | reason: %s",
                decision,
                decision_data.get("reason", ""),
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=decision,
                data={
                    "agent": decision,
                    "reason": decision_data.get("reason", ""),
                },
            )

        except json.JSONDecodeError as e:
            self.logger.error("Failed to parse OpenAI JSON response: %s", e)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="chat",
                data={"agent": "chat", "reason": "JSON parse error"},
                error=str(e),
            )
        except ValidationError as e:
            self.logger.error("Pydantic validation error: %s", e)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="chat",
                data={"agent": "chat", "reason": "Validation error"},
                error=str(e),
            )
        except Exception as e:
            self.logger.error("Orchestrator error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="chat",
                data={"agent": "chat", "reason": "Unexpected error"},
                error=str(e),
            )
