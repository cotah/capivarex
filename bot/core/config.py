"""
Configuration management system for CAPIVAREX Bot.

Handles:
- Bot configuration (modes, flags, settings)
- Credit system (multi-tenant credits tracking)
- Usage ledger (API usage tracking)
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger("unbx_bot.config")

# Default encoding
DEFAULT_ENCODING = "utf-8"

# Credit system state
_CREDIT_WARNING_SHOWN = False
_SESSION_CREDITS_DELTA = 0
_SESSION_CREDITS_BASE: Optional[int] = None


class ConfigManager:
    """Manages bot configuration and credit system."""

    def __init__(self, workspace_dir: Path):
        """Initialise the config manager."""
        self.workspace = workspace_dir
        self.config_file = workspace_dir / "config.json"
        self.usage_dir = workspace_dir / "usage"
        self.usage_ledger_file = self.usage_dir / "usage_ledger.jsonl"

        # Ensure directories exist
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.usage_dir.mkdir(parents=True, exist_ok=True)

        self.default_config = {
            "modo": "default",
            "quick_save": False,
            "pin": "1234",
            "tenants": {
                "local-dev": {
                    "credits_total": 100000,
                    "credits_used": 0,
                    "soft_threshold": 0.85,
                }
            },
        }

    def load(self) -> Dict:
        """Load configuration from file."""
        if not self.config_file.exists():
            self.save(self.default_config)
            return self.default_config.copy()

        try:
            with open(self.config_file, "r", encoding=DEFAULT_ENCODING) as f:
                cfg = json.load(f)

            # Merge with defaults
            for key, value in self.default_config.items():
                if key not in cfg:
                    cfg[key] = value

            return cfg
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return self.default_config.copy()

    def save(self, config: Dict):
        """Save configuration to file."""
        try:
            with open(self.config_file, "w", encoding=DEFAULT_ENCODING) as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def ensure_tenant_exists(self, tenant_id: str):
        """Ensure tenant exists in configuration."""
        cfg = self.load()
        tenants = cfg.get("tenants", {})

        if tenant_id not in tenants:
            tenants[tenant_id] = {
                "credits_total": 100000,
                "credits_used": 0,
                "soft_threshold": 0.85,
            }
            cfg["tenants"] = tenants
            self.save(cfg)

    def log_usage_event(
        self,
        tenant_id: str,
        user_id: str,
        provider: str,
        kind: str,
        status: str,
        model: Optional[str] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        meta: Optional[Dict] = None,
    ):
        """Log API usage event to ledger."""
        event = {
            "ts": datetime.now().isoformat(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "provider": provider,
            "kind": kind,
            "status": status,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "meta": meta or {},
        }

        # Sanitize meta (remove secrets)
        if "meta" in event and isinstance(event["meta"], dict):
            for key in list(event["meta"].keys()):
                if any(x in key.lower() for x in ["key", "secret", "token"]):
                    del event["meta"][key]

        # Append to ledger (JSONL)
        try:
            with open(self.usage_ledger_file, "a", encoding=DEFAULT_ENCODING) as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write usage ledger: {e}")

        # Increment credits
        self._increment_credits(tenant_id, tokens_in, tokens_out)

    def check_quota(self, tenant_id: str, cost: int) -> bool:
        """Check if a tenant has enough credits for an operation.

        Args:
            tenant_id: Tenant identifier.
            cost: Estimated credit cost for the operation.

        Returns:
            True if the tenant has sufficient credits remaining.
        """
        cfg = self.load()
        tenant_data = cfg.get("tenants", {}).get(tenant_id)
        if not tenant_data:
            return False

        return (tenant_data.get("credits_used", 0) + cost) <= tenant_data.get(
            "credits_total", 0
        )

    def log_billing_event(self, tenant_id: str, event_type: str, details: Dict) -> None:
        """Log a billing event for future integration (e.g. Stripe webhooks).

        This is a placeholder that currently only writes a structured log
        entry.  When a billing provider is integrated, this method becomes
        the single point of extension.

        Args:
            tenant_id: Tenant identifier.
            event_type: Event category (e.g. ``quota_exceeded``, ``usage``).
            details: Arbitrary event metadata.
        """
        logger.info(
            "BILLING EVENT: tenant_id=%s, event='%s', details=%s",
            tenant_id,
            event_type,
            details,
        )

    def _increment_credits(
        self,
        tenant_id: str,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
    ):
        """Increment credits used for tenant."""
        global _SESSION_CREDITS_DELTA, _SESSION_CREDITS_BASE, _CREDIT_WARNING_SHOWN

        if tokens_in is None and tokens_out is None:
            return

        # Simple cost calculation (can be refined)
        cost = 0
        if tokens_in:
            cost += tokens_in * 0.5
        if tokens_out:
            cost += tokens_out * 1.5

        cost = int(cost)

        # Check quota before allowing the operation
        if not self.check_quota(tenant_id, cost):
            self.log_billing_event(tenant_id, "quota_exceeded", {"cost": cost})
            raise ValueError(f"Quota exceeded for tenant {tenant_id}")

        # Update in-memory delta
        _SESSION_CREDITS_DELTA += cost

        # Load base if not loaded
        if _SESSION_CREDITS_BASE is None:
            cfg = self.load()
            tenant = cfg.get("tenants", {}).get(tenant_id, {})
            _SESSION_CREDITS_BASE = tenant.get("credits_used", 0)

        # Check threshold
        cfg = self.load()
        tenant = cfg.get("tenants", {}).get(tenant_id, {})
        total = tenant.get("credits_total", 100000)
        threshold = tenant.get("soft_threshold", 0.85)
        current_used = _SESSION_CREDITS_BASE + _SESSION_CREDITS_DELTA

        if not _CREDIT_WARNING_SHOWN and current_used >= (total * threshold):
            logger.warning(f"Credits threshold reached: {current_used}/{total}")
            _CREDIT_WARNING_SHOWN = True

    def flush_credits(self, tenant_id: str):
        """Flush in-memory credits delta to disk."""
        global _SESSION_CREDITS_DELTA, _SESSION_CREDITS_BASE

        if _SESSION_CREDITS_DELTA == 0:
            return

        cfg = self.load()
        tenant = cfg.get("tenants", {}).get(tenant_id, {})
        tenant["credits_used"] = tenant.get("credits_used", 0) + _SESSION_CREDITS_DELTA
        cfg["tenants"][tenant_id] = tenant
        self.save(cfg)

        # Reset delta
        _SESSION_CREDITS_DELTA = 0
        _SESSION_CREDITS_BASE = tenant["credits_used"]

    def get_credits_info(self, tenant_id: str) -> Dict:
        """Get credit information for tenant."""
        cfg = self.load()
        tenant = cfg.get("tenants", {}).get(tenant_id, {})

        total = tenant.get("credits_total", 100000)
        used = tenant.get("credits_used", 0) + _SESSION_CREDITS_DELTA
        remaining = max(0, total - used)
        percentage = (used / total * 100) if total > 0 else 0

        return {
            "total": total,
            "used": used,
            "remaining": remaining,
            "percentage": round(percentage, 2),
        }
