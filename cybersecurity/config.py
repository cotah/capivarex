"""CyberSecurity Bot configuration — all constants, env vars, thresholds."""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = PROJECT_ROOT / "capivarex-backend"
FRONTEND_ROOT = PROJECT_ROOT / "capivarex-frontend"
ADMIN_FRONTEND_ROOT = PROJECT_ROOT / "capivarex-admin-frontend"

# ---------------------------------------------------------------------------
# Scanner intervals (seconds)
# ---------------------------------------------------------------------------
FAST_SCAN_INTERVAL = 300  # 5 minutes
MEDIUM_SCAN_INTERVAL = 1800  # 30 minutes
SLOW_SCAN_INTERVAL = 21600  # 6 hours

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------
ALERT_THRESHOLD = 0.5  # Alert admin when confidence >= this
AUTOFIX_SUGGEST_THRESHOLD = 0.7  # Create autofix ticket when >= this
AUTOFIX_AUTO_THRESHOLD = 0.9  # Auto-fix without approval (Phase 2)
AUTO_FIX_ENABLED = os.getenv("CYBER_AUTO_FIX_ENABLED", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------
ALERT_SEVERITIES = {"high", "critical"}
DIGEST_DAY = 0  # Monday
DIGEST_HOUR = 9  # 09:00 UTC
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Fuzzer safety
# ---------------------------------------------------------------------------
FUZZER_ENABLED = os.getenv("CYBER_FUZZER_ENABLED", "false").lower() == "true"
FUZZER_TARGET_HOST = os.getenv("CYBER_FUZZER_TARGET", "http://localhost:8000")
FUZZER_SAFE_MODE = True

# ---------------------------------------------------------------------------
# Sentry API (for runtime monitor)
# ---------------------------------------------------------------------------
SENTRY_AUTH_TOKEN = os.getenv("SENTRY_AUTH_TOKEN", "")
SENTRY_ORG = os.getenv("SENTRY_ORG", "")
SENTRY_PROJECT = os.getenv("SENTRY_PROJECT", "")

# ---------------------------------------------------------------------------
# LLM API Keys (separate from service keys — admin/security only)
# ---------------------------------------------------------------------------
CYBER_OPENAI_API_KEY = os.getenv("CYBER_OPENAI_API_KEY", "")
CYBER_ANTHROPIC_API_KEY = os.getenv("CYBER_ANTHROPIC_API_KEY", "")

# LLM Models
CYBER_TRIAGE_MODEL = "gpt-4o-mini"  # Fast + cheap for triaging findings
CYBER_PATCH_MODEL = "claude-sonnet-4-5-20250514"  # Best for code analysis + patches

# LLM feature toggle — graceful degradation if no keys
LLM_TRIAGE_ENABLED = bool(CYBER_OPENAI_API_KEY)
LLM_PATCH_ENABLED = bool(CYBER_ANTHROPIC_API_KEY)

# ---------------------------------------------------------------------------
# RAG settings
# ---------------------------------------------------------------------------
KNOWLEDGE_SIMILARITY_THRESHOLD = 0.7
KNOWLEDGE_MAX_RESULTS = 10

# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------
EXCLUDED_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    ".next",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "workspace",
    "cybersecurity/migrations",
}
PYTHON_EXTENSIONS = {".py"}
TYPESCRIPT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}
ALL_CODE_EXTENSIONS = PYTHON_EXTENSIONS | TYPESCRIPT_EXTENSIONS

# ---------------------------------------------------------------------------
# Severity emoji (for Telegram alerts)
# ---------------------------------------------------------------------------
SEVERITY_EMOJI = {
    "critical": "\u2620\ufe0f",  # skull
    "high": "\ud83d\udd34",  # red circle
    "medium": "\u26a0\ufe0f",  # warning
    "low": "\u2139\ufe0f",  # info
    "info": "\ud83d\udcac",  # speech bubble
}
