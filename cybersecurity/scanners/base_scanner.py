"""Abstract base scanner — all scanners inherit from this."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from cybersecurity.engine.finding import SecurityFinding

logger = logging.getLogger("cybersecurity")


class BaseScanner(ABC):
    """Base class for all CyberSecurity scanners."""

    name: str = "base"
    schedule: str = "medium"  # 'fast', 'medium', 'slow', 'triggered'

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"cybersecurity.scanner.{self.name}")
        self._last_run: datetime | None = None
        self._run_count = 0
        self._total_findings = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self) -> list[SecurityFinding]:
        """Run the scan with timing, logging, and error handling."""
        self.logger.info("Scanner [%s] starting...", self.name)
        t0 = time.monotonic()
        try:
            findings = await self.scan()
            elapsed = int((time.monotonic() - t0) * 1000)
            self._last_run = datetime.now(timezone.utc)
            self._run_count += 1
            self._total_findings += len(findings)
            self.logger.info(
                "Scanner [%s] completed in %d ms — %d findings",
                self.name, elapsed, len(findings),
            )
            return findings
        except Exception:
            elapsed = int((time.monotonic() - t0) * 1000)
            self.logger.exception(
                "Scanner [%s] failed after %d ms", self.name, elapsed,
            )
            return []

    def get_metrics(self) -> dict:
        return {
            "name": self.name,
            "schedule": self.schedule,
            "run_count": self._run_count,
            "total_findings": self._total_findings,
            "last_run": self._last_run.isoformat() if self._last_run else None,
        }

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    @abstractmethod
    async def scan(self) -> list[SecurityFinding]:
        """Run the scan and return findings. Implemented by each scanner."""

    async def health_check(self) -> bool:
        """Override if the scanner has prerequisites to verify."""
        return True
