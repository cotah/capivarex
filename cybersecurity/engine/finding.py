"""SecurityFinding dataclass — the universal output of every scanner."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SecurityFinding:
    """Represents a single security issue detected by a scanner."""

    scanner: str
    finding_type: str
    severity: str          # 'info', 'low', 'medium', 'high', 'critical'
    confidence: float      # 0.0 – 1.0
    title: str
    description: str = ""
    file_path: str | None = None
    line_number: int | None = None
    code_snippet: str | None = None
    suggested_fix: str | None = None
    cve_id: str | None = None
    owasp_category: str | None = None
    evidence: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # Set automatically
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint for deduplication."""
        raw = f"{self.scanner}:{self.finding_type}:{self.file_path or ''}:{self.line_number or 0}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_db_row(self) -> dict:
        """Convert to a dict ready for Supabase insert."""
        return {
            "scanner": self.scanner,
            "finding_type": self.finding_type,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "status": "open",
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_snippet": (self.code_snippet or "")[:2000],
            "suggested_fix": self.suggested_fix,
            "cve_id": self.cve_id,
            "owasp_category": self.owasp_category,
            "evidence": self.evidence,
            "metadata": {**self.metadata, "fingerprint": self.fingerprint},
            "first_seen": self.first_seen.isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }
