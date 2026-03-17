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
  OPENAI_ORCHESTRATOR_MODEL=gpt-4.1-mini   (único barato — só roteia)
  OPENAI_CHAT_MODEL=gpt-5-mini             (cérebro — conversa)
  OPENAI_DEFAULT_MODEL=gpt-5-mini          (fallback agents)
  OPENAI_INTENT_MODEL=gpt-5-mini           (sub-intents)
  OPENAI_VISION_MODEL=gpt-5-mini           (imagens)

NOTA: gpt-4o-mini foi DEPRECATED pela OpenAI em Fev 2026.
      gpt-4.1-mini é o substituto oficial (usado SÓ no orchestrador).
      gpt-5-mini é o modelo principal — TODO o resto usa ele.
"""

import os

# ── Modelo do Orchestrator ─────────────────────────────────────────────────
# Tarefa: classificar intent do user → rotear para agent correcto
# Requisitos: rápido, barato, JSON output fiável
# NOTA: único modelo que fica barato — economia de custo
ORCHESTRATOR_MODEL = os.getenv("OPENAI_ORCHESTRATOR_MODEL", "gpt-4.1-mini")

# ── Modelo do Chat (Cérebro) ──────────────────────────────────────────────
# Tarefa: conversar com o user, responder perguntas, ser inteligente
# Requisitos: inteligente, criativo, bom em português
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini")

# ── Modelo Default ─────────────────────────────────────────────────────────
# Tarefa: fallback para agents que não especificam modelo
# Requisitos: inteligente (usado em features do user)
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5-mini")

# ── Modelo para classificação de intent dentro dos agents ──────────────────
# Tarefa: classificar sub-intents (ex: smart home on/off/brightness)
# Requisitos: inteligente (impacta qualidade da resposta)
INTENT_MODEL = os.getenv("OPENAI_INTENT_MODEL", "gpt-5-mini")

# ── Modelo Vision (análise de imagens) ─────────────────────────────────────
# Tarefa: analisar imagens enviadas pelo user
# Requisitos: suporte a vision/multimodal
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-5-mini")
