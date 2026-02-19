# schemas/context.py
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Device(BaseModel):
    type: str  # ex: "mobile", "car", "pc"
    id: str
    permissions: List[str] = Field(default_factory=list)


class UserContext(BaseModel):
    user_id: str  # UUID do usuario no nosso sistema
    telegram_chat_id: int
    full_name: str
    locale: str = "en_US"
    timezone: str = "UTC"
    devices: List[Device] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    # Campo para dados extras que ainda nao foram modelados
    extra_data: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        # Permite que o modelo seja criado a partir de um dicionario que tenha campos extras
        extra = "ignore"
