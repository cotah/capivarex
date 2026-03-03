# schemas/context.py
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Device(BaseModel):
    type: str  # ex: "mobile", "car", "pc"
    id: str
    permissions: List[str] = Field(default_factory=list)


class UserContext(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    user_id: str = Field(..., alias="id")  # Aceita "id" (Supabase) e "user_id"
    telegram_chat_id: int
    full_name: str = ""
    locale: str = "en_US"
    timezone: str = "UTC"
    devices: List[Device] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    location_preference: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    proactivity_preferences: Optional[Dict[str, Any]] = None
    # Campo para dados extras que ainda nao foram modelados
    extra_data: Dict[str, Any] = Field(default_factory=dict)
