"""
Claude client for DEV Agent.

Provides:
- Claude API wrapper
- DEV mode (proposes actions)
- STRICT mode (enforced valid JSON)
- EXPLAIN mode (explanations only, no actions)
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("unbx_bot.dev.claude_client")

try:
    from anthropic import Anthropic

    claude_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
except Exception as e:
    logger.error(f"Failed to initialize Claude client: {e}")
    claude_client = None


def _claude_text(resp) -> str:
    """
    Extract text from Claude response.

    Args:
        resp: Claude API response

    Returns:
        Extracted text content
    """
    try:
        out_parts = []
        for blk in getattr(resp, "content", []) or []:
            if hasattr(blk, "text") and blk.text:
                out_parts.append(blk.text)
        return "\n".join(out_parts).strip()
    except Exception:
        return ""


def claude_dev_call(
    task: str,
    context: str = "",
    log_usage_fn: Optional[callable] = None,
    record_exception_fn: Optional[callable] = None,
    tenant_id: str = "local-dev",
    user_id: str = "unknown",
) -> str:
    """
    Call Claude as DEV Agent (proposes actions with ACTIONS_JSON).

    Args:
        task: Development task description
        context: Additional context (git status, files, etc.)
        log_usage_fn: Optional function to log API usage
        record_exception_fn: Optional function to record exceptions
        tenant_id: Tenant ID for logging
        user_id: User ID for logging

    Returns:
        Claude response with PLAN + ACTIONS_JSON
    """
    if not claude_client:
        return "ERROR: Claude client not available (check ANTHROPIC_API_KEY)"

    model_id = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5-20251101")

    system = (
        "Você é o DEV AGENT do UNBX-BOT (engenheiro sênior).\n"
        "REGRAS OBRIGATÓRIAS:\n"
        "- Você NÃO executa comandos.\n"
        "- Você SEMPRE retorna:\n"
        "  1) PLANO curto (bullets)\n"
        "  2) ACTIONS_JSON dentro de UM ÚNICO bloco ```json ... ```\n"
        '- ACTIONS_JSON deve conter {"actions": [...]}.\n'
        "- Cada action DEVE ter: type, path, e (quando aplicável) content/find/replace.\n"
        "- Tipos válidos: create_file, overwrite_file, append_file, replace_in_file.\n"
        "- Se precisar escrever arquivo, use overwrite_file.\n"
        "\n"
        "PROIBIÇÕES:\n"
        "- NUNCA repita o bloco ```json mais de uma vez.\n"
        "- NUNCA duplique chaves ou linhas dentro do JSON.\n"
        "- NUNCA deixe JSON incompleto ou mal-formado.\n"
        "- O JSON DEVE começar com { e terminar com } (sem texto extra dentro).\n"
    )

    user_msg = f"TAREFA:\n{task}\n\nCONTEXTO:\n{context}".strip()

    try:
        resp = claude_client.messages.create(
            model=model_id,
            max_tokens=1800,
            temperature=0.2,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )

        # Extract tokens
        tokens_in = None
        tokens_out = None
        if hasattr(resp, "usage") and resp.usage:
            tokens_in = getattr(resp.usage, "input_tokens", None)
            tokens_out = getattr(resp.usage, "output_tokens", None)

        # Log usage
        if log_usage_fn:
            log_usage_fn(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                kind="dev",
                status="ok",
                model=model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                meta={"command": "/dev"},
            )

        out = _claude_text(resp)
        return out if out else "ERROR: Claude returned empty response"

    except Exception as e:
        logger.error(f"Claude DEV call failed: {e}")

        # Log error
        if log_usage_fn:
            log_usage_fn(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                kind="dev",
                status="err",
                model=model_id,
                meta={"error_type": type(e).__name__, "message": str(e)[:200]},
            )

        # Record exception
        if record_exception_fn:
            record_exception_fn(
                chat_id="bot_main",
                text=f"claude_dev_call task={task[:200]}",
                error=e,
                tenant_id=tenant_id,
                user_id=user_id,
            )

        return f"ERROR: {e}"


def claude_dev_strict_call(
    task: str,
    context: str = "",
    log_usage_fn: Optional[callable] = None,
    record_exception_fn: Optional[callable] = None,
    tenant_id: str = "local-dev",
    user_id: str = "unknown",
) -> str:
    """
    Call Claude in STRICT mode (enforces valid ACTIONS_JSON).

    Args:
        task: Development task description
        context: Additional context
        log_usage_fn: Optional function to log API usage
        record_exception_fn: Optional function to record exceptions
        tenant_id: Tenant ID for logging
        user_id: User ID for logging

    Returns:
        Claude response with enforced valid ACTIONS_JSON
    """
    if not claude_client:
        return "ERROR: Claude client not available (check ANTHROPIC_API_KEY)"

    model_id = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5-20251101")

    system = (
        "Você é o DEV AGENT STRICT do UNBX-BOT.\n"
        "FORMATO OBRIGATÓRIO (sem texto fora disso):\n\n"
        "RESUMO:\n"
        "- (máx 5 linhas)\n\n"
        "ACTIONS_JSON:\n"
        "```json\n"
        "{\n"
        '  "actions": [\n'
        '    {"type":"overwrite_file","path":"workspace/exemplo.txt","content":"ok"}\n'
        "  ]\n"
        "}\n"
        "```\n\n"
        "REGRAS CRÍTICAS:\n"
        "- JSON DEVE ser válido e bem-formado.\n"
        "- JSON começa com { e termina com }.\n"
        "- Sempre feche o bloco ```json com ```.\n"
        "- Cada action DEVE ter: type, path.\n"
        "- Tipos: create_file, overwrite_file, append_file, replace_in_file.\n"
        "- Para replace_in_file: inclua find e replace.\n"
        "\n"
        "PROIBIÇÕES ABSOLUTAS:\n"
        "- NUNCA escreva mais de UM bloco ```json.\n"
        "- NUNCA duplique chaves ou repita linhas.\n"
        "- NUNCA deixe JSON truncado ou incompleto.\n"
    )

    user_msg = f"TAREFA:\n{task}\n\nCONTEXTO:\n{context}".strip()

    try:
        resp = claude_client.messages.create(
            model=model_id,
            max_tokens=1800,
            temperature=0.2,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )

        # Extract tokens
        tokens_in = None
        tokens_out = None
        if hasattr(resp, "usage") and resp.usage:
            tokens_in = getattr(resp.usage, "input_tokens", None)
            tokens_out = getattr(resp.usage, "output_tokens", None)

        # Log usage
        if log_usage_fn:
            log_usage_fn(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                kind="dev",
                status="ok",
                model=model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                meta={"command": "/dev_strict"},
            )

        out = _claude_text(resp)
        return out if out else "ERROR: Claude returned empty response"

    except Exception as e:
        logger.error(f"Claude DEV STRICT call failed: {e}")

        # Log error
        if log_usage_fn:
            log_usage_fn(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                kind="dev",
                status="err",
                model=model_id,
                meta={"error_type": type(e).__name__, "message": str(e)[:200]},
            )

        # Record exception
        if record_exception_fn:
            record_exception_fn(
                chat_id="bot_main",
                text=f"claude_dev_strict_call task={task[:200]}",
                error=e,
                tenant_id=tenant_id,
                user_id=user_id,
            )

        return f"ERROR: {e}"


def claude_dev_explain_call(
    task: str,
    context: str = "",
    log_usage_fn: Optional[callable] = None,
    record_exception_fn: Optional[callable] = None,
    tenant_id: str = "local-dev",
    user_id: str = "unknown",
) -> str:
    """
    Call Claude in EXPLAIN mode (explanations only, no actions).

    Args:
        task: Question or topic to explain
        context: Additional context
        log_usage_fn: Optional function to log API usage
        record_exception_fn: Optional function to record exceptions
        tenant_id: Tenant ID for logging
        user_id: User ID for logging

    Returns:
        Claude explanation (no ACTIONS_JSON)
    """
    if not claude_client:
        return "ERROR: Claude client not available (check ANTHROPIC_API_KEY)"

    model_id = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5-20251101")

    system = (
        "Você é o DEV AGENT EXPLAIN do UNBX-BOT.\n"
        "MODO: APENAS EXPLICAÇÕES\n"
        "\n"
        "REGRAS:\n"
        "- Você NUNCA gera ACTIONS_JSON.\n"
        "- Você NUNCA gera blocos ```json.\n"
        "- Você APENAS explica conceitos técnicos de forma clara.\n"
        "- Use exemplos de código quando útil (mas não como ações).\n"
        "- Seja didático e completo.\n"
    )

    user_msg = f"PERGUNTA:\n{task}\n\nCONTEXTO:\n{context}".strip()

    try:
        resp = claude_client.messages.create(
            model=model_id,
            max_tokens=2000,
            temperature=0.3,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )

        # Extract tokens
        tokens_in = None
        tokens_out = None
        if hasattr(resp, "usage") and resp.usage:
            tokens_in = getattr(resp.usage, "input_tokens", None)
            tokens_out = getattr(resp.usage, "output_tokens", None)

        # Log usage
        if log_usage_fn:
            log_usage_fn(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                kind="dev",
                status="ok",
                model=model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                meta={"command": "/dev_explain"},
            )

        out = _claude_text(resp)
        return out if out else "ERROR: Claude returned empty response"

    except Exception as e:
        logger.error(f"Claude DEV EXPLAIN call failed: {e}")

        # Log error
        if log_usage_fn:
            log_usage_fn(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                kind="dev",
                status="err",
                model=model_id,
                meta={"error_type": type(e).__name__, "message": str(e)[:200]},
            )

        # Record exception
        if record_exception_fn:
            record_exception_fn(
                chat_id="bot_main",
                text=f"claude_dev_explain_call task={task[:200]}",
                error=e,
                tenant_id=tenant_id,
                user_id=user_id,
            )

        return f"ERROR: {e}"


def is_claude_available() -> bool:
    """Check if Claude client is available."""
    return claude_client is not None
