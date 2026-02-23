"""
Memory management system for CapivaraX Bot.

Handles:
- Notes storage and retrieval via database (Supabase)
- User preferences
- Auditable memory with request_id tracking
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("capivarex.memory")


class MemoryManager:
    """Manages bot memory using the database for persistence and audit."""

    def __init__(self, db_service: Any):
        """
        Initialize MemoryManager with a database service.

        Args:
            db_service: Database service instance (Supabase client wrapper)
        """
        self.db = db_service

    def _get_client(self):
        """Get the Supabase client from the database service."""
        return self.db.get_client()

    async def add_memory(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        source: str = "user_input",
        request_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Add a memory to the database and log the audit event.

        Args:
            user_id: User UUID
            memory_type: Memory type ('short_term', 'long_term', 'factual')
            content: Memory content text
            source: Origin of the memory ('user_input', 'proactivity_insight', etc.)
            request_id: Optional request_id for audit tracing

        Returns:
            The memory ID if successful, None otherwise
        """
        try:
            client = self._get_client()
            result = (
                client.table("memories")
                .insert({
                    "user_id": user_id,
                    "type": memory_type,
                    "content": content,
                    "source": source,
                })
                .execute()
            )

            if result.data and len(result.data) > 0:
                memory_id = result.data[0]["id"]
                await self._log_audit(request_id, memory_id, user_id, "created")
                return memory_id

            return None
        except Exception as e:
            logger.error(f"Failed to add memory for user {user_id}: {e}")
            return None

    async def get_memories(
        self,
        user_id: str,
        memory_type: str,
        request_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """
        Get memories by user and type, logging read access.

        Args:
            user_id: User UUID
            memory_type: Memory type filter
            request_id: Optional request_id for audit tracing
            limit: Maximum number of memories to return

        Returns:
            List of memory dictionaries
        """
        try:
            client = self._get_client()
            result = (
                client.table("memories")
                .select("*")
                .eq("user_id", user_id)
                .eq("type", memory_type)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )

            memories = result.data or []

            # Log read access for each memory
            for mem in memories:
                await self._log_audit(request_id, mem["id"], user_id, "read")

            return memories
        except Exception as e:
            logger.error(f"Failed to get memories for user {user_id}: {e}")
            return []

    async def get_all_memories(
        self,
        user_id: str,
        request_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Get all memories for a user regardless of type.

        Args:
            user_id: User UUID
            request_id: Optional request_id for audit tracing
            limit: Maximum number of memories to return

        Returns:
            List of memory dictionaries
        """
        try:
            client = self._get_client()
            result = (
                client.table("memories")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )

            memories = result.data or []

            for mem in memories:
                await self._log_audit(request_id, mem["id"], user_id, "read")

            return memories
        except Exception as e:
            logger.error(f"Failed to get all memories for user {user_id}: {e}")
            return []

    async def search_memories(self, user_id: str, query: str) -> List[Dict]:
        """
        Search memories by content (case-insensitive).

        Args:
            user_id: User UUID
            query: Search query string

        Returns:
            List of matching memory dictionaries
        """
        try:
            client = self._get_client()
            result = (
                client.table("memories")
                .select("*")
                .eq("user_id", user_id)
                .ilike("content", f"%{query}%")
                .order("created_at", desc=True)
                .execute()
            )

            return result.data or []
        except Exception as e:
            logger.error(f"Failed to search memories for user {user_id}: {e}")
            return []

    async def delete_memory(self, memory_id: str, user_id: str) -> bool:
        """
        Delete a specific memory by ID.

        Args:
            memory_id: Memory UUID
            user_id: User UUID (for safety check)

        Returns:
            True if deleted successfully
        """
        try:
            client = self._get_client()
            client.table("memories").delete().eq("id", memory_id).eq("user_id", user_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False

    async def log_memory_usage(
        self,
        request_id: str,
        memory_id: str,
        user_id: str,
    ) -> None:
        """
        Log that a memory was used in a prompt (for audit trail).

        Args:
            request_id: Request UUID for tracing
            memory_id: Memory UUID
            user_id: User UUID
        """
        await self._log_audit(request_id, memory_id, user_id, "used_for_prompt")

    async def _log_audit(
        self,
        request_id: Optional[str],
        memory_id: str,
        user_id: str,
        action: str,
    ) -> None:
        """
        Write an entry to the memory audit log.

        Args:
            request_id: Request UUID (can be None)
            memory_id: Memory UUID
            user_id: User UUID
            action: Action type ('created', 'read', 'used_for_prompt')
        """
        try:
            client = self._get_client()
            client.table("memory_audit_log").insert({
                "request_id": request_id,
                "memory_id": memory_id,
                "user_id": user_id,
                "action": action,
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to log memory audit ({action}): {e}")

    async def get_context_for_ai(
        self,
        user_id: str,
        request_id: Optional[str] = None,
    ) -> str:
        """
        Get memory context formatted for AI prompt injection.

        Args:
            user_id: User UUID
            request_id: Optional request_id for audit tracing

        Returns:
            Formatted string with recent memories
        """
        memories = await self.get_memories(user_id, "long_term", request_id, limit=5)

        if not memories:
            return ""

        # Log usage for prompt
        for mem in memories:
            await self._log_audit(request_id, mem["id"], user_id, "used_for_prompt")

        context_parts = ["Lembre-se destas informacoes sobre o usuario:"]
        for mem in memories:
            context_parts.append(f"- {mem.get('content', '')}")

        return "\n".join(context_parts)
