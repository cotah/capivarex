"""Confidence Scorer — adjusts finding confidence using RAG + LLM triage.

Scoring pipeline:
1. RAG: Check knowledge base for similar true/false positives
2. LLM: Ask GPT-4o-mini to triage the finding (is this real? confidence?)
3. Combine adjustments into final confidence score

The LLM triage uses CYBER_OPENAI_API_KEY (separate from service key).
If the key is not set, falls back to RAG-only scoring (graceful degradation).
"""

from __future__ import annotations

import json
import logging

from cybersecurity.engine.finding import SecurityFinding

logger = logging.getLogger("cybersecurity.confidence_scorer")

# Adjustment weights
_TRUE_POSITIVE_BOOST = 0.1     # Max boost from similar true positives
_FALSE_POSITIVE_PENALTY = 0.15  # Max penalty from similar false positives
_KNOWN_FIX_BOOST = 0.05        # Boost when a known fix exists
_LLM_MAX_ADJUSTMENT = 0.2      # Max confidence change from LLM triage

# Auto-fix eligibility thresholds
_AUTO_FIX_MIN_OCCURRENCES = 10
_AUTO_FIX_MIN_TP_RATE = 0.95
_AUTO_FIX_MIN_FIX_RATE = 0.90

# LLM client singleton
_openai_client = None


def _get_llm_client():
    """Get OpenAI client using CYBER-specific API key."""
    global _openai_client
    if _openai_client is None:
        from cybersecurity.config import CYBER_OPENAI_API_KEY
        if not CYBER_OPENAI_API_KEY:
            return None
        try:
            from openai import AsyncOpenAI
            _openai_client = AsyncOpenAI(api_key=CYBER_OPENAI_API_KEY)
        except ImportError:
            logger.warning("openai package not installed — LLM triage disabled")
    return _openai_client


# ---------------------------------------------------------------------------
# LLM Triage
# ---------------------------------------------------------------------------

_TRIAGE_SYSTEM_PROMPT = """You are a senior cybersecurity analyst triaging security findings.

Given a security finding with its code context, determine:
1. Is this a TRUE vulnerability or a FALSE POSITIVE?
2. How confident are you? (0.0 to 1.0)
3. Brief reasoning (1 sentence)

Consider:
- Is the code in a test file, example, or mock? → likely false positive
- Is the "secret" actually an env var reference or placeholder? → false positive
- Is the dangerous function called with hardcoded safe input? → likely false positive
- Is user input flowing into the dangerous operation? → true positive
- Is there proper validation/sanitization before the operation? → lower risk

Respond ONLY with valid JSON:
{"is_true_positive": true/false, "confidence": 0.0-1.0, "reasoning": "..."}"""


async def _llm_triage(finding: SecurityFinding) -> dict | None:
    """Ask GPT-4o-mini to triage a finding. Returns dict or None on failure."""
    client = _get_llm_client()
    if not client:
        return None

    from cybersecurity.config import CYBER_TRIAGE_MODEL

    # Build context for the LLM
    context_parts = [
        f"Scanner: {finding.scanner}",
        f"Type: {finding.finding_type}",
        f"Severity: {finding.severity}",
        f"Title: {finding.title}",
    ]
    if finding.description:
        context_parts.append(f"Description: {finding.description}")
    if finding.file_path:
        context_parts.append(f"File: {finding.file_path}")
        if finding.line_number:
            context_parts[-1] += f":{finding.line_number}"
    if finding.code_snippet:
        context_parts.append(f"Code:\n```\n{finding.code_snippet}\n```")
    if finding.owasp_category:
        context_parts.append(f"OWASP: {finding.owasp_category}")

    user_msg = "\n".join(context_parts)

    try:
        response = await client.chat.completions.create(
            model=CYBER_TRIAGE_MODEL,
            messages=[
                {"role": "system", "content": _TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""
        result = json.loads(content)

        # Validate response structure
        if "is_true_positive" in result and "confidence" in result:
            logger.info(
                "LLM triage: %s (conf=%.2f) — %s",
                "TRUE_POSITIVE" if result["is_true_positive"] else "FALSE_POSITIVE",
                result["confidence"],
                result.get("reasoning", "")[:80],
            )
            return result
    except json.JSONDecodeError:
        logger.debug("LLM returned invalid JSON")
    except Exception:
        logger.debug("LLM triage failed — falling back to RAG-only")

    return None


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


async def score_finding(finding: SecurityFinding) -> float:
    """Adjust confidence score using RAG knowledge base + LLM triage.

    Pipeline:
    1. Start with scanner's base confidence
    2. Adjust based on RAG (similar findings, false positives, known fixes)
    3. Adjust based on LLM triage (if enabled)
    4. Clamp to [0.0, 1.0]
    """
    base_confidence = finding.confidence
    rag_adjustment = 0.0
    llm_adjustment = 0.0

    # --- Step 1: RAG-based adjustments ---
    try:
        from cybersecurity.intelligence.knowledge_base import (
            search_false_positives,
            search_similar_findings,
            search_similar_fixes,
        )

        query = f"{finding.title} {finding.description or ''} {finding.finding_type}"

        # Check for similar true positive findings
        similar_findings = await search_similar_findings(query, limit=3)
        if similar_findings:
            avg_similarity = sum(f.get("similarity", 0) for f in similar_findings) / len(similar_findings)
            rag_adjustment += avg_similarity * _TRUE_POSITIVE_BOOST

        # Check for similar false positives
        similar_fps = await search_false_positives(query, limit=3)
        if similar_fps:
            avg_similarity = sum(f.get("similarity", 0) for f in similar_fps) / len(similar_fps)
            rag_adjustment -= avg_similarity * _FALSE_POSITIVE_PENALTY

        # Check for known fix patterns
        if not finding.suggested_fix:
            similar_fixes = await search_similar_fixes(query, limit=1)
            if similar_fixes:
                fix_content = similar_fixes[0].get("content", "")
                if fix_content:
                    finding.suggested_fix = _extract_fix_from_content(fix_content)
                    rag_adjustment += _KNOWN_FIX_BOOST

    except Exception:
        logger.debug("RAG scoring failed — continuing with LLM")

    # --- Step 2: LLM triage (only for high/critical or uncertain findings) ---
    from cybersecurity.config import LLM_TRIAGE_ENABLED

    should_triage = LLM_TRIAGE_ENABLED and (
        finding.severity in {"high", "critical"}
        or (0.4 <= base_confidence <= 0.7)  # Uncertain range — LLM helps most here
    )

    if should_triage:
        triage = await _llm_triage(finding)
        if triage:
            llm_confidence = triage.get("confidence", base_confidence)
            is_tp = triage.get("is_true_positive", True)

            if is_tp:
                # LLM says true positive — boost toward LLM's confidence
                llm_adjustment = min(
                    (llm_confidence - base_confidence) * 0.5,
                    _LLM_MAX_ADJUSTMENT,
                )
            else:
                # LLM says false positive — reduce confidence
                llm_adjustment = max(
                    -(base_confidence * 0.4),
                    -_LLM_MAX_ADJUSTMENT,
                )

            # Store LLM reasoning in metadata for transparency
            finding.metadata["llm_triage"] = {
                "is_true_positive": is_tp,
                "llm_confidence": llm_confidence,
                "reasoning": triage.get("reasoning", ""),
            }

    # --- Combine ---
    total_adjustment = rag_adjustment + llm_adjustment
    final = max(0.0, min(1.0, base_confidence + total_adjustment))

    if total_adjustment != 0:
        logger.info(
            "Confidence: %.2f → %.2f (rag=%+.3f, llm=%+.3f) for: %s",
            base_confidence, final, rag_adjustment, llm_adjustment,
            finding.title[:60],
        )

    return final


# ---------------------------------------------------------------------------
# Auto-fix eligibility
# ---------------------------------------------------------------------------


async def is_auto_fix_eligible(finding_type: str) -> bool:
    """Check if a finding type has enough history for autonomous auto-fix."""
    try:
        from cybersecurity.intelligence.knowledge_base import get_finding_type_stats
        stats = await get_finding_type_stats(finding_type)

        eligible = (
            stats["total"] >= _AUTO_FIX_MIN_OCCURRENCES
            and stats.get("true_positive_rate", 0) >= _AUTO_FIX_MIN_TP_RATE
            and stats.get("fix_success_rate", 0) >= _AUTO_FIX_MIN_FIX_RATE
        )

        if eligible:
            logger.info(
                "Finding type '%s' is auto-fix eligible: %d occurrences, TP=%.1f%%, Fix=%.1f%%",
                finding_type, stats["total"],
                stats.get("true_positive_rate", 0) * 100,
                stats.get("fix_success_rate", 0) * 100,
            )

        return eligible
    except Exception:
        return False


def _extract_fix_from_content(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("Resolution:"):
            return line.replace("Resolution:", "").strip()
    return content[:300]
