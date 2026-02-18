"""
SmartThings Data Models
Pydantic models for SmartThings entities and commands.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SmartThingsDevice(BaseModel):
    """
    Represents a SmartThings device with its capabilities and current status.

    Attributes:
        device_id: Unique device identifier from SmartThings API
        label: Human-readable device name
        device_type: Device category (light, lock, thermostat, etc.)
        room: Optional room assignment
        capabilities: List of supported capabilities
            (switch, switchLevel, etc.)
        status: Current device state as key-value pairs
    """

    device_id: str
    label: str
    device_type: str
    room: Optional[str] = None
    capabilities: List[str]
    status: Dict[str, Any]


class SmartThingsCommand(BaseModel):
    """
    Represents a command to be executed on a SmartThings device.

    Attributes:
        device_id: Target device identifier
        capability: Capability namespace (e.g., 'switch', 'switchLevel')
        command: Command name (e.g., 'on', 'off', 'setLevel')
        arguments: Optional command arguments
    """

    device_id: str
    capability: str
    command: str
    arguments: Optional[List[Any]] = Field(default_factory=list)


class SmartThingsOAuthTokens(BaseModel):
    """
    OAuth 2.0 tokens for SmartThings API authentication.

    Attributes:
        user_id: SuperBot user identifier
        access_token: OAuth access token (encrypted in database)
        refresh_token: OAuth refresh token (encrypted in database)
        expires_at: Token expiration timestamp
    """

    user_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime


class SmartThingsRoutine(BaseModel):
    """
    Represents an automated routine with triggers and actions.

    Attributes:
        name: Routine identifier
        triggers: List of trigger conditions
        actions: List of commands to execute
    """

    name: str
    triggers: List[str]
    actions: List[SmartThingsCommand]
