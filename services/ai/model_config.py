# -*- coding: utf-8 -*-
"""
services/ai/model_config.py
=============================
Configuração centralizada dos modelos OpenAI.

Cada componente do bot usa o modelo mais adequado:
- Orchestrator: modelo rápido/barato (só classifica intent)
- Chat (cérebro): modelo inteligente (conversa com o user)
- Default: fallback para agents que não especificam

Nota: DevAgent usa Claude (Anthropic) — não está aqui.

Configurável via variáveis de ambiente no Railway:
  OPENAI_ORCHESTRATOR_MODEL=gpt-4.1-mini
  OPENAI_CHAT_MODEL=gpt-5-mini
  OPENAI_DEFAULT_MODEL=gpt-4.1-mini

NOTA: gpt-4o-mini foi DEPRECATED pela OpenAI em Fev 2026.
      gpt-4.1-mini é o substituto oficial.
      gpt-5-mini é o modelo de reasoning (mais inteligente).
"""

import os

# ── Modelo do Orchestrator ─────────────────────────────────────────────────
# Tarefa: classificar intent do user → rotear para agent correcto
# Requisitos: rápido, barato, JSON output fiável
ORCHESTRATOR_MODEL = os.getenv("OPENAI_ORCHESTRATOR_MODEL", "gpt-4.1-mini")

# ── Modelo do Chat (Cérebro) ──────────────────────────────────────────────
# Tarefa: conversar com o user, responder perguntas, ser inteligente
# Requisitos: inteligente, criativo, bom em português
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini")

# ── Modelo Default ─────────────────────────────────────────────────────────
# Tarefa: fallback para agents que não especificam modelo
# Requisitos: bom custo-benefício
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4.1-mini")
