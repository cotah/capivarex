# capivarex_modules/access_service.py
"""
Module Access Service
Checks if a user has access to a specific capivara module.

Access rules:
1. ARA is ALWAYS accessible (it's the base product)
2. Core agents (orchestrator, chat) are ALWAYS accessible
3. All other modules require explicit unlock in user's subscription
4. Coming Soon modules return a special "coming_soon" response
5. Disabled modules return a "disabled" response

Data source: Supabase table `user_modules` (created in migration 008)
Redis cache: TTL 5 minutes per user to avoid DB hammering
"""
import logging
from typing import Optional, Dict, Any, List

from capivarex_modules.config import (
    CAPIVARA_MODULES,
    MODULE_STATUS_COMING_SOON,
    MODULE_STATUS_DISABLED,
    get_module_for_agent,
    is_core_agent,
)

logger = logging.getLogger("capivarex.modules.access")

# Redis cache TTL for module access (5 minutes)
MODULE_ACCESS_CACHE_TTL = 300
MODULE_ACCESS_CACHE_PREFIX = "module_access:"


class ModuleAccessResult:
    """Result of a module access check."""

    def __init__(
        self,
        allowed: bool,
        reason: str,
        module_name: str,
        agent_name: str,
        upgrade_message: Optional[str] = None,
    ):
        self.allowed = allowed
        self.reason = reason
        self.module_name = module_name
        self.agent_name = agent_name
        self.upgrade_message = upgrade_message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "module_name": self.module_name,
            "agent_name": self.agent_name,
            "upgrade_message": self.upgrade_message,
        }


class ModuleAccessService:
    """
    Checks and manages user access to capivara modules.

    Usage:
        access_svc = ModuleAccessService(db_service, redis_service)
        result = await access_svc.check_agent_access(user_id, "finance")
        if not result.allowed:
            return locked_response(result)
    """

    def __init__(self, db_service=None, redis_service=None):
        self._db = db_service
        self._redis = redis_service

    async def check_agent_access(
        self, user_id: str, agent_name: str
    ) -> ModuleAccessResult:
        """
        Check if a user has access to a specific agent.

        Returns ModuleAccessResult with allowed=True if access is granted,
        or allowed=False with the reason and upgrade message.
        """
        # 1. Core agents always pass
        if is_core_agent(agent_name):
            return ModuleAccessResult(
                allowed=True,
                reason="core_agent",
                module_name="core",
                agent_name=agent_name,
            )

        # 2. Determine which module this agent belongs to
        module_name = get_module_for_agent(agent_name)
        module_config = CAPIVARA_MODULES.get(module_name, {})

        # 3. ARA agents always pass (ARA is always included)
        if module_config.get("always_included", False):
            return ModuleAccessResult(
                allowed=True,
                reason="always_included",
                module_name=module_name,
                agent_name=agent_name,
            )

        # 4. Check module global status
        module_status = module_config.get("status", MODULE_STATUS_COMING_SOON)
        if module_status == MODULE_STATUS_DISABLED:
            return ModuleAccessResult(
                allowed=False,
                reason="module_disabled",
                module_name=module_name,
                agent_name=agent_name,
                upgrade_message=f"The {module_config.get('name', module_name)} module is not yet available.",
            )

        # 5. Check user's subscription for this module
        has_access = await self._user_has_module(user_id, module_name)

        if has_access:
            return ModuleAccessResult(
                allowed=True,
                reason="subscription_active",
                module_name=module_name,
                agent_name=agent_name,
            )

        # 6. User doesn't have access — build upgrade message
        if module_status == MODULE_STATUS_COMING_SOON:
            upgrade_msg = (
                f"🔒 *{module_config.get('full_name', module_name)}* is coming soon!\n\n"
                f"{module_config.get('description', '')}\n\n"
                f"Add it to your plan for €{module_config.get('price_eur', 9.99)}/month at capivarex.com/upgrade"
            )
        else:
            upgrade_msg = (
                f"🔒 *{module_config.get('full_name', module_name)}* is not included in your current plan.\n\n"
                f"{module_config.get('description', '')}\n\n"
                f"Upgrade at capivarex.com/upgrade — from €{module_config.get('price_eur', 9.99)}/month"
            )

        return ModuleAccessResult(
            allowed=False,
            reason="not_subscribed",
            module_name=module_name,
            agent_name=agent_name,
            upgrade_message=upgrade_msg,
        )

    async def _user_has_module(self, user_id: str, module_name: str) -> bool:
        """
        Check if user has an active subscription to a module.
        Uses Redis cache (5 min TTL) → Supabase fallback.
        """
        # Try Redis cache first
        cache_key = f"{MODULE_ACCESS_CACHE_PREFIX}{user_id}:{module_name}"
        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached is not None:
                    return cached == "1"
            except Exception as e:
                logger.warning("Redis cache miss for module access: %s", e)

        # Query Supabase
        has_access = await self._query_db_access(user_id, module_name)

        # Store in Redis cache
        if self._redis:
            try:
                await self._redis.set(
                    cache_key, "1" if has_access else "0", ex=MODULE_ACCESS_CACHE_TTL
                )
            except Exception as e:
                logger.warning("Failed to cache module access in Redis: %s", e)

        return has_access

    async def _query_db_access(self, user_id: str, module_name: str) -> bool:
        """Query Supabase for user module access."""
        if not self._db:
            logger.warning("No DB service available for module access check")
            return False
        try:
            response = (
                self._db.get_client()
                .table("user_modules")
                .select("status")
                .eq("user_id", user_id)
                .eq("module_name", module_name)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0].get("status") == "active"
            return False
        except Exception as e:
            logger.error("DB error checking module access for user %s: %s", user_id[:8], e)
            return False

    async def get_user_modules(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Returns all modules with their access status for a user.
        Used by the dashboard/frontend to show locked/unlocked state.
        """
        result = []
        for module_name, module_config in CAPIVARA_MODULES.items():
            if module_config.get("always_included"):
                status = "active"
            else:
                has_access = await self._user_has_module(user_id, module_name)
                if has_access:
                    status = "active"
                elif module_config.get("status") == MODULE_STATUS_COMING_SOON:
                    status = "coming_soon"
                elif module_config.get("status") == MODULE_STATUS_DISABLED:
                    status = "disabled"
                else:
                    status = "locked"

            result.append({
                "module_name": module_name,
                "name": module_config["name"],
                "full_name": module_config["full_name"],
                "description": module_config["description"],
                "color": module_config["color"],
                "emoji": module_config["emoji"],
                "status": status,
                "price_eur": module_config.get("price_eur"),
                "agents": module_config["agents"],
            })
        return result

    async def unlock_module(self, user_id: str, module_name: str) -> bool:
        """
        Unlock a module for a user (called by Stripe webhook after payment).
        Creates or updates record in user_modules table.
        """
        if not self._db:
            return False
        try:
            self._db.get_client().table("user_modules").upsert({
                "user_id": user_id,
                "module_name": module_name,
                "status": "active",
            }).execute()

            # Invalidate Redis cache
            if self._redis:
                cache_key = f"{MODULE_ACCESS_CACHE_PREFIX}{user_id}:{module_name}"
                try:
                    await self._redis.delete(cache_key)
                except Exception:
                    pass

            logger.info("Module %s unlocked for user %s", module_name, user_id[:8])
            return True
        except Exception as e:
            logger.error("Failed to unlock module %s for user %s: %s", module_name, user_id[:8], e)
            return False

    async def lock_module(self, user_id: str, module_name: str) -> bool:
        """
        Lock a module for a user (called by Stripe webhook on cancellation).
        """
        if not self._db:
            return False
        try:
            self._db.get_client().table("user_modules").upsert({
                "user_id": user_id,
                "module_name": module_name,
                "status": "cancelled",
            }).execute()

            # Invalidate Redis cache
            if self._redis:
                cache_key = f"{MODULE_ACCESS_CACHE_PREFIX}{user_id}:{module_name}"
                try:
                    await self._redis.delete(cache_key)
                except Exception:
                    pass

            logger.info("Module %s locked for user %s", module_name, user_id[:8])
            return True
        except Exception as e:
            logger.error("Failed to lock module %s for user %s: %s", module_name, user_id[:8], e)
            return False


# Singleton factory
_access_service_instance: Optional[ModuleAccessService] = None


def get_module_access_service() -> ModuleAccessService:
    """Get or create the singleton ModuleAccessService."""
    global _access_service_instance
    if _access_service_instance is None:
        try:
            from services.core import get_service
            db = get_service("database")
            redis = get_service("redis")
            _access_service_instance = ModuleAccessService(db, redis)
        except Exception as e:
            logger.warning("Could not initialize ModuleAccessService with services: %s", e)
            _access_service_instance = ModuleAccessService()
    return _access_service_instance
