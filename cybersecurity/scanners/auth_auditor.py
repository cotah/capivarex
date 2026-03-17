"""Auth Auditor — verifies JWT config, brute force patterns, token security."""

from __future__ import annotations

import os
import re
from pathlib import Path

from cybersecurity.config import BACKEND_ROOT
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner


class AuthAuditorScanner(BaseScanner):
    name = "auth_auditor"
    schedule = "fast"

    async def scan(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        findings.extend(self._check_jwt_config())
        findings.extend(self._check_password_hashing())
        findings.extend(self._check_auth_endpoints())
        findings.extend(self._check_websocket_auth())
        return findings

    # ------------------------------------------------------------------
    # JWT configuration
    # ------------------------------------------------------------------

    def _check_jwt_config(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []

        # Check env vars
        secret = os.getenv("JWT_SECRET_KEY", "")
        algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        expiration = os.getenv("JWT_EXPIRATION_MINUTES", "60")

        if not secret:
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="empty_jwt_secret",
                severity="critical",
                confidence=0.95,
                title="JWT_SECRET_KEY esta vazio — tokens podem ser forjados",
                description="Com secret vazio, atacante pode assinar tokens JWT arbitrarios",
                suggested_fix="Definir JWT_SECRET_KEY com pelo menos 32 caracteres aleatorios",
                owasp_category="A07:2021-Identification and Authentication Failures",
            ))

        # Check algorithm
        weak_algorithms = {"none", "HS256"}  # HS256 is okay but note it
        if algorithm.lower() == "none":
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="jwt_algorithm_none",
                severity="critical",
                confidence=0.95,
                title="JWT algorithm definido como 'none' — sem assinatura!",
                suggested_fix="Usar HS256 ou RS256",
                owasp_category="A02:2021-Cryptographic Failures",
            ))

        # Check expiration
        try:
            exp_min = int(expiration)
            if exp_min > 1440:  # More than 24 hours
                findings.append(SecurityFinding(
                    scanner=self.name,
                    finding_type="jwt_long_expiration",
                    severity="medium",
                    confidence=0.7,
                    title=f"JWT expiration muito longo: {exp_min} minutos ({exp_min // 60}h)",
                    suggested_fix="Reduzir para 60 minutos e implementar refresh tokens",
                    owasp_category="A07:2021-Identification and Authentication Failures",
                ))
        except ValueError:
            pass

        # Check auth.py source for code-level issues
        auth_file = BACKEND_ROOT / "api" / "dependencies" / "auth.py"
        if auth_file.exists():
            try:
                content = auth_file.read_text(encoding="utf-8", errors="ignore")

                # Check if empty secret is allowed in production
                if "SECRET_KEY" in content and ('= ""' in content or "= ''" in content):
                    findings.append(SecurityFinding(
                        scanner=self.name,
                        finding_type="auth_allows_empty_secret",
                        severity="critical",
                        confidence=0.85,
                        title="Codigo permite SECRET_KEY vazio sem bloquear",
                        file_path="capivarex-backend/api/dependencies/auth.py",
                        suggested_fix="Adicionar validacao: if not SECRET_KEY: raise RuntimeError()",
                        owasp_category="A07:2021-Identification and Authentication Failures",
                    ))
            except OSError:
                pass

        return findings

    # ------------------------------------------------------------------
    # Password hashing
    # ------------------------------------------------------------------

    def _check_password_hashing(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        auth_routes = BACKEND_ROOT / "api" / "routes" / "auth.py"
        if not auth_routes.exists():
            return findings

        try:
            content = auth_routes.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return findings

        # Check for MD5/SHA1 password hashing
        if re.search(r"hashlib\.(?:md5|sha1)\s*\(", content):
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="weak_password_hash",
                severity="critical",
                confidence=0.9,
                title="Password hashing com MD5 ou SHA1 — inseguro",
                file_path="capivarex-backend/api/routes/auth.py",
                suggested_fix="Usar bcrypt ou argon2 para hashing de passwords",
                owasp_category="A02:2021-Cryptographic Failures",
            ))

        # Check bcrypt is being used (positive signal)
        if "bcrypt" not in content and "argon2" not in content:
            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="no_password_hashing_library",
                severity="high",
                confidence=0.7,
                title="Nenhuma biblioteca de hashing segura encontrada em auth routes",
                file_path="capivarex-backend/api/routes/auth.py",
                suggested_fix="Usar bcrypt.hashpw() ou argon2 para hash de passwords",
                owasp_category="A02:2021-Cryptographic Failures",
            ))

        return findings

    # ------------------------------------------------------------------
    # Auth endpoint checks
    # ------------------------------------------------------------------

    def _check_auth_endpoints(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []

        # Check for unprotected endpoints in route files
        routes_dir = BACKEND_ROOT / "api" / "routes"
        if not routes_dir.exists():
            return findings

        for route_file in routes_dir.glob("*.py"):
            if route_file.name.startswith("_"):
                continue
            try:
                content = route_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # Check for endpoints without auth dependency
            # Pattern: @router.post/get/etc without Depends(get_current_user) or get_admin_user
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if re.match(r'\s*@router\.(post|get|put|patch|delete)\s*\(', line):
                    # Look ahead for the function definition and auth deps
                    block = "\n".join(lines[i:i + 10])
                    has_auth = (
                        "get_current_user" in block
                        or "get_admin_user" in block
                        or "get_optional_user" in block
                        or "verify_webapp_user" in block
                        or "verify_admin_token" in block
                    )
                    # Skip known public endpoints
                    is_public = any(kw in block for kw in [
                        "/health", "/login", "/register", "/callback",
                        "/authorize", "/webhook", "/forgot",
                    ])
                    if not has_auth and not is_public:
                        endpoint_match = re.search(r'["\']([^"\']+)["\']', line)
                        endpoint = endpoint_match.group(1) if endpoint_match else "unknown"
                        findings.append(SecurityFinding(
                            scanner=self.name,
                            finding_type="unprotected_endpoint",
                            severity="high",
                            confidence=0.6,
                            title=f"Endpoint possivelmente sem autenticacao: {endpoint}",
                            file_path=f"capivarex-backend/api/routes/{route_file.name}",
                            line_number=i + 1,
                            suggested_fix="Adicionar Depends(get_current_user) ou Depends(get_admin_user)",
                            owasp_category="A01:2021-Broken Access Control",
                        ))

        return findings

    # ------------------------------------------------------------------
    # WebSocket auth
    # ------------------------------------------------------------------

    def _check_websocket_auth(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []

        ws_files = [
            BACKEND_ROOT / "api" / "routes" / "voice_ws.py",
            BACKEND_ROOT / "api" / "routes" / "chat.py",
        ]

        for ws_file in ws_files:
            if not ws_file.exists():
                continue
            try:
                content = ws_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # Check for verify_aud: False
            if "verify_aud" in content and "False" in content:
                match = re.search(r"verify_aud.*False", content)
                lineno = content[:match.start()].count("\n") + 1 if match else 0
                findings.append(SecurityFinding(
                    scanner=self.name,
                    finding_type="ws_auth_no_audience_check",
                    severity="high",
                    confidence=0.85,
                    title=f"WebSocket JWT sem verificacao de audience em {ws_file.name}",
                    file_path=f"capivarex-backend/api/routes/{ws_file.name}",
                    line_number=lineno,
                    suggested_fix="Habilitar verify_aud: True para validar audience claim",
                    owasp_category="A07:2021-Identification and Authentication Failures",
                ))

            # Check for verify_signature: False
            if "verify_signature" in content and "False" in content:
                match = re.search(r"verify_signature.*False", content)
                lineno = content[:match.start()].count("\n") + 1 if match else 0
                findings.append(SecurityFinding(
                    scanner=self.name,
                    finding_type="ws_auth_no_signature_check",
                    severity="critical",
                    confidence=0.9,
                    title=f"WebSocket JWT sem verificacao de assinatura em {ws_file.name}",
                    file_path=f"capivarex-backend/api/routes/{ws_file.name}",
                    line_number=lineno,
                    suggested_fix="Nunca desabilitar verify_signature em producao",
                    owasp_category="A02:2021-Cryptographic Failures",
                ))

        return findings
