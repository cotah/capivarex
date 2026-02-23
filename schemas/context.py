# schemas/context.py
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Device(BaseModel):
    type: str  # ex: "mobile", "car", "pc"
    id: str
    permissions: List[str] = Field(default_factory=list)


class UserContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str  # UUID do usuario no nosso sistema
    telegram_chat_id: int
    full_name: str
    locale: str = "en_US"
    timezone: str = "UTC"
    devices: List[Device] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    location_preference: Optional[str] = None
    proactivity_preferences: Optional[Dict[str, Any]] = None
    # Campo para dados extras que ainda nao foram modelados
    extra_data: Dict[str, Any] = Field(default_factory=dict)
