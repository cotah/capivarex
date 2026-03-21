# schemas/orchestrator.py
"""Pydantic schema for OrchestratorAgent JSON responses."""

from pydantic import BaseModel, Field
from typing import Literal

# Allowed agent types for Pydantic validation.
# INTENTIONALLY includes ALL agents (active + disabled + coming_soon).
# If GPT routes to a disabled agent, the orchestrator handles it gracefully
# (returns "coming soon" or falls back to chat). Keeping all agents here
# prevents Pydantic validation errors when GPT suggests a disabled agent.
# See orchestrator_agent.py ALLOWED_AGENTS set for the runtime active list.
ALLOWED_AGENTS = Literal[
    # ── Active (15 agents) ──
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
    # ── Coming Soon Q3 2026 (13 agents) ──
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
    # ── Disabled (4 agents) ──
    "image",
    "video",
    "youtube",
    "media_cast",
    "time",
]


class OrchestratorDecision(BaseModel):
    agent: ALLOWED_AGENTS = Field(
        ..., description="O agente especialista escolhido para lidar com o prompt."
    )
    reason: str = Field(
        ...,
        description="Uma breve justificativa em uma frase para a escolha do agente.",
    )
