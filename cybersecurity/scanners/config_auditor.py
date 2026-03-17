"""Config Auditor — checks env vars, CORS, headers, rate limits, debug mode."""

from __future__ import annotations

import os
import re
from pathlib import Path

from cybersecurity.config import BACKEND_ROOT, FRONTEND_ROOT
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner


class ConfigAuditorScanner(BaseScanner):
    name = "config_auditor"
    schedule = "medium"

    async def scan(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        findings.extend(self._check_env_vars())
        findings.extend(self._check_cors_config())
        findings.extend(self._check_security_headers())
        findings.extend(self._check_debug_mode())
        findings.extend(self._check_rate_limiting())
        return findings

    # ------------------------------------------------------------------
    # ENV VAR checks
    # ------------------------------------------------------------------

    def _check_env_vars(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []

        # JWT Secret Key
        jwt_key = os.getenv("JWT_SECRET_KEY", "")
        if not jwt_key:
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="missing_jwt_secret",
                severity="critical",
                confidence=0.95,
                title="JWT_SECRET_KEY vazio ou nao definido",
                description="Sem JWT secret, tokens podem ser forjados com chave vazia",
                suggested_fix="Gerar chave segura: python -c \"import secrets; print(secrets.token_hex(32))\"",
                owasp_category="A07:2021-Security Misconfiguration",
            ))
        elif len(jwt_key) < 32:
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="weak_jwt_secret",
                severity="high",
                confidence=0.9,
                title=f"JWT_SECRET_KEY muito curta ({len(jwt_key)} chars, minimo 32)",
                description="Secret key curta e vulneravel a brute force",
                suggested_fix="Usar chave com pelo menos 32 caracteres aleatorios",
                owasp_category="A02:2021-Cryptographic Failures",
            ))

        # Encryption Key
        enc_key = os.getenv("ENCRYPTION_KEY", "")
        if not enc_key and os.getenv("ENVIRONMENT") == "production":
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="missing_encryption_key",
                severity="high",
                confidence=0.9,
                title="ENCRYPTION_KEY nao definida em producao",
                description="Sem encryption key, OAuth tokens nao podem ser cifrados de forma persistente",
                suggested_fix="Gerar Fernet key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
                owasp_category="A02:2021-Cryptographic Failures",
            ))

        # Sentry DSN
        if not os.getenv("SENTRY_DSN") and os.getenv("ENVIRONMENT") == "production":
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="missing_sentry",
                severity="medium",
                confidence=0.8,
                title="SENTRY_DSN nao configurado em producao",
                description="Sem Sentry, erros em producao nao serao rastreados",
                suggested_fix="Configurar Sentry DSN para monitoramento de erros",
                owasp_category="A09:2021-Security Logging and Monitoring Failures",
            ))

        # Environment variable
        env = os.getenv("ENVIRONMENT", "")
        if not env:
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="missing_environment",
                severity="medium",
                confidence=0.8,
                title="ENVIRONMENT nao definido",
                description="Sem ENVIRONMENT definido, o app pode rodar com configs de dev em producao",
                suggested_fix="Definir ENVIRONMENT=production em producao",
                owasp_category="A05:2021-Security Misconfiguration",
            ))

        return findings

    # ------------------------------------------------------------------
    # CORS checks (read from source code)
    # ------------------------------------------------------------------

    def _check_cors_config(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        main_py = BACKEND_ROOT / "api" / "main.py"
        if not main_py.exists():
            return findings

        try:
            content = main_py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return findings

        # Check for wildcard headers
        if 'allow_headers=["*"]' in content or "allow_headers=['*']" in content:
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="cors_wildcard_headers",
                severity="high",
                confidence=0.9,
                title="CORS permite qualquer header (allow_headers=[\"*\"])",
                description="Permite requisicoes com qualquer header, facilitando CSRF",
                file_path="capivarex-backend/api/main.py",
                suggested_fix='Substituir por lista explicita: allow_headers=["Content-Type", "Authorization"]',
                owasp_category="A05:2021-Security Misconfiguration",
            ))

        # Check for overly broad origin regex
        vercel_match = re.search(r"allow_origin_regex.*vercel\.app", content)
        if vercel_match:
            lineno = content[:vercel_match.start()].count("\n") + 1
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="cors_broad_regex",
                severity="medium",
                confidence=0.7,
                title="CORS origin regex inclui *.vercel.app — pode aceitar origens nao autorizadas",
                file_path="capivarex-backend/api/main.py",
                line_number=lineno,
                suggested_fix="Restringir regex para dominio especifico: r\"https://capivarex\\.vercel\\.app$\"",
                owasp_category="A05:2021-Security Misconfiguration",
            ))

        return findings

    # ------------------------------------------------------------------
    # Security headers check
    # ------------------------------------------------------------------

    def _check_security_headers(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        headers_file = BACKEND_ROOT / "api" / "middleware" / "security_headers.py"
        if not headers_file.exists():
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="missing_security_headers",
                severity="high",
                confidence=0.9,
                title="Middleware de security headers nao encontrado",
                suggested_fix="Adicionar middleware com X-Content-Type-Options, X-Frame-Options, HSTS, etc.",
                owasp_category="A05:2021-Security Misconfiguration",
            ))
            return findings

        try:
            content = headers_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return findings

        required_headers = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "strict-transport-security": "max-age",
        }
        for header, expected in required_headers.items():
            if header not in content.lower():
                findings.append(SecurityFinding(
                    scanner=self.name,
                    finding_type=f"missing_header_{header.replace('-', '_')}",
                    severity="medium",
                    confidence=0.85,
                    title=f"Security header ausente: {header}",
                    file_path="capivarex-backend/api/middleware/security_headers.py",
                    suggested_fix=f"Adicionar header: {header}: {expected}",
                    owasp_category="A05:2021-Security Misconfiguration",
                ))

        return findings

    # ------------------------------------------------------------------
    # Debug mode check
    # ------------------------------------------------------------------

    def _check_debug_mode(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        env = os.getenv("ENVIRONMENT", "development")
        if env == "production":
            # Check if debug endpoints are accessible
            main_py = BACKEND_ROOT / "api" / "main.py"
            if main_py.exists():
                try:
                    content = main_py.read_text(encoding="utf-8", errors="ignore")
                    if "/debug/" in content and 'ENVIRONMENT' in content:
                        # The code checks ENVIRONMENT, so it's probably gated — low confidence
                        pass
                    elif "/debug/" in content:
                        findings.append(SecurityFinding(
                            scanner=self.name,
                            finding_type="debug_endpoints_production",
                            severity="high",
                            confidence=0.7,
                            title="Debug endpoints podem estar acessiveis em producao",
                            file_path="capivarex-backend/api/main.py",
                            suggested_fix="Garantir que /debug/* retorna 404 quando ENVIRONMENT != development",
                            owasp_category="A05:2021-Security Misconfiguration",
                        ))
                except OSError:
                    pass
        return findings

    # ------------------------------------------------------------------
    # Rate limiting check
    # ------------------------------------------------------------------

    def _check_rate_limiting(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        rate_limit_file = BACKEND_ROOT / "api" / "middleware" / "rate_limit.py"

        if not rate_limit_file.exists():
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="missing_rate_limiting",
                severity="high",
                confidence=0.9,
                title="Rate limiting middleware nao encontrado",
                suggested_fix="Implementar rate limiting com slowapi ou similar",
                owasp_category="A05:2021-Security Misconfiguration",
            ))
            return findings

        try:
            content = rate_limit_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return findings

        # Check if JWT is decoded without signature verification
        if "verify_signature" in content and "False" in content:
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="rate_limit_jwt_no_verify",
                severity="high",
                confidence=0.9,
                title="Rate limiter decodifica JWT sem verificar assinatura",
                description="verify_signature=False permite tokens falsos para bypass de rate limit",
                file_path="capivarex-backend/api/middleware/rate_limit.py",
                suggested_fix="Usar mesma SECRET_KEY para verificar assinatura no rate limiter",
                owasp_category="A07:2021-Security Misconfiguration",
            ))

        return findings
