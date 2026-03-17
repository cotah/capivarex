"""Code Diff Scanner — analyzes git diff on new commits for vulnerabilities (Phase 2).

Triggered via GitHub webhook on every push. Scans only changed lines for
security issues, making it fast and targeted.
"""

from __future__ import annotations

from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner


class CodeDiffScanner(BaseScanner):
    name = "code_diff_scanner"
    schedule = "triggered"

    async def scan(self) -> list[SecurityFinding]:
        # TODO: Phase 2 — implement diff-based scanning
        # 1. Receive push webhook with commit SHAs
        # 2. Fetch diff from GitHub API
        # 3. Run static analysis rules on added lines only
        self.logger.info("Code diff scanner not yet implemented — placeholder")
        return []

    async def scan_diff(self, diff_text: str, commit_sha: str) -> list[SecurityFinding]:
        """Scan a specific diff for vulnerabilities."""
        # TODO: Parse unified diff, extract added lines, run rules
        return []
