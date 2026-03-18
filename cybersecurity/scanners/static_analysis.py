"""Static Analysis Scanner — detects OWASP Top 10 patterns in Python & TypeScript."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from cybersecurity.config import (
    ADMIN_FRONTEND_ROOT,
    ALL_CODE_EXTENSIONS,
    BACKEND_ROOT,
    EXCLUDED_DIRS,
    FRONTEND_ROOT,
    PYTHON_EXTENSIONS,
)
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner

# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------

# Python AST-level rules (function names / patterns to flag)
_DANGEROUS_CALLS = {
    "eval": (
        "Uso de eval() — execucao de codigo arbitrario",
        "critical",
        "A03:2021-Injection",
    ),
    "exec": (
        "Uso de exec() — execucao de codigo arbitrario",
        "critical",
        "A03:2021-Injection",
    ),
    "compile": (
        "Uso de compile() — possivel execucao de codigo",
        "medium",
        "A03:2021-Injection",
    ),
    "__import__": ("Uso de __import__() dinamico", "medium", "A03:2021-Injection"),
}

_DANGEROUS_MODULES = {
    "pickle": (
        "Uso de pickle — desserializacao insegura",
        "high",
        "A08:2021-Insecure Deserialization",
    ),
    "marshal": (
        "Uso de marshal — desserializacao insegura",
        "high",
        "A08:2021-Insecure Deserialization",
    ),
    "shelve": (
        "Uso de shelve — desserializacao insegura",
        "medium",
        "A08:2021-Insecure Deserialization",
    ),
}

# Regex-based rules (work on both Python and TypeScript)
_REGEX_RULES: list[tuple[re.Pattern, str, str, str, str]] = [
    # pattern, finding_type, title, severity, owasp
    (
        re.compile(
            r"""(?:password|passwd|secret|api_key|apikey|token|auth)\s*=\s*['"][^'"]{4,}['"]""",
            re.I,
        ),
        "hardcoded_secret",
        "Possivel secret hardcoded no codigo",
        "high",
        "A07:2021-Security Misconfiguration",
    ),
    (
        re.compile(
            r"""subprocess\.(?:call|run|Popen)\s*\([^)]*shell\s*=\s*True""", re.I
        ),
        "command_injection",
        "subprocess com shell=True — risco de command injection",
        "high",
        "A03:2021-Injection",
    ),
    (
        re.compile(r"""os\.system\s*\("""),
        "command_injection",
        "os.system() — risco de command injection",
        "high",
        "A03:2021-Injection",
    ),
    (
        re.compile(r"""\.format\s*\(.*\)\s*\)?\s*\.execute""", re.S),
        "sql_injection",
        "String format em query SQL — risco de SQL injection",
        "critical",
        "A03:2021-Injection",
    ),
    (
        re.compile(r"""f['"].*\{.*\}.*['"].*\.execute""", re.S),
        "sql_injection",
        "f-string em query SQL — risco de SQL injection",
        "critical",
        "A03:2021-Injection",
    ),
    (
        re.compile(r"""random\.(?:random|randint|choice|randrange)\s*\("""),
        "insecure_randomness",
        "random stdlib para fins de seguranca — use secrets module",
        "medium",
        "A02:2021-Cryptographic Failures",
    ),
    (
        re.compile(r"""DEBUG\s*=\s*True"""),
        "debug_enabled",
        "DEBUG=True em codigo — desabilitar em producao",
        "medium",
        "A05:2021-Security Misconfiguration",
    ),
    (
        re.compile(r"""dangerouslySetInnerHTML"""),
        "xss_risk",
        "dangerouslySetInnerHTML — risco de XSS",
        "high",
        "A03:2021-Injection",
    ),
    (
        re.compile(r"""innerHTML\s*="""),
        "xss_risk",
        "innerHTML assignment — risco de XSS",
        "high",
        "A03:2021-Injection",
    ),
    (
        re.compile(r"""verify\s*=\s*False"""),
        "ssl_verification_disabled",
        "SSL verification desabilitada",
        "high",
        "A07:2021-Security Misconfiguration",
    ),
    (
        re.compile(r"""(?:md5|sha1)\s*\(""", re.I),
        "weak_hash",
        "Uso de hash fraco (MD5/SHA1) — use SHA-256+ ou bcrypt",
        "medium",
        "A02:2021-Cryptographic Failures",
    ),
    (
        re.compile(r"""allow_origins\s*=\s*\[\s*["']\*["']\s*\]"""),
        "cors_wildcard",
        "CORS com wildcard '*' — permite requisicoes de qualquer origem",
        "high",
        "A05:2021-Security Misconfiguration",
    ),
    (
        re.compile(r"""(?:PRIVATE[_ ]KEY|private_key)\s*=\s*['"]""", re.I),
        "hardcoded_private_key",
        "Private key hardcoded no codigo",
        "critical",
        "A07:2021-Security Misconfiguration",
    ),
]


def _iter_code_files(*roots: Path) -> list[Path]:
    """Yield all code files from the given root directories."""
    files = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if any(ex in p.parts for ex in EXCLUDED_DIRS):
                continue
            if p.suffix in ALL_CODE_EXTENSIONS and p.is_file():
                files.append(p)
    return files


class StaticAnalysisScanner(BaseScanner):
    name = "static_analysis"
    schedule = "medium"

    async def scan(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        files = _iter_code_files(BACKEND_ROOT, FRONTEND_ROOT, ADMIN_FRONTEND_ROOT)

        for fpath in files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            lines = content.splitlines()
            rel = str(
                fpath.relative_to(fpath.parents[2]) if len(fpath.parents) > 2 else fpath
            )

            # --- Python AST checks ---
            if fpath.suffix in PYTHON_EXTENSIONS:
                findings.extend(self._check_python_ast(content, rel, fpath))

            # --- Regex checks (Python + TypeScript) ---
            for pattern, ftype, title, sev, owasp in _REGEX_RULES:
                for m in pattern.finditer(content):
                    lineno = content[: m.start()].count("\n") + 1
                    snippet = lines[lineno - 1].strip() if lineno <= len(lines) else ""
                    # Skip test files and examples for some rules
                    if ftype == "hardcoded_secret" and _is_test_or_example(rel):
                        continue
                    findings.append(
                        SecurityFinding(
                            scanner=self.name,
                            finding_type=ftype,
                            severity=sev,
                            confidence=0.7,
                            title=title,
                            description=f"Encontrado em {rel}:{lineno}",
                            file_path=rel,
                            line_number=lineno,
                            code_snippet=snippet[:200],
                            owasp_category=owasp,
                        )
                    )

        return findings

    def _check_python_ast(
        self,
        source: str,
        rel_path: str,
        fpath: Path,
    ) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        try:
            tree = ast.parse(source, filename=str(fpath))
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            # Check dangerous function calls
            if isinstance(node, ast.Call):
                func_name = _get_call_name(node)
                if func_name in _DANGEROUS_CALLS:
                    title, sev, owasp = _DANGEROUS_CALLS[func_name]
                    # Skip if inside test file
                    if _is_test_or_example(rel_path):
                        continue
                    findings.append(
                        SecurityFinding(
                            scanner=self.name,
                            finding_type=f"dangerous_call_{func_name}",
                            severity=sev,
                            confidence=0.85,
                            title=title,
                            file_path=rel_path,
                            line_number=getattr(node, "lineno", 0),
                            owasp_category=owasp,
                        )
                    )

            # Check dangerous imports
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import) and node.names:
                    module = node.names[0].name
                for mod_name, (title, sev, owasp) in _DANGEROUS_MODULES.items():
                    if mod_name in module:
                        findings.append(
                            SecurityFinding(
                                scanner=self.name,
                                finding_type=f"dangerous_import_{mod_name}",
                                severity=sev,
                                confidence=0.6,
                                title=title,
                                file_path=rel_path,
                                line_number=getattr(node, "lineno", 0),
                                owasp_category=owasp,
                            )
                        )
        return findings


def _get_call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _is_test_or_example(path: str) -> bool:
    lower = path.lower()
    return (
        "test" in lower
        or "example" in lower
        or "fixture" in lower
        or "mock" in lower
        or "conftest" in lower
    )
