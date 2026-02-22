# schemas/orchestrator.py
"""Pydantic schema for OrchestratorAgent JSON responses."""

from pydantic import BaseModel, Field
from typing import Literal

# Allowed agent types — must stay in sync with orchestrator_agent.py
ALLOWED_AGENTS = Literal[
    "chat", "research", "dev", "weather", "finance",
    "image", "video", "voice", "calendar", "traffic",
    "car", "smarthome", "github", "time", "translate",
    "crypto", "timer", "reminder", "youtube", "tracking",
    "meeting", "search", "leaving_now", "mercado", "notes",
    "restaurant",
]


class OrchestratorDecision(BaseModel):
    agent: ALLOWED_AGENTS = Field(
        ..., description="O agente especialista escolhido para lidar com o prompt."
    )
    reason: str = Field(
        ..., description="Uma breve justificativa em uma frase para a escolha do agente."
    )
