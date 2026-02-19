"""
Database Service - Supabase client with BaseService architecture.

Provides:
- Supabase client management
- User queries
- Automatic connection handling
- Health checks
"""

import asyncio
import json as _json
import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from supabase import Client, create_client

from utils.encryption import encrypt_token, decrypt_token

from services.core import (
    BaseService,
    register_service,
    ServiceConfigurationError,
    ServiceUnavailableError
)


load_dotenv()


@register_service("database")
class DatabaseService(BaseService):
    """
    Database service for Supabase operations.

    Features:
    - Supabase client management
    - User queries with proactivity
    - Connection pooling
    - Health monitoring
    """

    def __init__(self, name: str = "database", config: Dict[str, Any] = None):
        """Initialise the database service."""
        super().__init__(name, config)
        self.client: Optional[Client] = None
        self.url: Optional[str] = None
        self.key: Optional[str] = None

    async def _initialize(self):
        """Initialize Supabase client."""
        self.url = os.environ.get("SUPABASE_URL")
        self.key = os.environ.get("SUPABASE_SERVICE_KEY")

        if not self.url:
            raise ServiceConfigurationError("SUPABASE_URL not found in environment")

        if not self.key:
            raise ServiceConfigurationError("SUPABASE_SERVICE_KEY not found in environment")

        try:
            self.client = create_client(self.url, self.key)
            self.logger.info("Supabase client initialized successfully")
        except Exception as e:
            raise ServiceUnavailableError(f"Failed to create Supabase client: {e}") from e

    async def _health_check(self) -> bool:
        """Check if database connection is healthy."""
        if not self.client:
            return False

        try:
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.table("users").select("id").limit(1).execute()
                ),
                timeout=5.0
            )
            return True
        except asyncio.TimeoutError:
            self.logger.warning("Database health check timed out")
            return False
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            return False

    def get_client(self) -> Client:
        """
        Get the Supabase client.

        Returns:
            Supabase Client instance
        """
        if not self.client:
            raise ServiceUnavailableError("Database service not initialized")
        return self.client

    async def get_all_users_with_preferences(self) -> List[Dict[str, Any]]:
        """
        Get all users with proactivity enabled and telegram_chat_id.

        Returns:
            List of user dictionaries
        """
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("users").select(
                "id, email, full_name, telegram_chat_id, location_preference, proactivity_preferences"
            ).neq(
                "telegram_chat_id", None
            ).execute()

            if not response.data:
                return []

            # Filter users with proactivity enabled
            users_with_proactivity = [
                user for user in response.data
                if user.get("proactivity_preferences", {}).get("enabled", False) is True
            ]

            self.logger.info(
                f"Found {len(users_with_proactivity)} users with proactivity enabled"
            )

            return users_with_proactivity

        except Exception as e:
            self.logger.error(f"Failed to get users with preferences: {e}", exc_info=True)
            return []

    async def get_user_by_telegram_id(self, telegram_chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user by telegram chat ID.

        Args:
            telegram_chat_id: Telegram chat ID

        Returns:
            User dict or None
        """
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("users").select("*").eq(
                "telegram_chat_id", telegram_chat_id
            ).execute()

            if response.data and len(response.data) > 0:
                return response.data[0]

            return None

        except Exception as e:
            self.logger.error(
                f"Failed to get user by telegram ID {telegram_chat_id}: {e}",
                exc_info=True
            )
            return None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user by their primary ID (UUID).

        Args:
            user_id: The user's primary key ID.

        Returns:
            User dict or None if not found.
        """
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("users").select("*").eq(
                "id", user_id
            ).execute()

            if response.data and len(response.data) > 0:
                return response.data[0]

            return None

        except Exception as e:
            self.logger.error(
                f"Failed to get user by ID {user_id}: {e}",
                exc_info=True
            )
            return None

    async def update_user_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any]
    ) -> bool:
        """
        Update user preferences.

        Args:
            user_id: User ID
            preferences: Preferences dict to update

        Returns:
            True if successful
        """
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("users").update(
                preferences
            ).eq("id", user_id).execute()

            success = response.data is not None

            if success:
                self.logger.info(f"Updated preferences for user {user_id}")

            return success

        except Exception as e:
            self.logger.error(
                f"Failed to update preferences for user {user_id}: {e}",
                exc_info=True
            )
            return False

    # ------------------------------------------------------------------
    # proactivity_preferences table
    # ------------------------------------------------------------------

    async def get_proactivity_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get proactivity preferences for a user."""
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("proactivity_preferences").select("*").eq(
                "user_id", user_id
            ).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            self.logger.error(f"Failed to get proactivity preferences for {user_id}: {e}")
            return None

    async def update_proactivity_preferences(self, user_id: str, enabled: bool) -> bool:
        """Create or update proactivity enabled status for a user."""
        if not self.client:
            await self.initialize()

        try:
            existing = await self.get_proactivity_preferences(user_id)
            if existing:
                self.client.table("proactivity_preferences").update(
                    {"enabled": enabled}
                ).eq("user_id", user_id).execute()
            else:
                self.client.table("proactivity_preferences").insert(
                    {"user_id": user_id, "enabled": enabled}
                ).execute()
            return True
        except Exception as e:
            self.logger.error(f"Failed to update proactivity preferences for {user_id}: {e}")
            return False

    async def get_all_users_with_proactivity_enabled(self) -> List[Dict[str, Any]]:
        """Get all users who have proactivity enabled."""
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("proactivity_preferences").select(
                "user_id, check_interval_minutes, insights_enabled"
            ).eq("enabled", True).execute()
            return response.data if response.data else []
        except Exception as e:
            self.logger.error(f"Failed to get users with proactivity enabled: {e}")
            return []

    # ------------------------------------------------------------------
    # user_context table
    # ------------------------------------------------------------------

    async def save_user_context(
        self, user_id: str, context_type: str, data: Dict[str, Any]
    ) -> bool:
        """Save or update a user context entry."""
        if not self.client:
            await self.initialize()

        try:
            existing = self.client.table("user_context").select("id").eq(
                "user_id", user_id
            ).eq("context_type", context_type).execute()

            if existing.data:
                self.client.table("user_context").update(
                    {"data": data}
                ).eq("user_id", user_id).eq("context_type", context_type).execute()
            else:
                self.client.table("user_context").insert({
                    "user_id": user_id,
                    "context_type": context_type,
                    "data": data,
                }).execute()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save user context: {e}")
            return False

    async def get_user_context(
        self, user_id: str, context_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get a user context entry by type."""
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("user_context").select("data").eq(
                "user_id", user_id
            ).eq("context_type", context_type).execute()
            return response.data[0]["data"] if response.data else None
        except Exception as e:
            self.logger.error(f"Failed to get user context: {e}")
            return None

    # ------------------------------------------------------------------
    # car_connections table
    # ------------------------------------------------------------------

    async def save_car_connection(
        self,
        user_id: str,
        vehicle_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: str,
    ) -> bool:
        """Save or update a Smartcar connection for a user."""
        if not self.client:
            await self.initialize()

        try:
            existing = self.client.table("car_connections").select("id").eq(
                "user_id", user_id
            ).eq("vehicle_id", vehicle_id).execute()

            payload = {
                "access_token": encrypt_token(access_token),
                "refresh_token": encrypt_token(refresh_token),
                "expires_at": expires_at,
            }

            if existing.data:
                self.client.table("car_connections").update(payload).eq(
                    "user_id", user_id
                ).eq("vehicle_id", vehicle_id).execute()
            else:
                payload["user_id"] = user_id
                payload["vehicle_id"] = vehicle_id
                self.client.table("car_connections").insert(payload).execute()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save car connection: {e}")
            return False

    async def get_car_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get the Smartcar connection for a user."""
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("car_connections").select("*").eq(
                "user_id", user_id
            ).execute()
            if not response.data:
                return None
            connection = response.data[0]
            connection["access_token"] = decrypt_token(connection["access_token"])
            connection["refresh_token"] = decrypt_token(connection["refresh_token"])
            return connection
        except Exception as e:
            self.logger.error(f"Failed to get car connection: {e}")
            return None

    # ------------------------------------------------------------------
    # smartthings_connections table
    # ------------------------------------------------------------------

    async def save_smartthings_connection(
        self,
        user_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: str,
        installed_app_id: str,
        location_id: str,
    ) -> bool:
        """Save or update a SmartThings connection for a user."""
        if not self.client:
            await self.initialize()

        try:
            existing = self.client.table("smartthings_connections").select("id").eq(
                "user_id", user_id
            ).execute()

            payload = {
                "access_token": encrypt_token(access_token),
                "refresh_token": encrypt_token(refresh_token),
                "expires_at": expires_at,
                "installed_app_id": installed_app_id,
                "location_id": location_id,
            }

            if existing.data:
                self.client.table("smartthings_connections").update(payload).eq(
                    "user_id", user_id
                ).execute()
            else:
                payload["user_id"] = user_id
                self.client.table("smartthings_connections").insert(payload).execute()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save smartthings connection: {e}")
            return False

    async def get_smartthings_connection(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get the SmartThings connection for a user."""
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("smartthings_connections").select("*").eq(
                "user_id", user_id
            ).execute()
            if not response.data:
                return None
            connection = response.data[0]
            connection["access_token"] = decrypt_token(connection["access_token"])
            connection["refresh_token"] = decrypt_token(connection["refresh_token"])
            return connection
        except Exception as e:
            self.logger.error(f"Failed to get smartthings connection: {e}")
            return None

    # ------------------------------------------------------------------
    # calendar_connections table
    # ------------------------------------------------------------------

    async def save_calendar_credentials(
        self, user_id: str, credentials: Dict[str, Any]
    ) -> bool:
        """Save or update Google Calendar credentials for a user."""
        if not self.client:
            await self.initialize()

        try:
            existing = self.client.table("calendar_connections").select("id").eq(
                "user_id", user_id
            ).execute()

            encrypted_creds = encrypt_token(_json.dumps(credentials))

            if existing.data:
                self.client.table("calendar_connections").update(
                    {"credentials": encrypted_creds}
                ).eq("user_id", user_id).execute()
            else:
                self.client.table("calendar_connections").insert({
                    "user_id": user_id,
                    "credentials": encrypted_creds,
                }).execute()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save calendar credentials: {e}")
            return False

    async def get_calendar_credentials(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get Google Calendar credentials for a user."""
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("calendar_connections").select(
                "credentials"
            ).eq("user_id", user_id).execute()
            if not response.data:
                return None
            raw = response.data[0]["credentials"]
            decrypted = decrypt_token(raw)
            return _json.loads(decrypted)
        except Exception as e:
            self.logger.error(f"Failed to get calendar credentials: {e}")
            return None

    # ------------------------------------------------------------------
    # github_connections table
    # ------------------------------------------------------------------

    async def save_github_connection(
        self, user_id: str, github_username: str, access_token: str
    ) -> bool:
        """Save or update a GitHub connection for a user."""
        if not self.client:
            await self.initialize()

        try:
            existing = self.client.table("github_connections").select("id").eq(
                "user_id", user_id
            ).execute()

            payload = {
                "github_username": github_username,
                "access_token": encrypt_token(access_token),
            }

            if existing.data:
                self.client.table("github_connections").update(payload).eq(
                    "user_id", user_id
                ).execute()
            else:
                payload["user_id"] = user_id
                self.client.table("github_connections").insert(payload).execute()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save github connection: {e}")
            return False

    async def get_github_connection(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get the GitHub connection for a user."""
        if not self.client:
            await self.initialize()

        try:
            response = self.client.table("github_connections").select("*").eq(
                "user_id", user_id
            ).execute()
            if not response.data:
                return None
            connection = response.data[0]
            connection["access_token"] = decrypt_token(connection["access_token"])
            return connection
        except Exception as e:
            self.logger.error(f"Failed to get github connection: {e}")
            return None

    # ------------------------------------------------------------------
    # Messages table (conversation history)
    # ------------------------------------------------------------------

    async def get_messages_for_conversation(
        self, conversation_id: str
    ) -> List[Dict[str, Any]]:
        """Get all messages for a conversation, ordered by date.

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            List of message dicts with role, content, created_at.
        """
        if not self.client:
            await self.initialize()

        try:
            response = (
                self.client.table("messages")
                .select("role, content, created_at")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=False)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            self.logger.error(
                f"Failed to get messages for conversation {conversation_id}: {e}"
            )
            return []


# Backward compatibility functions
def get_db() -> Client:
    """Get Supabase client (backward compatibility)."""
    from services.core import get_service
    service = get_service("database")
    if service and isinstance(service, DatabaseService):
        if not service.is_initialized():
            import asyncio
            asyncio.create_task(service.initialize())
        return service.get_client()
    return None


async def get_all_users_with_preferences() -> List[Dict[str, Any]]:
    """Get all users with preferences (backward compatibility)."""
    from services.core import get_service
    service = get_service("database")
    if service and isinstance(service, DatabaseService):
        if not service.is_initialized():
            await service.initialize()
        return await service.get_all_users_with_preferences()
    return []
