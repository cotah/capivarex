"""Secret Scanner — detects leaked secrets in code and git history."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from cybersecurity.config import (
    ADMIN_FRONTEND_ROOT,
    ALL_CODE_EXTENSIONS,
    BACKEND_ROOT,
    EXCLUDED_DIRS,
    FRONTEND_ROOT,
)
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner

# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    # pattern, finding_type, title, severity
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "aws_access_key",
        "AWS Access Key ID encontrada no codigo",
        "critical",
    ),
    (
        re.compile(
            r"(?:aws_secret|AWS_SECRET)[_A-Z]*\s*=\s*['\"][A-Za-z0-9/+=]{30,}['\"]"
        ),
        "aws_secret_key",
        "AWS Secret Key encontrada no codigo",
        "critical",
    ),
    (
        re.compile(r"sk-[a-zA-Z0-9]{20,}"),
        "openai_api_key",
        "OpenAI API Key encontrada no codigo",
        "critical",
    ),
    (
        re.compile(r"sk-ant-[a-zA-Z0-9\-]{20,}"),
        "anthropic_api_key",
        "Anthropic API Key encontrada no codigo",
        "critical",
    ),
    (
        re.compile(r"ghp_[a-zA-Z0-9]{36}"),
        "github_token",
        "GitHub Personal Access Token encontrado",
        "critical",
    ),
    (
        re.compile(r"gho_[a-zA-Z0-9]{36}"),
        "github_oauth_token",
        "GitHub OAuth Token encontrado",
        "critical",
    ),
    (
        re.compile(r"xoxb-[0-9]{10,}-[0-9]{10,}-[a-zA-Z0-9]{24,}"),
        "slack_bot_token",
        "Slack Bot Token encontrado",
        "critical",
    ),
    (
        re.compile(r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH)?\s*PRIVATE\s+KEY-----"),
        "private_key",
        "Private key encontrada no codigo",
        "critical",
    ),
    (
        re.compile(r"(?:postgres|mysql|mongodb)://[^:]+:[^@]+@[^\s'\"]+"),
        "database_url_with_password",
        "Database connection string com password",
        "high",
    ),
    (
        re.compile(
            r"(?:sendgrid|twilio|stripe)[_.](?:api[_.])?(?:key|token|secret)\s*=\s*['\"][a-zA-Z0-9_\-.]{20,}['\"]",
            re.I,
        ),
        "service_api_key",
        "API key de servico externo hardcoded",
        "high",
    ),
    (
        re.compile(r"Bearer\s+[a-zA-Z0-9_\-.]{20,}"),
        "bearer_token",
        "Bearer token hardcoded",
        "high",
    ),
    (
        re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),
        "jwt_token",
        "JWT token hardcoded no codigo",
        "high",
    ),
]

# Files to always skip
_SKIP_FILES = {
    ".env.example",
    ".env.prod.example",
    "package-lock.json",
    "requirements.txt",
    "poetry.lock",
    "yarn.lock",
}

_SKIP_EXTENSIONS = {".map", ".min.js", ".min.css", ".svg", ".png", ".jpg", ".ico"}


def _should_scan(path: Path) -> bool:
    if path.name in _SKIP_FILES:
        return False
    if path.suffix in _SKIP_EXTENSIONS:
        return False
    if any(ex in path.parts for ex in EXCLUDED_DIRS):
        return False
    # Only scan code files + config files
    return path.suffix in ALL_CODE_EXTENSIONS or path.suffix in {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".cfg",
        ".ini",
        ".env",
    }


class SecretScanner(BaseScanner):
    name = "secret_scanner"
    schedule = "medium"

    async def scan(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []

        # Scan current files
        for root in (BACKEND_ROOT, FRONTEND_ROOT, ADMIN_FRONTEND_ROOT):
            if not root.exists():
                continue
            for fpath in root.rglob("*"):
                if not fpath.is_file() or not _should_scan(fpath):
                    continue
                findings.extend(self._scan_file(fpath))

        # Scan for .env files committed to git
        findings.extend(self._scan_committed_env_files())

        return findings

    def _scan_file(self, fpath: Path) -> list[SecurityFinding]:
        results: list[SecurityFinding] = []
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return results

        # Skip test/example/fixture files
        rel = str(fpath)
        lower_rel = rel.lower()
        if any(
            skip in lower_rel
            for skip in ("test", "example", "fixture", "mock", "conftest")
        ):
            return results

        lines = content.splitlines()
        for pattern, ftype, title, severity in _SECRET_PATTERNS:
            for m in pattern.finditer(content):
                lineno = content[: m.start()].count("\n") + 1
                line_text = lines[lineno - 1].strip() if lineno <= len(lines) else ""

                # Skip comments
                stripped = line_text.lstrip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue

                # Skip env var references (os.getenv, process.env)
                if (
                    "getenv" in line_text
                    or "process.env" in line_text
                    or "os.environ" in line_text
                ):
                    continue

                try:
                    rel_path = str(fpath.relative_to(fpath.parents[2]))
                except (ValueError, IndexError):
                    rel_path = str(fpath)

                # Redact the actual secret in the snippet
                redacted = _redact_secret(line_text, m.group())

                results.append(
                    SecurityFinding(
                        scanner=self.name,
                        finding_type=ftype,
                        severity=severity,
                        confidence=0.8,
                        title=title,
                        description=f"Secret detectado em {rel_path}:{lineno}",
                        file_path=rel_path,
                        line_number=lineno,
                        code_snippet=redacted[:200],
                        suggested_fix="Mover para variavel de ambiente (.env) e usar os.getenv()",
                        owasp_category="A07:2021-Security Misconfiguration",
                    )
                )
        return results

    def _scan_committed_env_files(self) -> list[SecurityFinding]:
        """Check if .env files are tracked by git."""
        findings: list[SecurityFinding] = []
        for root in (BACKEND_ROOT, FRONTEND_ROOT, ADMIN_FRONTEND_ROOT):
            if not (root / ".git").exists():
                continue
            try:
                result = subprocess.run(
                    ["git", "ls-files", "--cached", "*.env", ".env*"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                for line in result.stdout.strip().splitlines():
                    name = line.strip()
                    if name and not name.endswith(".example"):
                        findings.append(
                            SecurityFinding(
                                scanner=self.name,
                                finding_type="env_file_committed",
                                severity="critical",
                                confidence=0.95,
                                title=f"Arquivo .env commitado no git: {name}",
                                description="Arquivos .env com secrets NAO devem ser commitados",
                                file_path=name,
                                suggested_fix="Adicionar ao .gitignore e remover do git: git rm --cached "
                                + name,
                                owasp_category="A07:2021-Security Misconfiguration",
                            )
                        )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return findings


def _redact_secret(line: str, secret: str) -> str:
    """Replace the secret value with [REDACTED] in the snippet."""
    if len(secret) > 8:
        return line.replace(secret, secret[:4] + "****" + secret[-2:])
    return line.replace(secret, "[REDACTED]")
