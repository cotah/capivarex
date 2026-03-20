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
  OPENAI_ORCHESTRATOR_MODEL=gpt-5.4-nano    (mais barato — só roteia)
  OPENAI_CHAT_MODEL=gpt-5.4-mini            (cérebro — conversa)
  OPENAI_DEFAULT_MODEL=gpt-5.4-mini         (fallback agents)
  OPENAI_INTENT_MODEL=gpt-5.4-mini          (sub-intents)
  OPENAI_VISION_MODEL=gpt-5.4-mini          (imagens)

NOTA: Upgrade Março 2026:
      gpt-5-mini → gpt-5.4-mini (2x mais rápido, melhor qualidade, preço similar)
      gpt-4.1-mini → gpt-5.4-nano (metade do preço, mesmo ou melhor desempenho)
"""

import os

# ── Modelo do Orchestrator ─────────────────────────────────────────────────
# Tarefa: classificar intent do user → rotear para agent correcto
# Requisitos: rápido, barato, JSON output fiável
# gpt-5.4-nano: $0.20/1M input, $1.25/1M output — mais barato que gpt-4.1-mini
ORCHESTRATOR_MODEL = os.getenv("OPENAI_ORCHESTRATOR_MODEL", "gpt-5.4-nano")

# ── Modelo do Chat (Cérebro) ──────────────────────────────────────────────
# Tarefa: conversar com o user, responder perguntas, ser inteligente
# Requisitos: inteligente, criativo, bom em português
# gpt-5.4-mini: $0.75/1M input, $4.50/1M output — 2x mais rápido que gpt-5-mini
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.4-mini")

# ── Modelo Default ─────────────────────────────────────────────────────────
# Tarefa: fallback para agents que não especificam modelo
# Requisitos: inteligente (usado em features do user)
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5.4-mini")

# ── Modelo para classificação de intent dentro dos agents ──────────────────
# Tarefa: classificar sub-intents (ex: smart home on/off/brightness)
# Requisitos: inteligente (impacta qualidade da resposta)
INTENT_MODEL = os.getenv("OPENAI_INTENT_MODEL", "gpt-5.4-mini")

# ── Modelo Vision (análise de imagens) ─────────────────────────────────────
# Tarefa: analisar imagens enviadas pelo user
# Requisitos: suporte a vision/multimodal
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-5.4-mini")
