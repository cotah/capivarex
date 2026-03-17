"""Endpoint Fuzzer — tests API endpoints with malicious payloads (Phase 2).

This scanner sends test payloads (SQLi, XSS, SSRF, path traversal) against the
running API to detect vulnerabilities at runtime. Only runs when FUZZER_ENABLED=true.
"""

from __future__ import annotations

from cybersecurity.config import FUZZER_ENABLED
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner


class EndpointFuzzerScanner(BaseScanner):
    name = "endpoint_fuzzer"
    schedule = "slow"

    async def scan(self) -> list[SecurityFinding]:
        if not FUZZER_ENABLED:
            self.logger.debug("Fuzzer disabled — skipping")
            return []

        # TODO: Phase 2 — implement full fuzzer
        # 1. Introspect FastAPI routes
        # 2. Send SQLi, XSS, SSRF, path traversal payloads
        # 3. Analyze responses for success indicators
        self.logger.info("Endpoint fuzzer not yet implemented — placeholder")
        return []
