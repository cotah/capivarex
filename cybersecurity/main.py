"""CyberSecurity Bot entry point — starts the 24/7 security loop."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure backend is importable
_BACKEND_PATH = str(Path(__file__).resolve().parent.parent / "capivarex-backend")
if _BACKEND_PATH not in sys.path:
    sys.path.insert(0, _BACKEND_PATH)

logger = logging.getLogger("cybersecurity")

# Global orchestrator instance
_orchestrator = None


async def start_cybersecurity_loop() -> None:
    """Start the CyberSecurity bot background loop.

    Called from api/main.py lifespan or standalone.
    """
    global _orchestrator

    from cybersecurity.engine.orchestrator import CyberSecurityOrchestrator

    _orchestrator = CyberSecurityOrchestrator()
    await _orchestrator.initialize()

    logger.info("=" * 60)
    logger.info("  CYBERSECURITY BOT v1.0 — 24/7 Guardian Active")
    logger.info("=" * 60)

    await _orchestrator.run_loop()


def get_orchestrator():
    """Get the global orchestrator instance (for API endpoints)."""
    return _orchestrator


async def stop_cybersecurity_loop() -> None:
    """Gracefully stop the security loop."""
    global _orchestrator
    if _orchestrator:
        _orchestrator.stop()
        logger.info("CyberSecurity loop stop requested")


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    # Load env
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parent.parent / "capivarex-backend" / ".env")
    except ImportError:
        pass

    asyncio.run(start_cybersecurity_loop())
