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

# ── Grupo 1 — CORE BUSINESS: Manter 100% Ativos ──
# ── Grupo 2 — COMING SOON: Roteamento desativado temporariamente ──
# ── Grupo 3 — DESATIVADO: Roteamento cortado indefinidamente ──
ALLOWED_AGENTS = {
    # Grupo 1 — Core Business (ativos)
    "chat",
    "calendar",
    "email",
    "meeting",
    "notes",
    "reminder",
    "research",
    "search",
    "voice",
    "translate",
    "tracking",
    "finance",
    "weather",
    "timer",
    "maps",
    # "travel",        # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "restaurant",    # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "mercado",       # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "crypto",        # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "dev",           # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "github",        # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "twilio",        # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "traffic",       # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "leaving_now",   # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "transport",     # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "smarthome",     # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "car",           # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "music",         # TODO: Reativar no Q3 2026 — Coming Soon (Grupo 2)
    # "image",         # DISABLED: Fora do escopo executivo atual (Grupo 3)
    # "video",         # DISABLED: Fora do escopo executivo atual (Grupo 3)
    # "youtube",       # DISABLED: Fora do escopo executivo atual (Grupo 3)
    # "media_cast",    # DISABLED: Fora do escopo executivo atual (Grupo 3)
    # "time",          # DISABLED: Fora do escopo executivo atual (Grupo 3)
}

# Agents desativados — usados para retornar mensagem correta ao user
_COMING_SOON_AGENTS = {
    "travel",
    "restaurant",
    "mercado",
    "crypto",
    "dev",
    "github",
    "twilio",
    "traffic",
    "leaving_now",
    "transport",
    "smarthome",
    "car",
    "music",
}
_DISABLED_AGENTS = {"image", "video", "youtube", "media_cast", "time"}


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
                max_completion_tokens=150,
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
                reason_override = ""
                if decision in _COMING_SOON_AGENTS:
                    reason_override = "coming_soon"  # Grupo 2 - Coming Soon Q3 2026
                    self.logger.info(
                        "Agent '%s' is Coming Soon (Grupo 2), routing to chat", decision
                    )
                elif decision in _DISABLED_AGENTS:
                    reason_override = "disabled"  # Grupo 3 - Desativado
                    self.logger.info(
                        "Agent '%s' is Disabled (Grupo 3), routing to chat", decision
                    )
                else:
                    self.logger.warning(
                        "Agent '%s' not in ALLOWED_AGENTS, defaulting to chat", decision
                    )
                decision = "chat"
                if reason_override:
                    return AgentResponse(
                        status=AgentStatus.SUCCESS,
                        response=decision,
                        data={
                            "agent": decision,
                            "reason": reason_override,
                            "original_agent": decision_data.get("agent", ""),
                        },
                    )

            # Guard: transcription keywords must NOT go to voice (voice is TTS only)
            if decision == "voice":
                _lower = prompt.lower()
                _transcription_keywords = (
                    "transcrever",
                    "transcreve",
                    "transcrição",
                    "o que eu disse",
                    "o que eu falei",
                    "o que está escrito",
                    "gravar áudio",
                    "transcribe",
                    "transcription",
                    "what did i say",
                    "speech to text",
                    "audio to text",
                )
                if any(kw in _lower for kw in _transcription_keywords):
                    self.logger.info(
                        "Orchestrator: overriding 'voice' → 'chat' for transcription request"
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
