"""
Schemas Pydantic
Define a estrutura de dados para a API.
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
import uuid


# ====================================================================
#                       USER SCHEMAS
# ====================================================================


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)
    phone: Optional[str] = Field(None, max_length=20, description="Phone number with country code (e.g. +353891234567)")
    country_code: Optional[str] = Field(None, max_length=5, description="Country dial code (e.g. +353)")
    preferred_channel: Optional[str] = Field("telegram", description="Preferred messaging channel: telegram or whatsapp")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Clean phone: remove spaces, dashes, parentheses
        cleaned = v.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not cleaned.replace("+", "").isdigit():
            raise ValueError("Phone must contain only digits and optional + prefix")
        if len(cleaned.replace("+", "")) < 7:
            raise ValueError("Phone number too short")
        return cleaned

    @field_validator("preferred_channel")
    @classmethod
    def validate_channel(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in ("telegram", "whatsapp", "both"):
            raise ValueError("Channel must be telegram, whatsapp, or both")
        return v or "telegram"


class User(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    # Novos campos: Planos e Limites
    plan: Optional[str] = "basic"
    messages_limit: Optional[int] = 100
    messages_used: Optional[int] = 0

    # Phone
    phone: Optional[str] = None

    # Novos campos: APIs Pessoais
    github_token: Optional[str] = None
    use_own_apis: Optional[bool] = False

    created_at: datetime


# ====================================================================
#                       TOKEN SCHEMAS
# ====================================================================


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


# ====================================================================
#                       NOTE SCHEMAS
# ====================================================================


class NoteBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=50000)
    tags: Optional[List[str]] = []


class NoteCreate(NoteBase):
    pass


class Note(NoteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


# ============================================
# SPEC #4: Chat Schemas
# ============================================


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: str
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    created_at: datetime


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Strip whitespace and reject empty messages."""
        return v.strip()


# ============================================
# SPEC #7: Workspace + Git Schemas
# ============================================


class GitInitRequest(BaseModel):
    project_name: str


class GitCommitRequest(BaseModel):
    project_name: str
    message: str
    files: Optional[List[str]] = None


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    template_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


# ============================================
# SPEC #8: Git Remote Schemas
# ============================================


class GitCloneRequest(BaseModel):
    repo_url: str = Field(
        ..., pattern=r"^https?://"
    )  # ex: https://github.com/user/repo.git


class GitRemoteRequest(BaseModel):
    remote_url: str
    remote_name: str = "origin"


class GitPushRequest(BaseModel):
    remote_name: str = "origin"
    branch_name: Optional[str] = None  # Se None, usa o branch ativo


# ============================================
# WebApp Chat Schemas
# ============================================


class WebAppChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Strip whitespace and reject empty messages."""
        return v.strip()


class WebAppChatResponse(BaseModel):
    response: str
    agent: str
    type: str = "text"
    data: dict = {}
    conversation_id: str
    message_id: str
    conversation_title: Optional[str] = None


class WebAppConversationRename(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    color: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_archived: Optional[bool] = None
