"""Remediation Engine — generates fix suggestions using templates + Claude LLM.

Pipeline:
1. RAG knowledge base (similar past fixes)
2. Claude LLM (reads actual code, generates precise patch) — CYBER_ANTHROPIC_API_KEY
3. Template-based suggestion (fallback)
4. Scanner's own suggested_fix (last resort)

The LLM patch generation uses CYBER_ANTHROPIC_API_KEY (separate from service key).
If the key is not set, falls back to templates (graceful degradation).
"""

from __future__ import annotations

import logging

from cybersecurity.engine.finding import SecurityFinding

logger = logging.getLogger("cybersecurity.remediation_engine")

# ---------------------------------------------------------------------------
# Fix suggestion templates (by finding_type)
# ---------------------------------------------------------------------------

_FIX_TEMPLATES: dict[str, str] = {
    "hardcoded_secret": (
        "1. Mover o secret para variavel de ambiente (.env)\n"
        "2. Usar os.getenv('NOME_DA_VAR') no codigo\n"
        "3. Adicionar .env ao .gitignore\n"
        "4. Rotacionar o secret comprometido"
    ),
    "sql_injection": (
        "1. Usar queries parametrizadas (placeholders)\n"
        "2. Nunca concatenar input do usuario em SQL\n"
        "3. Exemplo: cursor.execute('SELECT * FROM t WHERE id = %s', (user_id,))"
    ),
    "command_injection": (
        "1. Usar subprocess com lista de argumentos (sem shell=True)\n"
        "2. Validar e sanitizar todo input antes de passar ao subprocess\n"
        "3. Exemplo: subprocess.run(['cmd', arg1, arg2], shell=False)"
    ),
    "xss_risk": (
        "1. Usar sanitizacao de HTML (DOMPurify no frontend)\n"
        "2. Nunca usar dangerouslySetInnerHTML com input do usuario\n"
        "3. Usar react-markdown ou similar para renderizar conteudo"
    ),
    "vulnerable_dependency": (
        "1. Atualizar pacote para versao corrigida\n"
        "2. Rodar pip-audit / npm audit para verificar\n"
        "3. Testar a aplicacao apos atualizar"
    ),
    "missing_jwt_secret": (
        '1. Gerar secret seguro: python -c "import secrets; print(secrets.token_hex(32))"\n'
        "2. Adicionar JWT_SECRET_KEY=<secret> ao .env\n"
        "3. Validar no startup que a key nao esta vazia"
    ),
    "cors_wildcard_headers": (
        "1. Substituir allow_headers=['*'] por lista explicita\n"
        "2. Exemplo: allow_headers=['Content-Type', 'Authorization']\n"
        "3. Testar que o frontend continua funcionando"
    ),
    "env_file_committed": (
        "1. Remover do git: git rm --cached .env\n"
        "2. Adicionar ao .gitignore: echo '.env' >> .gitignore\n"
        "3. Rotacionar TODOS os secrets que estavam no arquivo"
    ),
    "brute_force_detected": (
        "1. Bloquear IP temporariamente (rate limit mais agressivo)\n"
        "2. Verificar se alguma conta foi comprometida\n"
        "3. Considerar implementar CAPTCHA no login\n"
        "4. Adicionar delay progressivo em tentativas falhas"
    ),
}

# ---------------------------------------------------------------------------
# Claude LLM client singleton
# ---------------------------------------------------------------------------

_anthropic_client = None


def _get_claude_client():
    """Get Anthropic client using CYBER-specific API key."""
    global _anthropic_client
    if _anthropic_client is None:
        from cybersecurity.config import CYBER_ANTHROPIC_API_KEY

        if not CYBER_ANTHROPIC_API_KEY:
            return None
        try:
            from anthropic import AsyncAnthropic

            _anthropic_client = AsyncAnthropic(api_key=CYBER_ANTHROPIC_API_KEY)
        except ImportError:
            logger.warning("anthropic package not installed — LLM patch gen disabled")
    return _anthropic_client


# ---------------------------------------------------------------------------
# Claude patch generation
# ---------------------------------------------------------------------------

_PATCH_SYSTEM_PROMPT = """You are an elite cybersecurity engineer generating precise code fixes.

Given a security vulnerability with its file path, line number, and code context, generate:
1. A clear explanation of WHY this is a vulnerability
2. The EXACT code fix (show before → after)
3. Any additional steps needed (env vars, config changes, etc.)

Rules:
- Be precise and specific to THIS code, not generic advice
- Show the minimal change needed — don't refactor unrelated code
- If you need more context to generate a safe fix, say so
- Always consider backwards compatibility
- Write in Portuguese (the team's language)

Format your response as:
## Problema
[Why this is vulnerable]

## Fix
```python
# Before (vulnerable):
[old code]

# After (fixed):
[new code]
```

## Passos Adicionais
[Any extra steps, or "Nenhum" if not needed]"""


async def _generate_llm_patch(finding: SecurityFinding) -> str | None:
    """Use Claude to generate a precise code fix for the finding."""
    client = _get_claude_client()
    if not client:
        return None

    from cybersecurity.config import CYBER_PATCH_MODEL, BACKEND_ROOT, FRONTEND_ROOT

    # Try to read the actual source file for full context
    source_context = ""
    if finding.file_path and finding.line_number:
        for root in (BACKEND_ROOT, FRONTEND_ROOT):
            full_path = root.parent / finding.file_path
            if full_path.exists():
                try:
                    lines = full_path.read_text(
                        encoding="utf-8", errors="ignore"
                    ).splitlines()
                    start = max(0, finding.line_number - 10)
                    end = min(len(lines), finding.line_number + 10)
                    numbered = [
                        f"{'→' if i + 1 == finding.line_number else ' '} {i + 1:4d} | {line}"
                        for i, line in enumerate(lines[start:end], start=start)
                    ]
                    source_context = (
                        f"\nSource code ({finding.file_path}, lines {start + 1}-{end}):\n```\n"
                        + "\n".join(numbered)
                        + "\n```"
                    )
                except OSError:
                    pass
                break

    # Build prompt
    user_msg_parts = [
        f"Vulnerability: {finding.title}",
        f"Type: {finding.finding_type}",
        f"Severity: {finding.severity}",
        f"File: {finding.file_path or 'unknown'}",
    ]
    if finding.line_number:
        user_msg_parts.append(f"Line: {finding.line_number}")
    if finding.owasp_category:
        user_msg_parts.append(f"OWASP: {finding.owasp_category}")
    if finding.description:
        user_msg_parts.append(f"Description: {finding.description}")
    if finding.code_snippet:
        user_msg_parts.append(f"Code snippet: `{finding.code_snippet}`")
    if source_context:
        user_msg_parts.append(source_context)

    user_msg = "\n".join(user_msg_parts)

    try:
        response = await client.messages.create(
            model=CYBER_PATCH_MODEL,
            max_tokens=1000,
            messages=[
                {"role": "user", "content": user_msg},
            ],
            system=_PATCH_SYSTEM_PROMPT,
            temperature=0.2,
        )

        content = response.content[0].text if response.content else ""
        if content:
            logger.info(
                "Claude generated patch for: %s (%d chars)",
                finding.title[:60],
                len(content),
            )
            return content
    except Exception:
        logger.debug("Claude patch generation failed")

    return None


# ---------------------------------------------------------------------------
# Fix suggestion (main entry point)
# ---------------------------------------------------------------------------


async def suggest_fix(finding: SecurityFinding) -> str | None:
    """Generate a fix suggestion for a finding.

    Priority:
    1. RAG knowledge base (similar past fixes)
    2. Claude LLM (reads actual code, generates precise patch)
    3. Template-based suggestion
    4. Scanner's own suggested_fix
    """
    # 1. Try knowledge base first
    try:
        from cybersecurity.intelligence.knowledge_base import search_similar_fixes

        similar_fixes = await search_similar_fixes(
            f"{finding.title} {finding.finding_type}", limit=1
        )
        if similar_fixes and similar_fixes[0].get("similarity", 0) > 0.8:
            content = similar_fixes[0].get("content", "")
            for line in content.splitlines():
                if line.startswith("Resolution:"):
                    fix = line.replace("Resolution:", "").strip()
                    if fix:
                        logger.debug("Fix from knowledge base: %s", fix[:60])
                        return fix
    except Exception:
        pass

    # 2. Claude LLM for high/critical findings with code context
    from cybersecurity.config import LLM_PATCH_ENABLED

    should_use_llm = LLM_PATCH_ENABLED and (
        finding.severity in {"high", "critical"}
        and finding.file_path
        and finding.line_number
    )

    if should_use_llm:
        llm_fix = await _generate_llm_patch(finding)
        if llm_fix:
            finding.metadata["llm_patch"] = True
            return llm_fix

    # 3. Template-based
    template = _FIX_TEMPLATES.get(finding.finding_type)
    if template:
        return template

    # 4. Scanner's own suggestion
    return finding.suggested_fix


# ---------------------------------------------------------------------------
# Auto-remediation (Phase 2)
# ---------------------------------------------------------------------------


async def auto_remediate(finding: SecurityFinding) -> bool:
    """Attempt to automatically fix a finding.

    Only runs when:
    - AUTO_FIX_ENABLED is True in config
    - Finding type is eligible (enough historical data)
    - Confidence >= AUTOFIX_AUTO_THRESHOLD

    Returns True if fix was applied, False otherwise.
    """
    from cybersecurity.config import AUTO_FIX_ENABLED, AUTOFIX_AUTO_THRESHOLD

    if not AUTO_FIX_ENABLED:
        return False

    if finding.confidence < AUTOFIX_AUTO_THRESHOLD:
        return False

    # Check eligibility
    try:
        from cybersecurity.intelligence.confidence_scorer import is_auto_fix_eligible

        eligible = await is_auto_fix_eligible(finding.finding_type)
        if not eligible:
            logger.debug(
                "Finding type '%s' not eligible for auto-fix",
                finding.finding_type,
            )
            return False
    except Exception:
        return False

    # Create autofix ticket and PR
    try:
        from cybersecurity.integrations.autofix_bridge import create_ticket_from_finding

        ticket = await create_ticket_from_finding(finding)

        if ticket:
            # Notify admin after the fact
            from cybersecurity.integrations.notification_bridge import alert_finding

            finding.metadata["auto_fixed"] = True
            await alert_finding(finding)

            # Store success in knowledge base
            from cybersecurity.intelligence.knowledge_base import store_resolution

            await store_resolution(
                finding_id=ticket.get("id", ""),
                resolution=f"Auto-fixed: {finding.suggested_fix or 'automated patch'}",
                was_true_positive=True,
                finding_title=finding.title,
                tags=[finding.finding_type, "auto_fix"],
            )

            logger.info("Auto-remediated: %s", finding.title[:60])
            return True
    except Exception:
        logger.exception("Auto-remediation failed for: %s", finding.title[:60])

    return False
