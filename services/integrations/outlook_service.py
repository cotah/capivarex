"""
Outlook Email Service — reads and sends emails via Microsoft Graph API.

Follows the same pattern as gmail_service.py.
Uses microsoft_oauth_service for token management.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from services.core import BaseService, register_service

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@register_service("outlook")
class OutlookService(BaseService):
    """Microsoft Outlook email operations via Graph API."""

    def __init__(self) -> None:
        super().__init__(name="outlook")

    async def _initialize(self) -> None:
        self.logger.info("OutlookService initialized")

    async def _health_check(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Internal: authenticated Graph API call
    # ------------------------------------------------------------------

    async def _api(
        self,
        user_id: str,
        method: str,
        path: str,
        json_body: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make authenticated Microsoft Graph API call."""
        from services.auth.microsoft_oauth_service import get_microsoft_oauth

        token = await get_microsoft_oauth().get_valid_token(user_id)
        if not token:
            self.logger.warning("No valid Microsoft token for user %s", user_id[:8])
            return None

        url = f"{_GRAPH_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
            )

            if resp.status_code == 401:
                self.logger.warning("Microsoft API 401 — token may be expired")
                return None
            if resp.status_code == 204:
                return {"status": "ok"}

            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Email Operations
    # ------------------------------------------------------------------

    async def list_emails(
        self,
        user_id: str,
        max_results: int = 10,
        unread_only: bool = False,
        folder: str = "inbox",
    ) -> List[Dict[str, Any]]:
        """List emails from Microsoft Outlook."""
        params: Dict[str, Any] = {
            "$top": max_results,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
        }
        if unread_only:
            params["$filter"] = "isRead eq false"

        path = f"/me/mailFolders/{folder}/messages"
        data = await self._api(user_id, "GET", path, params=params)
        if not data:
            return []

        messages = data.get("value", [])
        return [
            {
                "id": msg["id"],
                "subject": msg.get("subject", "(no subject)"),
                "from": _extract_sender(msg),
                "from_name": _extract_sender_name(msg),
                "date": msg.get("receivedDateTime", ""),
                "snippet": msg.get("bodyPreview", "")[:200],
                "is_read": msg.get("isRead", False),
                "has_attachments": msg.get("hasAttachments", False),
                "provider": "microsoft",
            }
            for msg in messages
        ]

    async def get_email_body(self, user_id: str, message_id: str) -> Optional[str]:
        """Get full email body."""
        data = await self._api(
            user_id,
            "GET",
            f"/me/messages/{message_id}",
            params={"$select": "body"},
        )
        if not data:
            return None
        body = data.get("body", {})
        return body.get("content", "")

    async def send_email(
        self,
        user_id: str,
        to: str,
        subject: str,
        body: str,
        reply_to_id: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email via Microsoft Graph.

        Accepts both reply_to_id and reply_to_message_id for compatibility
        with the email agent (which passes reply_to_message_id).
        thread_id is accepted but ignored (Microsoft Graph handles threads internally).
        """
        _reply_id = reply_to_id or reply_to_message_id
        if _reply_id:
            # Reply to existing message
            reply_body = {
                "message": {"body": {"contentType": "Text", "content": body}},
            }
            result = await self._api(
                user_id,
                "POST",
                f"/me/messages/{_reply_id}/reply",
                json_body=reply_body,
            )
        else:
            # New email
            message = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [
                        {"emailAddress": {"address": to}},
                    ],
                },
                "saveToSentItems": True,
            }
            result = await self._api(user_id, "POST", "/me/sendMail", json_body=message)

        return {"id": "", "threadId": ""} if result is not None else {}

    async def send_email_with_attachment(
        self,
        user_id: str,
        to: str,
        subject: str,
        body: str,
        attachment_bytes: bytes,
        attachment_filename: str,
        attachment_mime: str = "application/octet-stream",
    ) -> bool:
        """Send an email with a file attachment via Microsoft Graph.

        Args:
            user_id: User UUID for OAuth2
            to: Recipient email
            subject: Email subject
            body: Email body (plain text)
            attachment_bytes: Raw file bytes
            attachment_filename: Filename (e.g. "report.xlsx")
            attachment_mime: MIME type of attachment

        Returns:
            True if sent successfully
        """
        import base64

        attachment_b64 = base64.b64encode(attachment_bytes).decode("utf-8")

        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [
                    {"emailAddress": {"address": to}},
                ],
                "attachments": [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": attachment_filename,
                        "contentType": attachment_mime,
                        "contentBytes": attachment_b64,
                    }
                ],
            },
            "saveToSentItems": True,
        }
        result = await self._api(user_id, "POST", "/me/sendMail", json_body=message)
        return result is not None

    async def mark_as_read(self, user_id: str, message_id: str) -> bool:
        """Mark email as read."""
        result = await self._api(
            user_id,
            "PATCH",
            f"/me/messages/{message_id}",
            json_body={"isRead": True},
        )
        return result is not None

    async def archive(self, user_id: str, message_id: str) -> bool:
        """Move email to archive folder."""
        result = await self._api(
            user_id,
            "POST",
            f"/me/messages/{message_id}/move",
            json_body={"destinationId": "archive"},
        )
        return result is not None

    async def trash(self, user_id: str, message_id: str) -> bool:
        """Move email to trash."""
        result = await self._api(
            user_id,
            "POST",
            f"/me/messages/{message_id}/move",
            json_body={"destinationId": "deleteditems"},
        )
        return result is not None

    async def get_profile(self, user_id: str) -> Optional[Dict[str, str]]:
        """Get user email profile."""
        data = await self._api(user_id, "GET", "/me")
        if not data:
            return None
        return {
            "email": data.get("mail") or data.get("userPrincipalName", ""),
            "name": data.get("displayName", ""),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_sender(msg: Dict) -> str:
    return msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")


def _extract_sender_name(msg: Dict) -> str:
    return msg.get("from", {}).get("emailAddress", {}).get("name", "")
