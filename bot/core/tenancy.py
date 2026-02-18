"""
Multi-tenancy system for CapivaraX Bot.

Handles:
- Tenant context management
- Identity mapping (telegram, webapp, cli)
- Context resolution
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("unbx_bot.tenancy")

DEFAULT_ENCODING = "utf-8"


@dataclass
class TenantContext:
    """Represents a tenant/user context."""
    tenant_id: str
    user_id: str
    channel: str  # "cli", "telegram", "webapp"
    session_id: Optional[str] = None
    chat_id: Optional[str] = None


class TenancyManager:
    """Manages multi-tenancy and identity mapping."""

    def __init__(self, workspace_dir: Path):
        self.workspace = workspace_dir
        self.tenancy_dir = workspace_dir / "tenancy"
        self.identity_map_file = self.tenancy_dir / "identity_map.json"

        # Ensure directories exist
        self.tenancy_dir.mkdir(parents=True, exist_ok=True)

        self.default_identity_map = {
            "telegram": {},
            "webapp": {}
        }

        # Cache
        self._identity_map_cache: Optional[Dict] = None

        # Current context (global state)
        self.current_context = TenantContext(
            tenant_id="local-dev",
            user_id="henrique",
            channel="cli"
        )

    def load_identity_map(self) -> Dict:
        """Load identity map from file."""
        if self._identity_map_cache is not None:
            return self._identity_map_cache

        if not self.identity_map_file.exists():
            self.save_identity_map(self.default_identity_map)
            return self.default_identity_map.copy()

        try:
            with open(self.identity_map_file, 'r', encoding=DEFAULT_ENCODING) as f:
                self._identity_map_cache = json.load(f)
                return self._identity_map_cache
        except Exception as e:
            logger.error(f"Failed to load identity map: {e}")
            return self.default_identity_map.copy()

    def save_identity_map(self, identity_map: Dict):
        """Save identity map to file."""
        try:
            with open(self.identity_map_file, 'w', encoding=DEFAULT_ENCODING) as f:
                json.dump(identity_map, f, indent=2, ensure_ascii=False)
            self._identity_map_cache = identity_map
        except Exception as e:
            logger.error(f"Failed to save identity map: {e}")

    def set_current_context(self, context: TenantContext):
        """Set the current tenant context."""
        self.current_context = context

    def get_current_context(self) -> TenantContext:
        """Get the current tenant context."""
        return self.current_context

    def resolve_context(self, channel: str, meta: Dict) -> TenantContext:
        """Resolve tenant context from channel and metadata."""
        if channel == "cli":
            return TenantContext(
                tenant_id=self.current_context.tenant_id,
                user_id=self.current_context.user_id,
                channel="cli"
            )

        identity_map = self.load_identity_map()

        if channel == "telegram":
            chat_id = meta.get("chat_id", "")
            key = f"chat_id:{chat_id}"
            mapping = identity_map.get("telegram", {}).get(key, {})

            return TenantContext(
                tenant_id=mapping.get("tenant_id", "local-dev"),
                user_id=mapping.get("user_id", "unknown"),
                channel="telegram",
                chat_id=chat_id
            )

        if channel == "webapp":
            session_id = meta.get("session_id")
            email = meta.get("email")
            webapp_map = identity_map.get("webapp", {})

            # Try session_id first
            if session_id:
                key = f"session_id:{session_id}"
                mapping = webapp_map.get(key, {})
                if mapping:
                    return TenantContext(
                        tenant_id=mapping.get("tenant_id", "local-dev"),
                        user_id=mapping.get("user_id", "unknown"),
                        channel="webapp",
                        session_id=session_id
                    )

            # Try email
            if email:
                key = f"email:{email}"
                mapping = webapp_map.get(key, {})
                if mapping:
                    return TenantContext(
                        tenant_id=mapping.get("tenant_id", "local-dev"),
                        user_id=mapping.get("user_id", "unknown"),
                        channel="webapp",
                        session_id=session_id
                    )

            # Default webapp context
            return TenantContext(
                tenant_id="local-dev",
                user_id="unknown",
                channel="webapp",
                session_id=session_id
            )

        # Unknown channel
        return TenantContext(
            tenant_id="local-dev",
            user_id="unknown",
            channel=channel
        )

    def get_context_for_telegram(self, chat_id: str) -> TenantContext:
        """Get context for telegram channel."""
        return self.resolve_context("telegram", {"chat_id": chat_id})

    def get_context_for_webapp(
        self,
        session_id: Optional[str],
        email: Optional[str]
    ) -> TenantContext:
        """Get context for webapp channel."""
        return self.resolve_context("webapp", {
            "session_id": session_id,
            "email": email
        })

    def register_telegram_user(
        self,
        chat_id: str,
        tenant_id: str,
        user_id: str
    ):
        """Register a telegram user in identity map."""
        identity_map = self.load_identity_map()
        key = f"chat_id:{chat_id}"

        if "telegram" not in identity_map:
            identity_map["telegram"] = {}

        identity_map["telegram"][key] = {
            "tenant_id": tenant_id,
            "user_id": user_id
        }

        self.save_identity_map(identity_map)

    def register_webapp_user(
        self,
        tenant_id: str,
        user_id: str,
        session_id: Optional[str] = None,
        email: Optional[str] = None
    ):
        """Register a webapp user in identity map."""
        identity_map = self.load_identity_map()

        if "webapp" not in identity_map:
            identity_map["webapp"] = {}

        if session_id:
            key = f"session_id:{session_id}"
            identity_map["webapp"][key] = {
                "tenant_id": tenant_id,
                "user_id": user_id
            }

        if email:
            key = f"email:{email}"
            identity_map["webapp"][key] = {
                "tenant_id": tenant_id,
                "user_id": user_id
            }

        self.save_identity_map(identity_map)
