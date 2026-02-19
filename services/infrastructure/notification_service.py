# services/infrastructure/notification_service.py
"""
NotificationService — abstract notification delivery layer.

Currently supports Telegram; designed so additional channels
(push notifications, in-app, Orb, etc.) can be added later
without touching the callers.
"""

from services.core import BaseService, register_service


@register_service("notification")
class NotificationService(BaseService):
    """Delivers notifications through pluggable channels."""

    async def _initialize(self):
        self.logger.info("NotificationService ready")

    async def _health_check(self) -> bool:
        return True

    async def send_message(self, channel: str, recipient: str, message: str) -> bool:
        """
        Send a message through the specified channel.

        Args:
            channel: Delivery channel ('telegram', 'app', 'orb').
            recipient: Recipient identifier (e.g. Telegram chat_id).
            message: The message body.

        Returns:
            True if sent successfully, False otherwise.
        """
        if channel == "telegram":
            # Local import to avoid circular dependency
            from telegram_bot import send_proactive_message

            return await send_proactive_message(recipient, message)

        self.logger.warning("Notification channel '%s' not supported.", channel)
        return False
