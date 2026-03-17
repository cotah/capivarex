"""Settings endpoints — bot configuration via API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cybersecurity import config

router = APIRouter()


class SettingsUpdate(BaseModel):
    fast_scan_interval: int | None = None
    medium_scan_interval: int | None = None
    slow_scan_interval: int | None = None
    alert_threshold: float | None = None
    autofix_suggest_threshold: float | None = None
    fuzzer_enabled: bool | None = None


@router.get("/settings")
async def get_settings():
    """Get current CyberSecurity bot configuration."""
    from cybersecurity.main import get_orchestrator
    orch = get_orchestrator()

    return {
        "intervals": {
            "fast_scan_seconds": config.FAST_SCAN_INTERVAL,
            "medium_scan_seconds": config.MEDIUM_SCAN_INTERVAL,
            "slow_scan_seconds": config.SLOW_SCAN_INTERVAL,
        },
        "thresholds": {
            "alert_threshold": config.ALERT_THRESHOLD,
            "autofix_suggest_threshold": config.AUTOFIX_SUGGEST_THRESHOLD,
            "autofix_auto_threshold": config.AUTOFIX_AUTO_THRESHOLD,
        },
        "features": {
            "auto_fix_enabled": config.AUTO_FIX_ENABLED,
            "fuzzer_enabled": config.FUZZER_ENABLED,
            "fuzzer_safe_mode": config.FUZZER_SAFE_MODE,
        },
        "scanners": orch.get_scanner_names() if orch else [],
        "bot_running": orch.is_running if orch else False,
    }


@router.patch("/settings")
async def update_settings(body: SettingsUpdate):
    """Update bot configuration (runtime only, not persisted to env)."""
    updated = {}

    if body.fast_scan_interval is not None:
        if body.fast_scan_interval < 60:
            raise HTTPException(status_code=400, detail="fast_scan_interval must be >= 60s")
        config.FAST_SCAN_INTERVAL = body.fast_scan_interval
        updated["fast_scan_interval"] = body.fast_scan_interval

    if body.medium_scan_interval is not None:
        if body.medium_scan_interval < 300:
            raise HTTPException(status_code=400, detail="medium_scan_interval must be >= 300s")
        config.MEDIUM_SCAN_INTERVAL = body.medium_scan_interval
        updated["medium_scan_interval"] = body.medium_scan_interval

    if body.slow_scan_interval is not None:
        if body.slow_scan_interval < 1800:
            raise HTTPException(status_code=400, detail="slow_scan_interval must be >= 1800s")
        config.SLOW_SCAN_INTERVAL = body.slow_scan_interval
        updated["slow_scan_interval"] = body.slow_scan_interval

    if body.alert_threshold is not None:
        if not 0 <= body.alert_threshold <= 1:
            raise HTTPException(status_code=400, detail="alert_threshold must be 0.0-1.0")
        config.ALERT_THRESHOLD = body.alert_threshold
        updated["alert_threshold"] = body.alert_threshold

    if body.autofix_suggest_threshold is not None:
        if not 0 <= body.autofix_suggest_threshold <= 1:
            raise HTTPException(status_code=400, detail="autofix_suggest_threshold must be 0.0-1.0")
        config.AUTOFIX_SUGGEST_THRESHOLD = body.autofix_suggest_threshold
        updated["autofix_suggest_threshold"] = body.autofix_suggest_threshold

    if body.fuzzer_enabled is not None:
        config.FUZZER_ENABLED = body.fuzzer_enabled
        updated["fuzzer_enabled"] = body.fuzzer_enabled

    if not updated:
        raise HTTPException(status_code=400, detail="No settings to update")

    return {"status": "updated", "changes": updated}
